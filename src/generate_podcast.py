"""`notebooklm-py` CLI を subprocess で叩いて Audio Overview を生成する。

Python API は非安定のため CLI 経由を採用（spec §6.2）。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
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


# `notebooklm-py/_artifact_polling.py:377` が投げる例外メッセージ:
#   f"Task {task_id} timed out after {timeout}s (last status: {last_status})"
# これが CLI の UNEXPECTED_ERROR envelope の `message` フィールドに乗る。
# task_id は UUID（hex + dash）が一般的だが、念のため英数字+`-_` で広めに。
_TASK_TIMEOUT_RE = re.compile(r"Task\s+([A-Za-z0-9_-]+)\s+timed out")


def _extract_task_id_from_error(message: str | None) -> str | None:
    """エラーメッセージ文字列に埋め込まれた task_id を正規表現で取り出す。"""
    if not message:
        return None
    m = _TASK_TIMEOUT_RE.search(message)
    return m.group(1) if m else None


def _extract_task_id_from_response(
    stdout: str, stderr: str = ""
) -> str | None:
    """generate audio のレスポンス全体から task_id を取り出す。

    優先順:
      1. payload["task_id"] (status:pending / status:completed の正常系)
      2. payload["message"] 内のエラー文字列に埋め込まれた task_id
      3. 最終手段として stdout+stderr 全体に対する正規表現マッチ
    """
    payload: object = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None

    if isinstance(payload, dict):
        tid = _extract_task_id(payload)
        if tid:
            return tid
        msg = payload.get("message")
        if isinstance(msg, str):
            tid = _extract_task_id_from_error(msg)
            if tid:
                return tid

    # 最後の保険: stdout/stderr どこかにメッセージが転がっていれば拾う
    combined = (stdout or "") + "\n" + (stderr or "")
    return _extract_task_id_from_error(combined)


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
    """Audio Overview を生成し、完了を待つ。

    NotebookLM の audio 生成は典型的に 10〜20 分かかる。`generate audio`
    を1回だけ submit し、初回 --wait が短いタイムアウトで返ってきたら
    レスポンス（あるいはエラーメッセージ）から task_id を救出して、
    同じタスクを `artifact wait` で `AUDIO_WAIT_RETRY_TIMEOUT_SECONDS`
    まで `AUDIO_WAIT_CHUNK_SECONDS` 刻みでポーリングする。

    決して `generate audio` 自体を再投入しない（新タスクを作って
    永遠に追いつけなくなるため）。
    """
    submit_cmd = [
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
        str(config.AUDIO_INITIAL_WAIT_TIMEOUT_SECONDS),
        "--json",
    ]
    proc = _run(
        submit_cmd,
        check=False,
        timeout=config.AUDIO_INITIAL_WAIT_TIMEOUT_SECONDS + 100,
    )

    # 速攻で完了した場合（短い音声・キャッシュなど）
    submit_payload = _try_parse_json(proc.stdout)
    if (
        proc.returncode == 0
        and isinstance(submit_payload, dict)
        and submit_payload.get("status") == "completed"
    ):
        logger.info(
            "audio overview completed in initial wait (task=%s)",
            _extract_task_id(submit_payload),
        )
        return

    # task_id 抽出 (構造化 → エラーメッセージ正規表現)
    task_id = _extract_task_id_from_response(proc.stdout, proc.stderr)
    if not task_id:
        # task_id が無いと再待機できない。auth エラーかその他の致命的失敗
        _raise_for_output(submit_cmd, proc)

    total_budget = config.AUDIO_WAIT_RETRY_TIMEOUT_SECONDS
    chunk_size = config.AUDIO_WAIT_CHUNK_SECONDS
    logger.info(
        "audio task %s pending after %ds initial wait; polling up to %ds total",
        task_id,
        config.AUDIO_INITIAL_WAIT_TIMEOUT_SECONDS,
        total_budget,
    )

    waited = 0
    while waited < total_budget:
        chunk = min(chunk_size, total_budget - waited)
        wait_cmd = [
            *_base_cmd(),
            "artifact",
            "wait",
            task_id,
            "--notebook",
            notebook_id,
            "--timeout",
            str(chunk),
            "--json",
        ]
        wait_proc = _run(wait_cmd, check=False, timeout=chunk + 60)
        wait_payload = _try_parse_json(wait_proc.stdout)
        status = (
            wait_payload.get("status") if isinstance(wait_payload, dict) else None
        )

        if wait_proc.returncode == 0 and status == "completed":
            logger.info(
                "audio task %s completed (post-initial wait ~%ds)",
                task_id,
                waited + chunk,
            )
            return

        if status == "timeout":
            waited += chunk
            logger.info(
                "audio task %s still pending after %ds (%ds remaining)",
                task_id,
                waited,
                total_budget - waited,
            )
            continue

        # 認証失効・サーバ側失敗・JSON 不正など — リトライしても無駄
        _raise_for_output(wait_cmd, wait_proc)

    raise NotebookLMError(
        f"audio task {task_id} did not complete within "
        f"{total_budget}s post-initial wait; NotebookLM may be stuck"
    )


def _try_parse_json(stdout: str) -> object | None:
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
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
