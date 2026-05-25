"""`notebooklm-py` CLI を subprocess で叩いて Audio Overview を生成する。

Python API は非安定のため CLI 経由を採用（spec §6.2）。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Sequence

from src import config
from src.fetch_arxiv import ArxivPaper

logger = logging.getLogger(__name__)

# storage_state.json の復元先。CLI 既定の profile dir でなく固定パスを
# 使い、`--storage` で明示的に指定する。GitHub Actions 環境でも
# ローカルでも同じ振る舞いになる。
STORAGE_STATE_PATH = Path.home() / ".notebooklm" / "storage_state.json"

# 環境変数名（base64 エンコードされた storage_state.json を期待）
STORAGE_STATE_ENV = "NOTEBOOKLM_STORAGE_STATE"


class NotebookLMError(RuntimeError):
    """notebooklm CLI 由来の失敗をまとめる例外。"""


class NotebookLMAuthError(NotebookLMError):
    """セッション失効が疑われるエラー。即時終了→Discord通知の合図。"""


def restore_storage_state(
    env_var: str = STORAGE_STATE_ENV, path: Path = STORAGE_STATE_PATH
) -> Path | None:
    """環境変数から base64 を取り出して storage_state.json に書き戻す。

    未設定なら何もしない（ローカルで `notebooklm login` 済みの想定）。
    """
    encoded = os.environ.get(env_var)
    if not encoded:
        logger.info("%s is not set — using existing local credentials", env_var)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    decoded = base64.b64decode(encoded.strip())
    path.write_bytes(decoded)
    path.chmod(0o600)
    logger.info("restored storage state to %s (%d bytes)", path, len(decoded))
    return path


def _base_cmd() -> list[str]:
    """全 notebooklm 呼び出しに共通の prefix。"""
    cmd = ["uv", "run", "notebooklm"]
    if STORAGE_STATE_PATH.exists():
        cmd.extend(["--storage", str(STORAGE_STATE_PATH)])
    return cmd


def _run(
    cmd: Sequence[str],
    *,
    check: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    logger.debug("$ %s", " ".join(cmd))
    proc = subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.stderr:
        logger.debug("stderr: %s", proc.stderr.strip())
    if check and proc.returncode != 0:
        _raise_for_output(cmd, proc)
    return proc


def _raise_for_output(
    cmd: Sequence[str], proc: subprocess.CompletedProcess[str]
) -> None:
    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    auth_signals = (
        "auth_required",
        "auth not found",
        "login required",
        "not authenticated",
        "session expired",
        "unauthorized",
    )
    msg = (
        f"notebooklm command failed (exit {proc.returncode}): {' '.join(cmd)}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    if any(sig in combined for sig in auth_signals):
        raise NotebookLMAuthError(msg)
    raise NotebookLMError(msg)


def _parse_json(stdout: str) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise NotebookLMError(f"could not parse JSON: {stdout!r}") from exc


def set_language(code: str = "ja") -> None:
    """日本語出力を保証する。冪等。"""
    _run([*_base_cmd(), "language", "set", code, "--local"], check=False)


def create_notebook(title: str) -> str:
    """ノートブックを作って current context にし、ID を返す。"""
    proc = _run([*_base_cmd(), "create", title, "--use", "--json"])
    payload = _parse_json(proc.stdout)
    notebook_id = (
        payload.get("id")
        or payload.get("notebook_id")
        or payload.get("data", {}).get("id")
    )
    if not notebook_id:
        raise NotebookLMError(f"notebook id missing in create response: {payload}")
    logger.info("created notebook %s (%s)", notebook_id, title)
    return notebook_id


def add_source(notebook_id: str, url: str) -> str | None:
    """論文 abs URL を source として追加。失敗時は None を返してスキップ。"""
    try:
        proc = _run(
            [
                *_base_cmd(),
                "source",
                "add",
                url,
                "--notebook",
                notebook_id,
                "--type",
                "url",
                "--timeout",
                "120",
                "--json",
            ]
        )
    except NotebookLMAuthError:
        raise
    except NotebookLMError as exc:
        logger.warning("failed to add source %s — skipping. %s", url, exc)
        return None

    payload = _parse_json(proc.stdout)
    source_id = (
        payload.get("id")
        or payload.get("source_id")
        or payload.get("data", {}).get("id")
    )
    if not source_id:
        logger.warning("no source id in add response for %s: %s", url, payload)
        return None
    logger.info("added source %s for %s", source_id, url)
    return source_id


def wait_for_source(notebook_id: str, source_id: str, *, timeout: int) -> bool:
    """1ソースが ready になるまで待つ。成功なら True。"""
    proc = _run(
        [
            *_base_cmd(),
            "source",
            "wait",
            source_id,
            "--notebook",
            notebook_id,
            "--timeout",
            str(timeout),
            "--interval",
            str(config.SOURCE_READY_POLL_INTERVAL_SECONDS),
        ],
        check=False,
        timeout=timeout + 30,
    )
    if proc.returncode == 0:
        return True
    logger.warning(
        "source %s did not become ready (exit %d): %s",
        source_id,
        proc.returncode,
        proc.stderr.strip(),
    )
    return False


def generate_audio(
    notebook_id: str, instruction: str, *, language: str = "ja"
) -> None:
    """Audio Overview を生成。タイムアウトしたら artifact wait で再待機。"""
    last_exc: NotebookLMError | None = None
    for attempt in range(1, config.GENERATE_AUDIO_MAX_RETRIES + 2):
        cmd = [
            *_base_cmd(),
            "generate",
            "audio",
            instruction,
            "--notebook",
            notebook_id,
            "--language",
            language,
            "--wait",
            "--timeout",
            "300",
            "--json",
        ]
        proc = _run(cmd, check=False, timeout=400)

        if proc.returncode == 0:
            logger.info("audio overview ready (attempt %d)", attempt)
            return

        # --wait が300秒で切れた場合: artifact_id が出ていれば再待機を試す
        artifact_id = _extract_artifact_id(proc.stdout)
        if artifact_id:
            logger.info(
                "generate exited but artifact %s exists; waiting up to %ds",
                artifact_id,
                config.AUDIO_WAIT_RETRY_TIMEOUT_SECONDS,
            )
            wait_proc = _run(
                [
                    *_base_cmd(),
                    "artifact",
                    "wait",
                    artifact_id,
                    "--notebook",
                    notebook_id,
                    "--timeout",
                    str(config.AUDIO_WAIT_RETRY_TIMEOUT_SECONDS),
                ],
                check=False,
                timeout=config.AUDIO_WAIT_RETRY_TIMEOUT_SECONDS + 60,
            )
            if wait_proc.returncode == 0:
                return

        try:
            _raise_for_output(cmd, proc)
        except NotebookLMAuthError:
            raise
        except NotebookLMError as exc:
            last_exc = exc
            logger.warning(
                "generate audio failed on attempt %d/%d: %s",
                attempt,
                config.GENERATE_AUDIO_MAX_RETRIES + 1,
                exc,
            )

    raise NotebookLMError(
        f"generate audio failed after {config.GENERATE_AUDIO_MAX_RETRIES + 1} attempts"
    ) from last_exc


def _extract_artifact_id(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return (
            payload.get("artifact_id")
            or payload.get("task_id")
            or payload.get("id")
            or payload.get("data", {}).get("artifact_id")
            or payload.get("data", {}).get("task_id")
        )
    return None


def download_audio(notebook_id: str, output_path: Path) -> Path:
    """生成済み audio をダウンロード。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            *_base_cmd(),
            "download",
            "audio",
            str(output_path),
            "--notebook",
            notebook_id,
            "--latest",
            "--force",
        ],
        timeout=600,
    )
    if not output_path.exists():
        raise NotebookLMError(f"download succeeded but {output_path} missing")
    size = output_path.stat().st_size
    if size < 1024:
        raise NotebookLMError(f"downloaded mp3 is too small ({size} bytes)")
    logger.info("downloaded mp3 to %s (%d bytes)", output_path, size)
    return output_path


# ---- 高レベル API --------------------------------------------------------


def generate_audio_overview(
    papers: Sequence[ArxivPaper],
    today: date,
    *,
    output_path: Path | None = None,
) -> Path:
    """論文一覧から Audio Overview を生成し、mp3 パスを返す。"""
    if not papers:
        raise ValueError("generate_audio_overview called with empty paper list")

    output_path = output_path or config.EPISODE_MP3_PATH
    restore_storage_state()
    set_language(config.PODCAST_LANGUAGE)

    title = config.NOTEBOOK_NAME_FORMAT.format(date=today.isoformat())
    notebook_id = create_notebook(title)

    source_ids: list[str] = []
    for paper in papers:
        sid = add_source(notebook_id, paper.abs_url)
        if sid:
            source_ids.append(sid)
    if not source_ids:
        raise NotebookLMError("no sources were added successfully")

    logger.info("waiting for %d sources to become ready", len(source_ids))
    ready: list[str] = []
    for sid in source_ids:
        if wait_for_source(
            notebook_id, sid, timeout=config.SOURCE_READY_TIMEOUT_SECONDS
        ):
            ready.append(sid)
    if not ready:
        raise NotebookLMError("no sources became ready in time")

    generate_audio(
        notebook_id,
        config.AUDIO_OVERVIEW_INSTRUCTION,
        language=config.PODCAST_LANGUAGE,
    )
    return download_audio(notebook_id, output_path)
