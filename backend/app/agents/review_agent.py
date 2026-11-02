"""GDD review agent: audits a document against the design checklist and,
on user confirmation, applies selected corrections.

Transport reuses GDDAgent (Meta muse-wonder-1.0). No mock fallback: a fake
audit is worse than an explicit error, so every failure returns status=error
(never raises past the agent boundary, never a 500 from the routes).
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel  # type: ignore

from app.agents.gdd_agent import GDDAgent, GDDType

logger = logging.getLogger(__name__)

DOC_LABELS = {
    GDDType.ONE_SHEET: "one-sheet pitch",
    GDDType.TEN_PAGER: "ten-page treatment",
    GDDType.BEAT_CHART: "beat chart",
    GDDType.FULL_GDD: "full game design document",
}

REVIEW_CHECKLISTS: Dict[GDDType, List[str]] = {
    GDDType.ONE_SHEET: [
        "Title and hook",
        "Target audience and platforms",
        "Story summary (2-3 concrete sentences)",
        "At least 3 specific USPs (no generic claims)",
        "Gameplay modes",
        "Competitive products",
        "Visual style direction",
    ],
    GDDType.TEN_PAGER: [
        "One-sheet essentials (title, audience, summary, USPs)",
        "Camera (3C)",
        "Character (3C)",
        "Controls (3C)",
        "Core loop with fail state",
        "Menu flow",
    ],
    GDDType.BEAT_CHART: [
        "Compact one-sheet (title, summary, USPs)",
        "At least 4 levels in story order",
        "Mechanics introduced progressively",
        "Enemies or challenges per level",
        "Playtime estimate per level",
    ],
    GDDType.FULL_GDD: [
        "One-sheet essentials",
        "3Cs (camera, character, controls)",
        "Core loop and menu flow",
        "Lore and world-building",
        "Level design detail",
        "Feature list",
        "AI type and physics engine",
        "Beat chart covering tutorial to finale",
    ],
}

MAX_DOC_CHARS = 6000


class CheckItem(BaseModel):
    item: str
    status: str  # ok | weak | missing
    detail: str = ""


class Suggestion(BaseModel):
    id: str
    section: str = ""
    issue: str = ""
    proposal: str = ""


class GDDReviewResponse(BaseModel):
    status: str  # success | error
    score: int = 0
    verdict: str = ""
    checks: List[CheckItem] = []
    suggestions: List[Suggestion] = []
    error: Optional[str] = None


class GDDFixResponse(BaseModel):
    status: str  # success | error
    doc_format: str = ""  # json | text
    improved_json: Optional[Dict[str, Any]] = None
    improved_text: str = ""
    applied: List[str] = []
    notes: str = ""
    error: Optional[str] = None


def _strip_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


def _as_json(text: str) -> Optional[Any]:
    try:
        return json.loads(_strip_fences(text))
    except ValueError:
        return None


class ReviewAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else os.getenv("META_LLAMA_API_KEY", "")
        self._llm = GDDAgent(api_key=self.api_key)

    def _checklist(self, doc_type: GDDType) -> List[str]:
        return REVIEW_CHECKLISTS.get(doc_type) or REVIEW_CHECKLISTS[GDDType.ONE_SHEET]

    def _review_prompt(self, doc_type: GDDType, document: str) -> str:
        label = DOC_LABELS.get(doc_type, "game design document")
        items = "\n".join(f"- {item}" for item in self._checklist(doc_type))
        return (
            f"You are a senior game designer auditing a {label} "
            f"(industry-standard game design framework). Be strict but fair.\n"
            f"DOCUMENT:\n{document[:MAX_DOC_CHARS]}\n"
            f"Checklist to verify:\n{items}\n"
            "Respond with VALID JSON ONLY, no markdown fences, matching exactly:\n"
            '{"score": int 0-10, "verdict": str (one sentence), '
            '"checks": [{"item": str, "status": "ok"|"weak"|"missing", "detail": str}], '
            '"suggestions": [{"id": "s1".., "section": str, "issue": str, '
            '"proposal": str (concrete replacement text)}]}\n'
            "Rules: one check per checklist item; 'missing' if absent, 'weak' if "
            "generic or vague, 'ok' only if concrete; 1-6 suggestions ordered by "
            "impact; write in the document's language."
        )

    def _fix_prompt(
        self, doc_type: GDDType, document: str, selected: List[Suggestion], want_json: bool
    ) -> str:
        label = DOC_LABELS.get(doc_type, "game design document")
        corrections = "\n".join(
            f"- [{s.id}] {s.section}: {s.issue} -> {s.proposal}" for s in selected
        )
        out_rule = (
            "Return the FULL patched document as VALID JSON ONLY (same schema, "
            "no markdown fences, no commentary)."
            if want_json
            else "Return the FULL improved document as markdown text, no commentary."
        )
        return (
            f"You are a senior game designer. Improve this {label} by applying "
            f"ONLY the approved corrections below; keep everything else identical, "
            f"same language as the original.\n"
            f"ORIGINAL DOCUMENT:\n{document[:MAX_DOC_CHARS]}\n"
            f"APPROVED CORRECTIONS:\n{corrections}\n"
            f"{out_rule}"
        )

    @staticmethod
    def _clean_checks(raw: Any, checklist: List[str]) -> List[CheckItem]:
        items: List[CheckItem] = []
        if not isinstance(raw, list):
            return items
        for entry in raw[:20]:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status") or "").strip().lower()
            if status not in ("ok", "weak", "missing"):
                continue
            items.append(
                CheckItem(
                    item=str(entry.get("item") or "Check")[:200],
                    status=status,
                    detail=str(entry.get("detail") or "")[:500],
                )
            )
        if not items:
            items = [
                CheckItem(item=name, status="missing", detail="Not evaluated.")
                for name in checklist
            ]
        return items

    @staticmethod
    def _clean_suggestions(raw: Any) -> List[Suggestion]:
        out: List[Suggestion] = []
        if not isinstance(raw, list):
            return out
        for i, entry in enumerate(raw[:8]):
            if not isinstance(entry, dict):
                continue
            proposal = str(entry.get("proposal") or "").strip()
            issue = str(entry.get("issue") or "").strip()
            if not proposal and not issue:
                continue
            out.append(
                Suggestion(
                    id=f"s{i + 1}",
                    section=str(entry.get("section") or "")[:120],
                    issue=issue[:500],
                    proposal=proposal[:2000],
                )
            )
        return out

    async def review_document(
        self, doc_type: GDDType, document: str
    ) -> GDDReviewResponse:
        """Audit a GDD. Never raises: failures become status=error."""
        if not (document or "").strip():
            return GDDReviewResponse(status="error", error="Le document à auditer ne peut pas être vide.")
        if not self.api_key:
            logger.warning("META_LLAMA_API_KEY missing: cannot audit GDD.")
            return GDDReviewResponse(
                status="error", error="Clé API Meta manquante : audit impossible."
            )
        try:
            raw = await self._llm.generate_text(
                self._review_prompt(doc_type, document.strip()), effort="medium"
            )
        except Exception as exc:
            logger.error("GDD audit call failed: %s", str(exc)[:300])
            return GDDReviewResponse(
                status="error", error="Audit impossible : réponse Meta inutilisable."
            )
        parsed = _as_json(raw)
        if not isinstance(parsed, dict):
            logger.error("GDD audit output unusable: %.300s", raw)
            return GDDReviewResponse(
                status="error", error="Audit impossible : réponse Meta inutilisable."
            )
        try:
            score = int(parsed.get("score", 0))
        except (TypeError, ValueError):
            score = 0
        checklist = self._checklist(doc_type)
        return GDDReviewResponse(
            status="success",
            score=max(0, min(10, score)),
            verdict=str(parsed.get("verdict") or "")[:500],
            checks=self._clean_checks(parsed.get("checks"), checklist),
            suggestions=self._clean_suggestions(parsed.get("suggestions")),
        )

    async def apply_fixes(
        self,
        doc_type: GDDType,
        document: str,
        suggestions: List[Suggestion],
        apply_ids: List[str],
    ) -> GDDFixResponse:
        """Apply user-approved suggestions. Never raises: failures are status=error."""
        if not (document or "").strip():
            return GDDFixResponse(status="error", error="Le document à auditer ne peut pas être vide.")
        wanted = [s for s in suggestions if s.id in set(apply_ids or [])]
        if not wanted:
            return GDDFixResponse(
                status="error", error="Sélectionnez au moins une suggestion."
            )
        if not self.api_key:
            logger.warning("META_LLAMA_API_KEY missing: cannot fix GDD.")
            return GDDFixResponse(
                status="error", error="Clé API Meta manquante : audit impossible."
            )
        want_json = _as_json(document.strip()) is not None
        try:
            raw = await self._llm.generate_text(
                self._fix_prompt(doc_type, document.strip(), wanted, want_json),
                effort="medium",
            )
        except Exception as exc:
            logger.error("GDD fix call failed: %s", str(exc)[:300])
            return GDDFixResponse(
                status="error", error="Correction impossible : réponse Meta inutilisable."
            )
        if want_json:
            improved = _as_json(raw)
            if not isinstance(improved, dict):
                logger.error("GDD fix output unusable: %.300s", raw)
                return GDDFixResponse(
                    status="error", error="Correction impossible : réponse Meta inutilisable."
                )
            return GDDFixResponse(
                status="success",
                doc_format="json",
                improved_json=improved,
                applied=[s.id for s in wanted],
            )
        text = _strip_fences(raw)
        if not text:
            return GDDFixResponse(
                status="error", error="Correction impossible : réponse Meta inutilisable."
            )
        return GDDFixResponse(
            status="success",
            doc_format="text",
            improved_text=text,
            applied=[s.id for s in wanted],
        )


__all__ = [
    "ReviewAgent",
    "GDDReviewResponse",
    "GDDFixResponse",
    "CheckItem",
    "Suggestion",
    "REVIEW_CHECKLISTS",
]
