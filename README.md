# arXiv Daily Podcast Bot

毎朝 6:00 JST に arXiv から論文候補を取得し、Claude Haiku で興味プロファイルに合う上位5本を選抜、NotebookLM で日本語ポッドキャストを作って自分専用の RSS で配信する個人用 bot。

## 動き
1. GitHub Actions が cron で発火（21:00 UTC = 06:00 JST）
2. arXiv から `src/config.py` の `ARXIV_CATEGORIES` に沿って最新論文を `CANDIDATE_POOL_SIZE` 本（既定 30）取得
3. Claude Haiku で `INTEREST_PROFILE` とのマッチ度を 0〜10 でスコアリングし、上位 `PAPERS_PER_EPISODE` 本（既定 5）に絞る
4. `notebooklm-py` CLI で NotebookLM にソース投入 → Audio Overview 生成 → mp3 ダウンロード
5. GitHub Releases に mp3 をアップロード、`feed/podcast.xml` に新エピソードを追記
6. GitHub Pages 経由で配信、Podcast アプリで自動受信

詳細は `SPEC.md`、初期セットアップは `docs/SETUP.md`、認証更新は `docs/REAUTH.md` を参照。

## クイックスタート

```bash
uv sync
uv run playwright install chromium
uv run notebooklm login                              # 初回のみ
export ANTHROPIC_API_KEY=...                         # ランキング有効化（任意）
uv run python scripts/local_test.py --fetch-only     # 動作確認
uv run pytest                                        # テスト
```

## 興味プロファイルの編集

論文選定基準は `src/config.py` の `INTEREST_PROFILE` 定数（日本語の Markdown）一箇所に集約されている。

- 「強く興味あり / 優先度高」「普通に興味あり / 優先度中」「スキップしたい / 優先度低」の3階層で書き、各論文は Claude Haiku がこのプロファイルと照合して 0〜10 でスコア付けする
- カテゴリの追加・優先順位変更・対象分野の入れ替えなど、選定方針を変えたいときはこのテキストを書き換えるだけでよい（コード変更は不要）
- `ANTHROPIC_API_KEY` 環境変数（GitHub Actions では `secrets.ANTHROPIC_API_KEY`）が未設定、または API が完全に失敗した場合は、フォールバックとして取得順そのままで上位 N 本を選ぶ（bot は止まらない）
