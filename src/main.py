"""日次ポッドキャスト生成パイプライン。

GitHub Actions から `uv run python -m src.main` で呼ばれる。
"""
from __future__ import annotations

import logging
import sys
from datetime import date

from src import config
from src.fetch_arxiv import (
    fetch_latest_papers,
    load_published_ids,
    record_published_ids,
)
from src.generate_podcast import generate_audio_overview
from src.notify import notify
from src.publish import publish_episode

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    today = date.today()
    try:
        published_ids = load_published_ids()
        papers = fetch_latest_papers(exclude_published_ids=published_ids)
        if not papers:
            notify(f"{today}: 該当論文0本のため生成スキップ")
            return 0

        mp3_path = generate_audio_overview(papers, today)
        publish_episode(mp3_path, papers, today)
        record_published_ids([p.arxiv_id for p in papers])
        notify(f"{today}: ✅ {len(papers)}本のエピソード配信完了")
        return 0

    except Exception as e:
        logger.exception("daily pipeline failed")
        notify(f"{today}: ❌ 失敗 — {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    sys.exit(main())
