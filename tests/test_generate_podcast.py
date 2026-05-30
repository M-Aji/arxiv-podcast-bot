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
    captured: dict = {}

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        captured["cmd"] = list(cmd)
        return _FakeProc(stdout='{"source": {"id": "src-1", "type": "url"}}')

    monkeypatch.setattr(generate_podcast, "_run", fake_run)
    pdf_url = "https://arxiv.org/pdf/2405.12345"
    assert generate_podcast.add_source("nb-1", pdf_url) == "src-1"
    # PDF URL がそのまま CLI 引数として渡っていることを確認
    assert pdf_url in captured["cmd"]
    # デフォルト source_type は url
    assert "--type" in captured["cmd"]
    type_idx = captured["cmd"].index("--type")
    assert captured["cmd"][type_idx + 1] == "url"


def test_add_source_uses_file_type_and_mime_for_uploaded_pdf(monkeypatch):
    """source_type=file 時に --type file / --mime-type / --title が渡る。"""
    captured: dict = {}

    def fake_run(cmd, **kwargs):  # noqa: ARG001
        captured["cmd"] = list(cmd)
        return _FakeProc(stdout='{"source": {"id": "src-file-1", "type": "file"}}')

    monkeypatch.setattr(generate_podcast, "_run", fake_run)
    sid = generate_podcast.add_source(
        "nb-1",
        "/tmp/build/pdfs/2405.12345.pdf",
        source_type="file",
        mime_type="application/pdf",
        title="Some Paper Title",
    )
    assert sid == "src-file-1"
    cmd = captured["cmd"]
    # ファイルパスが直接渡されている
    assert "/tmp/build/pdfs/2405.12345.pdf" in cmd
    # --type file
    type_idx = cmd.index("--type")
    assert cmd[type_idx + 1] == "file"
    # --mime-type application/pdf
    assert "--mime-type" in cmd
    mime_idx = cmd.index("--mime-type")
    assert cmd[mime_idx + 1] == "application/pdf"
    # --title
    assert "--title" in cmd
    title_idx = cmd.index("--title")
    assert cmd[title_idx + 1] == "Some Paper Title"


# ---- _extract_task_id_from_error -----------------------------------------


def test_extract_task_id_from_error_matches_real_format():
    msg = (
        "Unexpected error: Task abc-123-def timed out after 300.0s "
        "(last status: in_progress)"
    )
    assert generate_podcast._extract_task_id_from_error(msg) == "abc-123-def"


def test_extract_task_id_from_error_matches_uuid():
    uuid = "9527f563-3b20-40fe-8544-290216b98fb7"
    msg = f"Task {uuid} timed out after 300.0s (last status: pending)"
    assert generate_podcast._extract_task_id_from_error(msg) == uuid


def test_extract_task_id_from_error_returns_none_for_no_match():
    assert generate_podcast._extract_task_id_from_error("") is None
    assert generate_podcast._extract_task_id_from_error(None) is None
    assert (
        generate_podcast._extract_task_id_from_error("Some other error") is None
    )


# ---- _extract_task_id_from_response --------------------------------------


def test_extract_task_id_from_response_prefers_structured_field():
    stdout = '{"task_id": "from-struct", "status": "pending"}'
    assert (
        generate_podcast._extract_task_id_from_response(stdout) == "from-struct"
    )


def test_extract_task_id_from_response_extracts_from_error_message():
    stdout = (
        '{"error": true, "code": "UNEXPECTED_ERROR", '
        '"message": "Unexpected error: Task tsk-xyz timed out after 300.0s '
        '(last status: in_progress)"}'
    )
    assert (
        generate_podcast._extract_task_id_from_response(stdout) == "tsk-xyz"
    )


def test_extract_task_id_from_response_falls_back_to_stderr():
    stdout = "not json output"
    stderr = "ERROR: Task tsk-stderr timed out after 300.0s"
    assert (
        generate_podcast._extract_task_id_from_response(stdout, stderr)
        == "tsk-stderr"
    )


def test_extract_task_id_from_response_returns_none_when_unrecoverable():
    assert generate_podcast._extract_task_id_from_response("") is None
    assert (
        generate_podcast._extract_task_id_from_response(
            '{"error": true, "message": "Some other error"}'
        )
        is None
    )


# ---- generate_audio: 新挙動の網羅 -----------------------------------------


class _SequenceRunner:
    """`_run` を順序付きで差し替えるためのモック。各呼び出しの cmd を記録する。"""

    def __init__(self, *procs: _FakeProc):
        self._procs = list(procs)
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):  # noqa: ARG002
        self.calls.append(list(cmd))
        assert self._procs, f"unexpected extra _run call: {cmd}"
        return self._procs.pop(0)


def _patch_run(monkeypatch, *procs: _FakeProc) -> _SequenceRunner:
    runner = _SequenceRunner(*procs)
    monkeypatch.setattr(generate_podcast, "_run", runner)
    return runner


def test_generate_audio_completes_in_initial_wait(monkeypatch):
    runner = _patch_run(
        monkeypatch,
        _FakeProc(
            stdout='{"task_id": "tsk-1", "status": "completed", "url": "https://x/y"}',
            returncode=0,
        ),
    )
    generate_podcast.generate_audio("nb-1", "instr")
    # generate audio 1回だけ
    assert len(runner.calls) == 1
    assert "generate" in runner.calls[0] and "audio" in runner.calls[0]


def test_generate_audio_polls_same_task_until_completion(monkeypatch):
    # 初回 generate audio は UNEXPECTED_ERROR(タイムアウト) で返る
    timeout_error = _FakeProc(
        stdout='{"error": true, "code": "UNEXPECTED_ERROR", '
        '"message": "Unexpected error: Task tsk-stuck timed out after 300.0s '
        '(last status: in_progress)"}',
        returncode=1,
    )
    # 続く artifact wait は2回タイムアウトしてから3回目で完了
    pending1 = _FakeProc(
        stdout='{"artifact_id": "tsk-stuck", "status": "timeout", '
        '"error": "Timed out after 600 seconds"}',
        returncode=1,
    )
    pending2 = _FakeProc(
        stdout='{"artifact_id": "tsk-stuck", "status": "timeout", '
        '"error": "Timed out after 600 seconds"}',
        returncode=1,
    )
    done = _FakeProc(
        stdout='{"artifact_id": "tsk-stuck", "status": "completed", '
        '"url": "https://audio/done", "error": null}',
        returncode=0,
    )
    runner = _patch_run(monkeypatch, timeout_error, pending1, pending2, done)

    generate_podcast.generate_audio("nb-1", "instr")

    # 1: generate audio, 2-4: artifact wait (all on same task_id)
    assert len(runner.calls) == 4
    assert "generate" in runner.calls[0] and "audio" in runner.calls[0]
    for c in runner.calls[1:]:
        assert "artifact" in c and "wait" in c
        assert "tsk-stuck" in c
    # 同じ generate audio を二度と呼ばない
    assert sum(1 for c in runner.calls if "generate" in c) == 1


def test_generate_audio_gives_up_after_total_budget(monkeypatch):
    # チャンク 600s、総予算 1800s → 3回 wait → タイムアウト確定
    monkeypatch.setattr(generate_podcast.config, "AUDIO_WAIT_CHUNK_SECONDS", 600)
    monkeypatch.setattr(
        generate_podcast.config, "AUDIO_WAIT_RETRY_TIMEOUT_SECONDS", 1800
    )
    timeout_error = _FakeProc(
        stdout='{"error": true, "code": "UNEXPECTED_ERROR", '
        '"message": "Task tsk-zombie timed out after 300.0s"}',
        returncode=1,
    )
    pending = lambda: _FakeProc(  # noqa: E731
        stdout='{"artifact_id": "tsk-zombie", "status": "timeout"}',
        returncode=1,
    )
    runner = _patch_run(
        monkeypatch, timeout_error, pending(), pending(), pending()
    )

    with pytest.raises(
        generate_podcast.NotebookLMError, match="did not complete"
    ) as exc_info:
        generate_podcast.generate_audio("nb-1", "instr")

    assert "tsk-zombie" in str(exc_info.value)
    # initial + 3 chunks (1800 / 600 = 3)
    assert len(runner.calls) == 4


def test_generate_audio_aborts_on_real_failure(monkeypatch):
    # task_id は取れる、しかし wait が status=failed を返す → リトライしない
    timeout_error = _FakeProc(
        stdout='{"error": true, "code": "UNEXPECTED_ERROR", '
        '"message": "Task tsk-fail timed out after 300.0s"}',
        returncode=1,
    )
    failure = _FakeProc(
        stdout='{"artifact_id": "tsk-fail", "status": "failed", '
        '"error": "server-side generation error"}',
        returncode=1,
    )
    runner = _patch_run(monkeypatch, timeout_error, failure)

    with pytest.raises(generate_podcast.NotebookLMError):
        generate_podcast.generate_audio("nb-1", "instr")
    # 1 generate + 1 wait のみ、status=failed で即座に諦める
    assert len(runner.calls) == 2


def test_generate_audio_raises_when_no_task_id_extractable(monkeypatch):
    # auth error などで task_id がそもそも見えないケース
    auth_error = _FakeProc(
        stdout='{"error": true, "code": "AUTH_REQUIRED", '
        '"message": "Auth not found. Run notebooklm login first."}',
        returncode=1,
    )
    runner = _patch_run(monkeypatch, auth_error)

    with pytest.raises(generate_podcast.NotebookLMAuthError):
        generate_podcast.generate_audio("nb-1", "instr")
    # artifact wait は呼ばれない
    assert len(runner.calls) == 1


# ---- _raise_for_output: RATE_LIMITED 検出 --------------------------------


def _make_proc(stdout: str = "", stderr: str = "", returncode: int = 1):
    proc = subprocess.CompletedProcess(
        args=["dummy"], returncode=returncode, stdout=stdout, stderr=stderr
    )
    return proc


def test_raise_for_output_detects_rate_limited_by_code():
    proc = _make_proc(
        stdout='{"error": true, "code": "RATE_LIMITED", '
        '"message": "Error: Rate limited. Retry after 3600s.", '
        '"retry_after": 3600}',
    )
    with pytest.raises(generate_podcast.NotebookLMRateLimitError) as exc_info:
        generate_podcast._raise_for_output(["notebooklm", "create"], proc)
    assert exc_info.value.retry_after == 3600


def test_raise_for_output_detects_rate_limited_by_message_text():
    # code フィールドが無くてもメッセージから拾える（保険）
    proc = _make_proc(stdout="", stderr="Error: rate-limited (HTTP 429)")
    with pytest.raises(generate_podcast.NotebookLMRateLimitError) as exc_info:
        generate_podcast._raise_for_output(["notebooklm", "x"], proc)
    assert exc_info.value.retry_after is None


def test_raise_for_output_rate_limit_takes_precedence_over_auth():
    # 万一同じレスポンスに両方のシグナルが入っていた場合、
    # rate limit が優先される（cron で翌日リトライさせるため）
    proc = _make_proc(
        stdout='{"code": "RATE_LIMITED", "message": "Auth not found"}'
    )
    with pytest.raises(generate_podcast.NotebookLMRateLimitError):
        generate_podcast._raise_for_output(["notebooklm", "x"], proc)


def test_raise_for_output_auth_error_still_works():
    proc = _make_proc(
        stdout='{"error": true, "code": "AUTH_REQUIRED", '
        '"message": "Auth not found."}'
    )
    with pytest.raises(generate_podcast.NotebookLMAuthError):
        generate_podcast._raise_for_output(["notebooklm", "x"], proc)


def test_raise_for_output_generic_error_for_other_failures():
    proc = _make_proc(
        stdout='{"error": true, "code": "VALIDATION_ERROR", '
        '"message": "bad input"}'
    )
    with pytest.raises(generate_podcast.NotebookLMError) as exc_info:
        generate_podcast._raise_for_output(["notebooklm", "x"], proc)
    # 親クラスではあるが、rate-limit / auth サブクラスではないことを確認
    assert not isinstance(
        exc_info.value, generate_podcast.NotebookLMRateLimitError
    )
    assert not isinstance(
        exc_info.value, generate_podcast.NotebookLMAuthError
    )


# ---- add_source: rate limit を再 raise ----------------------------------


def test_add_source_reraises_rate_limit(monkeypatch):
    def fake_run(cmd, **kwargs):  # noqa: ARG001
        raise generate_podcast.NotebookLMRateLimitError(
            "Error: Rate limited.", retry_after=3600
        )

    monkeypatch.setattr(generate_podcast, "_run", fake_run)
    with pytest.raises(generate_podcast.NotebookLMRateLimitError):
        generate_podcast.add_source("nb-1", "https://arxiv.org/pdf/x")


# ---- _download_pdf -------------------------------------------------------


class _FakeStreamResponse:
    """`requests.get(stream=True)` の最小モック。with context として動く。"""

    def __init__(self, content: bytes, status_code: int = 200):
        self._content = content
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):  # noqa: ARG002
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            err = __import__("requests").HTTPError(f"HTTP {self.status_code}")
            err.response = self  # type: ignore[attr-defined]
            raise err

    def iter_content(self, chunk_size: int = 8192):
        view = memoryview(self._content)
        for i in range(0, len(view), chunk_size):
            yield bytes(view[i : i + chunk_size])


def _make_paper(arxiv_id: str = "2405.00001") -> "generate_podcast.ArxivPaper":
    from datetime import datetime, timezone
    return generate_podcast.ArxivPaper(
        arxiv_id=arxiv_id,
        title=f"Title {arxiv_id}",
        authors=["A"],
        abstract="abs",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        published=datetime(2026, 5, 27, tzinfo=timezone.utc),
        primary_category="cs.AI",
    )


def test_download_pdf_writes_file_under_arxiv_id_name(monkeypatch, tmp_path):
    paper = _make_paper("2405.00042")
    content = b"%PDF-1.4 fake body" + b"x" * 1024

    captured: dict = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["stream"] = kwargs.get("stream")
        captured["timeout"] = kwargs.get("timeout")
        return _FakeStreamResponse(content)

    monkeypatch.setattr(generate_podcast.requests, "get", fake_get)

    dest = generate_podcast._download_pdf(paper, tmp_path)
    assert dest == tmp_path / "2405.00042.pdf"
    assert dest.read_bytes() == content
    assert captured["url"] == paper.pdf_url
    assert captured["stream"] is True
    # config の値を尊重しているか
    assert captured["timeout"] == generate_podcast.config.PDF_DOWNLOAD_TIMEOUT_SECONDS


def test_download_pdf_raises_arxiv_rate_limit_on_429(monkeypatch, tmp_path):
    paper = _make_paper()

    def fake_get(url, **kwargs):  # noqa: ARG001
        return _FakeStreamResponse(b"", status_code=429)

    monkeypatch.setattr(generate_podcast.requests, "get", fake_get)
    # リトライ間 sleep を消す
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: None)

    with pytest.raises(generate_podcast.ArxivRateLimitError) as exc_info:
        generate_podcast._download_pdf(paper, tmp_path)
    assert exc_info.value.status == 429


def test_download_pdf_raises_arxiv_rate_limit_on_503(monkeypatch, tmp_path):
    paper = _make_paper()

    def fake_get(url, **kwargs):  # noqa: ARG001
        return _FakeStreamResponse(b"", status_code=503)

    monkeypatch.setattr(generate_podcast.requests, "get", fake_get)
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: None)

    with pytest.raises(generate_podcast.ArxivRateLimitError) as exc_info:
        generate_podcast._download_pdf(paper, tmp_path)
    assert exc_info.value.status == 503


def test_download_pdf_aborts_when_exceeding_size_cap(monkeypatch, tmp_path):
    paper = _make_paper("2405.toolarge")
    # 1MB に絞って簡単に上限を超えさせる
    monkeypatch.setattr(
        generate_podcast.config, "PDF_DOWNLOAD_MAX_SIZE_MB", 1
    )
    huge = b"x" * (2 * 1024 * 1024)  # 2MB

    def fake_get(url, **kwargs):  # noqa: ARG001
        return _FakeStreamResponse(huge)

    monkeypatch.setattr(generate_podcast.requests, "get", fake_get)
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: None)

    with pytest.raises(generate_podcast.NotebookLMError, match="exceeded"):
        generate_podcast._download_pdf(paper, tmp_path)
    # 部分書き込みファイルは残さない
    assert not (tmp_path / "2405.toolarge.pdf").exists()


def test_download_pdf_retries_then_succeeds(monkeypatch, tmp_path):
    paper = _make_paper("2405.flaky")
    content = b"ok" * 100
    calls = {"n": 0}

    def fake_get(url, **kwargs):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] < 2:
            raise generate_podcast.requests.ConnectionError("transient")
        return _FakeStreamResponse(content)

    monkeypatch.setattr(generate_podcast.requests, "get", fake_get)
    sleeps: list[float] = []
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: sleeps.append(s))

    dest = generate_podcast._download_pdf(paper, tmp_path)
    assert dest.read_bytes() == content
    assert calls["n"] == 2
    # 1回バックオフして再試行している
    assert len(sleeps) == 1


def test_download_pdf_raises_notebooklm_error_after_all_retries(monkeypatch, tmp_path):
    paper = _make_paper("2405.dead")

    def fake_get(url, **kwargs):  # noqa: ARG001
        raise generate_podcast.requests.ConnectionError("dead host")

    monkeypatch.setattr(generate_podcast.requests, "get", fake_get)
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: None)

    with pytest.raises(generate_podcast.NotebookLMError, match="failed to download"):
        generate_podcast._download_pdf(paper, tmp_path)


# ---- generate_audio_overview: PDF をダウンロードしてからファイル送付 ------


def test_generate_audio_overview_downloads_pdfs_then_uploads_files(
    monkeypatch, tmp_path
):
    """abs/PDF URL ではなくローカルファイルパスを add_source に渡し、
    終了時に PDF ディレクトリが片付くことを保証する。
    """
    from datetime import date

    papers = [_make_paper("2405.00001"), _make_paper("2405.00002")]

    monkeypatch.setattr(generate_podcast, "restore_storage_state", lambda: None)
    monkeypatch.setattr(generate_podcast, "set_language", lambda code="ja": None)
    monkeypatch.setattr(
        generate_podcast, "create_notebook", lambda title: "nb-fake"
    )

    pdf_dir = tmp_path / "pdfs"
    monkeypatch.setattr(generate_podcast.config, "PDF_DOWNLOAD_DIR", pdf_dir)
    # download 間隔の sleep は飛ばす
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: None)

    download_calls: list[str] = []

    def fake_download_pdf(paper, dest_dir):
        download_calls.append(paper.arxiv_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{paper.arxiv_id}.pdf"
        path.write_bytes(b"%PDF-fake")
        return path

    monkeypatch.setattr(generate_podcast, "_download_pdf", fake_download_pdf)

    add_source_calls: list[dict] = []

    def fake_add_source(
        notebook_id, content, *, source_type="url",
        mime_type=None, title=None,
    ):  # noqa: ARG001
        add_source_calls.append(
            {
                "content": content,
                "source_type": source_type,
                "mime_type": mime_type,
                "title": title,
            }
        )
        return f"src-{len(add_source_calls)}"

    monkeypatch.setattr(generate_podcast, "add_source", fake_add_source)
    monkeypatch.setattr(
        generate_podcast,
        "wait_for_source",
        lambda notebook_id, source_id, *, timeout: True,
    )
    monkeypatch.setattr(
        generate_podcast,
        "generate_audio",
        lambda notebook_id, instruction, *, language="ja": None,
    )

    output = tmp_path / "ep.mp3"

    def fake_download_audio(notebook_id, path):  # noqa: ARG001
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 2048)
        return path

    monkeypatch.setattr(generate_podcast, "download_audio", fake_download_audio)

    result = generate_podcast.generate_audio_overview(
        papers, date(2026, 5, 27), output_path=output
    )
    assert result == output

    # 各 paper につき 1 回ずつダウンロード
    assert download_calls == [p.arxiv_id for p in papers]

    # add_source にはローカルファイルパス文字列 + type=file が渡る
    assert len(add_source_calls) == len(papers)
    for call, paper in zip(add_source_calls, papers):
        assert call["source_type"] == "file"
        assert call["mime_type"] == "application/pdf"
        assert call["content"] == str(pdf_dir / f"{paper.arxiv_id}.pdf")
        # URL は渡されていない
        assert "://" not in call["content"]
        assert call["title"] == paper.title

    # 後始末で PDF ディレクトリが消えている
    assert not pdf_dir.exists()


def test_generate_audio_overview_skips_paper_on_download_failure(
    monkeypatch, tmp_path
):
    """個別の PDF ダウンロード失敗は warning ログでスキップし、残りで続行。"""
    from datetime import date

    papers = [_make_paper("2405.00001"), _make_paper("2405.00002")]

    monkeypatch.setattr(generate_podcast, "restore_storage_state", lambda: None)
    monkeypatch.setattr(generate_podcast, "set_language", lambda code="ja": None)
    monkeypatch.setattr(
        generate_podcast, "create_notebook", lambda title: "nb-fake"
    )
    pdf_dir = tmp_path / "pdfs"
    monkeypatch.setattr(generate_podcast.config, "PDF_DOWNLOAD_DIR", pdf_dir)
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: None)

    def fake_download_pdf(paper, dest_dir):
        if paper.arxiv_id == "2405.00001":
            raise generate_podcast.NotebookLMError("transient I/O")
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / f"{paper.arxiv_id}.pdf"
        path.write_bytes(b"ok")
        return path

    monkeypatch.setattr(generate_podcast, "_download_pdf", fake_download_pdf)

    add_source_calls: list[str] = []

    def fake_add_source(
        notebook_id, content, *, source_type="url",
        mime_type=None, title=None,
    ):  # noqa: ARG001
        add_source_calls.append(content)
        return f"src-{len(add_source_calls)}"

    monkeypatch.setattr(generate_podcast, "add_source", fake_add_source)
    monkeypatch.setattr(
        generate_podcast,
        "wait_for_source",
        lambda notebook_id, source_id, *, timeout: True,
    )
    monkeypatch.setattr(
        generate_podcast,
        "generate_audio",
        lambda notebook_id, instruction, *, language="ja": None,
    )

    output = tmp_path / "ep.mp3"
    monkeypatch.setattr(
        generate_podcast,
        "download_audio",
        lambda nb, path: (
            path.parent.mkdir(parents=True, exist_ok=True),
            path.write_bytes(b"\x00" * 2048),
            path,
        )[-1],
    )

    generate_podcast.generate_audio_overview(
        papers, date(2026, 5, 27), output_path=output
    )

    # 失敗した 1 本は add_source されず、残り 1 本だけ
    assert len(add_source_calls) == 1
    assert add_source_calls[0].endswith("2405.00002.pdf")


def test_generate_audio_overview_propagates_arxiv_rate_limit(
    monkeypatch, tmp_path
):
    """arxiv 側で 429/503 が出たら個別スキップではなく上位へ伝播。"""
    from datetime import date

    papers = [_make_paper("2405.00001"), _make_paper("2405.00002")]

    monkeypatch.setattr(generate_podcast, "restore_storage_state", lambda: None)
    monkeypatch.setattr(generate_podcast, "set_language", lambda code="ja": None)
    monkeypatch.setattr(
        generate_podcast, "create_notebook", lambda title: "nb-fake"
    )
    monkeypatch.setattr(
        generate_podcast.config, "PDF_DOWNLOAD_DIR", tmp_path / "pdfs"
    )
    monkeypatch.setattr(generate_podcast.time, "sleep", lambda s: None)

    def fake_download_pdf(paper, dest_dir):  # noqa: ARG001
        raise generate_podcast.ArxivRateLimitError(
            "HTTP 429 after retries", status=429
        )

    monkeypatch.setattr(generate_podcast, "_download_pdf", fake_download_pdf)

    with pytest.raises(generate_podcast.ArxivRateLimitError):
        generate_podcast.generate_audio_overview(
            papers, date(2026, 5, 27), output_path=tmp_path / "ep.mp3"
        )


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
