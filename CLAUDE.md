# Claude Code 指示

このプロジェクトは arXiv の最新論文を NotebookLM 経由でポッドキャスト化する個人用 bot。

## 実行コマンド
- セットアップ: `uv sync && uv run playwright install chromium`
- 初回ログイン: `uv run notebooklm login`
- ローカル試走（取得のみ）: `uv run python scripts/local_test.py --fetch-only`
- ローカル試走（生成まで）: `uv run python scripts/local_test.py --no-publish`
- ローカル試走（全工程・push なし）: `uv run python scripts/local_test.py --dry-run`
- テスト: `uv run pytest`
- 本番実行: `uv run python -m src.main`

## 重要な規約
- 設定は必ず `src/config.py` に集約する。コード中にハードコードしない
- `notebooklm-py` の操作は CLI を `subprocess` で呼ぶ方針（Python API は不安定）
- arXiv API は3秒間隔を遵守（`config.ARXIV_DELAY_SECONDS`）
- 認証ファイル（`storage_state.json`）は絶対にコミットしない（.gitignore 済み）
- リトライ回数の上限を常に設定する（無限ループ防止）

## ファイル構成
- `src/fetch_arxiv.py` — arXiv 取得＋過去配信ID管理
- `src/generate_podcast.py` — NotebookLM CLI ラッパー
- `src/rss.py` — RSS XML 生成・更新（feedgen + iTunes 拡張）
- `src/publish.py` — gh CLI で Release 作成、RSS commit/push
- `src/main.py` — 全体オーケストレーション
- `src/notify.py` — Discord webhook 通知
- `state/published_papers.json` — 配信済 arxiv_id 履歴（コミット対象）
- `feed/podcast.xml` — GitHub Pages から配信される RSS 本体（コミット対象）
- `build/episode.mp3` — 一時生成物（.gitignore で除外）

## 注意
- `notebooklm-py` は非公式ライブラリで、Google 側の変更で突然動かなくなる可能性がある
- 動かなくなった場合は notebooklm-py の GitHub Issues を確認
- 失敗通知が来たら `docs/REAUTH.md` を最初に疑う（セッション失効が最頻ケース）
