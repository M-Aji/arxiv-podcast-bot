"""JST 基準の配信日決定ロジック検証。

cron は 21:00 UTC = 06:00 JST に発火する。`date.today()` が UTC 基準だと
「昨日の日付」のノートブック名・タグ・ファイル名が生成されてしまうため、
全モジュールが config.today_jst() を経由していることを担保する。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src import config, main as main_module, publish as publish_module, rss
from src.fetch_arxiv import ArxivPaper


# ---- config.today_jst の境界 ---------------------------------------------


def test_jst_constant_is_plus_9_hours():
    """JST = UTC+9 を厳格に確認。"""
    offset = config.JST.utcoffset(None)
    assert offset is not None
    assert offset.total_seconds() == 9 * 3600


@pytest.mark.parametrize(
    "utc_iso,expected_date",
    [
        # UTC 14:59 → JST 23:59 (同じ日)
        ("2026-05-26T14:59:00+00:00", date(2026, 5, 26)),
        # UTC 15:00 → JST 00:00 (翌日にロールオーバー)
        ("2026-05-26T15:00:00+00:00", date(2026, 5, 27)),
        # cron 発火時刻 21:00 UTC → 06:00 JST 翌日
        ("2026-05-26T21:00:00+00:00", date(2026, 5, 27)),
        # 真夜中 UTC → JST 09:00 同日
        ("2026-05-26T00:00:00+00:00", date(2026, 5, 26)),
    ],
)
def test_today_jst_returns_jst_calendar_date(utc_iso, expected_date):
    """UTC 時刻に対し JST カレンダー日付が返る。"""
    fixed_utc = datetime.fromisoformat(utc_iso)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003
            return fixed_utc.astimezone(tz) if tz else fixed_utc

    with patch("src.config.datetime", _FrozenDatetime):
        assert config.today_jst() == expected_date


# ---- main.py が JST を使う ----------------------------------------------


def _paper(arxiv_id: str = "2405.00001") -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title="Sample",
        authors=["A"],
        abstract="…",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        published=datetime(2026, 5, 26, tzinfo=timezone.utc),
        primary_category="cs.AI",
    )


def test_main_uses_today_jst_not_utc(monkeypatch, tmp_path):
    """main.main() は config.today_jst() を呼び、その日付を generate/publish に渡す。"""
    monkeypatch.setattr(main_module, "load_published_ids", lambda: set())
    monkeypatch.setattr(
        main_module, "fetch_latest_papers", lambda **kwargs: [_paper()]
    )
    monkeypatch.setattr(
        main_module,
        "write_daily_archive",
        lambda *a, **kw: tmp_path / "archive.md",
    )
    monkeypatch.setattr(main_module, "notify", lambda msg: None)
    monkeypatch.setattr(
        main_module, "record_published_ids", lambda ids: None
    )

    sentinel_date = date(2026, 5, 27)
    monkeypatch.setattr(main_module.config, "today_jst", lambda: sentinel_date)

    captured: dict = {}

    def fake_generate(papers, today):
        captured["generate_today"] = today
        return tmp_path / "episode.mp3"

    def fake_publish(mp3, papers, today, **kwargs):
        captured["publish_today"] = today

    monkeypatch.setattr(main_module, "generate_audio_overview", fake_generate)
    monkeypatch.setattr(main_module, "publish_episode", fake_publish)

    assert main_module.main() == 0
    assert captured["generate_today"] == sentinel_date
    assert captured["publish_today"] == sentinel_date


# ---- rss.py の pubDate は JST 06:00 ---------------------------------------


def test_rss_pub_date_is_jst_06_00():
    """make_episode の pub_date は JST 06:00 (= UTC 21:00 前日)。"""
    today = date(2026, 5, 27)
    ep = rss.make_episode([], today, repo="owner/repo")
    assert ep.pub_date.tzinfo is not None
    # JST 表現に正規化して 06:00 を確認
    jst_dt = ep.pub_date.astimezone(config.JST)
    assert jst_dt.date() == today
    assert (jst_dt.hour, jst_dt.minute) == (6, 0)
    # 同時に UTC では前日 21:00 になっているはず
    utc_dt = ep.pub_date.astimezone(timezone.utc)
    assert utc_dt.hour == 21
    assert utc_dt.date() == date(2026, 5, 26)


def test_rss_module_shares_jst_with_config():
    """rss.JST は config.JST と同じ実体（タイムゾーン定義の重複防止）。"""
    assert rss.JST is config.JST


# ---- publish.py / generate_podcast.py は与えられた today をそのまま使う ----


def test_publish_create_release_uses_given_date(monkeypatch, tmp_path):
    """create_release のタグ・タイトルが渡された JST 日付の isoformat() になる。"""
    mp3 = tmp_path / "episode.mp3"
    mp3.write_bytes(b"x" * 2048)

    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(publish_module.shutil, "which", lambda name: "/bin/gh")
    monkeypatch.setattr(
        publish_module,
        "_run",
        lambda cmd, **kw: (calls.append(list(cmd)), _Proc())[1],
    )

    jst_date = date(2026, 5, 27)
    publish_module.create_release(mp3, jst_date, repo="owner/repo")

    create_calls = [c for c in calls if "release" in c and "create" in c]
    assert len(create_calls) == 1
    cmd = create_calls[0]
    # gh release create <tag> ... の <tag> 位置に JST 日付
    assert "2026-05-27" in cmd
    # title にも入っている
    title_idx = cmd.index("--title")
    assert "2026-05-27" in cmd[title_idx + 1]


def test_generate_podcast_notebook_title_uses_given_date():
    """notebook 名フォーマットは渡された JST 日付に置換される。"""
    jst_date = date(2026, 5, 27)
    title = config.NOTEBOOK_NAME_FORMAT.format(date=jst_date.isoformat())
    assert "2026-05-27" in title
    # cron 発火直後の UTC 日付 (2026-05-26) は含まれない
    assert "2026-05-26" not in title


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
