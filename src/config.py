"""ユーザーが編集する想定の設定値を集約するモジュール。

コードで直書きせず、すべての設定はここに置く。
"""
from __future__ import annotations

from pathlib import Path

# ---- arXiv 検索設定 -------------------------------------------------------

ARXIV_CATEGORIES: list[str] = [
    "cs.AI",          # Artificial Intelligence
    "cs.LG",          # Machine Learning
    "cs.CL",          # Computation and Language (NLP)
    "cs.MA",          # Multi-Agent Systems
    "cs.SI",          # Social and Information Networks
    "cs.CY",          # Computers and Society
    "physics.soc-ph", # Physics and Society
]

# 取得ウィンドウ。最初は ARXIV_QUERY_DAYS で試し、取得本数が少ない場合は
# 倍々に拡大して ARXIV_QUERY_DAYS_MAX まで再試行する。arXiv は土日に新着
# 公開がない（金夜 ET → 土朝 UTC が最終バッチ）ため、月曜朝 UTC の実行は
# 1日窓だとゼロ件になりがち。
ARXIV_QUERY_DAYS: int = 1
ARXIV_QUERY_DAYS_MAX: int = 14
ARXIV_MIN_PAPERS: int = 5

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

# NotebookLM CLI 操作のタイムアウト設定
SOURCE_READY_POLL_INTERVAL_SECONDS: int = 10
SOURCE_READY_TIMEOUT_SECONDS: int = 10 * 60

# Audio 生成は 10〜20分かかる。`generate audio --wait --timeout 300` は
# 短めに切り、タイムアウトで返って来たレスポンスから task_id を救出し
# `artifact wait` で同じタスクを `AUDIO_WAIT_RETRY_TIMEOUT_SECONDS` まで
# `AUDIO_WAIT_CHUNK_SECONDS` 刻みでポーリングする。決して再生成しない。
AUDIO_INITIAL_WAIT_TIMEOUT_SECONDS: int = 300
AUDIO_WAIT_CHUNK_SECONDS: int = 600
AUDIO_WAIT_RETRY_TIMEOUT_SECONDS: int = 30 * 60

# ---- Podcast メタデータ ---------------------------------------------------

PODCAST_TITLE: str = "Daily arXiv Digest (JP)"
PODCAST_DESCRIPTION: str = (
    "毎朝の arXiv 注目論文10本を、NotebookLM が日本語ポッドキャストで紹介。"
)
PODCAST_AUTHOR: str = "M-Aji"
PODCAST_LANGUAGE: str = "ja"
PODCAST_CATEGORY: str = "Technology"
PODCAST_IMAGE_URL: str = "https://m-aji.github.io/arxiv-podcast-bot/cover.png"

# ---- 配信 -----------------------------------------------------------------

GITHUB_REPO: str = "M-Aji/arxiv-podcast-bot"
GITHUB_PAGES_BASE_URL: str = "https://m-aji.github.io/arxiv-podcast-bot"

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
