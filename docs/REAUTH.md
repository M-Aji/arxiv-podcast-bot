# 認証更新（NotebookLM セッション失効時）

NotebookLM のセッションは概ね **2週間** で失効する。失効すると Actions の実行が `AUTH_REQUIRED` / `Login required` で落ち、Discord に通知が来るので、10分以内に以下を実施する。

## 手順（所要 5〜10 分）

### 1. ローカルで再ログイン

```bash
cd /path/to/arxiv-podcast-bot
uv run notebooklm login
```

ブラウザが立ち上がる → Google アカウントでログイン → ブラウザを閉じれば storage_state が更新される。

### 2. 認証確認

```bash
uv run notebooklm doctor
```

`Auth ✓ pass` が出ていれば OK。

### 3. base64 化してクリップボードへ

```bash
./scripts/export_storage_state.sh
```

スクリプトは新パス `~/.notebooklm/profiles/default/storage_state.json` を優先的に探し、見つからなければ旧パス `~/.notebooklm/storage_state.json` をフォールバックで使う。別の場所に置いている場合は明示指定：

```bash
./scripts/export_storage_state.sh /path/to/storage_state.json
```

### 4. GitHub の Secret を更新

1. `https://github.com/<owner>/<repo>/settings/secrets/actions` を開く
2. `NOTEBOOKLM_STORAGE_STATE` の編集ボタン
3. クリップボードの内容を貼り付けて保存

### 5. 手動実行で動作確認

GitHub → Actions → "Daily arXiv Podcast" → "Run workflow"。緑になれば完了。

---

## トラブルシュート

### `notebooklm doctor` で `Profile Dir: ✗ fail` と出る

初回ログインがまだ。`uv run notebooklm login` を実行。

### `storage_state.json` のパスがわからない

```bash
uv run notebooklm doctor
```

の `Profile Dir` 行に表示される。`storage_state.json` はその直下にある。

### 同じアカウントから何度もログインを求められる

`uv run notebooklm auth check` でセッションを確認。失敗するなら `notebooklm auth logout` してから再ログイン。

### 一日経っても storage_state が安定しない

`notebooklm-py` の GitHub Issues を確認（Google 側で UI 変更があった可能性）。最悪、修正版が出るまで cron を一時停止：

```bash
gh workflow disable daily-podcast.yml
```

復旧したら `gh workflow enable daily-podcast.yml`。
