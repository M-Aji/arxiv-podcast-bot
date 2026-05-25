"""Discord webhook 通知。未設定なら標準エラーに出すだけ。"""
from __future__ import annotations

import logging
import os
import sys
from typing import Iterable

import requests

from src import config

logger = logging.getLogger(__name__)

_DISCORD_LIMIT = 1900  # Discord content limit (2000) を少し下回るところでカット


def notify(message: str, *, env_var: str | None = None) -> None:
    """Discord に通知。失敗しても例外は投げない（通知は best-effort）。"""
    env_var = env_var or config.DISCORD_WEBHOOK_URL_ENV
    url = os.environ.get(env_var)
    if not url:
        print(f"[notify] {message}", file=sys.stderr)
        return

    truncated = message if len(message) <= _DISCORD_LIMIT else (
        message[: _DISCORD_LIMIT - 3] + "..."
    )
    try:
        resp = requests.post(url, json={"content": truncated}, timeout=15)
        if resp.status_code >= 400:
            logger.warning(
                "discord webhook returned %s: %s", resp.status_code, resp.text[:200]
            )
    except requests.RequestException as exc:
        logger.warning("discord webhook failed: %s", exc)


def main(argv: Iterable[str] | None = None) -> int:
    """`python -m src.notify "<message>"` で呼ばれるエントリポイント。"""
    args = list(argv if argv is not None else sys.argv[1:])
    message = " ".join(args) if args else "(no message)"
    notify(message)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
