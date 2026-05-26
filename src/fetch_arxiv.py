"""arXiv API から最新論文を取得し、過去配信ぶんを除外して返す。"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import arxiv

from src import config

logger = logging.getLogger(__name__)

# entry_id 末尾の "v3" のようなバージョン表記を取り除く
_VERSION_SUFFIX = re.compile(r"v\d+$")

# arXiv API が返す「冷ましてくれ」系ステータス。これ以外の HTTPError は
# 本物のバグの可能性が高いので素通しする。
_RATE_LIMIT_STATUSES = frozenset({429, 503})

# arxiv ライブラリ内部のリトライ (num_retries=5) を越えてなお 429/503 が
# 返ってくる場合のアプリ層リトライ間隔。arxiv 側が落ち着くのを待つために
# だいぶ長め (合計約5分) に取る。値の数だけ追加リトライが走る。
_FETCH_RETRY_BACKOFFS_SECONDS: tuple[int, ...] = (30, 90, 180)


class ArxivRateLimitError(Exception):
    """arXiv API がアプリ層リトライ後も 429/503 を返し続けたときに raise。"""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


def _fetch_window(
    *,
    categories: list[str],
    n: int,
    query_days: int,
    exclude_keywords: list[str],
    excluded_ids: set[str],
    delay_seconds: float,
    now: datetime,
) -> list[ArxivPaper]:
    """1つの時間窓 (`query_days`) で取得して返す。

    arxiv ライブラリ内部のリトライを越えて 429/503 が返ってきたら、
    `_FETCH_RETRY_BACKOFFS_SECONDS` の間隔で _fetch_window 全体を再試行。
    それでも失敗したら `ArxivRateLimitError` を raise する（呼び出し側の
    `fetch_latest_papers` はこれを catch せず、窓拡大ループに入らない）。
    """
    last_error: arxiv.HTTPError | None = None
    total_attempts = len(_FETCH_RETRY_BACKOFFS_SECONDS) + 1
    for attempt in range(1, total_attempts + 1):
        try:
            return _fetch_window_once(
                categories=categories,
                n=n,
                query_days=query_days,
                exclude_keywords=exclude_keywords,
                excluded_ids=excluded_ids,
                delay_seconds=delay_seconds,
                now=now,
            )
        except arxiv.HTTPError as exc:
            if exc.status not in _RATE_LIMIT_STATUSES:
                raise
            last_error = exc
            if attempt < total_attempts:
                backoff = _FETCH_RETRY_BACKOFFS_SECONDS[attempt - 1]
                logger.warning(
                    "arXiv HTTP %d (attempt %d/%d); sleeping %ds before retry",
                    exc.status,
                    attempt,
                    total_attempts,
                    backoff,
                )
                time.sleep(backoff)
            else:
                logger.error(
                    "arXiv HTTP %d after %d attempts; giving up",
                    exc.status,
                    total_attempts,
                )

    assert last_error is not None
    raise ArxivRateLimitError(
        f"arXiv API returned HTTP {last_error.status} after {total_attempts} attempts",
        status=last_error.status,
    )


def _fetch_window_once(
    *,
    categories: list[str],
    n: int,
    query_days: int,
    exclude_keywords: list[str],
    excluded_ids: set[str],
    delay_seconds: float,
    now: datetime,
) -> list[ArxivPaper]:
    """単一窓ぶんの 1 回の取得。レートリミットリトライは `_fetch_window` 側。"""
    cutoff = now - timedelta(days=query_days)
    query = _build_category_query(categories)
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

    return results


def _next_window(current_days: int, max_days: int) -> int:
    """窓拡大の次値。倍々で、上限を超えないように丸める。"""
    return min(current_days * 2, max_days)


def fetch_latest_papers(
    *,
    categories: Iterable[str] | None = None,
    n: int | None = None,
    query_days: int | None = None,
    query_days_max: int | None = None,
    min_papers: int | None = None,
    exclude_keywords: Iterable[str] | None = None,
    exclude_published_ids: Iterable[str] | None = None,
    delay_seconds: float | None = None,
    now: datetime | None = None,
) -> list[ArxivPaper]:
    """最新論文を返す。少ない場合は窓を倍々に拡大して再取得する。

    取得は SubmittedDate 降順。最初に `query_days` 窓で取得し、結果が
    `n` 未満かつ `min_papers` 未満ならば窓を 1 → 2 → 4 → 8 → … と倍々
    （上限 `query_days_max`）で再試行する。
    """
    categories = list(categories or config.ARXIV_CATEGORIES)
    n = n if n is not None else config.CANDIDATE_POOL_SIZE
    start_days = query_days if query_days is not None else config.ARXIV_QUERY_DAYS
    max_days = (
        query_days_max if query_days_max is not None else config.ARXIV_QUERY_DAYS_MAX
    )
    min_papers = (
        min_papers if min_papers is not None else config.CANDIDATE_POOL_SIZE
    )
    exclude_keywords = list(exclude_keywords or config.EXCLUDE_KEYWORDS)
    excluded_ids = set(exclude_published_ids or ())
    delay_seconds = (
        delay_seconds if delay_seconds is not None else config.ARXIV_DELAY_SECONDS
    )
    now = now or datetime.now(timezone.utc)

    days = max(1, start_days)
    max_days = max(days, max_days)

    results: list[ArxivPaper] = []
    attempt = 0
    while True:
        if attempt > 0:
            # 連続でクライアントを作るとレート制限に当たりやすいので一拍置く
            time.sleep(delay_seconds)

        results = _fetch_window(
            categories=categories,
            n=n,
            query_days=days,
            exclude_keywords=exclude_keywords,
            excluded_ids=excluded_ids,
            delay_seconds=delay_seconds,
            now=now,
        )
        attempt += 1
        logger.info(
            "fetched %d papers from arXiv (categories=%s, days=%d)",
            len(results),
            categories,
            days,
        )

        if len(results) >= n or len(results) >= min_papers:
            return results
        if days >= max_days:
            logger.warning(
                "上限 %d 日に到達、結果 %d 本で諦め", max_days, len(results)
            )
            return results

        next_days = _next_window(days, max_days)
        logger.info(
            "窓拡大: %d日 → %d日 (取得%d本)", days, next_days, len(results)
        )
        days = next_days


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
