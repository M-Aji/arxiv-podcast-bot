# arXiv Daily Podcast Bot

毎朝 6:00 JST に arXiv から論文を10本取って NotebookLM で日本語ポッドキャストを作り、自分専用の RSS で配信する個人用 bot。

## 動き
1. GitHub Actions が cron で発火（21:00 UTC = 06:00 JST）
2. arXiv から `cs.AI` / `cs.LG` / `cs.CL` の最新論文を10本取得
3. `notebooklm-py` CLI で NotebookLM にソース投入 → Audio Overview 生成 → mp3 ダウンロード
4. GitHub Releases に mp3 をアップロード、`feed/podcast.xml` に新エピソードを追記
5. GitHub Pages 経由で配信、Podcast アプリで自動受信

詳細は `SPEC.md`、初期セットアップは `docs/SETUP.md`、認証更新は `docs/REAUTH.md` を参照。

## クイックスタート

```bash
uv sync
uv run playwright install chromium
uv run notebooklm login                              # 初回のみ
uv run python scripts/local_test.py --fetch-only     # 動作確認
uv run pytest                                        # テスト
```
