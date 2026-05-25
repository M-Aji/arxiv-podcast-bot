# 初期セットアップ手順

別マシンでも再現できるよう、ゼロから手順を並べる。所要時間 30〜45分。

## 0. 事前に用意するもの

- GitHub アカウント（リポジトリは **Private 推奨**）
- Google アカウント（NotebookLM が使えるもの）
- ローカル PC（macOS / Linux）
- ホストツール: `git`、`gh` CLI、Homebrew (mac) または apt (Linux)

## 1. ローカル環境を整える

```bash
# uv（Python パッケージマネージャ）
brew install uv          # macOS
# or: curl -LsSf https://astral.sh/uv/install.sh | sh

# GitHub CLI
brew install gh
gh auth login            # PAT でログイン（repo + workflow スコープ）
```

## 2. リポジトリを clone して依存を入れる

```bash
git clone https://github.com/<yourname>/arxiv-podcast-bot.git
cd arxiv-podcast-bot
uv sync
uv run playwright install chromium
```

## 3. 設定をカスタマイズ

`src/config.py` を開き、以下を自分の値に書き換える：

| 変数 | 内容 |
|---|---|
| `ARXIV_CATEGORIES` | 興味のあるカテゴリ（`cs.AI`, `cs.LG`, `cs.CL` など） |
| `PAPERS_PER_EPISODE` | 1エピソードに含める論文数（既定10） |
| `PODCAST_TITLE` / `PODCAST_AUTHOR` | Podcast 側で表示される情報 |
| `GITHUB_REPO` | `yourname/arxiv-podcast-bot` 形式 |
| `GITHUB_PAGES_BASE_URL` | `https://yourname.github.io/arxiv-podcast-bot` |
| `PODCAST_IMAGE_URL` | カバー画像の URL（1400x1400px 推奨） |

## 4. NotebookLM にログインしてセッションを保存

```bash
uv run notebooklm login
```

ブラウザが立ち上がるので Google でログイン。`~/.notebooklm/profiles/default/storage_state.json` または `~/.notebooklm/storage_state.json` が作られる。次のステップで base64 化して secret に登録する。

## 5. fetch だけ動かして確認

NotebookLM はまだ呼ばずに、arXiv 取得だけ動くことを見る。

```bash
uv run python scripts/local_test.py --fetch-only
```

10本ぶんのタイトルが出れば OK。

## 6. NotebookLM 生成までローカルで通す

```bash
uv run python scripts/local_test.py --no-publish
```

`build/episode.mp3` が出来上がれば成功。所要 5〜20 分。

## 7. GitHub Pages を有効化

1. GitHub の Settings → Pages
2. Source: `Deploy from a branch` / Branch: `main` / Folder: `/ (root)`
3. 保存して数分待つと `https://<yourname>.github.io/arxiv-podcast-bot/feed/podcast.xml` で配信される

`feed/podcast.xml` が存在しないと 404 になるので、初回はステップ6で生成→コミットしておく。

## 8. Secret を登録

```bash
# storage_state.json を base64 化してクリップボードへ
./scripts/export_storage_state.sh
```

GitHub の Settings → Secrets and variables → Actions → New repository secret で以下を登録：

| Secret 名 | 値 |
|---|---|
| `NOTEBOOKLM_STORAGE_STATE` | クリップボード（base64） |
| `DISCORD_WEBHOOK_URL` | 任意。Discord チャンネルの webhook URL |

`GITHUB_TOKEN` は自動付与なので登録不要。

## 9. Actions を手動実行して通しテスト

GitHub の Actions タブから "Daily arXiv Podcast" → "Run workflow"。

完了したら：

- Releases に `YYYY-MM-DD` というタグでエピソードができている
- `feed/podcast.xml` に新しい `<item>` が追加されている
- Discord に成功通知が来る

## 10. Podcast アプリで購読

`https://<yourname>.github.io/arxiv-podcast-bot/feed/podcast.xml` を Pocket Casts / Overcast の URL 直接購読で追加。

## 11. cron に任せる

`.github/workflows/daily-podcast.yml` の `cron: '0 21 * * *'` がそのまま動く。3日連続で成功すれば本番運用 OK。

---

うまく動かないときは `docs/REAUTH.md`、または GitHub Actions のログを参照。
