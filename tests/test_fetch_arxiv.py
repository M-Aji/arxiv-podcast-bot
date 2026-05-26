"""fetch_arxiv: arxiv.Client.results をモックして検証する。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import fetch_arxiv


@dataclass
class _FakeAuthor:
    name: str


@dataclass
class _FakeResult:
    entry_id: str
    title: str
    summary: str
    authors: list[_FakeAuthor]
    published: datetime
    primary_category: str
    pdf_url: str


def _make_result(
    arxiv_id: str,
    title: str = "A neat paper",
    summary: str = "Summary",
    days_ago: float = 0.1,
    category: str = "cs.AI",
) -> _FakeResult:
    pub = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return _FakeResult(
        entry_id=f"http://arxiv.org/abs/{arxiv_id}v1",
        title=title,
        summary=summary,
        authors=[_FakeAuthor("Alice"), _FakeAuthor("Bob")],
        published=pub,
        primary_category=category,
        pdf_url=f"http://arxiv.org/pdf/{arxiv_id}",
    )


class _FakeClient:
    def __init__(self, results, **kwargs):
        self._results = results

    def results(self, search):  # noqa: ARG002 — match arxiv.Client signature
        return iter(self._results)


class _RateLimitedClient:
    """`results()` を呼ぶと arxiv.HTTPError を投げるフェイク。"""

    def __init__(self, status: int = 429) -> None:
        self._status = status

    def results(self, search):  # noqa: ARG002 — match arxiv.Client signature
        raise fetch_arxiv.arxiv.HTTPError(
            "http://export.arxiv.org/api/query", retry=0, status=self._status
        )


def _install_fake_client(monkeypatch, results) -> list[int]:
    """`arxiv.Client` を fake に差し替え、呼ばれた回数を返す list を返す。"""
    call_count = [0]

    def factory(*args, **kwargs):  # noqa: ARG001
        call_count[0] += 1
        return _FakeClient(results)

    monkeypatch.setattr(fetch_arxiv.arxiv, "Client", factory)
    return call_count


def _install_scripted_clients(monkeypatch, scripted: list) -> list[int]:
    """各 `Client(...)` 呼び出しごとに `scripted` の要素を順に返す。

    要素は `_FakeClient`/`_RateLimitedClient` インスタンスを直接書ける。
    呼び出し回数のカウンタ list を返す。
    """
    call_count = [0]

    def factory(*args, **kwargs):  # noqa: ARG001
        idx = call_count[0]
        call_count[0] += 1
        if idx >= len(scripted):
            raise AssertionError(
                f"unexpected extra arxiv.Client call #{idx + 1}"
            )
        return scripted[idx]

    monkeypatch.setattr(fetch_arxiv.arxiv, "Client", factory)
    return call_count


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """フォールバック時の time.sleep でテストを遅らせない。"""
    monkeypatch.setattr(fetch_arxiv.time, "sleep", lambda _: None)


# ---- 基本ヘルパー --------------------------------------------------------


def test_arxiv_id_strips_version_suffix():
    assert (
        fetch_arxiv._arxiv_id_from_entry("http://arxiv.org/abs/2405.12345v3")
        == "2405.12345"
    )
    assert (
        fetch_arxiv._arxiv_id_from_entry("https://arxiv.org/abs/2401.00001")
        == "2401.00001"
    )


def test_build_category_query():
    assert (
        fetch_arxiv._build_category_query(["cs.AI", "cs.LG"])
        == "cat:cs.AI OR cat:cs.LG"
    )


def test_next_window_doubles_with_cap():
    assert fetch_arxiv._next_window(1, 14) == 2
    assert fetch_arxiv._next_window(2, 14) == 4
    assert fetch_arxiv._next_window(8, 14) == 14
    assert fetch_arxiv._next_window(14, 14) == 14


# ---- 単一窓の振る舞い ----------------------------------------------------


def test_fetch_returns_up_to_n_papers(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [_make_result(f"2405.0000{i}") for i in range(5)],
    )
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"], n=3, query_days=7, query_days_max=7, min_papers=3
    )
    assert len(papers) == 3
    assert papers[0].arxiv_id == "2405.00000"
    assert papers[0].abs_url == "https://arxiv.org/abs/2405.00000"
    assert papers[0].authors == ["Alice", "Bob"]


def test_fetch_excludes_keywords(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [
            _make_result("2405.00001", title="A boring survey paper"),
            _make_result("2405.00002", title="A solid empirical study"),
        ],
    )
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"],
        n=5,
        query_days=7,
        query_days_max=7,
        min_papers=1,
        exclude_keywords=["survey"],
    )
    assert [p.arxiv_id for p in papers] == ["2405.00002"]


def test_fetch_excludes_already_published(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [
            _make_result("2405.00001"),
            _make_result("2405.00002"),
        ],
    )
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"],
        n=5,
        query_days=7,
        query_days_max=7,
        min_papers=1,
        exclude_published_ids={"2405.00001"},
    )
    assert [p.arxiv_id for p in papers] == ["2405.00002"]


def test_fetch_drops_old_papers_in_single_window(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [
            _make_result("2405.00001", days_ago=0.2),
            _make_result("2405.00002", days_ago=2.5),  # outside query_days=1
        ],
    )
    # query_days_max=query_days で拡大を抑止 → 単一窓の挙動を検証
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"],
        n=5,
        query_days=1,
        query_days_max=1,
        min_papers=1,
    )
    assert [p.arxiv_id for p in papers] == ["2405.00001"]


# ---- フォールバック（窓拡大）の振る舞い ----------------------------------


def test_fetch_expands_window_until_min_papers_reached(monkeypatch, caplog):
    # days_ago = [0.5, 3, 5, 10, 13] の 5 本
    # window 1→2→4→8→14 で取れる本数は 1→1→2→3→5
    # min_papers=5 を満たすのは 14 日窓
    results = [
        _make_result("p1", days_ago=0.5),
        _make_result("p2", days_ago=3),
        _make_result("p3", days_ago=5),
        _make_result("p4", days_ago=10),
        _make_result("p5", days_ago=13),
    ]
    call_count = _install_fake_client(monkeypatch, results)

    with caplog.at_level("INFO", logger="src.fetch_arxiv"):
        papers = fetch_arxiv.fetch_latest_papers(
            categories=["cs.AI"],
            n=10,
            query_days=1,
            query_days_max=14,
            min_papers=5,
        )

    assert [p.arxiv_id for p in papers] == ["p1", "p2", "p3", "p4", "p5"]
    # 1 → 2 → 4 → 8 → 14 の 5 回呼び出される
    assert call_count[0] == 5

    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "窓拡大: 1日 → 2日 (取得1本)" in log_text
    assert "窓拡大: 2日 → 4日 (取得1本)" in log_text
    assert "窓拡大: 4日 → 8日 (取得2本)" in log_text
    assert "窓拡大: 8日 → 14日 (取得3本)" in log_text


def test_fetch_does_not_expand_when_n_papers_already_available(monkeypatch):
    # 5 本すべて新しい → 最初の窓で n=10 でも min_papers=5 を満たして停止
    results = [_make_result(f"p{i}", days_ago=0.1) for i in range(5)]
    call_count = _install_fake_client(monkeypatch, results)

    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"],
        n=10,
        query_days=1,
        query_days_max=14,
        min_papers=5,
    )
    assert len(papers) == 5
    assert call_count[0] == 1  # 1回のみ呼ばれる


def test_fetch_does_not_expand_when_exactly_n_reached(monkeypatch):
    # 10 本すべて新しい → n=10 ぴったりで停止
    results = [_make_result(f"p{i}", days_ago=0.1) for i in range(10)]
    call_count = _install_fake_client(monkeypatch, results)

    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"],
        n=10,
        query_days=1,
        query_days_max=14,
        min_papers=5,
    )
    assert len(papers) == 10
    assert call_count[0] == 1


def test_fetch_gives_up_at_max_window(monkeypatch, caplog):
    # 1 本だけ、しかも 20 日前 → どの窓でも対象外
    _install_fake_client(monkeypatch, [_make_result("ancient", days_ago=20)])

    with caplog.at_level("WARNING", logger="src.fetch_arxiv"):
        papers = fetch_arxiv.fetch_latest_papers(
            categories=["cs.AI"],
            n=10,
            query_days=1,
            query_days_max=14,
            min_papers=5,
        )
    assert papers == []
    assert any("上限" in rec.message for rec in caplog.records)


# ---- 配信済みIDの状態管理 -------------------------------------------------


def test_published_ids_roundtrip(tmp_path: Path):
    state_file = tmp_path / "published.json"
    assert fetch_arxiv.load_published_ids(state_file) == set()

    fetch_arxiv.record_published_ids(["a", "b"], path=state_file)
    assert fetch_arxiv.load_published_ids(state_file) == {"a", "b"}

    fetch_arxiv.record_published_ids(["b", "c"], path=state_file)
    assert fetch_arxiv.load_published_ids(state_file) == {"a", "b", "c"}

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload == {"ids": ["a", "b", "c"]}


# ---- アプリ層レートリミットリトライ -------------------------------------


def test_fetch_recovers_after_initial_429(monkeypatch, caplog):
    # 1 回目 429 → 2 回目 (アプリ層リトライ) で成功
    scripted = [
        _RateLimitedClient(429),
        _FakeClient([_make_result("p1")]),
    ]
    call_count = _install_scripted_clients(monkeypatch, scripted)

    with caplog.at_level("WARNING", logger="src.fetch_arxiv"):
        papers = fetch_arxiv.fetch_latest_papers(
            categories=["cs.AI"],
            n=5,
            query_days=1,
            query_days_max=1,
            min_papers=1,
        )

    assert [p.arxiv_id for p in papers] == ["p1"]
    assert call_count[0] == 2
    assert any(
        "arXiv HTTP 429" in rec.message and "before retry" in rec.message
        for rec in caplog.records
    )


def test_fetch_raises_after_all_attempts_429(monkeypatch, caplog):
    # 全アプリ層リトライ (初回 + 3 回 = 4 回) で 429 → ArxivRateLimitError
    scripted = [_RateLimitedClient(429) for _ in range(4)]
    call_count = _install_scripted_clients(monkeypatch, scripted)

    with caplog.at_level("ERROR", logger="src.fetch_arxiv"):
        with pytest.raises(fetch_arxiv.ArxivRateLimitError) as exc_info:
            fetch_arxiv.fetch_latest_papers(
                categories=["cs.AI"],
                n=5,
                query_days=1,
                query_days_max=1,
                min_papers=1,
            )

    assert exc_info.value.status == 429
    assert "429" in str(exc_info.value)
    assert call_count[0] == 4  # 4 回試して全部失敗
    assert any("giving up" in rec.message for rec in caplog.records)


def test_fetch_raises_after_all_attempts_503(monkeypatch):
    # 503 も 429 と同様にレートリミット扱い
    scripted = [_RateLimitedClient(503) for _ in range(4)]
    _install_scripted_clients(monkeypatch, scripted)

    with pytest.raises(fetch_arxiv.ArxivRateLimitError) as exc_info:
        fetch_arxiv.fetch_latest_papers(
            categories=["cs.AI"],
            n=5,
            query_days=1,
            query_days_max=1,
            min_papers=1,
        )
    assert exc_info.value.status == 503


def test_non_rate_limit_http_error_is_not_retried(monkeypatch):
    # 500 のようなレートリミット以外の HTTPError はリトライせず素通し
    scripted = [_RateLimitedClient(500)]
    call_count = _install_scripted_clients(monkeypatch, scripted)

    with pytest.raises(fetch_arxiv.arxiv.HTTPError):
        fetch_arxiv.fetch_latest_papers(
            categories=["cs.AI"],
            n=5,
            query_days=1,
            query_days_max=1,
            min_papers=1,
        )
    assert call_count[0] == 1


def test_rate_limit_skips_adaptive_window_expansion(monkeypatch):
    # 適応窓ループの最中に ArxivRateLimitError が出たら、
    # 窓を変えても結果は同じなので拡大せず即 raise する。
    window_calls = [0]
    real_fetch_window = fetch_arxiv._fetch_window

    def fake_fetch_window(**kwargs):
        window_calls[0] += 1
        raise fetch_arxiv.ArxivRateLimitError(
            "simulated rate limit", status=429
        )

    monkeypatch.setattr(fetch_arxiv, "_fetch_window", fake_fetch_window)

    with pytest.raises(fetch_arxiv.ArxivRateLimitError):
        fetch_arxiv.fetch_latest_papers(
            categories=["cs.AI"],
            n=10,
            query_days=1,
            query_days_max=14,
            min_papers=5,
        )

    # 窓拡大せず 1 回だけ呼ばれて即 raise
    assert window_calls[0] == 1
    # silence unused warning
    _ = real_fetch_window


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
