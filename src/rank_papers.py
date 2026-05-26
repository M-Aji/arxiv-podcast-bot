"""Claude Haiku による論文関連度スコアリング。

`config.INTEREST_PROFILE` を基準に各論文を 0.0〜10.0 でスコアリングし、
降順に並べ替えて返す。API 失敗時は元の順序を維持するフォールバックを持つ。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass

from src import config
from src.fetch_arxiv import ArxivPaper

logger = logging.getLogger(__name__)


FALLBACK_SCORE = 5.0
FALLBACK_RATIONALE_API = "(評価失敗のため中立評価)"
FALLBACK_RATIONALE_SKIP = "(ranking skipped)"

_RETRY_BACKOFFS = (1, 2, 4)  # 指数バックオフ (秒)


@dataclass
class RankedPaper:
    paper: ArxivPaper
    score: float
    rationale: str


def _system_prompt() -> str:
    return (
        "あなたは研究者の興味プロファイルに基づいて論文を評価するアシスタントです。\n"
        "以下のプロファイルを基準に、与えられた論文がこの研究者にとってどの程度\n"
        "関連性が高いかを 0.0〜10.0 でスコアリングしてください。\n"
        "\n"
        "評価軸:\n"
        "- プロファイルの「強く興味あり/優先度高」のテーマと合致 → 7.0〜10.0\n"
        "- 「普通に興味あり/優先度中」のテーマと合致 → 4.0〜7.0\n"
        "- 「スキップしたい/優先度低」に該当 → 0.0〜3.0\n"
        "- どれにも明確に当てはまらない → 3.0〜5.0\n"
        "\n"
        "出力は厳密に以下のJSON形式のみ（前後に何も書かない）:\n"
        '{"score": <float>, "rationale": "<日本語で1行、なぜこのスコアなのか>"}\n'
        "\n"
        "プロファイル:\n"
        f"{config.INTEREST_PROFILE}"
    )


def _user_prompt(paper: ArxivPaper) -> str:
    return f"タイトル: {paper.title}\n要約: {paper.abstract}"


def _extract_text(response) -> str:
    """Anthropic Messages API のレスポンスから本文テキストを抜く。"""
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


def _parse_score_json(text: str) -> tuple[float, str]:
    """`{"score": ..., "rationale": "..."}` を取り出す。

    モデルが前後に余分な文字を付けたケースを許容するため、最初の `{` から
    最後の `}` までを切り出してパースする。
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"JSON object not found in: {text!r}")
    payload = json.loads(text[start : end + 1])
    score = float(payload["score"])
    rationale = str(payload.get("rationale", "")).strip()
    # 0.0〜10.0 の範囲にクランプ
    score = max(0.0, min(10.0, score))
    return score, rationale


def _score_single_paper(client, paper: ArxivPaper) -> RankedPaper:
    """1本だけ API を叩いてスコアリング。失敗時は中立評価で返す。"""
    last_error: Exception | None = None
    for attempt, backoff in enumerate(_RETRY_BACKOFFS, start=1):
        try:
            response = client.messages.create(
                model=config.RANKING_MODEL,
                max_tokens=200,
                temperature=0.3,
                timeout=config.RANKING_TIMEOUT_SECONDS,
                system=_system_prompt(),
                messages=[{"role": "user", "content": _user_prompt(paper)}],
            )
            text = _extract_text(response)
            score, rationale = _parse_score_json(text)
            return RankedPaper(paper=paper, score=score, rationale=rationale)
        except Exception as exc:  # noqa: BLE001 — API/parse どちらも捕捉
            last_error = exc
            if attempt < len(_RETRY_BACKOFFS):
                logger.warning(
                    "ranking attempt %d/%d failed for %s: %s; retrying in %ds",
                    attempt,
                    len(_RETRY_BACKOFFS),
                    paper.arxiv_id,
                    exc,
                    backoff,
                )
                time.sleep(backoff)
            else:
                logger.warning(
                    "ranking failed for %s after %d attempts: %s",
                    paper.arxiv_id,
                    len(_RETRY_BACKOFFS),
                    exc,
                )
    # ここに来るのは全リトライ失敗時
    assert last_error is not None
    return RankedPaper(
        paper=paper,
        score=FALLBACK_SCORE,
        rationale=FALLBACK_RATIONALE_API,
    )


def _fallback_all(candidates: list[ArxivPaper]) -> list[RankedPaper]:
    """全件 score=5.0、元の順序のままで返す。"""
    return [
        RankedPaper(
            paper=p, score=FALLBACK_SCORE, rationale=FALLBACK_RATIONALE_SKIP
        )
        for p in candidates
    ]


def _build_client():
    """Anthropic クライアントを生成。SDK 未インストールなら例外を投げる。"""
    from anthropic import Anthropic  # 遅延 import（テスト時のモック容易化）

    return Anthropic()


def _truncate(text: str, n: int = 80) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def rank_papers(candidates: list[ArxivPaper]) -> list[RankedPaper]:
    """各論文を Claude Haiku で 0-10 スコアリングし、降順ソートで返す。"""
    if not candidates:
        return []

    if not os.environ.get(config.ANTHROPIC_API_KEY_ENV):
        logger.warning(
            "%s not set; skipping ranking and preserving original order",
            config.ANTHROPIC_API_KEY_ENV,
        )
        return _fallback_all(candidates)

    try:
        client = _build_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "failed to build Anthropic client (%s); skipping ranking", exc
        )
        return _fallback_all(candidates)

    ranked: list[RankedPaper] = []
    api_failures = 0
    for paper in candidates:
        result = _score_single_paper(client, paper)
        if result.rationale == FALLBACK_RATIONALE_API:
            api_failures += 1
        ranked.append(result)
        logger.info(
            "ranked: %.1f | %s | %s",
            result.score,
            _truncate(paper.title),
            _truncate(result.rationale, 60),
        )

    if api_failures == len(candidates):
        logger.warning(
            "all %d papers failed ranking; preserving original order",
            len(candidates),
        )
        return _fallback_all(candidates)

    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked


def select_top_n(ranked: list[RankedPaper], n: int) -> list[ArxivPaper]:
    """上位 n 本の ArxivPaper を返す。"""
    return [r.paper for r in ranked[:n]]
