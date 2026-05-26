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
from src.generate_podcast import NotebookLMRateLimitError, generate_audio_overview
from src.notify import notify
from src.publish import publish_episode
from src.rank_papers import rank_papers, select_top_n

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
            logger.info("no fresh papers in adaptive window, skipping today")
            notify(f"{today}: 📭 該当論文0本のため生成スキップ")
            return 0

        ranked = rank_papers(papers)
        selected = select_top_n(ranked, config.PAPERS_PER_EPISODE)
        mp3_path = generate_audio_overview(selected, today)
        publish_episode(mp3_path, selected, today)
        record_published_ids([p.arxiv_id for p in selected])
        notify(
            f"{today}: ✅ 候補{len(papers)}本→上位{len(selected)}本でエピソード配信完了"
        )
        return 0

    except NotebookLMRateLimitError as e:
        # 1日3回制限などのレートリミット。cron が翌日再試行するので
        # exit 0 で正常終了し、GitHub Actions の失敗通知を抑止する。
        # 「論文0本」とはログ内容・絵文字とも別物に。
        retry_hint = (
            f"（retry_after={e.retry_after}s）" if e.retry_after else ""
        )
        logger.info(
            "rate-limited by NotebookLM; cron will retry tomorrow%s", retry_hint
        )
        notify(
            f"{today}: 🛑 NotebookLM の1日3回制限に到達。"
            f"24時間後に再試行されます。{retry_hint}"
        )
        return 0

    except Exception as e:
        logger.exception("daily pipeline failed")
        notify(f"{today}: ❌ 失敗 — {type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    sys.exit(main())
