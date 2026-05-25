"""fetch_arxiv: arxiv.Client.results をモックして検証する。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import fetch_arxiv


@dataclass
class _FakeAuthor:
    name: str


@dataclass
class _FakeResult:
    entry_id: str
    title: str
    summary: str
    authors: list[_FakeAuthor]
    published: datetime
    primary_category: str
    pdf_url: str


def _make_result(
    arxiv_id: str,
    title: str = "A neat paper",
    summary: str = "Summary",
    days_ago: float = 0.1,
    category: str = "cs.AI",
) -> _FakeResult:
    pub = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return _FakeResult(
        entry_id=f"http://arxiv.org/abs/{arxiv_id}v1",
        title=title,
        summary=summary,
        authors=[_FakeAuthor("Alice"), _FakeAuthor("Bob")],
        published=pub,
        primary_category=category,
        pdf_url=f"http://arxiv.org/pdf/{arxiv_id}",
    )


class _FakeClient:
    def __init__(self, results, **kwargs):
        self._results = results

    def results(self, search):  # noqa: ARG002 — match arxiv.Client signature
        return iter(self._results)


def _install_fake_client(monkeypatch, results):
    def factory(*args, **kwargs):  # noqa: ARG001
        return _FakeClient(results)

    monkeypatch.setattr(fetch_arxiv.arxiv, "Client", factory)


def test_arxiv_id_strips_version_suffix():
    assert (
        fetch_arxiv._arxiv_id_from_entry("http://arxiv.org/abs/2405.12345v3")
        == "2405.12345"
    )
    assert (
        fetch_arxiv._arxiv_id_from_entry("https://arxiv.org/abs/2401.00001")
        == "2401.00001"
    )


def test_build_category_query():
    assert (
        fetch_arxiv._build_category_query(["cs.AI", "cs.LG"])
        == "cat:cs.AI OR cat:cs.LG"
    )


def test_fetch_returns_up_to_n_papers(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [_make_result(f"2405.0000{i}") for i in range(5)],
    )
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"], n=3, query_days=7
    )
    assert len(papers) == 3
    assert papers[0].arxiv_id == "2405.00000"
    assert papers[0].abs_url == "https://arxiv.org/abs/2405.00000"
    assert papers[0].authors == ["Alice", "Bob"]


def test_fetch_excludes_keywords(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [
            _make_result("2405.00001", title="A boring survey paper"),
            _make_result("2405.00002", title="A solid empirical study"),
        ],
    )
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"],
        n=5,
        query_days=7,
        exclude_keywords=["survey"],
    )
    assert [p.arxiv_id for p in papers] == ["2405.00002"]


def test_fetch_excludes_already_published(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [
            _make_result("2405.00001"),
            _make_result("2405.00002"),
        ],
    )
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"],
        n=5,
        query_days=7,
        exclude_published_ids={"2405.00001"},
    )
    assert [p.arxiv_id for p in papers] == ["2405.00002"]


def test_fetch_drops_old_papers(monkeypatch):
    _install_fake_client(
        monkeypatch,
        [
            _make_result("2405.00001", days_ago=0.2),
            _make_result("2405.00002", days_ago=2.5),  # outside query_days=1
        ],
    )
    papers = fetch_arxiv.fetch_latest_papers(
        categories=["cs.AI"], n=5, query_days=1
    )
    assert [p.arxiv_id for p in papers] == ["2405.00001"]


def test_published_ids_roundtrip(tmp_path: Path):
    state_file = tmp_path / "published.json"
    assert fetch_arxiv.load_published_ids(state_file) == set()

    fetch_arxiv.record_published_ids(["a", "b"], path=state_file)
    assert fetch_arxiv.load_published_ids(state_file) == {"a", "b"}

    fetch_arxiv.record_published_ids(["b", "c"], path=state_file)
    assert fetch_arxiv.load_published_ids(state_file) == {"a", "b", "c"}

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload == {"ids": ["a", "b", "c"]}


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
