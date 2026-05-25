"""rss モジュールのテスト。"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src import rss
from src.fetch_arxiv import ArxivPaper

_NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}


def _paper(arxiv_id: str, title: str, *authors: str) -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=title,
        authors=list(authors) or ["Alice"],
        abstract="Abstract text.",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        published=datetime(2026, 5, 25, 0, 0, tzinfo=timezone.utc),
        primary_category="cs.AI",
    )


def test_format_description_lists_papers():
    papers = [
        _paper("2405.00001", "Paper A", "Alice", "Bob"),
        _paper("2405.00002", "Paper B", "Carol", "Dan", "Eve"),
    ]
    desc = rss.format_description(papers)
    assert "1. Paper A — Alice, Bob" in desc
    assert "2. Paper B — Carol, Dan et al." in desc
    assert "https://arxiv.org/abs/2405.00001" in desc


def test_episode_audio_url_uses_repo():
    url = rss.episode_audio_url(date(2026, 5, 25), repo="me/podcast")
    assert url == (
        "https://github.com/me/podcast/releases/download/2026-05-25/episode.mp3"
    )


def test_format_duration_zero_padded():
    assert rss._format_duration(930) == "00:15:30"
    assert rss._format_duration(None) is None
    assert rss._format_duration(3661) == "01:01:01"


def test_make_episode_uses_jst_06():
    papers = [_paper("2405.00001", "Paper A")]
    ep = rss.make_episode(papers, date(2026, 5, 25), audio_size_bytes=12345)
    assert ep.pub_date.hour == 6
    assert ep.pub_date.minute == 0
    assert ep.pub_date.utcoffset().total_seconds() == 9 * 3600
    assert ep.guid == "arxiv-podcast-2026-05-25"
    assert ep.audio_size_bytes == 12345
    assert ep.paper_ids == ["2405.00001"]


def test_build_feed_produces_well_formed_xml_with_required_elements():
    papers = [_paper("2405.00001", "Paper A")]
    ep = rss.make_episode(
        papers,
        date(2026, 5, 25),
        audio_size_bytes=10_000,
        duration_seconds=930,
    )
    xml_bytes = rss.build_feed([ep])
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    assert channel is not None
    items = channel.findall("item")
    assert len(items) == 1
    item = items[0]
    assert item.findtext("title") == "arXiv 2026-05-25"
    assert item.findtext("guid") == "arxiv-podcast-2026-05-25"
    enclosure = item.find("enclosure")
    assert enclosure is not None
    assert enclosure.get("type") == "audio/mpeg"
    assert enclosure.get("length") == "10000"
    assert enclosure.get("url").endswith("/2026-05-25/episode.mp3")
    assert item.findtext("itunes:duration", namespaces=_NS) == "00:15:30"


def test_update_feed_prepends_new_episode(tmp_path: Path):
    feed_path = tmp_path / "podcast.xml"
    ep1 = rss.make_episode(
        [_paper("2405.00001", "Older")],
        date(2026, 5, 24),
        audio_size_bytes=1000,
    )
    rss.update_feed(ep1, path=feed_path)

    ep2 = rss.make_episode(
        [_paper("2405.00002", "Newer")],
        date(2026, 5, 25),
        audio_size_bytes=2000,
    )
    rss.update_feed(ep2, path=feed_path)

    root = ET.fromstring(feed_path.read_bytes())
    items = root.findall("./channel/item")
    titles = [it.findtext("title") for it in items]
    assert titles[0] == "arXiv 2026-05-25"
    assert titles[1] == "arXiv 2026-05-24"


def test_update_feed_replaces_same_guid(tmp_path: Path):
    feed_path = tmp_path / "podcast.xml"
    ep1 = rss.make_episode(
        [_paper("2405.00001", "First take")],
        date(2026, 5, 25),
        audio_size_bytes=1000,
    )
    rss.update_feed(ep1, path=feed_path)

    ep2 = rss.make_episode(
        [_paper("2405.00002", "Retry")],
        date(2026, 5, 25),
        audio_size_bytes=2000,
    )
    rss.update_feed(ep2, path=feed_path)

    items = ET.fromstring(feed_path.read_bytes()).findall("./channel/item")
    assert len(items) == 1
    enclosure = items[0].find("enclosure")
    assert enclosure.get("length") == "2000"


def test_update_feed_respects_max_episodes(tmp_path: Path):
    feed_path = tmp_path / "podcast.xml"
    for day in range(1, 6):
        ep = rss.make_episode(
            [_paper(f"2405.0000{day}", f"Day {day}")],
            date(2026, 5, day),
            audio_size_bytes=day * 100,
        )
        rss.update_feed(ep, path=feed_path, max_episodes=3)

    items = ET.fromstring(feed_path.read_bytes()).findall("./channel/item")
    assert len(items) == 3
    titles = [it.findtext("title") for it in items]
    assert titles == ["arXiv 2026-05-05", "arXiv 2026-05-04", "arXiv 2026-05-03"]


def test_load_existing_episodes_handles_missing_file(tmp_path: Path):
    assert rss.load_existing_episodes(tmp_path / "absent.xml") == []


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
