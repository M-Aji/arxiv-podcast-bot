"""daily_archive: 候補論文 Markdown ダンプの構造を検証する。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.daily_archive import write_daily_archive
from src.fetch_arxiv import ArxivPaper
from src.rank_papers import RankedPaper


def _paper(
    arxiv_id: str,
    title: str = "Sample Paper Title",
    *,
    authors: list[str] | None = None,
    abstract: str = "First line of abstract.\nSecond line.\n\nThird line after a blank.",
    category: str = "cs.AI",
) -> ArxivPaper:
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors if authors is not None else ["Alice", "Bob"],
        abstract=abstract,
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        published=datetime(2026, 5, 26, tzinfo=timezone.utc),
        primary_category=category,
    )


def _ranked(
    arxiv_id: str,
    score: float,
    *,
    title: str = "Sample Paper Title",
    rationale: str = "テスト用の評価理由",
    japanese_title: str | None = None,
    abstract: str | None = None,
) -> RankedPaper:
    kwargs = {"title": title}
    if abstract is not None:
        kwargs["abstract"] = abstract
    return RankedPaper(
        paper=_paper(arxiv_id, **kwargs),
        score=score,
        rationale=rationale,
        japanese_title=japanese_title,
    )


# ---- 基本構造 -----------------------------------------------------------


def test_writes_file_at_expected_path(tmp_path):
    ranked = [_ranked(f"p{i}", score=10.0 - i) for i in range(3)]

    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=2, output_dir=tmp_path
    )

    assert path == tmp_path / "2026-05-26.md"
    assert path.exists()


def test_creates_output_dir_if_missing(tmp_path):
    nested = tmp_path / "does" / "not" / "exist"
    ranked = [_ranked("p1", score=9.0)]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=1, output_dir=nested
    )
    assert path.parent == nested
    assert nested.is_dir()


def test_overwrites_existing_file(tmp_path):
    path = tmp_path / "2026-05-26.md"
    path.write_text("OLD CONTENT", encoding="utf-8")

    ranked = [_ranked("p1", score=9.0, title="New Title")]
    write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=1, output_dir=tmp_path
    )

    new_content = path.read_text(encoding="utf-8")
    assert "OLD CONTENT" not in new_content
    assert "New Title" in new_content


# ---- ヘッダー & 件数表示 -----------------------------------------------


def test_header_includes_date_and_counts(tmp_path):
    # 30本: 上位5本 + 見送り25本
    ranked = [_ranked(f"p{i:02d}", score=10.0 - i * 0.1) for i in range(30)]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=5, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")

    assert "# arXiv Daily Digest — 2026-05-26" in text
    assert "候補プール: 30本" in text
    assert "ポッドキャスト化: 上位5本" in text
    assert "見送り25本" in text


# ---- 上位N本の表示 ------------------------------------------------------


def test_selected_section_lists_top_n_with_links_and_scores(tmp_path):
    ranked = [
        _ranked("p1", score=8.5, title="Paper One"),
        _ranked("p2", score=7.2, title="Paper Two"),
        _ranked("p3", score=6.0, title="Paper Three"),
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=2, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")

    assert "## 📻 ポッドキャストに使用した2本" in text
    assert "[Paper One](https://arxiv.org/abs/p1) — score 8.5" in text
    assert "[Paper Two](https://arxiv.org/abs/p2) — score 7.2" in text
    # 見送り側にしか出ないはずの詳細（評価理由）が選定側に出ない
    selected_section = text.split("---")[0]
    assert "評価理由" not in selected_section


# ---- 邦訳行のルール ----------------------------------------------------


def test_english_title_gets_japanese_translation_line(tmp_path):
    ranked = [
        _ranked(
            "p1",
            score=9.0,
            title="An English Title About LLMs",
            japanese_title="LLMに関する英語タイトル",
        ),
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=1, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")
    assert "邦訳: LLMに関する英語タイトル" in text


def test_japanese_title_omits_translation_line(tmp_path):
    ranked = [
        _ranked(
            "p1",
            score=9.0,
            title="日本語のタイトルです",
            japanese_title="should be ignored",
        ),
        # 見送り側にも日本語タイトルを置く
        _ranked(
            "p2",
            score=5.0,
            title="混在 with English タイトル",
            japanese_title="ignored too",
        ),
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=1, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")
    # 日本語タイトルには邦訳を一切出さない
    assert "邦訳:" not in text


def test_english_title_with_none_translation_falls_back(tmp_path):
    ranked = [
        _ranked(
            "p1",
            score=9.0,
            title="English Title Without Translation",
            japanese_title=None,
        ),
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=0, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")
    assert "邦訳: (翻訳失敗)" in text or "邦訳:** (翻訳失敗)" in text


def test_english_title_with_empty_translation_falls_back(tmp_path):
    ranked = [
        _ranked(
            "p1",
            score=9.0,
            title="English Title",
            japanese_title="   ",
        ),
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=0, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")
    assert "(翻訳失敗)" in text


# ---- 見送りセクションの詳細フィールド ----------------------------------


def test_unselected_entry_includes_all_fields(tmp_path):
    ranked = [
        _ranked("p1", score=9.5, title="Top Paper"),  # selected
        RankedPaper(
            paper=ArxivPaper(
                arxiv_id="p2",
                title="Skipped Paper",
                authors=["Charlie", "Dave"],
                abstract="Multiline\nabstract here.",
                abs_url="https://arxiv.org/abs/p2",
                pdf_url="https://arxiv.org/pdf/p2",
                published=datetime(2026, 5, 25, tzinfo=timezone.utc),
                primary_category="cs.CL",
            ),
            score=6.8,
            rationale="ベンチマーク中心で応用が薄い",
            japanese_title="見送られた論文",
        ),
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=1, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")

    assert "### #2 / score 6.8" in text
    assert "**Title:** Skipped Paper" in text
    assert "**邦訳:** 見送られた論文" in text
    assert "**Authors:** Charlie, Dave" in text
    assert "**Category:** cs.CL" in text
    assert "**Published:** 2026-05-25" in text
    assert "**arXiv:** https://arxiv.org/abs/p2" in text
    assert "**評価理由:** ベンチマーク中心で応用が薄い" in text


def test_abstract_preserves_line_breaks_as_blockquote(tmp_path):
    abstract = "Line one.\nLine two.\n\nLine four after blank."
    ranked = [
        _ranked("p1", score=9.0, title="Top", abstract="ignored"),  # selected
        _ranked(
            "p2",
            score=5.0,
            title="Unselected Paper",
            abstract=abstract,
        ),
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=1, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")

    # 各行が "> " 接頭辞付きの引用ブロックになっている
    assert "> Line one." in text
    assert "> Line two." in text
    assert "> Line four after blank." in text
    # 空行は ">" のみ（行末スペースなし）で保持される
    assert "\n>\n" in text


# ---- 順序と件数 --------------------------------------------------------


def test_unselected_section_is_in_descending_score_order(tmp_path):
    ranked = [
        _ranked(f"p{i}", score=10.0 - i, title=f"Paper {i}")
        for i in range(5)
    ]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=2, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")

    # 見送り側は #3 → #4 → #5 の順
    pos_3 = text.find("### #3")
    pos_4 = text.find("### #4")
    pos_5 = text.find("### #5")
    assert 0 < pos_3 < pos_4 < pos_5


# ---- エッジケース ------------------------------------------------------


def test_empty_ranked_input_does_not_crash(tmp_path):
    path = write_daily_archive(
        date(2026, 5, 26), [], selected_count=5, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")

    assert "候補プール: 0本" in text
    assert "ポッドキャスト化: 上位0本" in text
    assert "見送り0本" in text
    # 「該当なし」フォールバックが両セクションに出る
    assert text.count("(該当なし)") >= 2


def test_all_selected_no_unselected(tmp_path):
    ranked = [_ranked(f"p{i}", score=9.0 - i) for i in range(3)]
    path = write_daily_archive(
        date(2026, 5, 26), ranked, selected_count=5, output_dir=tmp_path
    )
    text = path.read_text(encoding="utf-8")
    assert "見送り0本" in text
    assert "ポッドキャスト化: 上位3本" in text


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
