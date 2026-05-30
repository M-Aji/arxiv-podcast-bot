"""ユーザーが編集する想定の設定値を集約するモジュール。

コードで直書きせず、すべての設定はここに置く。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ---- タイムゾーン ---------------------------------------------------------
# 配信日は日本時間（JST）基準で決める。cron が 21:00 UTC = 06:00 JST に
# 発火するため、`date.today()` (= UTC) を素朴に使うと「昨日の日付」で
# ノートブック名・タグ・ファイル名が生成されてしまう。
JST: timezone = timezone(timedelta(hours=9))


def today_jst() -> date:
    """JST 基準の本日日付。全モジュールで配信日を決める唯一の入口。"""
    return datetime.now(JST).date()

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

PAPERS_PER_EPISODE: int = 5
EXCLUDE_KEYWORDS: list[str] = []

# arXiv API のレート制限。連続アクセス時の推奨間隔は3秒。
ARXIV_DELAY_SECONDS: float = 3.0

# ---- 論文ランキング（Claude Haiku） ---------------------------------------

# arXiv から取得する候補プール本数（この中から PAPERS_PER_EPISODE 本を選抜）
CANDIDATE_POOL_SIZE: int = 30
RANKING_MODEL: str = "claude-haiku-4-5"
RANKING_TIMEOUT_SECONDS: int = 30
ANTHROPIC_API_KEY_ENV: str = "ANTHROPIC_API_KEY"

INTEREST_PROFILE: str = """\
# Daily arXiv Audio Digest 用・論文選定プロファイル

## 目的

私は、研究者として日々の研究インプットを継続するために、arXivから毎朝10本程度の論文を抽出し、通勤中に音声で聴きたい。

目的は、毎日10本を精読することではなく、最新研究の流れに触れ、後で読むべき論文や研究アイデアの種を見つけることである。そのため、音声では細部よりも、研究の問題設定、方法、主な知見、限界、応用可能性を把握できればよい。

## 自分の立場

私は、都市計画・交通計画・社会データ分析を専門とする応用研究者である。
SNS、YouTubeコメント、メディア言説、人流・プローブデータ、交通安全、災害情報、都市政策などを対象に、機械学習、テキスト分析、空間分析、シミュレーション、LLMを活用した研究に関心がある。

純粋なAI理論研究者ではなく、AI・機械学習・LLMを社会課題や都市・交通・情報空間の分析に応用する立場である。

## 知識レベル

機械学習、自然言語処理、LLM、統計分析、社会ネットワーク分析については基礎的な知識がある。
ただし、最新のAI研究については、詳細な数式や実装上の細部よりも、以下を把握できればよい。

- 何を問題にしているのか
- どのような方法を使っているのか
- 既存研究と何が違うのか
- どのような結果が得られたのか
- 限界や注意点は何か
- 自分の研究や学生指導にどう関係しそうか

## 用途

主な用途は、通勤中の流し聴きである。
音声で聞いて面白そうだと思った論文だけ、後で原文を読む。
したがって、論文選定では「専門的に深すぎるが応用先が見えにくい論文」よりも、「概念が分かりやすく、自分の研究に接続できそうな論文」を優先する。

---

# 論文選定の優先度

## 強く興味あり / 優先度高

以下のテーマを最優先で抽出する。

### 1. LLM・基盤モデルの能力と限界

大規模言語モデル、基盤モデル、マルチモーダルモデルの能力、限界、評価、失敗パターン、社会実装上の課題に関する研究を重視する。

特に関心がある内容：

- LLMの推論能力
- LLMの限界、誤り、ハルシネーション
- LLM評価手法
- LLMを用いた社会データ分析
- LLMによるテキスト分類、要約、トピック抽出
- LLMの政策・研究支援への応用
- RAG、根拠付き生成、ソース接地型生成

### 2. AIエージェント、マルチエージェント協調

AIエージェント、LLMエージェント、マルチエージェントシステム、エージェントベースシミュレーションに関する研究を重視する。

特に関心がある内容：

- LLMエージェント
- マルチエージェント協調
- エージェント間コミュニケーション
- 社会シミュレーション
- 群衆行動、避難行動、交通行動のシミュレーション
- 人間行動モデル
- AIを用いた仮想社会・仮想都市・仮想交通環境

### 3. AIの社会的影響、ガバナンス、安全性

AIが社会、政策、公共圏、民主主義、教育、労働、研究活動に与える影響に関する研究を重視する。

特に関心がある内容：

- AIガバナンス
- AI安全性
- AI倫理
- AIと社会制度
- AIと公共政策
- AIと選挙・政治コミュニケーション
- AIとメディア環境
- AIによる情報操作、誤情報、世論形成
- AI活用のリスク評価

### 4. 情報ネットワーク・社会ネットワーク分析

SNS、YouTube、ニュース、オンラインコミュニティ、情報拡散、世論形成、社会ネットワークに関する研究を重視する。

特に関心がある内容：

- 情報拡散
- SNS分析
- YouTubeコメント分析
- オンライン公共圏
- メディア言説分析
- 選挙・政治コミュニケーション
- 災害時の情報流通
- 社会ネットワーク分析
- 計算社会科学
- computational social science

### 5. 因果推論・因果機械学習

因果推論、因果機械学習、政策評価、処置効果推定、反実仮想分析に関する研究を重視する。
特に観察データから因果関係を推定する手法と、社会・都市・交通データへの応用を優先する。

特に関心がある内容：

- 因果推論（causal inference）の手法論
- 因果機械学習（causal machine learning）
- 処置効果推定（ATE、CATE、HTE などの treatment effect estimation）
- 反実仮想分析（counterfactual analysis）
- 操作変数法、傾向スコア、差分の差分法、回帰不連続デザイン
- 因果探索（causal discovery）
- 政策評価・プログラム評価への応用
- 都市政策・交通政策・社会政策の因果効果分析
- LLM・AI を活用した因果推論支援
- 観察研究における選択バイアス・交絡の扱い

---

## 普通に興味あり / 優先度中

以下のテーマは、応用可能性が高い場合に抽出する。

### 1. 機械学習の応用研究

医療、教育、都市、交通、防災、行政、環境、社会科学などへの機械学習応用に関心がある。

ただし、個別分野の性能改善だけでなく、方法論や研究設計が自分の研究に転用できそうなものを優先する。

優先するもの：

- 社会課題へのAI応用
- 公共政策へのAI応用
- 都市・交通・防災へのAI応用
- 教育・研究支援へのAI応用
- 実データを用いた分析
- 解釈可能性、説明可能性、評価設計が含まれる研究

### 2. 推論能力

LLMやAIモデルのreasoning、chain-of-thought、planning、multi-step reasoningに関する研究に関心がある。

ただし、純粋なベンチマーク改善よりも、実世界タスクや社会データ分析に関係しそうな研究を優先する。

### 3. ヒューマン-AI協調

人間とAIの協調、AIによる研究支援、意思決定支援、教育支援、政策形成支援に関する研究に関心がある。

特に関心がある内容：

- human-AI collaboration
- human-in-the-loop
- AI-assisted research
- AI-assisted decision making
- AIを使った知識整理
- AIと専門家判断の組み合わせ

---

## スキップしたい / 優先度低

以下の論文は、原則として選定しない。

### 1. 純粋数学的な理論解析だけの論文

数学的には高度でも、応用先や社会的含意が見えにくいものは優先しない。

スキップ例：

- 汎化誤差の純粋理論解析のみ
- 最適化理論のみ
- 証明中心で応用例がほぼない論文
- 数式展開が主で、実データや社会応用がない論文

### 2. 画像生成・動画生成の品質改善系

画像生成、動画生成、3D生成、拡散モデルの画質改善だけを目的とする論文は、基本的に優先しない。

スキップ例：

- diffusion modelの画質改善
- text-to-image生成の品質向上
- video generationの視覚品質改善
- 画像編集・スタイル変換のみ
- benchmark上のFID改善のみ

ただし、災害、都市、交通、社会調査、空間分析などに応用可能な場合は例外的に残してよい。

### 3. 狭いベンチマーク改善のみの論文

特定データセットや特定ベンチマークでの性能向上だけを目的とする論文は優先しない。

スキップ例：

- 既存モデルの精度を数％改善しただけの論文
- 新規性がベンチマークスコアの改善に偏っている論文
- 応用上の意味や限界の議論が薄い論文
- 自分の研究分野への転用可能性が低い論文
"""

# ---- NotebookLM 生成指示 --------------------------------------------------

NOTEBOOK_NAME_FORMAT: str = "arXiv {date}"  # {date}=YYYY-MM-DD
AUDIO_OVERVIEW_INSTRUCTION: str = (
    "本日のarXiv注目論文を、機械学習に詳しくない聴衆にも分かるように、"
    "論文ごとに『何を解決した研究か』『使った手法』『主な結果』『限界』"
    "の順で2〜3分ずつ紹介してください。論文に書かれていないことは推測せず、"
    "不明な点はそう述べてください。"
)

# NotebookLM CLI 操作のタイムアウト設定。
# PDF を source に渡すようになってからは abstract URL より処理に時間がかかる
# ので、ready 待ちを 15 分まで広めに取る。ポーリング間隔は 10s のまま。
SOURCE_READY_POLL_INTERVAL_SECONDS: int = 10
SOURCE_READY_TIMEOUT_SECONDS: int = 15 * 60

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

# arXiv PDF をローカルに落としてから NotebookLM にアップロードする。
# URL 直渡しだと NotebookLM サーバ側で NETWORK_ERROR / GENERATION_FAILED が
# 頻発したため、こちらで PDF を確保して file 型 source として上げる。
PDF_DOWNLOAD_DIR: Path = BUILD_DIR / "pdfs"
PDF_DOWNLOAD_TIMEOUT_SECONDS: int = 60
PDF_DOWNLOAD_MAX_SIZE_MB: int = 20

# ---- 通知（任意、未設定ならスキップ） ------------------------------------

DISCORD_WEBHOOK_URL_ENV: str = "DISCORD_WEBHOOK_URL"
