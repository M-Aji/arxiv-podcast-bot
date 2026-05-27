"""Podcast RSS 2.0 (iTunes 拡張あり) の生成・更新。

実装方針: 既存の `feed/podcast.xml` をパースしてエピソード一覧に戻し、
今回のエピソードを先頭に積んで feedgen で全体を再生成する。XML を
single source of truth に保つことで状態ファイルの二重管理を避ける。
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Sequence

from feedgen.feed import FeedGenerator

from src import config
from src.config import JST
from src.fetch_arxiv import ArxivPaper

logger = logging.getLogger(__name__)


@dataclass
class Episode:
    date: date
    title: str
    description: str
    audio_url: str
    guid: str
    pub_date: datetime
    audio_size_bytes: int | None = None
    duration_seconds: int | None = None
    paper_ids: list[str] = field(default_factory=list)


# ---- 構築 ----------------------------------------------------------------


def format_description(papers: Sequence[ArxivPaper]) -> str:
    lines = ["本日の注目論文：", ""]
    for i, p in enumerate(papers, 1):
        author_summary = ", ".join(p.authors[:2])
        if len(p.authors) > 2:
            author_summary += f" et al."
        lines.append(f"{i}. {p.title} — {author_summary}")
        lines.append(f"   {p.abs_url}")
    return "\n".join(lines)


def episode_audio_url(today: date, *, repo: str | None = None) -> str:
    repo = repo or config.GITHUB_REPO
    return (
        f"https://github.com/{repo}/releases/download/"
        f"{today.isoformat()}/episode.mp3"
    )


def episode_guid(today: date) -> str:
    return f"arxiv-podcast-{today.isoformat()}"


def make_episode(
    papers: Sequence[ArxivPaper],
    today: date,
    *,
    audio_size_bytes: int | None = None,
    duration_seconds: int | None = None,
    repo: str | None = None,
) -> Episode:
    pub_dt = datetime.combine(today, time(6, 0, 0), tzinfo=JST)
    return Episode(
        date=today,
        title=config.NOTEBOOK_NAME_FORMAT.format(date=today.isoformat()),
        description=format_description(papers),
        audio_url=episode_audio_url(today, repo=repo),
        guid=episode_guid(today),
        pub_date=pub_dt,
        audio_size_bytes=audio_size_bytes,
        duration_seconds=duration_seconds,
        paper_ids=[p.arxiv_id for p in papers],
    )


# ---- XML 生成 -------------------------------------------------------------


def _format_duration(seconds: int | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_feed(episodes: Iterable[Episode]) -> bytes:
    """エピソード一覧から RSS XML (bytes, utf-8) を生成する。

    episodes は新しい順で渡される想定。
    """
    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title(config.PODCAST_TITLE)
    fg.description(config.PODCAST_DESCRIPTION)
    fg.author({"name": config.PODCAST_AUTHOR})
    fg.language(config.PODCAST_LANGUAGE)
    fg.link(href=config.GITHUB_PAGES_BASE_URL, rel="alternate")
    fg.link(
        href=f"{config.GITHUB_PAGES_BASE_URL}/feed/podcast.xml", rel="self"
    )
    fg.logo(config.PODCAST_IMAGE_URL)
    fg.image(config.PODCAST_IMAGE_URL)

    fg.podcast.itunes_author(config.PODCAST_AUTHOR)
    fg.podcast.itunes_category(config.PODCAST_CATEGORY)
    fg.podcast.itunes_image(config.PODCAST_IMAGE_URL)
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_summary(config.PODCAST_DESCRIPTION)

    for ep in episodes:
        fe = fg.add_entry(order="append")
        fe.id(ep.guid)
        fe.guid(ep.guid, permalink=False)
        fe.title(ep.title)
        fe.description(ep.description)
        fe.pubDate(ep.pub_date)
        fe.enclosure(
            ep.audio_url,
            str(ep.audio_size_bytes) if ep.audio_size_bytes is not None else "0",
            "audio/mpeg",
        )
        duration = _format_duration(ep.duration_seconds)
        if duration:
            fe.podcast.itunes_duration(duration)
        fe.podcast.itunes_explicit("no")

    return fg.rss_str(pretty=True)


# ---- XML 解析 -------------------------------------------------------------

_NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}


def _parse_duration(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        parts_i = [int(p) for p in parts]
    except ValueError:
        return None
    if len(parts_i) == 3:
        h, m, s = parts_i
    elif len(parts_i) == 2:
        h, m, s = 0, parts_i[0], parts_i[1]
    elif len(parts_i) == 1:
        return parts_i[0]
    else:
        return None
    return h * 3600 + m * 60 + s


def load_existing_episodes(path: Path | None = None) -> list[Episode]:
    """`feed/podcast.xml` を読み、Episode のリストとして返す。なければ []。"""
    path = path or config.FEED_FILE
    if not path.exists():
        return []
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        logger.error("existing feed is malformed (%s); starting fresh", exc)
        return []

    episodes: list[Episode] = []
    for item in tree.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        pub_date_text = item.findtext("pubDate")
        if pub_date_text:
            try:
                pub_dt = parsedate_to_datetime(pub_date_text)
            except (TypeError, ValueError):
                pub_dt = datetime.now(tz=JST)
        else:
            pub_dt = datetime.now(tz=JST)

        enclosure = item.find("enclosure")
        if enclosure is not None:
            audio_url = enclosure.get("url", "")
            length_attr = enclosure.get("length")
            try:
                size = int(length_attr) if length_attr else None
            except ValueError:
                size = None
        else:
            audio_url = ""
            size = None

        duration_text = item.findtext("itunes:duration", namespaces=_NS)
        duration = _parse_duration(duration_text)

        ep_date = pub_dt.astimezone(JST).date()
        episodes.append(
            Episode(
                date=ep_date,
                title=title,
                description=description,
                audio_url=audio_url,
                guid=guid or f"arxiv-podcast-{ep_date.isoformat()}",
                pub_date=pub_dt,
                audio_size_bytes=size,
                duration_seconds=duration,
            )
        )
    return episodes


# ---- 更新 ----------------------------------------------------------------


def update_feed(
    new_episode: Episode,
    *,
    path: Path | None = None,
    max_episodes: int | None = None,
) -> bytes:
    """既存フィードに `new_episode` を先頭追加して書き戻し、生成XMLを返す。

    同じ guid のエピソードが既に存在する場合は置き換える（再実行への耐性）。
    """
    path = path or config.FEED_FILE
    max_episodes = (
        max_episodes if max_episodes is not None else config.MAX_EPISODES_IN_FEED
    )

    existing = [
        ep for ep in load_existing_episodes(path) if ep.guid != new_episode.guid
    ]
    merged = [new_episode, *existing][:max_episodes]
    xml_bytes = build_feed(merged)
    # 書き戻す前に well-formed か確認
    ET.fromstring(xml_bytes)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(xml_bytes)
    logger.info(
        "wrote %s with %d episodes (newest=%s)",
        path,
        len(merged),
        new_episode.guid,
    )
    return xml_bytes


def format_pub_date(dt: datetime) -> str:
    """テスト用ヘルパ: pubDate を RFC 822 形式で返す。"""
    return format_datetime(dt)
