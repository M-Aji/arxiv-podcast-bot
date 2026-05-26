"""rank_papers: Claude Haiku モックでスコアリング挙動を検証する。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src import config, rank_papers
from src.fetch_arxiv import ArxivPaper


# ---- ヘルパー -------------------------------------------------------------


def _paper(arxiv_id: str, title: str = "Sample", abstract: str = "abs") -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=title,
        authors=["Alice"],
        abstract=abstract,
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        published=datetime(2026, 5, 25, tzinfo=timezone.utc),
        primary_category="cs.AI",
    )


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    """list[Callable | Exception | str] を順に返すフェイク。"""

    def __init__(self, scripted: list) -> None:
        self._scripted = scripted
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        if index >= len(self._scripted):
            raise AssertionError(
                f"unexpected extra Anthropic call #{index + 1}: {kwargs}"
            )
        item = self._scripted[index]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(kwargs)
        # 文字列を本文として返す
        return _FakeResponse(item)


class _FakeClient:
    def __init__(self, scripted: list) -> None:
        self.messages = _FakeMessages(scripted)


def _script(monkeypatch, scripted: list) -> _FakeClient:
    fake = _FakeClient(scripted)
    monkeypatch.setattr(rank_papers, "_build_client", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rank_papers.time, "sleep", lambda _s: None)


@pytest.fixture
def _with_api_key(monkeypatch):
    monkeypatch.setenv(config.ANTHROPIC_API_KEY_ENV, "test-key")


# ---- 正常系 ---------------------------------------------------------------


def test_ranks_papers_in_descending_score_order(monkeypatch, _with_api_key):
    papers = [_paper("p1"), _paper("p2"), _paper("p3")]
    _script(
        monkeypatch,
        [
            '{"score": 3.0, "rationale": "low"}',
            '{"score": 9.0, "rationale": "high"}',
            '{"score": 6.0, "rationale": "mid"}',
        ],
    )

    ranked = rank_papers.rank_papers(papers)

    assert [r.paper.arxiv_id for r in ranked] == ["p2", "p3", "p1"]
    assert [r.score for r in ranked] == [9.0, 6.0, 3.0]
    assert ranked[0].rationale == "high"


def test_score_is_clamped_to_0_10_range(monkeypatch, _with_api_key):
    papers = [_paper("p1"), _paper("p2")]
    _script(
        monkeypatch,
        [
            '{"score": 99.0, "rationale": "too high"}',
            '{"score": -5.0, "rationale": "too low"}',
        ],
    )

    ranked = rank_papers.rank_papers(papers)
    by_id = {r.paper.arxiv_id: r for r in ranked}
    assert by_id["p1"].score == 10.0
    assert by_id["p2"].score == 0.0


def test_parses_json_with_surrounding_noise(monkeypatch, _with_api_key):
    papers = [_paper("p1")]
    _script(
        monkeypatch,
        [
            'Sure! here is the result:\n{"score": 7.5, "rationale": "ok"}\nThanks',
        ],
    )

    ranked = rank_papers.rank_papers(papers)
    assert ranked[0].score == 7.5
    assert ranked[0].rationale == "ok"
    # japanese_title 不在は None に正規化される
    assert ranked[0].japanese_title is None


# ---- japanese_title 抽出 -------------------------------------------------


def test_japanese_title_is_extracted_when_present(monkeypatch, _with_api_key):
    papers = [_paper("p1", title="An English Paper Title")]
    _script(
        monkeypatch,
        [
            '{"score": 8.0, "rationale": "ok",'
            ' "japanese_title": "英語論文のタイトル"}',
        ],
    )

    ranked = rank_papers.rank_papers(papers)
    assert ranked[0].japanese_title == "英語論文のタイトル"


def test_japanese_title_null_falls_back_to_none(monkeypatch, _with_api_key):
    papers = [_paper("p1")]
    _script(
        monkeypatch,
        [
            '{"score": 5.0, "rationale": "ok", "japanese_title": null}',
        ],
    )

    ranked = rank_papers.rank_papers(papers)
    assert ranked[0].japanese_title is None


def test_japanese_title_empty_string_falls_back_to_none(
    monkeypatch, _with_api_key
):
    papers = [_paper("p1")]
    _script(
        monkeypatch,
        [
            '{"score": 5.0, "rationale": "ok", "japanese_title": "   "}',
        ],
    )

    ranked = rank_papers.rank_papers(papers)
    assert ranked[0].japanese_title is None


def test_japanese_title_missing_field_is_none(monkeypatch, _with_api_key):
    """既存形式（japanese_title フィールドなし）も後方互換で動く。"""
    papers = [_paper("p1")]
    _script(monkeypatch, ['{"score": 5.0, "rationale": "ok"}'])

    ranked = rank_papers.rank_papers(papers)
    assert ranked[0].japanese_title is None


# ---- 全件失敗フォールバック ----------------------------------------------


def test_full_api_failure_falls_back_to_original_order(
    monkeypatch, _with_api_key, caplog
):
    papers = [_paper("p1"), _paper("p2"), _paper("p3")]
    # 各論文 3 リトライ × 3 本 = 9 回すべて失敗
    _script(monkeypatch, [RuntimeError("boom")] * 9)

    with caplog.at_level("WARNING", logger="src.rank_papers"):
        ranked = rank_papers.rank_papers(papers)

    assert [r.paper.arxiv_id for r in ranked] == ["p1", "p2", "p3"]
    assert all(r.score == 5.0 for r in ranked)
    assert all(r.rationale == "(ranking skipped)" for r in ranked)
    assert any("all 3 papers failed" in rec.message for rec in caplog.records)


def test_missing_api_key_falls_back_without_calling_api(monkeypatch, caplog):
    monkeypatch.delenv(config.ANTHROPIC_API_KEY_ENV, raising=False)
    # _build_client should never be called; raise loudly if it is
    monkeypatch.setattr(
        rank_papers,
        "_build_client",
        lambda: (_ for _ in ()).throw(AssertionError("should not build client")),
    )

    papers = [_paper("p1"), _paper("p2")]
    with caplog.at_level("WARNING", logger="src.rank_papers"):
        ranked = rank_papers.rank_papers(papers)

    assert [r.paper.arxiv_id for r in ranked] == ["p1", "p2"]
    assert all(r.score == 5.0 for r in ranked)
    assert all(r.rationale == "(ranking skipped)" for r in ranked)
    assert any(
        "ANTHROPIC_API_KEY" in rec.message and "skipping" in rec.message
        for rec in caplog.records
    )


# ---- 部分失敗 -------------------------------------------------------------


def test_partial_failures_keep_successful_scores_and_neutralize_failures(
    monkeypatch, _with_api_key
):
    # 3 本中 1 本だけ全リトライ失敗、残り 2 本は成功
    papers = [_paper("p1"), _paper("p2"), _paper("p3")]
    scripted = [
        '{"score": 8.0, "rationale": "p1 high"}',
        RuntimeError("fail"),
        RuntimeError("fail"),
        RuntimeError("fail"),  # p2 全リトライ失敗
        '{"score": 6.0, "rationale": "p3 mid"}',
    ]
    _script(monkeypatch, scripted)

    ranked = rank_papers.rank_papers(papers)

    by_id = {r.paper.arxiv_id: r for r in ranked}
    assert by_id["p1"].score == 8.0
    assert by_id["p3"].score == 6.0
    assert by_id["p2"].score == 5.0
    assert by_id["p2"].rationale == "(評価失敗のため中立評価)"
    # 並びは降順
    assert [r.paper.arxiv_id for r in ranked] == ["p1", "p3", "p2"]


def test_retry_succeeds_on_second_attempt(monkeypatch, _with_api_key):
    papers = [_paper("p1")]
    scripted = [
        RuntimeError("first try fails"),
        '{"score": 7.0, "rationale": "second try ok"}',
    ]
    fake = _script(monkeypatch, scripted)

    ranked = rank_papers.rank_papers(papers)
    assert ranked[0].score == 7.0
    assert ranked[0].rationale == "second try ok"
    assert len(fake.messages.calls) == 2


def test_json_parse_failure_triggers_retry_then_per_paper_fallback(
    monkeypatch, _with_api_key
):
    # 2 本中 1 本目だけ不正な JSON が 3 回続く（部分失敗）→ "(評価失敗のため中立評価)"
    papers = [_paper("p1"), _paper("p2")]
    _script(
        monkeypatch,
        [
            "not json at all",
            "still bad",
            "nope",
            '{"score": 8.0, "rationale": "ok"}',
        ],
    )

    ranked = rank_papers.rank_papers(papers)
    by_id = {r.paper.arxiv_id: r for r in ranked}
    assert by_id["p1"].score == 5.0
    assert by_id["p1"].rationale == "(評価失敗のため中立評価)"
    assert by_id["p2"].score == 8.0


def test_json_parse_failure_on_all_papers_triggers_ranking_skipped(
    monkeypatch, _with_api_key
):
    # 全件不正な JSON が 3 回連続 → 全件失敗扱いで "(ranking skipped)"
    papers = [_paper("p1")]
    _script(monkeypatch, ["not json at all", "still bad", "nope"])

    ranked = rank_papers.rank_papers(papers)
    assert ranked[0].score == 5.0
    assert ranked[0].rationale == "(ranking skipped)"


# ---- 空入力 ---------------------------------------------------------------


def test_empty_candidates_returns_empty(monkeypatch):
    # API キー有無に関わらず空入力は空出力
    monkeypatch.delenv(config.ANTHROPIC_API_KEY_ENV, raising=False)
    assert rank_papers.rank_papers([]) == []


# ---- select_top_n ---------------------------------------------------------


def test_select_top_n_returns_first_n(monkeypatch):
    ranked = [
        rank_papers.RankedPaper(paper=_paper("p1"), score=9.0, rationale=""),
        rank_papers.RankedPaper(paper=_paper("p2"), score=7.0, rationale=""),
        rank_papers.RankedPaper(paper=_paper("p3"), score=5.0, rationale=""),
    ]
    top = rank_papers.select_top_n(ranked, 2)
    assert [p.arxiv_id for p in top] == ["p1", "p2"]


def test_select_top_n_handles_fewer_candidates_than_n():
    ranked = [
        rank_papers.RankedPaper(paper=_paper("p1"), score=9.0, rationale=""),
    ]
    top = rank_papers.select_top_n(ranked, 5)
    assert [p.arxiv_id for p in top] == ["p1"]


def test_select_top_n_on_empty_input():
    assert rank_papers.select_top_n([], 5) == []


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
