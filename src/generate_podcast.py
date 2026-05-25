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

# storage_state.json の保存場所。
# 新しい notebooklm-py は profile dir 配下を既定とするが、旧バージョン
# でログイン済みのユーザーは旧パスに置いてある。両方を見て、新パスを優先。
STORAGE_STATE_PATH_NEW = (
    Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json"
)
STORAGE_STATE_PATH_OLD = Path.home() / ".notebooklm" / "storage_state.json"

# 後方互換: 旧コードが import している場合に備えて、新パスを既定値に。
STORAGE_STATE_PATH = STORAGE_STATE_PATH_NEW

# 環境変数名（base64 エンコードされた storage_state.json を期待）
STORAGE_STATE_ENV = "NOTEBOOKLM_STORAGE_STATE"


class NotebookLMError(RuntimeError):
    """notebooklm CLI 由来の失敗をまとめる例外。"""


class NotebookLMAuthError(NotebookLMError):
    """セッション失効が疑われるエラー。即時終了→Discord通知の合図。"""


def _resolve_storage_state_path() -> Path | None:
    """既存の storage_state.json のパスを返す。新パス優先、なければ旧。"""
    if STORAGE_STATE_PATH_NEW.exists():
        return STORAGE_STATE_PATH_NEW
    if STORAGE_STATE_PATH_OLD.exists():
        return STORAGE_STATE_PATH_OLD
    return None


def restore_storage_state(
    env_var: str = STORAGE_STATE_ENV, path: Path | None = None
) -> Path | None:
    """環境変数から base64 を取り出して storage_state.json に書き戻す。

    書き出し先は新パス（`~/.notebooklm/profiles/default/storage_state.json`）。
    環境変数が無ければ、実ファイルの存在を確認してログに出す（無い場合は
    `notebooklm login` が未実行）。
    """
    encoded = os.environ.get(env_var)
    if not encoded:
        existing = _resolve_storage_state_path()
        if existing:
            logger.info("using existing storage_state at %s", existing)
        else:
            logger.warning(
                "no storage_state.json found at %s nor %s; "
                "subsequent notebooklm CLI calls will fail. "
                "Run `uv run notebooklm login` or set %s.",
                STORAGE_STATE_PATH_NEW,
                STORAGE_STATE_PATH_OLD,
                env_var,
            )
        return None
    target = path or STORAGE_STATE_PATH_NEW
    target.parent.mkdir(parents=True, exist_ok=True)
    decoded = base64.b64decode(encoded.strip())
    target.write_bytes(decoded)
    target.chmod(0o600)
    logger.info("restored storage state to %s (%d bytes)", target, len(decoded))
    return target


def _base_cmd() -> list[str]:
    """全 notebooklm 呼び出しに共通の prefix。"""
    cmd = ["uv", "run", "notebooklm"]
    storage = _resolve_storage_state_path()
    if storage:
        cmd.extend(["--storage", str(storage)])
        logger.debug("using storage_state at %s", storage)
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


# ---- レスポンスID抽出ヘルパー --------------------------------------------
#
# notebooklm-py CLI の `--json` レスポンスは新バージョンでネスト化された:
#
#   create   →  {"notebook": {"id": ...}, "active_notebook_id": ...}
#   source   →  {"source":   {"id": ...}}
#   audio    →  {"task_id": ..., "status": "completed", "url": ...}
#
# ID 取得は「新ネスト構造 → active_*_id → フラット (旧)」の順でフォールバック
# し、CLI のマイナーバージョン差を吸収する。


def _extract_notebook_id(payload: dict) -> str | None:
    """create / use の response から notebook id を抽出。"""
    if not isinstance(payload, dict):
        return None
    notebook = payload.get("notebook")
    if isinstance(notebook, dict) and isinstance(notebook.get("id"), str):
        return notebook["id"]
    if isinstance(payload.get("active_notebook_id"), str):
        return payload["active_notebook_id"]
    for key in ("notebook_id", "id"):
        val = payload.get(key)
        if isinstance(val, str):
            return val
    return None


def _extract_source_id(payload: dict) -> str | None:
    """source add の response から source id を抽出。"""
    if not isinstance(payload, dict):
        return None
    source = payload.get("source")
    if isinstance(source, dict) and isinstance(source.get("id"), str):
        return source["id"]
    for key in ("source_id", "id"):
        val = payload.get(key)
        if isinstance(val, str):
            return val
    return None


def _extract_task_id(payload_or_stdout: dict | str) -> str | None:
    """generate audio / artifact wait の response から task_id を抽出。"""
    payload: object
    if isinstance(payload_or_stdout, str):
        try:
            payload = json.loads(payload_or_stdout)
        except json.JSONDecodeError:
            return None
    else:
        payload = payload_or_stdout
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("task_id"), str):
        return payload["task_id"]
    artifact = payload.get("artifact")
    if isinstance(artifact, dict) and isinstance(artifact.get("id"), str):
        return artifact["id"]
    for key in ("artifact_id", "id"):
        val = payload.get(key)
        if isinstance(val, str):
            return val
    return None


def set_language(code: str = "ja") -> None:
    """日本語出力を保証する。冪等。"""
    _run([*_base_cmd(), "language", "set", code, "--local"], check=False)


def create_notebook(title: str) -> str:
    """ノートブックを作って current context にし、ID を返す。"""
    proc = _run([*_base_cmd(), "create", title, "--use", "--json"])
    payload = _parse_json(proc.stdout)
    notebook_id = _extract_notebook_id(payload)
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
    source_id = _extract_source_id(payload)
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

        # --wait が300秒で切れた場合: task_id が出ていれば再待機を試す
        task_id = _extract_task_id(proc.stdout)
        if task_id:
            logger.info(
                "generate exited but task %s exists; waiting up to %ds",
                task_id,
                config.AUDIO_WAIT_RETRY_TIMEOUT_SECONDS,
            )
            wait_proc = _run(
                [
                    *_base_cmd(),
                    "artifact",
                    "wait",
                    task_id,
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
