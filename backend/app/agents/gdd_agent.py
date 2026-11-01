import os
import asyncio
import json
import logging
import re
import httpx
from enum import Enum
from pydantic import BaseModel
from typing import List, Optional

from app.services.gaming_data_tools import (
    get_igdb_metadata,
    get_rawg_game_details,
    get_steam_reviews,
    search_rawg_games,
)

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
    status: str


META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
MODEL_ID = "muse-wonder-1.0"


class GDDAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")
        self.url = META_RESPONSES_URL
        # Reasoning models need generous read timeouts: 10s connect, 120s read.
        self.timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

    def _build_prompt(
        self, prompt: str, genre: str, engine: str, doc_type: GDDType, references: str = ""
    ) -> str:
        want_beat_chart = doc_type in (GDDType.BEAT_CHART, GDDType.FULL_GDD)
        guidance = {
            GDDType.ONE_SHEET: (
                "FORMAT: ONE-SHEET PITCH (single page). Keep story_summary to 2-3 punchy sentences, "
                "exactly 3 USPs, and 2 gameplay_modes. Short and sellable, but CONCRETE: name specific "
                "mechanics, places, enemies and numbers instead of generic phrases."
            ),
            GDDType.TEN_PAGER: (
                "FORMAT: TEN-PAGE TREATMENT (expanded pitch, no level breakdown). Write a rich "
                "story_summary of one full paragraph, 4-5 USPs, and 3-4 gameplay_modes."
            ),
            GDDType.BEAT_CHART: (
                "FORMAT: BEAT CHART (progression plan). Keep the one_sheet compact (2-3 sentence "
                "summary, 3 USPs) and devote detail to beat_chart: 4-6 levels in story order, each "
                "with concrete mechanics, enemies and estimated_play_time."
            ),
            GDDType.FULL_GDD: (
                "FORMAT: FULL GAME DESIGN DOCUMENT. Maximum detail everywhere: long story_summary "
                "(one full paragraph), 5 USPs, 4+ gameplay_modes, and a beat_chart of 6-8 levels "
                "covering the entire game from tutorial to finale."
            ),
        }[doc_type]
        beat_chart_schema = (
            '\n  "beat_chart": [{"level_name": str, "progression_focus": str,'
            ' "mechanics_introduced": [str], "enemies_introduced": [str],'
            ' "estimated_play_time": str}],' if want_beat_chart else ""
        )
        refs_block = f"{references}\n" if references else ""
        return (
            f"Generate a game concept for this need: '{prompt}'. Genre: {genre}, Engine: {engine}.\n"
            f"{refs_block}"
            f"{guidance}\n"
            "Keep visual_style_prompt vivid but non-graphic (no blood or gore details): "
            "it doubles as an image-generation prompt.\n"
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

    async def _call_meta_api(self, text_prompt: str, effort: str = "medium") -> dict:
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
            "reasoning": {"effort": effort},
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

    async def generate_text(self, prompt: str, effort: str = "low") -> str:
        """Single text completion. Raises on transport/API/empty failures (caller handles fallback)."""
        data = await self._call_meta_api(prompt, effort=effort)
        text = self._extract_output_text(data).strip()
        if not text:
            raise RuntimeError("Meta returned empty text.")
        return text

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
            status="mock",
        )

    async def _fetch_steam_sentiment(self, rawg: Any) -> str:
        """Steam player sentiment for the top RAWG hit. "" when unavailable. Never raises."""
        try:
            if not isinstance(rawg, dict) or rawg.get("error"):
                return ""
            games = [g for g in rawg.get("games", []) or [] if isinstance(g, dict)]
            if not games or not games[0].get("slug"):
                return ""
            detail = await get_rawg_game_details(str(games[0]["slug"]))
            if not isinstance(detail, dict) or detail.get("error"):
                return ""
            store_urls = " ".join(
                str(s.get("url") or "")
                for s in detail.get("stores", []) or []
                if isinstance(s, dict)
            )
            blob = f"{detail.get('website') or ''} {detail.get('description') or ''} {store_urls}"
            match = re.search(r"store\.steampowered\.com/app/(\d+)", blob)
            if not match:
                return ""
            steam = await get_steam_reviews(int(match.group(1)))
            if not isinstance(steam, dict) or steam.get("error") or not steam.get("summary"):
                return ""
            summary = steam.get("summary") or {}
            praise: List[str] = []
            complaints: List[str] = []
            for rev in steam.get("sample_reviews", []) or []:
                if not isinstance(rev, dict) or not rev.get("text"):
                    continue
                target = praise if rev.get("recommended") else complaints
                if len(target) < 2:
                    target.append(f"\"{str(rev['text'])[:200]}\"")
            meta = ", ".join(
                p
                for p in [
                    str(summary.get("score_desc") or ""),
                    f"{summary.get('positive_pct')}% positive"
                    if summary.get("positive_pct") is not None
                    else "",
                    f"{summary.get('total_reviews')} reviews" if summary.get("total_reviews") else "",
                ]
                if p
            )
            block = f"Steam players on {detail.get('name') or 'a similar game'}"
            if meta:
                block += f" [{meta}]"
            block += ":"
            if praise:
                block += "\nPlayers praise: " + " ".join(praise)
            if complaints:
                block += "\nPlayers complain about: " + " ".join(complaints)
            if not meta and not praise and not complaints:
                return ""
            return block
        except Exception:
            logger.exception("Steam sentiment enrichment failed; skipping.")
            return ""

    async def _fetch_market_references(self, prompt: str, genre: Optional[str]) -> str:
        """Best-effort live market data (RAWG + IGDB + Steam). "" when unusable. Never raises."""
        try:
            rawg, igdb = await asyncio.gather(
                search_rawg_games(query=prompt[:120], genre=genre),
                get_igdb_metadata(theme=prompt[:80]),
            )
            lines: List[str] = []
            if isinstance(rawg, dict) and not rawg.get("error"):
                items: List[str] = []
                for game in [g for g in rawg.get("games", []) or [] if isinstance(g, dict)][:5]:
                    try:
                        bits = [str(game.get("name") or "?")]
                        if game.get("released"):
                            bits.append(str(game["released"])[:4])
                        if game.get("rating") is not None:
                            bits.append(f"rating {game['rating']}")
                        genres = ", ".join(str(x) for x in (game.get("genres") or [])[:3])
                        if genres:
                            bits.append(genres)
                        items.append(" - " + " | ".join(bits))
                    except Exception:
                        continue
                if items:
                    lines.append(
                        "Similar games on RAWG (use for competitive_products):\n" + "\n".join(items)
                    )
            steam_block = await self._fetch_steam_sentiment(rawg)
            if steam_block:
                lines.append(steam_block)
            if isinstance(igdb, dict) and not igdb.get("error"):
                items = []
                for game in [g for g in igdb.get("games", []) or [] if isinstance(g, dict)][:5]:
                    try:
                        bits = [str(game.get("name") or "?")]
                        modes = ", ".join(str(x) for x in (game.get("game_modes") or [])[:3])
                        if modes:
                            bits.append(modes)
                        if game.get("rating") is not None:
                            bits.append(f"rating {round(float(game['rating']))}")
                        items.append(" - " + " | ".join(bits))
                    except Exception:
                        continue
                if items:
                    lines.append(
                        "IGDB thematic references (gameplay inspiration):\n" + "\n".join(items)
                    )
            if not lines:
                return ""
            return (
                "MARKET REFERENCES (live data — ground competitive_products, "
                "USPs and genre conventions in these):\n" + "\n".join(lines)
            )
        except Exception:
            logger.exception("Market reference enrichment failed; continuing without it.")
            return ""

    async def generate_document(
        self,
        prompt: str,
        doc_type: GDDType = GDDType.ONE_SHEET,
        genre: str = "Survie 2D",
        engine: str = "Godot 4",
        extra_context: str = "",
    ) -> GameDesignDocumentResponse:
        doc_type = doc_type or GDDType.ONE_SHEET
        genre = genre or "Survie 2D"
        engine = engine or "Godot 4"
        want_beat = doc_type in (GDDType.BEAT_CHART, GDDType.FULL_GDD)

        if not self.api_key:
            logger.warning("META_LLAMA_API_KEY missing: serving mock GDD (no Meta call made).")
            return self._mock_response(prompt, doc_type, genre, engine)

        references = await self._fetch_market_references(prompt, genre)
        if extra_context:
            references = f"{references}\n{extra_context}" if references else extra_context

        try:
            data = await self._call_meta_api(
                self._build_prompt(prompt, genre, engine, doc_type, references)
            )
        except httpx.HTTPStatusError as e:
            logger.error("Meta API HTTP %s: %s", e.response.status_code, e.response.text[:500])
            return self._mock_response(prompt, doc_type, genre, engine)
        except httpx.TimeoutException:
            logger.error("Meta API timed out after %ss read timeout.", self.timeout.read)
            return self._mock_response(prompt, doc_type, genre, engine)
        except Exception:
            logger.exception("Unexpected Meta API call failure; falling back to mock GDD.")
            return self._mock_response(prompt, doc_type, genre, engine)

        raw_text = ""
        try:
            raw_text = (
                self._extract_output_text(data).strip().removeprefix("```json").removesuffix("```").strip()
            )
            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                raise ValueError(f"Top-level JSON is {type(parsed).__name__}, expected object.")
            one_sheet_raw = parsed["one_sheet"]
            if not isinstance(one_sheet_raw, dict):
                raise ValueError(f"one_sheet is {type(one_sheet_raw).__name__}, expected object.")
            beat_levels: Optional[list] = None
            if want_beat:
                beat_levels = parsed.get("beat_chart", [])
                if not isinstance(beat_levels, list) or any(
                    not isinstance(lvl, dict) for lvl in beat_levels
                ):
                    raise ValueError("beat_chart is not a list of objects.")
            return GameDesignDocumentResponse(
                document_type=doc_type.value,
                one_sheet=OneSheetData(**one_sheet_raw),
                beat_chart=[BeatChartLevel(**lvl) for lvl in beat_levels] if beat_levels is not None else None,
                visual_style_prompt=parsed["visual_style_prompt"],
                status="success",
            )
        except Exception:
            logger.exception(
                "Meta GDD output unusable; falling back to mock. Raw output snippet: %.500s",
                raw_text,
            )
            return self._mock_response(prompt, doc_type, genre, engine)
