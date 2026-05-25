"""generate_podcast のレスポンスパースと storage state 解決のテスト。"""
from __future__ import annotations

import base64
import logging
import subprocess
from pathlib import Path

import pytest

from src import generate_podcast


# ---- _extract_notebook_id ------------------------------------------------


def test_extract_notebook_id_new_nested_form():
    payload = {
        "notebook": {"id": "nb-uuid", "title": "x", "created_at": None},
        "active_notebook_id": "nb-uuid",
    }
    assert generate_podcast._extract_notebook_id(payload) == "nb-uuid"


def test_extract_notebook_id_falls_back_to_active_id():
    """notebook ネストが無いが active_notebook_id だけある場合。"""
    payload = {"active_notebook_id": "nb-from-active"}
    assert generate_podcast._extract_notebook_id(payload) == "nb-from-active"


def test_extract_notebook_id_legacy_flat_id():
    payload = {"id": "legacy-id", "title": "x"}
    assert generate_podcast._extract_notebook_id(payload) == "legacy-id"


def test_extract_notebook_id_legacy_notebook_id_key():
    payload = {"notebook_id": "explicit-key"}
    assert generate_podcast._extract_notebook_id(payload) == "explicit-key"


def test_extract_notebook_id_prefers_nested_over_active():
    payload = {
        "notebook": {"id": "from-nested"},
        "active_notebook_id": "from-active",
        "id": "from-flat",
    }
    assert generate_podcast._extract_notebook_id(payload) == "from-nested"


def test_extract_notebook_id_handles_malformed_input():
    assert generate_podcast._extract_notebook_id({}) is None
    assert generate_podcast._extract_notebook_id({"notebook": None}) is None
    assert generate_podcast._extract_notebook_id({"notebook": {"id": 123}}) is None
    assert generate_podcast._extract_notebook_id("not a dict") is None
    assert generate_podcast._extract_notebook_id(None) is None


# ---- _extract_source_id --------------------------------------------------


def test_extract_source_id_new_nested_form():
    payload = {"source": {"id": "src-uuid", "title": "x", "type": "url"}}
    assert generate_podcast._extract_source_id(payload) == "src-uuid"


def test_extract_source_id_legacy_flat():
    assert generate_podcast._extract_source_id({"id": "old"}) == "old"
    assert generate_podcast._extract_source_id({"source_id": "old2"}) == "old2"


def test_extract_source_id_handles_malformed():
    assert generate_podcast._extract_source_id({}) is None
    assert generate_podcast._extract_source_id({"source": {}}) is None
    assert generate_podcast._extract_source_id({"source": "not a dict"}) is None


# ---- _extract_task_id ----------------------------------------------------


def test_extract_task_id_from_generate_audio_completed():
    payload = {
        "task_id": "tsk-uuid",
        "status": "completed",
        "url": "https://x/y",
    }
    assert generate_podcast._extract_task_id(payload) == "tsk-uuid"


def test_extract_task_id_from_generate_audio_pending():
    payload = {"task_id": "pending-id", "status": "pending"}
    assert generate_podcast._extract_task_id(payload) == "pending-id"


def test_extract_task_id_from_artifact_nested():
    payload = {"artifact": {"id": "artifact-uuid", "title": "Audio"}}
    assert generate_podcast._extract_task_id(payload) == "artifact-uuid"


def test_extract_task_id_from_stdout_string():
    stdout = '{"task_id": "from-string", "status": "pending"}'
    assert generate_podcast._extract_task_id(stdout) == "from-string"


def test_extract_task_id_legacy_keys():
    assert generate_podcast._extract_task_id({"artifact_id": "legacy"}) == "legacy"
    assert generate_podcast._extract_task_id({"id": "even-older"}) == "even-older"


def test_extract_task_id_handles_garbage():
    assert generate_podcast._extract_task_id("not json") is None
    assert generate_podcast._extract_task_id({}) is None
    assert generate_podcast._extract_task_id({"task_id": 123}) is None


# ---- create_notebook (integration with mocked _run) ----------------------


class _FakeProc:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_create_notebook_parses_new_nested_response(monkeypatch):
    def fake_run(cmd, **kwargs):  # noqa: ARG001
        return _FakeProc(
            stdout='{"notebook": {"id": "nb-new", "title": "arXiv 2026-05-25"}, '
            '"active_notebook_id": "nb-new"}'
        )

    monkeypatch.setattr(generate_podcast, "_run", fake_run)
    assert generate_podcast.create_notebook("arXiv 2026-05-25") == "nb-new"


def test_create_notebook_raises_when_id_missing(monkeypatch):
    def fake_run(cmd, **kwargs):  # noqa: ARG001
        return _FakeProc(stdout='{"foo": "bar"}')

    monkeypatch.setattr(generate_podcast, "_run", fake_run)
    with pytest.raises(generate_podcast.NotebookLMError, match="notebook id missing"):
        generate_podcast.create_notebook("title")


def test_add_source_parses_new_nested_response(monkeypatch):
    def fake_run(cmd, **kwargs):  # noqa: ARG001
        return _FakeProc(stdout='{"source": {"id": "src-1", "type": "url"}}')

    monkeypatch.setattr(generate_podcast, "_run", fake_run)
    assert generate_podcast.add_source("nb-1", "https://arxiv.org/abs/x") == "src-1"


# ---- restore_storage_state logging --------------------------------------


def test_restore_storage_state_logs_existing_path_when_env_unset(
    monkeypatch, caplog
):
    monkeypatch.delenv(generate_podcast.STORAGE_STATE_ENV, raising=False)
    fake_path = Path("/tmp/fake-storage.json")
    monkeypatch.setattr(
        generate_podcast, "_resolve_storage_state_path", lambda: fake_path
    )

    with caplog.at_level(logging.INFO, logger="src.generate_podcast"):
        result = generate_podcast.restore_storage_state()

    assert result is None
    assert any(
        "using existing storage_state" in rec.message and str(fake_path) in rec.message
        for rec in caplog.records
    )


def test_restore_storage_state_warns_when_no_file(monkeypatch, caplog):
    monkeypatch.delenv(generate_podcast.STORAGE_STATE_ENV, raising=False)
    monkeypatch.setattr(
        generate_podcast, "_resolve_storage_state_path", lambda: None
    )

    with caplog.at_level(logging.WARNING, logger="src.generate_podcast"):
        result = generate_podcast.restore_storage_state()

    assert result is None
    assert any(
        "no storage_state.json found" in rec.message for rec in caplog.records
    )
    assert any(rec.levelno == logging.WARNING for rec in caplog.records)


def test_restore_storage_state_writes_file_when_env_set(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "storage_state.json"
    payload = b'{"cookies": []}'
    monkeypatch.setenv(
        generate_podcast.STORAGE_STATE_ENV,
        base64.b64encode(payload).decode("ascii"),
    )

    result = generate_podcast.restore_storage_state(path=target)
    assert result == target
    assert target.read_bytes() == payload
    # パーミッションが 0o600 になっているか
    assert (target.stat().st_mode & 0o777) == 0o600


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
