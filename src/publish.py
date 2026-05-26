"""配信フェーズ: mp3 を GitHub Release に上げ、RSS を更新してコミット。"""
from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Sequence

from src import config, rss
from src.fetch_arxiv import ArxivPaper

logger = logging.getLogger(__name__)


class PublishError(RuntimeError):
    """publish フェーズのエラーをまとめる。"""


def _run(cmd: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    logger.debug("$ %s", " ".join(cmd))
    proc = subprocess.run(list(cmd), capture_output=True, text=True)
    if proc.stdout:
        logger.debug("stdout: %s", proc.stdout.strip())
    if proc.stderr:
        logger.debug("stderr: %s", proc.stderr.strip())
    if check and proc.returncode != 0:
        raise PublishError(
            f"command failed (exit {proc.returncode}): {' '.join(cmd)}\n"
            f"stderr: {proc.stderr}"
        )
    return proc


def _require_gh() -> None:
    if shutil.which("gh") is None:
        raise PublishError(
            "gh CLI not found on PATH. Install via `brew install gh` "
            "or set up the GitHub Actions environment."
        )


def create_release(
    mp3_path: Path,
    today: date,
    *,
    repo: str | None = None,
    notes: str | None = None,
) -> None:
    """`gh release create` で当日の Release を作る。既存タグなら upload に切り替え。"""
    _require_gh()
    if not mp3_path.exists():
        raise PublishError(f"mp3 not found: {mp3_path}")

    repo = repo or config.GITHUB_REPO
    tag = today.isoformat()
    title = config.NOTEBOOK_NAME_FORMAT.format(date=tag)
    notes = notes or "本日の10論文"

    proc = _run(
        [
            "gh",
            "release",
            "create",
            tag,
            str(mp3_path),
            "--repo",
            repo,
            "--title",
            title,
            "--notes",
            notes,
        ],
        check=False,
    )
    if proc.returncode == 0:
        logger.info("created release %s on %s", tag, repo)
        return

    if "already exists" in proc.stderr.lower():
        logger.info("release %s exists; uploading asset with --clobber", tag)
        _run(
            [
                "gh",
                "release",
                "upload",
                tag,
                str(mp3_path),
                "--repo",
                repo,
                "--clobber",
            ]
        )
        return

    raise PublishError(
        f"gh release create failed (exit {proc.returncode}): {proc.stderr}"
    )


def update_rss(
    papers: Sequence[ArxivPaper],
    mp3_path: Path,
    today: date,
    *,
    feed_path: Path | None = None,
) -> Path:
    feed_path = feed_path or config.FEED_FILE
    size = mp3_path.stat().st_size if mp3_path.exists() else None
    episode = rss.make_episode(
        papers, today, audio_size_bytes=size, repo=config.GITHUB_REPO
    )
    rss.update_feed(episode, path=feed_path)
    return feed_path


def commit_and_push(
    paths: Sequence[Path], today: date, *, dry_run: bool = False
) -> None:
    """変更ファイルを stage → commit → push する。dry_run の場合は表示のみ。

    渡されたパスのうち実在するものだけを `git add` 対象にする。全パスが
    不在なら何もしない（初回実行で `published_papers.json` がまだ無い等で
    `git add` が exit 128 にならないように）。stage 後に変更が無ければ
    commit/push もスキップする。
    """
    existing = [p for p in paths if Path(p).exists()]
    missing = [p for p in paths if not Path(p).exists()]
    for p in missing:
        logger.info("skip non-existent path for git add: %s", p)

    if not existing:
        logger.info("no existing paths to stage — skipping commit")
        return

    paths_str = [str(p) for p in existing]
    if dry_run:
        logger.info("[dry-run] would `git add %s` and push", " ".join(paths_str))
        return

    _run(["git", "add", *paths_str])
    status = _run(["git", "diff", "--cached", "--quiet"], check=False)
    if status.returncode == 0:
        logger.info("no staged changes — skipping commit")
        return

    message = f"Daily episode {today.isoformat()}"
    _run(["git", "commit", "-m", message])
    _run(["git", "push"])
    logger.info("pushed episode %s", today.isoformat())


def publish_episode(
    mp3_path: Path,
    papers: Sequence[ArxivPaper],
    today: date,
    *,
    dry_run: bool = False,
) -> None:
    """Release 作成 → RSS 更新 → コミット&プッシュをまとめて実行する。"""
    if dry_run:
        logger.info("[dry-run] skipping gh release create")
    else:
        create_release(mp3_path, today)

    feed_path = update_rss(papers, mp3_path, today)
    commit_and_push(
        [feed_path, config.PUBLISHED_PAPERS_FILE],
        today,
        dry_run=dry_run,
    )
