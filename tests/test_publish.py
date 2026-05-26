"""src/publish.py の commit_and_push 堅牢化検証。

`git add` に存在しないパスを渡すと exit 128 で死ぬため、commit_and_push は
存在チェックで弾く必要がある。subprocess は monkeypatch で記録だけする。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src import publish as publish_module


@pytest.fixture
def captured_calls(monkeypatch):
    """publish._run の呼び出しを記録するフィクスチャ。"""
    calls: list[list[str]] = []

    class _Proc:
        returncode = 1  # diff --cached --quiet → 変更あり扱い
        stdout = ""
        stderr = ""

    def fake_run(cmd, *, check=True):  # noqa: ARG001
        calls.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(publish_module, "_run", fake_run)
    return calls


def _git_add_calls(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if len(c) >= 2 and c[:2] == ["git", "add"]]


def _git_commit_calls(calls: list[list[str]]) -> list[list[str]]:
    return [c for c in calls if len(c) >= 2 and c[:2] == ["git", "commit"]]


def test_commit_and_push_skips_missing_files(tmp_path, captured_calls):
    """存在するファイルだけ add 対象になり、存在しないものは混じっても壊れない。"""
    existing = tmp_path / "feed.xml"
    existing.write_text("<rss/>")
    missing = tmp_path / "does_not_exist.json"

    publish_module.commit_and_push([existing, missing], date(2026, 5, 26))

    add_calls = _git_add_calls(captured_calls)
    assert len(add_calls) == 1
    staged = add_calls[0][2:]
    assert str(existing) in staged
    assert str(missing) not in staged


def test_commit_and_push_returns_early_when_all_missing(tmp_path, captured_calls):
    """全パスが存在しなければ git は一切呼ばれない（exit 128 防止）。"""
    p1 = tmp_path / "nope1.xml"
    p2 = tmp_path / "nope2.json"

    publish_module.commit_and_push([p1, p2], date(2026, 5, 26))

    # git add も diff も commit も push も呼ばれない
    assert captured_calls == []


def test_commit_and_push_partial_existence_commits_only_existing(
    tmp_path, captured_calls
):
    """3 つ中 2 つだけ存在するなら、その 2 つだけが add される。"""
    a = tmp_path / "a.xml"
    a.write_text("a")
    b_missing = tmp_path / "b.json"
    c = tmp_path / "c.md"
    c.write_text("c")

    publish_module.commit_and_push([a, b_missing, c], date(2026, 5, 26))

    add_calls = _git_add_calls(captured_calls)
    assert len(add_calls) == 1
    staged = add_calls[0][2:]
    assert sorted(staged) == sorted([str(a), str(c)])
    # 変更ありなので commit/push まで進んでいるはず
    assert _git_commit_calls(captured_calls), "commit should be invoked"


def test_commit_and_push_skips_commit_when_no_staged_changes(
    tmp_path, monkeypatch
):
    """add 後に変更なし（diff --cached --quiet が exit 0）なら commit/push しない。"""
    existing = tmp_path / "feed.xml"
    existing.write_text("<rss/>")

    calls: list[list[str]] = []

    class _Proc:
        returncode = 0  # diff --cached --quiet で「変更なし」を表現
        stdout = ""
        stderr = ""

    def fake_run(cmd, *, check=True):  # noqa: ARG001
        calls.append(list(cmd))
        return _Proc()

    monkeypatch.setattr(publish_module, "_run", fake_run)

    publish_module.commit_and_push([existing], date(2026, 5, 26))

    assert _git_add_calls(calls), "git add should still be invoked"
    assert _git_commit_calls(calls) == []
    assert not any(c[:2] == ["git", "push"] for c in calls)


def test_commit_and_push_dry_run_skips_git(tmp_path, captured_calls):
    """dry_run=True なら git コマンドは一切呼ばれない。"""
    existing = tmp_path / "feed.xml"
    existing.write_text("<rss/>")

    publish_module.commit_and_push(
        [existing], date(2026, 5, 26), dry_run=True
    )

    assert captured_calls == []


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
