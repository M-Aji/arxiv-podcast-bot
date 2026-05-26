# Smart Paper Ranking 実装仕様（Claude Haiku版）

このドキュメントをClaude Codeに渡して、以下の機能を実装してください。

## 概要

現状: arxivから10本取得 → そのまま全部NotebookLMに渡す
変更後: arxivから30本取得 → Claude Haikuで興味プロファイルとのマッチ度スコアリング → 上位5本だけNotebookLMに渡す

## 1. `src/config.py` 変更

### 1-1. 既存定数の値変更

```python
PAPERS_PER_EPISODE: int = 5     # 10 → 5
```

### 1-2. 新規定数を追加

```python
CANDIDATE_POOL_SIZE: int = 30
RANKING_MODEL: str = "claude-haiku-4-5"
RANKING_TIMEOUT_SECONDS: int = 30
ANTHROPIC_API_KEY_ENV: str = "ANTHROPIC_API_KEY"
```

### 1-3. INTEREST_PROFILE 定数を新規追加

以下の本文をそのまま多行文字列としてPythonに埋め込むこと。
章番号・改行・箇条書きの形式を保つ。

```python
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
```

## 2. `src/fetch_arxiv.py` 調整

- `fetch_latest_papers()` の `n` のデフォルト値を `PAPERS_PER_EPISODE` ではなく `CANDIDATE_POOL_SIZE` に変更
- 適応窓の `min_papers` 判定も `CANDIDATE_POOL_SIZE` 基準で

## 3. 新規モジュール `src/rank_papers.py`

```python
"""Claude Haiku による論文関連度スコアリング。"""

@dataclass
class RankedPaper:
    paper: ArxivPaper
    score: float       # 0.0-10.0
    rationale: str     # 日本語1行の理由

def rank_papers(candidates: list[ArxivPaper]) -> list[RankedPaper]:
    """各論文をClaude Haikuで0-10スコアリングし、降順ソートで返す。"""

def select_top_n(ranked: list[RankedPaper], n: int) -> list[ArxivPaper]:
    """上位 n 本の ArxivPaper を返す。"""
```

### スコアリング詳細

各論文ごとに個別にClaude APIを呼ぶ（バッチ送信ではない、エラー耐性のため）。

**system プロンプト：**

```
あなたは研究者の興味プロファイルに基づいて論文を評価するアシスタントです。
以下のプロファイルを基準に、与えられた論文がこの研究者にとってどの程度
関連性が高いかを 0.0〜10.0 でスコアリングしてください。

評価軸:
- プロファイルの「強く興味あり/優先度高」のテーマと合致 → 7.0〜10.0
- 「普通に興味あり/優先度中」のテーマと合致 → 4.0〜7.0
- 「スキップしたい/優先度低」に該当 → 0.0〜3.0
- どれにも明確に当てはまらない → 3.0〜5.0

出力は厳密に以下のJSON形式のみ（前後に何も書かない）:
{"score": <float>, "rationale": "<日本語で1行、なぜこのスコアなのか>"}

プロファイル:
<config.INTEREST_PROFILE をここに展開>
```

**user プロンプト：**

```
タイトル: <paper.title>
要約: <paper.abstract>
```

### 技術要件

- `anthropic` Python SDK の Messages API を使用
- `model=config.RANKING_MODEL`, `max_tokens=200`, `temperature=0.3`
- `timeout=config.RANKING_TIMEOUT_SECONDS`
- リトライ3回、指数バックオフ（1秒 → 2秒 → 4秒）
- 単一論文の評価失敗時:
  - スコア 5.0、`rationale="(評価失敗のため中立評価)"` で続行
  - WARNINGログ
- 全件失敗 or `ANTHROPIC_API_KEY` 未設定:
  - WARNINGログを出力
  - 全候補に score=5.0, rationale="(ranking skipped)" を割り当て
  - 元の `candidates` 順をそのまま維持
- 各論文のスコアと理由はINFOログ:
  ```
  ranked: 8.5 | LLM Agents for Urban Mobility Simulation... | LLMエージェント＋交通シミュレーションで強く合致
  ```

## 4. `src/main.py` 修正

```python
from src.rank_papers import rank_papers, select_top_n

papers = fetch_latest_papers(...)   # CANDIDATE_POOL_SIZE 本
if not papers:
    ...
ranked = rank_papers(papers)
selected = select_top_n(ranked, config.PAPERS_PER_EPISODE)
mp3_path = generate_audio_overview(selected, today)
publish_episode(mp3_path, selected, today)
record_published_ids([p.arxiv_id for p in selected])
...
notify(f"{today}: ✅ 候補{len(papers)}本→上位{len(selected)}本でエピソード配信完了")
```

## 5. 依存追加

`pyproject.toml` に `anthropic>=0.45.0` を追加。

## 6. GitHub Actions ワークフロー

`.github/workflows/daily-podcast.yml` の `Run podcast generation` ステップに env を追加：

```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## 7. テスト `tests/test_rank_papers.py`（新規）

以下を網羅:

- スコアパース成功 → 順序が正しい降順
- API完全失敗 → フォールバック（全件 score=5.0、元の順序維持）
- 部分失敗（10本中3本のAPI失敗）→ 残り7本は正しくスコアリング、失敗3本は score=5.0
- 空入力 → 空出力
- `ANTHROPIC_API_KEY` 未設定 → フォールバック動作
- `select_top_n`: n より少ない入力でも壊れない
- JSON パース失敗（モデルが不正な出力を返した場合）→ フォールバック、リトライ

anthropic SDK の `Messages.create` を `pytest-mock` でモック化。

## 8. README.md 更新

「興味プロファイルの編集」セクションを追加し、`src/config.py` の `INTEREST_PROFILE`
を書き換えるだけで選定基準を変更できる旨を案内。

## 9. コミット & push

コミットメッセージ:

```
Add Claude Haiku based paper ranking for daily 5-paper selection from a 30-paper pool

- Fetch 30 candidate papers per day (was 10), rank by relevance to user's
  interest profile via Claude Haiku, pick top 5 for the NotebookLM podcast.
- Interest profile lives in src/config.py and is the single point of edit
  for changing selection criteria.
- Falls back to "publication date order" if ANTHROPIC_API_KEY is missing
  or the API fails entirely, so the bot keeps working even without ranking.
```

実装完了後、push してください。
