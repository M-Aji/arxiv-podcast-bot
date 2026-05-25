"""ユーザーが編集する想定の設定値を集約するモジュール。

コードで直書きせず、すべての設定はここに置く。
"""
from __future__ import annotations

from pathlib import Path

# ---- arXiv 検索設定 -------------------------------------------------------

ARXIV_CATEGORIES: list[str] = ["cs.AI", "cs.LG", "cs.CL"]
ARXIV_QUERY_DAYS: int = 1
PAPERS_PER_EPISODE: int = 10
EXCLUDE_KEYWORDS: list[str] = []

# arXiv API のレート制限。連続アクセス時の推奨間隔は3秒。
ARXIV_DELAY_SECONDS: float = 3.0

# ---- NotebookLM 生成指示 --------------------------------------------------

NOTEBOOK_NAME_FORMAT: str = "arXiv {date}"  # {date}=YYYY-MM-DD
AUDIO_OVERVIEW_INSTRUCTION: str = (
    "本日のarXiv注目論文を、機械学習に詳しくない聴衆にも分かるように、"
    "論文ごとに『何を解決した研究か』『使った手法』『主な結果』『限界』"
    "の順で2〜3分ずつ紹介してください。論文に書かれていないことは推測せず、"
    "不明な点はそう述べてください。"
)

# NotebookLM CLI 操作のタイムアウト・リトライ設定
SOURCE_READY_POLL_INTERVAL_SECONDS: int = 10
SOURCE_READY_TIMEOUT_SECONDS: int = 10 * 60
AUDIO_WAIT_RETRY_TIMEOUT_SECONDS: int = 30 * 60
GENERATE_AUDIO_MAX_RETRIES: int = 2

# ---- Podcast メタデータ ---------------------------------------------------

PODCAST_TITLE: str = "Daily arXiv Digest (JP)"
PODCAST_DESCRIPTION: str = (
    "毎朝の arXiv 注目論文10本を、NotebookLM が日本語ポッドキャストで紹介。"
)
PODCAST_AUTHOR: str = "Your Name"
PODCAST_LANGUAGE: str = "ja"
PODCAST_CATEGORY: str = "Technology"
PODCAST_IMAGE_URL: str = "https://yourname.github.io/arxiv-podcast-bot/cover.png"

# ---- 配信 -----------------------------------------------------------------

GITHUB_REPO: str = "yourname/arxiv-podcast-bot"
GITHUB_PAGES_BASE_URL: str = "https://yourname.github.io/arxiv-podcast-bot"

# RSS 保持エピソード上限
MAX_EPISODES_IN_FEED: int = 100

# ---- パス -----------------------------------------------------------------

# プロジェクトルート。state/、feed/、build/ の基準。
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

STATE_DIR: Path = PROJECT_ROOT / "state"
PUBLISHED_PAPERS_FILE: Path = STATE_DIR / "published_papers.json"

FEED_DIR: Path = PROJECT_ROOT / "feed"
FEED_FILE: Path = FEED_DIR / "podcast.xml"

BUILD_DIR: Path = PROJECT_ROOT / "build"
EPISODE_MP3_PATH: Path = BUILD_DIR / "episode.mp3"

# ---- 通知（任意、未設定ならスキップ） ------------------------------------

DISCORD_WEBHOOK_URL_ENV: str = "DISCORD_WEBHOOK_URL"
