import os
import json
import logging
import httpx
from enum import Enum
from pydantic import BaseModel, ValidationError
from typing import List, Optional

logger = logging.getLogger(__name__)


class GDDType(str, Enum):
    ONE_SHEET = "one_sheet"
    TEN_PAGER = "ten_pager"
    BEAT_CHART = "beat_chart"
    FULL_GDD = "full_gdd"


class OneSheetData(BaseModel):
    title: str
    target_systems: List[str]
    target_age: str
    esrb_rating: str
    story_summary: str
    gameplay_modes: List[str]
    usps: List[str]
    competitive_products: List[str]


class BeatChartLevel(BaseModel):
    level_name: str
    progression_focus: str
    mechanics_introduced: List[str]
    enemies_introduced: List[str]
    estimated_play_time: str


class GameDesignDocumentResponse(BaseModel):
    document_type: str
    one_sheet: OneSheetData
    beat_chart: Optional[List[BeatChartLevel]] = None
    visual_style_prompt: str


META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
MODEL_ID = "muse-wonder-1.0"


class GDDAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")
        self.url = META_RESPONSES_URL
        # Reasoning models need generous read timeouts: 10s connect, 120s read.
        self.timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

    def _build_prompt(self, prompt: str, genre: str, engine: str, want_beat_chart: bool) -> str:
        beat_chart_schema = (
            '\n  "beat_chart": [{"level_name": str, "progression_focus": str,'
            ' "mechanics_introduced": [str], "enemies_introduced": [str],'
            ' "estimated_play_time": str}],' if want_beat_chart else ""
        )
        return (
            f"Generate a game concept for this need: '{prompt}'. Genre: {genre}, Engine: {engine}.\n"
            "Respond with VALID JSON ONLY, no markdown fences, no commentary, matching exactly this schema:\n"
            "{\n"
            '  "one_sheet": {"title": str, "target_systems": [str], "target_age": str,'
            ' "esrb_rating": str, "story_summary": str, "gameplay_modes": [str],'
            f' "usps": [str], "competitive_products": [str]}},{beat_chart_schema}\n'
            '  "visual_style_prompt": str\n'
            "}"
        )

    @staticmethod
    def _extract_output_text(data: dict) -> str:
        """Per Meta docs: text lives in output[] message items' output_text blocks."""
        chunks: List[str] = []
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for block in item.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "output_text":
                    chunks.append(block.get("text", ""))
        return "".join(chunks)

    async def _call_meta_api(self, text_prompt: str) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": MODEL_ID,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": text_prompt}],
                }
            ],
            "reasoning": {"effort": "medium"},
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.url, headers=headers, json=payload)
        # 1. HTTP-level check: raises HTTPStatusError with status + body on 4xx/5xx.
        response.raise_for_status()
        data = response.json()
        # 2. Response-level check: incomplete/failed must not be treated as answers.
        if data.get("status") not in ("completed", None):
            raise RuntimeError(
                f"Meta response not completed: status={data.get('status')!r} details={str(data)[:500]}"
            )
        return data

    def _mock_response(
        self, prompt: str, doc_type: GDDType, genre: str, engine: str
    ) -> GameDesignDocumentResponse:
        one_sheet_data = {
            "title": f"Project: {prompt[:20]}...",
            "target_systems": [engine, "PC"],
            "target_age": "12+",
            "esrb_rating": "T (Teen)",
            "story_summary": f"Un jeu {genre} basé sur : {prompt}",
            "gameplay_modes": ["Story Mode", "Survival"],
            "usps": ["Interaction dynamique", "Inventaire temps réel"],
            "competitive_products": ["Don't Starve", "RimWorld"],
        }
        beat_chart_data = [
            {
                "level_name": "Niveau 1",
                "progression_focus": "Apprentissage des contrôles",
                "mechanics_introduced": ["Déplacement", "Récolte"],
                "enemies_introduced": ["Zombie lent"],
                "estimated_play_time": "5 min",
            }
        ]
        want_beat = doc_type in (GDDType.BEAT_CHART, GDDType.FULL_GDD)
        return GameDesignDocumentResponse(
            document_type=doc_type.value,
            one_sheet=OneSheetData(**one_sheet_data),
            beat_chart=[BeatChartLevel(**level) for level in beat_chart_data] if want_beat else None,
            visual_style_prompt=f"2D sprite sheet, {genre}, {prompt}, pixel art style",
        )

    async def generate_document(
        self,
        prompt: str,
        doc_type: GDDType = GDDType.ONE_SHEET,
        genre: str = "Survie 2D",
        engine: str = "Godot 4",
    ) -> GameDesignDocumentResponse:
        want_beat = doc_type in (GDDType.BEAT_CHART, GDDType.FULL_GDD)

        if not self.api_key:
            logger.warning("META_LLAMA_API_KEY missing: serving mock GDD (no Meta call made).")
            return self._mock_response(prompt, doc_type, genre, engine)

        try:
            data = await self._call_meta_api(self._build_prompt(prompt, genre, engine, want_beat))
            raw_text = (
                self._extract_output_text(data).strip().removeprefix("```json").removesuffix("```").strip()
            )
            parsed = json.loads(raw_text)
            return GameDesignDocumentResponse(
                document_type=doc_type.value,
                one_sheet=OneSheetData(**parsed["one_sheet"]),
                beat_chart=[BeatChartLevel(**lvl) for lvl in parsed.get("beat_chart", [])]
                if want_beat
                else None,
                visual_style_prompt=parsed["visual_style_prompt"],
            )
        except httpx.HTTPStatusError as e:
            logger.error("Meta API HTTP %s: %s", e.response.status_code, e.response.text[:500])
        except httpx.TimeoutException:
            logger.error("Meta API timed out after %ss read timeout.", self.timeout.read)
        except (json.JSONDecodeError, ValidationError, KeyError, RuntimeError) as e:
            logger.error("Meta response unusable, falling back to mock GDD: %s", e)
        return self._mock_response(prompt, doc_type, genre, engine)
