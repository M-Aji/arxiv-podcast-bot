#!/bin/bash
# storage_state.json を base64 化してクリップボードに送る。
# GitHub の NOTEBOOKLM_STORAGE_STATE secret に貼り付けて使う。
set -euo pipefail

STATE_FILE="${1:-$HOME/.notebooklm/storage_state.json}"
if [ ! -f "$STATE_FILE" ]; then
  echo "❌ $STATE_FILE が見つかりません。先に 'uv run notebooklm login' を実行してください。" >&2
  exit 1
fi

case "$(uname -s)" in
  Darwin)
    base64 -i "$STATE_FILE" | pbcopy
    echo "✔ macOS のクリップボードにコピー済み"
    ;;
  Linux)
    if command -v xclip >/dev/null 2>&1; then
      base64 -w 0 "$STATE_FILE" | xclip -selection clipboard
      echo "✔ xclip でクリップボードにコピー済み"
    elif command -v wl-copy >/dev/null 2>&1; then
      base64 -w 0 "$STATE_FILE" | wl-copy
      echo "✔ wl-copy でクリップボードにコピー済み"
    else
      base64 -w 0 "$STATE_FILE"
      echo "（xclip / wl-copy が無いので標準出力に出しました。手でコピーしてください。）" >&2
    fi
    ;;
  *)
    base64 "$STATE_FILE"
    ;;
esac

cat <<EOF
次の手順:
  1. https://github.com/<owner>/<repo>/settings/secrets/actions を開く
  2. NOTEBOOKLM_STORAGE_STATE を update（無ければ New repository secret）
  3. クリップボードの内容を貼り付けて保存
EOF
