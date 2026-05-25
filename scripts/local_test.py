"""ローカル試走スクリプト。

  uv run python scripts/local_test.py --fetch-only   # arXiv取得のみ
  uv run python scripts/local_test.py --no-publish   # NotebookLM生成までで止める
  uv run python scripts/local_test.py --dry-run      # 全工程通すが git push しない
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

# `python scripts/local_test.py` でも import できるようリポジトリ直下を sys.path に
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src import config  # noqa: E402
from src.fetch_arxiv import (  # noqa: E402
    fetch_latest_papers,
    load_published_ids,
    record_published_ids,
)


def _print_papers(papers) -> None:
    if not papers:
        print("(該当論文0本)")
        return
    for i, p in enumerate(papers, 1):
        authors = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors += f", … (+{len(p.authors) - 3})"
        print(f"{i:2d}. [{p.arxiv_id}] {p.title}")
        print(f"     by {authors}")
        print(f"     {p.abs_url}")
        print(f"     published: {p.published.isoformat()}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local test runner")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fetch-only", action="store_true", help="arXiv 取得のみ")
    mode.add_argument(
        "--no-publish",
        action="store_true",
        help="NotebookLM 生成までやって publish はしない",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="全工程を通すが git push と record は行わない",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    published_ids = load_published_ids()
    print(f"(履歴: 過去配信済 {len(published_ids)}件を除外)")
    papers = fetch_latest_papers(exclude_published_ids=published_ids)
    print(f"\n=== 取得 {len(papers)} 本 ===\n")
    _print_papers(papers)

    if args.fetch_only:
        return 0

    if not papers:
        print("該当論文なし。NotebookLM生成をスキップして終了。")
        return 0

    # 遅延 import: notebooklm CLI が未ログインでもfetch-onlyが動くようにする
    from src.generate_podcast import generate_audio_overview

    today = date.today()
    mp3_path = generate_audio_overview(papers, today)
    print(f"\n✔ MP3 生成完了: {mp3_path}")

    if args.no_publish:
        print("--no-publish のため publish はスキップ。")
        return 0

    from src.publish import publish_episode

    publish_episode(mp3_path, papers, today, dry_run=args.dry_run)

    if not args.dry_run:
        record_published_ids([p.arxiv_id for p in papers])
        print("✔ 配信済みIDを更新")
    else:
        print("--dry-run のため record_published_ids はスキップ")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
