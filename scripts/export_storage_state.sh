#!/bin/bash
# storage_state.json を base64 化してクリップボードに送る。
# GitHub の NOTEBOOKLM_STORAGE_STATE secret に貼り付けて使う。
#
# 引数で明示指定がなければ、新パス（profile dir 配下）→ 旧パスの順で探す。
set -euo pipefail

NEW_PATH="$HOME/.notebooklm/profiles/default/storage_state.json"
OLD_PATH="$HOME/.notebooklm/storage_state.json"

if [ "${1:-}" != "" ]; then
  STATE_FILE="$1"
elif [ -f "$NEW_PATH" ]; then
  STATE_FILE="$NEW_PATH"
elif [ -f "$OLD_PATH" ]; then
  STATE_FILE="$OLD_PATH"
  echo "⚠ 旧パスを検出: $OLD_PATH" >&2
  echo "  notebooklm-py の新バージョンは $NEW_PATH を使います。" >&2
else
  echo "❌ storage_state.json が見つかりません。" >&2
  echo "   探した場所:" >&2
  echo "     $NEW_PATH" >&2
  echo "     $OLD_PATH" >&2
  echo "   先に 'uv run notebooklm login' を実行してください。" >&2
  exit 1
fi

echo "→ $STATE_FILE を base64 化します"

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
