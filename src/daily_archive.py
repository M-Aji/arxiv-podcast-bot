"""日次候補論文アーカイブを Markdown で残す。

ポッドキャスト化する上位 N 本に加え、見送った残り全本をスコア順で
`daily_papers/YYYY-MM-DD.md` に保存する。後日「あの日見送った論文を読み
返したい」ニーズに応えるための備忘録。
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

from src.rank_papers import RankedPaper

logger = logging.getLogger(__name__)


_DEFAULT_DIR = Path("daily_papers")
_JP_TRANSLATION_FAILED = "(翻訳失敗)"
# CJK Unified Ideographs / Hiragana / Katakana のいずれか1文字でも含めば
# 「タイトルに日本語が混じっている」とみなして邦訳行を省く。
_JP_CHAR_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def _has_japanese(text: str) -> bool:
    return bool(_JP_CHAR_RE.search(text))


def _format_jp_line(ranked: RankedPaper) -> str | None:
    """英語タイトルなら邦訳行を返す。日本語混在なら None。"""
    if _has_japanese(ranked.paper.title):
        return None
    jp = (ranked.japanese_title or "").strip()
    if not jp:
        return f"邦訳: {_JP_TRANSLATION_FAILED}"
    return f"邦訳: {jp}"


def _format_selected_line(index: int, ranked: RankedPaper) -> str:
    """上位 N 本のサマリ行（番号付き、URL リンクと score 表示）。"""
    paper = ranked.paper
    lines = [
        f"{index}. [{paper.title}]({paper.abs_url}) — score {ranked.score:.1f}"
    ]
    jp_line = _format_jp_line(ranked)
    if jp_line is not None:
        # 末尾にスペース2つで Markdown の強制改行
        lines[-1] = lines[-1] + "  "
        lines.append(f"   {jp_line}")
    return "\n".join(lines)


def _format_abstract_quote(abstract: str) -> str:
    """abstract をマークダウンの引用ブロックに変換（改行は保持）。"""
    if not abstract:
        return "> (要約なし)"
    return "\n".join(f"> {line}" if line else ">" for line in abstract.split("\n"))


def _jp_translation_for_detail(ranked: RankedPaper) -> str | None:
    """詳細セクション用の邦訳テキスト。日本語混在タイトルなら None。"""
    if _has_japanese(ranked.paper.title):
        return None
    jp = (ranked.japanese_title or "").strip()
    return jp or _JP_TRANSLATION_FAILED


def _format_unselected_entry(rank: int, ranked: RankedPaper) -> str:
    """見送り論文1本ぶんの詳細セクション。"""
    paper = ranked.paper
    authors = ", ".join(paper.authors) if paper.authors else "(著者情報なし)"
    published = paper.published.date().isoformat()

    parts: list[str] = [
        f"### #{rank} / score {ranked.score:.1f}",
        "",
        f"**Title:** {paper.title}",
    ]
    jp = _jp_translation_for_detail(ranked)
    if jp is not None:
        parts.append(f"**邦訳:** {jp}")
    parts.extend(
        [
            f"**Authors:** {authors}",
            f"**Category:** {paper.primary_category}",
            f"**Published:** {published}",
            f"**arXiv:** {paper.abs_url}",
            "",
            f"**評価理由:** {ranked.rationale}",
            "",
            "**要約:**",
            _format_abstract_quote(paper.abstract),
        ]
    )
    return "\n".join(parts)


def _render_markdown(
    target_date: date,
    ranked: list[RankedPaper],
    selected_count: int,
) -> str:
    total = len(ranked)
    selected = ranked[:selected_count]
    unselected = ranked[selected_count:]

    sections: list[str] = [
        f"# arXiv Daily Digest — {target_date.isoformat()}",
        "",
        (
            f"候補プール: {total}本 / ポッドキャスト化: 上位{len(selected)}本 / "
            f"以下は見送り{len(unselected)}本"
        ),
        "",
        f"## 📻 ポッドキャストに使用した{len(selected)}本",
        "",
    ]

    if selected:
        for i, ranked_paper in enumerate(selected, start=1):
            sections.append(_format_selected_line(i, ranked_paper))
    else:
        sections.append("(該当なし)")

    sections.extend(
        [
            "",
            "---",
            "",
            f"## 📋 見送り{len(unselected)}本（スコア降順）",
            "",
        ]
    )

    if unselected:
        for offset, ranked_paper in enumerate(unselected, start=1):
            rank = selected_count + offset
            sections.append(_format_unselected_entry(rank, ranked_paper))
            sections.append("")
            sections.append("---")
            sections.append("")
    else:
        sections.append("(該当なし)")
        sections.append("")

    # 末尾の余計な空行を整理
    text = "\n".join(sections).rstrip() + "\n"
    return text


def write_daily_archive(
    target_date: date,
    ranked: list[RankedPaper],
    selected_count: int,
    output_dir: Path = _DEFAULT_DIR,
) -> Path:
    """daily_papers/YYYY-MM-DD.md を書き出して Path を返す。

    Args:
        target_date: 配信日。ファイル名に使う。
        ranked: 全候補論文（スコア降順済み想定）。
        selected_count: 上位 N 本をポッドキャスト化したか。
        output_dir: 書き出し先ディレクトリ。デフォルトは "daily_papers"。

    Returns:
        書き出したファイルのパス。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{target_date.isoformat()}.md"
    content = _render_markdown(target_date, ranked, selected_count)
    output_path.write_text(content, encoding="utf-8")
    return output_path
