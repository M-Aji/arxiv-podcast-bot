"""src/main.py のオーケストレーション・例外ハンドリング検証。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from src import main as main_module
from src.fetch_arxiv import ArxivPaper, ArxivRateLimitError
from src.generate_podcast import NotebookLMRateLimitError


def _paper(arxiv_id: str = "2405.00001") -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title="Sample Paper",
        authors=["Alice"],
        abstract="…",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        published=datetime(2026, 5, 25, tzinfo=timezone.utc),
        primary_category="cs.AI",
    )


@pytest.fixture
def captured_notifies(monkeypatch):
    """notify() の呼び出しを記録するフィクスチャ。"""
    captured: list[str] = []
    monkeypatch.setattr(main_module, "notify", lambda msg: captured.append(msg))
    return captured


# ---- 正常系（参照点） -----------------------------------------------------


def test_main_succeeds_with_papers(monkeypatch, captured_notifies, tmp_path):
    monkeypatch.setattr(main_module, "load_published_ids", lambda: set())
    monkeypatch.setattr(
        main_module,
        "fetch_latest_papers",
        lambda **kwargs: [_paper("p1"), _paper("p2")],
    )
    monkeypatch.setattr(
        main_module,
        "generate_audio_overview",
        lambda papers, today: tmp_path / "episode.mp3",
    )
    monkeypatch.setattr(
        main_module, "publish_episode", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        main_module, "record_published_ids", lambda ids: None
    )

    assert main_module.main() == 0
    assert any("✅" in m and "2本" in m for m in captured_notifies)


# ---- 「該当論文0本」スキップ -----------------------------------------------


def test_main_skips_when_no_papers_returns_0(
    monkeypatch, captured_notifies, caplog
):
    monkeypatch.setattr(main_module, "load_published_ids", lambda: set())
    monkeypatch.setattr(
        main_module, "fetch_latest_papers", lambda **kwargs: []
    )
    # generate / publish が呼ばれないことを検証するため、呼ばれたら fail
    monkeypatch.setattr(
        main_module,
        "generate_audio_overview",
        lambda *a, **k: pytest.fail("should not generate audio"),
    )

    with caplog.at_level(logging.INFO, logger="src.main"):
        assert main_module.main() == 0

    # 通知文面に「論文0本」マーカー（📭）が入る
    assert len(captured_notifies) == 1
    assert "📭" in captured_notifies[0]
    assert "論文0本" in captured_notifies[0]
    # ログには論文0本のメッセージ
    assert any("no fresh papers" in rec.message for rec in caplog.records)


# ---- レートリミット時の exit 0 -------------------------------------------


def test_main_returns_0_on_rate_limit_with_distinct_message(
    monkeypatch, captured_notifies, caplog
):
    monkeypatch.setattr(main_module, "load_published_ids", lambda: set())
    monkeypatch.setattr(
        main_module, "fetch_latest_papers", lambda **kwargs: [_paper()]
    )

    def raise_rate_limit(papers, today):  # noqa: ARG001
        raise NotebookLMRateLimitError(
            "Error: Rate limited.", retry_after=3600
        )

    monkeypatch.setattr(
        main_module, "generate_audio_overview", raise_rate_limit
    )

    with caplog.at_level(logging.INFO, logger="src.main"):
        result = main_module.main()

    assert result == 0
    # 通知文面が「論文0本」とは別の文言（🛑 と「制限」マーカー）
    assert len(captured_notifies) == 1
    msg = captured_notifies[0]
    assert "🛑" in msg
    assert "1日3回制限" in msg
    assert "24時間後に再試行" in msg
    assert "retry_after=3600s" in msg
    # 「論文0本」「📭」とは絶対に被らない
    assert "📭" not in msg
    assert "論文0本" not in msg
    # ログは INFO で、ERROR ではない
    rate_records = [
        r for r in caplog.records if "rate-limited" in r.message.lower()
    ]
    assert rate_records, "expected an INFO log about being rate-limited"
    assert all(r.levelno == logging.INFO for r in rate_records)


def test_main_rate_limit_without_retry_after_omits_hint(
    monkeypatch, captured_notifies
):
    monkeypatch.setattr(main_module, "load_published_ids", lambda: set())
    monkeypatch.setattr(
        main_module, "fetch_latest_papers", lambda **kwargs: [_paper()]
    )

    def raise_rate_limit(papers, today):  # noqa: ARG001
        raise NotebookLMRateLimitError("Error: Rate limited.")

    monkeypatch.setattr(
        main_module, "generate_audio_overview", raise_rate_limit
    )
    assert main_module.main() == 0
    msg = captured_notifies[0]
    assert "retry_after" not in msg


# ---- arXiv レートリミット時の exit 0 -------------------------------------


def test_main_returns_0_on_arxiv_rate_limit_with_distinct_message(
    monkeypatch, captured_notifies, caplog
):
    monkeypatch.setattr(main_module, "load_published_ids", lambda: set())

    def raise_arxiv_rate_limit(**kwargs):  # noqa: ARG001
        raise ArxivRateLimitError("HTTP 429 after retries", status=429)

    monkeypatch.setattr(
        main_module, "fetch_latest_papers", raise_arxiv_rate_limit
    )

    with caplog.at_level(logging.INFO, logger="src.main"):
        result = main_module.main()

    assert result == 0
    assert len(captured_notifies) == 1
    msg = captured_notifies[0]
    # arXiv 専用のマーカー絵文字と文言
    assert "🐌" in msg
    assert "arXiv" in msg
    assert "次回 cron で再試行" in msg
    # NotebookLM/論文0本 とは別文言
    assert "🛑" not in msg
    assert "📭" not in msg
    # ログは INFO で ERROR ではない
    arxiv_records = [
        r for r in caplog.records if "arXiv rate-limited" in r.message
    ]
    assert arxiv_records, "expected an INFO log about arXiv rate limit"
    assert all(r.levelno == logging.INFO for r in arxiv_records)


# ---- それ以外の例外は従来どおり raise ------------------------------------


def test_main_propagates_other_exceptions(
    monkeypatch, captured_notifies, caplog
):
    monkeypatch.setattr(main_module, "load_published_ids", lambda: set())
    monkeypatch.setattr(
        main_module, "fetch_latest_papers", lambda **kwargs: [_paper()]
    )

    def boom(papers, today):  # noqa: ARG001
        raise RuntimeError("kaboom")

    monkeypatch.setattr(main_module, "generate_audio_overview", boom)

    with caplog.at_level(logging.ERROR, logger="src.main"):
        with pytest.raises(RuntimeError, match="kaboom"):
            main_module.main()

    # 失敗通知が出る（rate limit や 0 本とは別文言）
    assert any("❌" in m and "kaboom" in m for m in captured_notifies)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
