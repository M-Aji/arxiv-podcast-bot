"""arXiv API から最新論文を取得し、過去配信ぶんを除外して返す。"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import arxiv

from src import config

logger = logging.getLogger(__name__)

# entry_id 末尾の "v3" のようなバージョン表記を取り除く
_VERSION_SUFFIX = re.compile(r"v\d+$")


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    abs_url: str
    pdf_url: str
    published: datetime
    primary_category: str


def _arxiv_id_from_entry(entry_id: str) -> str:
    """`http://arxiv.org/abs/2405.12345v2` → `2405.12345`."""
    tail = entry_id.rsplit("/", 1)[-1]
    return _VERSION_SUFFIX.sub("", tail)


def _build_category_query(categories: Iterable[str]) -> str:
    return " OR ".join(f"cat:{c}" for c in categories)


def _matches_exclude_keywords(paper: ArxivPaper, keywords: Iterable[str]) -> bool:
    text = f"{paper.title}\n{paper.abstract}".lower()
    return any(kw.lower() in text for kw in keywords if kw)


def fetch_latest_papers(
    *,
    categories: Iterable[str] | None = None,
    n: int | None = None,
    query_days: int | None = None,
    exclude_keywords: Iterable[str] | None = None,
    exclude_published_ids: Iterable[str] | None = None,
    delay_seconds: float | None = None,
    now: datetime | None = None,
) -> list[ArxivPaper]:
    """指定カテゴリの最新論文を返す。

    取得は SubmittedDate 降順。`query_days` 以内に投稿されたものに絞り、
    除外キーワードと過去配信IDを取り除いたうえで最大 `n` 本を返す。
    """
    categories = list(categories or config.ARXIV_CATEGORIES)
    n = n if n is not None else config.PAPERS_PER_EPISODE
    query_days = query_days if query_days is not None else config.ARXIV_QUERY_DAYS
    exclude_keywords = list(exclude_keywords or config.EXCLUDE_KEYWORDS)
    excluded_ids = set(exclude_published_ids or ())
    delay_seconds = (
        delay_seconds if delay_seconds is not None else config.ARXIV_DELAY_SECONDS
    )
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=query_days)

    query = _build_category_query(categories)
    # 日付フィルタ＋除外でこぼれることを見越して多めに取る
    fetch_limit = max(n * 5, 50)

    client = arxiv.Client(
        page_size=min(fetch_limit, 100),
        delay_seconds=delay_seconds,
        num_retries=5,
    )
    search = arxiv.Search(
        query=query,
        max_results=fetch_limit,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    results: list[ArxivPaper] = []
    seen_ids: set[str] = set()

    for result in client.results(search):
        arxiv_id = _arxiv_id_from_entry(result.entry_id)
        if arxiv_id in seen_ids or arxiv_id in excluded_ids:
            continue

        published = result.published
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if published < cutoff:
            # SubmittedDate 降順なので、これ以降は古いものしか出ない
            break

        paper = ArxivPaper(
            arxiv_id=arxiv_id,
            title=result.title.strip(),
            authors=[a.name for a in result.authors],
            abstract=result.summary.strip(),
            abs_url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=result.pdf_url,
            published=published,
            primary_category=result.primary_category,
        )
        if _matches_exclude_keywords(paper, exclude_keywords):
            continue

        seen_ids.add(arxiv_id)
        results.append(paper)
        if len(results) >= n:
            break

    logger.info(
        "fetched %d papers from arXiv (categories=%s, days=%s)",
        len(results),
        categories,
        query_days,
    )
    return results


# ---- 配信済み論文IDの状態管理 --------------------------------------------


def load_published_ids(path: Path | None = None) -> set[str]:
    path = path or config.PUBLISHED_PAPERS_FILE
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("ids", []))


def record_published_ids(
    new_ids: Iterable[str], *, path: Path | None = None
) -> set[str]:
    """配信済みIDに `new_ids` を追記してファイルに書き戻す。返り値は更新後の全ID集合。"""
    path = path or config.PUBLISHED_PAPERS_FILE
    existing = load_published_ids(path)
    updated = existing | set(new_ids)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ids": sorted(updated)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated
