# arXiv Daily Podcast Bot — 仕様書

## 1. プロジェクト概要

毎朝6:00 JSTに arXiv から論文10本を取得し、NotebookLM の Audio Overview（2人対話形式の日本語ポッドキャスト）を自動生成、自分専用のRSSフィードに配信するbot。Podcastアプリで通勤中に再生する個人用システム。

**コア要件**
- 完全自動化（人手介入は2週間に1回の認証更新のみ）
- ハルシネーション最小化（NotebookLMのRAGに依存）
- 月額コストは可能な限り低く（理想は無料）
- 失敗時は通知される（黙って止まらない）

**非要件**
- 一般公開（自分が聴ければよい）
- 高度な論文選定アルゴリズム（latest 10で十分、後で拡張可能な設計）
- マルチユーザー対応

---

## 2. アーキテクチャ

```
┌────────────────────────────────────────────────────────┐
│ GitHub Actions (毎日 21:00 UTC = 06:00 JST に発火)     │
└────────────────────┬───────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────┐
│ 1. arXiv API から指定カテゴリの最新論文を取得（10本）  │
│    - 3秒間隔のレート制限を遵守                          │
│    - 重複・既出論文を除外                               │
└────────────────────┬───────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────┐
│ 2. notebooklm-py CLI で NotebookLM 操作                │
│    - storage_state.json をsecretから復元                │
│    - 新規ノートブック作成                               │
│    - 10論文のabs URLをsourceとして追加                  │
│    - 全sourceが ready になるまで待機                    │
│    - Audio Overview 生成（カスタム指示つき、--wait）    │
│    - mp3 をローカルにダウンロード                       │
└────────────────────┬───────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────┐
│ 3. mp3 を GitHub Releases にアップロード                │
│    - リリースタグ: YYYY-MM-DD                           │
│    - アセット: episode.mp3                              │
└────────────────────┬───────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────┐
│ 4. RSS フィード(feed.xml)を更新してコミット             │
│    - 新エピソードを <item> として先頭に追加             │
│    - GitHub Pages 経由で配信                            │
└────────────────────┬───────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────┐
│ 5. Podcast アプリ（Pocket Casts / Overcast 等）が       │
│    RSS を購読しているので、新エピソードが自動配信       │
└────────────────────────────────────────────────────────┘

失敗時: GitHub Actions の失敗通知メール + （任意）Slack/Discord webhook
```

---

## 3. 技術スタック

| 用途 | 採用 | 理由 |
|---|---|---|
| 言語 | Python 3.11+ | notebooklm-py が Python |
| パッケージ管理 | uv | 高速、参考記事と一致 |
| arXiv 取得 | `arxiv` (PyPI) | 公式API公式ラッパー |
| NotebookLM 操作 | `notebooklm-py[browser]` | 非公式CLI、Playwright経由 |
| ブラウザ自動化 | Playwright (Chromium) | notebooklm-py の依存 |
| RSS 生成 | `feedgen` | Podcast用RSS 2.0対応 |
| スケジューラ | GitHub Actions cron | 無料、サーバー不要 |
| 音声ホスト | GitHub Releases | 帯域・サイズ制限が緩い |
| RSS ホスト | GitHub Pages | 無料、独自URL不要 |
| 通知（任意） | Discord/Slack webhook | 失敗時アラート |

---

## 4. ディレクトリ構成

```
arxiv-podcast-bot/
├── .github/
│   └── workflows/
│       └── daily-podcast.yml       # cronジョブ定義
├── src/
│   ├── __init__.py
│   ├── config.py                    # 設定（カテゴリ、本数、プロンプト等）
│   ├── fetch_arxiv.py               # arXiv API 呼び出し
│   ├── generate_podcast.py          # notebooklm CLI ラッパー
│   ├── publish.py                   # GitHub Releases + RSS 更新
│   ├── rss.py                       # RSS XML 生成・更新
│   └── notify.py                    # 失敗通知（任意）
├── tests/
│   ├── test_fetch_arxiv.py
│   └── test_rss.py
├── feed/
│   └── podcast.xml                  # GitHub Pages から配信される実体
├── docs/
│   ├── SETUP.md                     # 初期セットアップ手順
│   └── REAUTH.md                    # 認証更新手順
├── scripts/
│   ├── local_test.py                # ローカル試走スクリプト
│   └── export_storage_state.sh      # secret用に base64 化
├── pyproject.toml
├── uv.lock
├── .python-version
├── .gitignore
├── README.md
└── CLAUDE.md                        # Claude Code 用プロジェクト指示
```

---

## 5. 設定 (`src/config.py`)

ユーザーが編集する想定の設定値。**コードで直書きせず、ここに集約すること**。

```python
# arXiv 検索設定
ARXIV_CATEGORIES = ["cs.AI", "cs.LG", "cs.CL"]   # 興味分野
ARXIV_QUERY_DAYS = 1                              # 過去N日分から選定
PAPERS_PER_EPISODE = 10                           # 1エピソードに含める論文数
EXCLUDE_KEYWORDS = []                             # タイトル・要約で除外したい単語

# NotebookLM 生成指示
NOTEBOOK_NAME_FORMAT = "arXiv {date}"             # {date}=YYYY-MM-DD
AUDIO_OVERVIEW_INSTRUCTION = (
    "本日のarXiv注目論文を、機械学習に詳しくない聴衆にも分かるように、"
    "論文ごとに『何を解決した研究か』『使った手法』『主な結果』『限界』"
    "の順で2〜3分ずつ紹介してください。論文に書かれていないことは推測せず、"
    "不明な点はそう述べてください。"
)

# Podcast メタデータ
PODCAST_TITLE = "Daily arXiv Digest (JP)"
PODCAST_DESCRIPTION = "毎朝の arXiv 注目論文10本を、NotebookLM が日本語ポッドキャストで紹介。"
PODCAST_AUTHOR = "Your Name"
PODCAST_LANGUAGE = "ja"
PODCAST_CATEGORY = "Technology"
PODCAST_IMAGE_URL = "https://<github-pages-url>/cover.png"  # 1400x1400px推奨

# 配信
GITHUB_REPO = "yourname/arxiv-podcast-bot"
GITHUB_PAGES_BASE_URL = "https://yourname.github.io/arxiv-podcast-bot"

# 通知（任意、未設定ならスキップ）
DISCORD_WEBHOOK_URL_ENV = "DISCORD_WEBHOOK_URL"
```

---

## 6. 詳細ワークフロー

### 6.1 arXiv 取得 (`src/fetch_arxiv.py`)

**振る舞い**
- 設定された `ARXIV_CATEGORIES` のOR検索を `arxiv.Search` で実行
- ソート: `SubmittedDate` 降順
- `ARXIV_QUERY_DAYS` 日以内に投稿された論文に絞る
- `EXCLUDE_KEYWORDS` がタイトルまたは要約に含まれるものを除外
- 最大 `PAPERS_PER_EPISODE` 本を返す
- 各論文について `(title, authors, abstract, abs_url, pdf_url, published_date)` を保持
- **重要**: arXiv API は連続アクセス時に3秒間隔を推奨。`arxiv` ライブラリの `delay_seconds=3` を必ず指定

**返り値の型**
```python
@dataclass
class ArxivPaper:
    arxiv_id: str       # "2405.12345"
    title: str
    authors: list[str]
    abstract: str
    abs_url: str        # "https://arxiv.org/abs/2405.12345"
    pdf_url: str
    published: datetime
    primary_category: str
```

**過去配信済み論文の除外**
- `state/published_papers.json` に過去に配信した arxiv_id を記録
- 同じ論文が連続日に出てきても再配信しない
- このファイルはリポジトリにコミット（履歴管理用）

### 6.2 NotebookLM 操作 (`src/generate_podcast.py`)

参考記事（kirozero/Qiita）のCLIフローを Python から `subprocess` で実行する。**`notebooklm-py` のPython APIは安定していないため CLI 経由を推奨**。

**手順**
1. 環境変数 `NOTEBOOKLM_STORAGE_STATE` (base64) を `~/.notebooklm/storage_state.json` にデコード書き戻し
2. 出力言語が日本語であることを保証: `uv run notebooklm language set ja`（冪等）
3. ノートブック作成: `uv run notebooklm create "arXiv 2026-05-25"` → ID 抽出
4. `uv run notebooklm use <id>`
5. 各論文の `abs_url` を順次 source 追加: `uv run notebooklm source add <url>`
6. 全sourceが ready になるまでポーリング: `uv run notebooklm source list` を10秒間隔、最大10分
7. Audio Overview 生成: `uv run notebooklm generate audio "<AUDIO_OVERVIEW_INSTRUCTION>" --wait`
   - タイムアウト対策: `--wait` が300秒で切れることがあるため、切れた場合は `artifact wait <task_id>` で再待機（最大30分）
8. ダウンロード: `uv run notebooklm download audio ./build/episode.mp3`

**エラーハンドリング**
- 認証エラー（storage_state 失効）を検知したら例外を投げて即終了 → GitHub Actions で失敗 → メール通知
- source 追加でエラーになった論文はスキップして処理を続行（ログに記録）
- generate audio が失敗した場合は最大2回までリトライ

**1日3回制限への配慮**
- 1日1エピソードのみ生成するので問題なし
- もし連続失敗で消費した場合は当日諦めて翌日リトライ

### 6.3 RSS 生成・更新 (`src/rss.py`)

**振る舞い**
- 既存の `feed/podcast.xml` を読み込み、なければ新規作成
- 新エピソードを `<item>` として **先頭に追加**（最新が上）
- 過去エピソードは保持（最大100エピソードまで、それ以上は古いものから削除）
- `feedgen` を使用

**1エピソードの中身（例）**
```xml
<item>
  <title>arXiv 2026-05-25</title>
  <description>本日の注目論文10本：
1. [タイトル1] by [著者]
2. [タイトル2] by [著者]
...
</description>
  <pubDate>Mon, 25 May 2026 06:00:00 +0900</pubDate>
  <enclosure url="https://github.com/.../releases/download/2026-05-25/episode.mp3"
             type="audio/mpeg" length="..."/>
  <guid isPermaLink="false">arxiv-podcast-2026-05-25</guid>
  <itunes:duration>00:15:30</itunes:duration>
  <itunes:explicit>false</itunes:explicit>
</item>
```

**iTunes拡張タグ**を含めること（Apple Podcasts / Spotify への将来登録時に必要）。

### 6.4 配信 (`src/publish.py`)

**手順**
1. mp3 を `gh` CLI で GitHub Releases にアップロード
   ```
   gh release create 2026-05-25 ./build/episode.mp3 \
     --title "arXiv 2026-05-25" \
     --notes "本日の10論文"
   ```
2. RSS XML を `feed/podcast.xml` に書き戻し
3. git commit & push（main ブランチへ）
4. GitHub Pages が `feed/podcast.xml` を `https://yourname.github.io/arxiv-podcast-bot/feed/podcast.xml` で配信

**RSS の正当性検証**
- pushする前に Python の `xml.etree.ElementTree.parse` でパース可能か確認
- 任意で Apple の Cast Feed Validator（podcastsconnect.apple.com/tools/feed-validator）を月1回手動チェック

---

## 7. 認証戦略（最重要）

`notebooklm-py` は Google にブラウザログインしてセッションを保存する。サーバー上で都度ログインはできないので、以下の運用：

**初回セットアップ（ローカルPC）**
1. ローカルで `uv run notebooklm login` → ブラウザで Google ログイン
2. 生成された `~/.notebooklm/storage_state.json` を base64 エンコード
3. GitHub リポジトリの Settings > Secrets and variables > Actions に `NOTEBOOKLM_STORAGE_STATE` として登録

**GitHub Actions 実行時**
1. secret から base64 を取り出して `~/.notebooklm/storage_state.json` に書き戻す
2. その状態で `notebooklm` CLI を実行 → 認証済み状態として動作

**期限切れ対応（2週間ごと）**
- 認証エラー検知時に通知（Discord/メール）
- ローカルで再ログイン → storage_state.json を再エクスポート → secret 更新
- `scripts/export_storage_state.sh` がこの作業をワンライナーで補助
  ```bash
  #!/bin/bash
  base64 -w 0 ~/.notebooklm/storage_state.json | pbcopy  # macOS
  echo "クリップボードにコピー済み。GitHub の NOTEBOOKLM_STORAGE_STATE secret に貼り付けてください"
  ```
- 詳細手順は `docs/REAUTH.md` に記載

---

## 8. GitHub Actions (`.github/workflows/daily-podcast.yml`)

```yaml
name: Daily arXiv Podcast

on:
  schedule:
    - cron: '0 21 * * *'   # 21:00 UTC = 06:00 JST
  workflow_dispatch:       # 手動実行も可能に

jobs:
  generate:
    runs-on: ubuntu-latest
    timeout-minutes: 60    # NotebookLM生成が20分かかることがある
    permissions:
      contents: write       # Release作成 & RSSコミット用
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python with uv
        uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: uv sync

      - name: Install Playwright browsers
        run: uv run playwright install chromium

      - name: Restore NotebookLM session
        env:
          STORAGE_STATE_B64: ${{ secrets.NOTEBOOKLM_STORAGE_STATE }}
        run: |
          mkdir -p ~/.notebooklm
          echo "$STORAGE_STATE_B64" | base64 -d > ~/.notebooklm/storage_state.json

      - name: Run podcast generation
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: uv run python -m src.main

      - name: Commit RSS update
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add feed/podcast.xml state/published_papers.json
          git diff --cached --quiet || git commit -m "Daily episode $(date +%Y-%m-%d)"
          git push

      - name: Notify on failure
        if: failure()
        env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: uv run python -m src.notify "Daily podcast generation failed"
```

---

## 9. メインエントリポイント (`src/main.py`)

```python
"""日次ポッドキャスト生成パイプライン"""
from src import config
from src.fetch_arxiv import fetch_latest_papers
from src.generate_podcast import generate_audio_overview
from src.publish import publish_episode
from src.notify import notify

def main():
    today = date.today()
    try:
        papers = fetch_latest_papers(
            categories=config.ARXIV_CATEGORIES,
            n=config.PAPERS_PER_EPISODE,
            exclude_published_ids=load_published_ids(),
        )
        if not papers:
            notify(f"{today}: 該当論文0本のため生成スキップ")
            return

        mp3_path = generate_audio_overview(papers, today)
        publish_episode(mp3_path, papers, today)
        record_published_ids([p.arxiv_id for p in papers])

    except Exception as e:
        notify(f"{today}: 失敗 — {e}")
        raise

if __name__ == "__main__":
    main()
```

---

## 10. ローカル開発・テスト

`scripts/local_test.py` を提供:
```bash
# 論文取得のみ試す（NotebookLMは呼ばない）
uv run python scripts/local_test.py --fetch-only

# NotebookLM生成までやる（RSS更新・コミットはしない）
uv run python scripts/local_test.py --no-publish

# 全工程をローカルで（dry-runモード、git pushしない）
uv run python scripts/local_test.py --dry-run
```

ユニットテストは `tests/` 配下、`uv run pytest` で実行。

---

## 11. 失敗モードと復旧

| 障害 | 兆候 | 復旧 |
|---|---|---|
| storage_state 失効 | "Login required" 系エラー | ローカル再ログイン → secret 更新（10分） |
| notebooklm-py が Google 仕様変更で動作不能 | source追加 / generate失敗 | GitHub Issuesで状況確認、修正版が出るまで停止 |
| arXiv API 障害 | fetch_arxiv 例外 | 翌日リトライ（自動） |
| GitHub Actions 月間2000分超過 | 課金/停止通知 | 不要なログ削減・キャッシュ活用 |
| RSS が Podcast アプリで読めない | アプリ側でエラー | Cast Feed Validator で検証 |
| mp3 サイズが過大（>100MB） | アップロード失敗 | NotebookLM側の問題、長すぎる場合は分割検討 |

---

## 12. セキュリティ・コンプライアンス上の注意

- `notebooklm-py` は **Google 非公認**のツールであり、利用は自己責任
- 個人利用範囲に留め、生成された音声を公開・商用配信しないこと（NotebookLM 利用規約の範囲内で）
- `storage_state.json` は Google アカウントのセッション情報そのもの。漏洩した場合は速やかに Google パスワード変更・セッション無効化
- リポジトリは **Private 推奨**

---

## 13. 拡張アイデア（MVP後）

- 論文選定を Claude API でランク付け（自分の興味プロファイル × 論文要約）
- Slack/Discord に「今日の論文リスト + 音声リンク」を投稿
- 音声の途中に区切り音（ジングル）を pydub で挿入
- 文字起こし（Whisper）を生成して RSS の説明欄に章マーカー化
- 複数カテゴリを別フィードに分離（cs.AI 用 / cs.CL 用 etc.）

---

## 14. 実装順序（Claude Code への指示）

以下の順で進めること。各ステップ完了時に動作確認してから次へ。

1. **プロジェクト初期化** — `uv init`、依存追加、`.python-version`、`.gitignore`
2. **`src/config.py`** — 設定値の定義
3. **`src/fetch_arxiv.py` + テスト** — まず arXiv 取得だけが動く状態を作る
4. **`scripts/local_test.py --fetch-only`** — 取得結果を目視確認
5. **`src/generate_podcast.py`** — `notebooklm-py` CLI ラッパー実装
   - ローカルで `uv run notebooklm login` を済ませた状態で動作確認
6. **`src/rss.py` + テスト** — RSS 生成ロジック、サンプルデータで XML 出力テスト
7. **`src/publish.py`** — `gh` CLI で Release 作成、RSS コミット
8. **`src/main.py`** — 全体オーケストレーション
9. **`src/notify.py`** — Discord webhook 通知
10. **`.github/workflows/daily-podcast.yml`** — GitHub Actions
11. **GitHub Pages 有効化** — Settings から `main` ブランチの `/feed` を公開
12. **`workflow_dispatch` で手動実行 → 動作確認**
13. **`docs/SETUP.md` と `docs/REAUTH.md`** — 運用ドキュメント整備
14. cronスケジュールに任せて初日の自動実行を観察

---

## 15. CLAUDE.md（プロジェクト直下に配置）

別途 `CLAUDE.md` を生成すること。内容は以下：

```markdown
# Claude Code 指示

このプロジェクトは arXiv の最新論文を NotebookLM 経由でポッドキャスト化する個人用 bot。

## 実行コマンド
- セットアップ: `uv sync && uv run playwright install chromium`
- 初回ログイン: `uv run notebooklm login`
- ローカル試走: `uv run python scripts/local_test.py --dry-run`
- テスト: `uv run pytest`
- 本番実行: `uv run python -m src.main`

## 重要な規約
- 設定は必ず `src/config.py` に集約する。コード中にハードコードしない
- `notebooklm-py` の操作は CLI を `subprocess` で呼ぶ方針（Python API は不安定）
- arXiv API は3秒間隔を遵守
- 認証ファイル（`storage_state.json`）は絶対にコミットしない（.gitignore済み）
- リトライ回数の上限を常に設定する（無限ループ防止）

## 注意
- `notebooklm-py` は非公式ライブラリで、Google側の変更で突然動かなくなる可能性がある
- 動かなくなった場合は notebooklm-py の GitHub Issues を確認
```

---

## 16. 受け入れ基準

このシステムは以下を満たして「完成」とみなす：

- [ ] `workflow_dispatch` で手動実行して、Podcast アプリに新エピソードが届く
- [ ] cron による自動実行が3日連続で成功する
- [ ] 認証期限切れ時に Discord 通知が来て、復旧手順通りに10分以内で再開できる
- [ ] エピソードの音声がNotebookLM標準品質で、各論文の内容が事実に基づいて紹介されている
- [ ] 過去配信済み論文が翌日に重複して登場しない
- [ ] `docs/SETUP.md` を見れば、別マシンでも初期セットアップを再現できる
