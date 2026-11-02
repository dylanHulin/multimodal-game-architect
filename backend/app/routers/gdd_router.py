"""GDD generation router: Rogers-based dynamic forms + visual prompt variance.

POST /api/v1/generate-gdd accepts both the legacy minimal payload
({prompt, doc_type, engine}) and the rich GDDForm payload (one-sheet /
ten-pager / full-gdd fields + visual configs). Mounted from app.main.
"""

import asyncio
import json
import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException  # type: ignore
from pydantic import BaseModel, Field  # type: ignore

from app.agents.asset_agent import AssetAgent
from app.agents.gdd_agent import GDDAgent, GDDType, GameDesignDocumentResponse
from app.auth import user_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["gdd"])

# Flip to True during UI dev to skip ALL Meta calls for visuals
# (mock sub-prompts + mock image URLs, fully offline).
MOCK_VISUALS = False


class CameraType(str, Enum):
    FIRST_PERSON = "first_person"
    THIRD_PERSON = "third_person"
    TOP_DOWN = "top_down"
    SIDE_VIEW = "side_view"
    ISOMETRIC = "isometric"


class AIType(str, Enum):
    FINITE_STATE_MACHINE = "finite_state_machine"
    BEHAVIOR_TREE = "behavior_tree"
    UTILITY_AI = "utility_ai"
    GOAP = "goap"


class PhysicsEngine(str, Enum):
    BUILTIN = "builtin"
    PHYSX = "physx"
    BOX2D = "box2d"
    RAPIER = "rapier"
    CUSTOM = "custom"


class VisualAssetConfig(BaseModel):
    """One visual generation row from the frontend (checkbox + quantity)."""

    asset_type: str = Field(..., description="concept_art | ui_concept | sprite")
    enabled: bool = Field(True, description="Row checkbox state; disabled rows are skipped.")
    count: int = Field(1, ge=1, le=5, description="Images to generate (1-5).")
    style: Optional[str] = Field("pixel art", description="Art style applied at render time.")


class GDDRequest(BaseModel):
    """Union payload: legacy minimal fields + rich Rogers-form fields (all optional)."""

    prompt: Optional[str] = Field(
        None, description="Legacy free-text prompt; or omit and use title/pitch."
    )
    doc_type: Optional[GDDType] = GDDType.ONE_SHEET
    genre: Optional[str] = "Survie 2D"
    engine: Optional[str] = "Godot 4"
    title: Optional[str] = None
    platform: Optional[str] = None
    audience: Optional[str] = None
    pitch: Optional[str] = None
    usp: Optional[str] = None
    camera: Optional[CameraType] = None
    character: Optional[str] = None
    controls: Optional[str] = None
    core_loop: Optional[str] = None
    menu_flow: Optional[str] = None
    lore: Optional[str] = None
    level_design: Optional[str] = None
    features: List[str] = []
    ai_type: Optional[AIType] = None
    physics_engine: Optional[PhysicsEngine] = None
    visuals: List[VisualAssetConfig] = []


class TenPagerSection(BaseModel):
    camera: Optional[CameraType] = None
    character: Optional[str] = None
    controls: Optional[str] = None
    core_loop: Optional[str] = None
    menu_flow: Optional[str] = None


class FullGDDSection(BaseModel):
    lore: Optional[str] = None
    level_design: Optional[str] = None
    features: List[str] = []
    ai_type: Optional[AIType] = None
    physics_engine: Optional[PhysicsEngine] = None


class GeneratedImage(BaseModel):
    asset_type: str
    prompt_used: str
    image_url: str
    status: str


class GDDGenerateResponse(GameDesignDocumentResponse):
    """Legacy GDD fields + form sections + images (superset: old clients unaffected)."""

    ten_pager: Optional[TenPagerSection] = None
    full_gdd: Optional[FullGDDSection] = None
    images: List[GeneratedImage] = []


_MOCK_ANGLES: Dict[str, List[str]] = {
    "concept_art": [
        "wide establishing shot at dawn",
        "close-up detail study of a key location",
        "aerial view of the game world",
        "night-time mood piece with dramatic lighting",
        "decisive action moment with the main threat",
    ],
    "ui_concept": [
        "main HUD layout with health and status bars",
        "inventory screen with item grid",
        "main menu screen with title treatment",
        "pause menu overlay with options",
        "character stats and equipment panel",
    ],
    "sprite": [
        "front-facing idle pose",
        "three-quarter action pose",
        "side-view walk frame",
        "back view",
        "close-up portrait bust",
    ],
}


def _mock_visual_prompts(theme: str, asset_type: str, count: int, start: int = 0) -> List[str]:
    angles = _MOCK_ANGLES.get(asset_type) or [f"alternate composition {i + 1}" for i in range(5)]
    return [f"{theme}. Variation: {angles[(start + i) % len(angles)]}." for i in range(count)]


def _parse_visual_list(raw: str, count: int) -> List[str]:
    """Parse an LLM answer into distinct prompts: JSON array first, numbered list fallback."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(p).strip() for p in parsed if str(p).strip()][:count]
    except ValueError:
        pass
    items = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:\d+[.)]\s*|[-*]\s+)", "", line).strip().strip("\"'")
        if cleaned:
            items.append(cleaned)
    return items[:count]


async def _llm_visual_prompts(
    theme: str, asset_type: str, count: int, api_key: Optional[str] = None
) -> List[str]:
    """Real Meta call returning distinct sub-prompts. Raises on any failure."""
    agent = GDDAgent(api_key=api_key)
    if not agent.api_key:
        raise RuntimeError("META_LLAMA_API_KEY missing.")
    label = asset_type.replace("_", " ")
    raw = await agent.generate_text(
        f"Generate exactly {count} DISTINCT image-generation prompts about '{theme}' "
        f"for 2D game {label}. Each must depict a DIFFERENT subject, scene or "
        f"composition on the same theme. Respond with a JSON array of exactly "
        f"{count} strings and nothing else.",
        effort="low",
    )
    prompts = _parse_visual_list(raw, count)
    if not prompts:
        raise RuntimeError("LLM returned no usable sub-prompts.")
    return prompts


async def generate_visual_prompts(
    theme: str, asset_type: str, count: int, api_key: Optional[str] = None
) -> List[str]:
    """Return `count` DISTINCT sub-prompts for one asset type.

    Real LLM call with deterministic mock fallback. Never raises: always
    returns exactly `count` strings (clamped to 1-5).
    """
    count = max(1, min(5, count))
    if not MOCK_VISUALS:
        try:
            prompts = await _llm_visual_prompts(theme, asset_type, count, api_key)
            if len(prompts) >= count:
                return prompts[:count]
            prompts += _mock_visual_prompts(theme, asset_type, count - len(prompts), start=len(prompts))
            return prompts
        except Exception:
            logger.exception("visual prompt variance failed; using mock prompts.")
    return _mock_visual_prompts(theme, asset_type, count)


gdd_agent = GDDAgent()
asset_agent = AssetAgent()


async def _render_one(
    cfg: VisualAssetConfig, sub_prompt: str, index: int, api_key: Optional[str] = None
) -> GeneratedImage:
    if MOCK_VISUALS:
        slug = f"{cfg.asset_type}-{index + 1}"
        return GeneratedImage(
            asset_type=cfg.asset_type,
            prompt_used=sub_prompt,
            image_url=f"https://placehold.co/600x400/png?text={slug}",
            status="mock",
        )
    agent = asset_agent if api_key is None else AssetAgent(api_key=api_key)
    res = await agent.generate_asset(
        prompt=sub_prompt, asset_type=cfg.asset_type, style=cfg.style or "pixel art"
    )
    return GeneratedImage(
        asset_type=res.asset_type,
        prompt_used=res.prompt_used,
        image_url=res.image_url,
        status=res.status,
    )


def _user_facts_block(request: GDDRequest, doc: GDDType) -> str:
    pairs = [
        ("Title", request.title),
        ("Platform", request.platform),
        ("Target audience", request.audience),
        ("Pitch", request.pitch),
        ("USP", request.usp),
    ]
    if doc in (GDDType.TEN_PAGER, GDDType.FULL_GDD):
        pairs += [
            ("Camera", request.camera.value if request.camera else None),
            ("Character", request.character),
            ("Controls", request.controls),
            ("Core loop", request.core_loop),
            ("Menu flow", request.menu_flow),
        ]
    if doc is GDDType.FULL_GDD:
        pairs += [
            ("Lore", request.lore),
            ("Level design", request.level_design),
            ("Features", ", ".join(request.features) if request.features else None),
            ("AI type", request.ai_type.value if request.ai_type else None),
            ("Physics engine", request.physics_engine.value if request.physics_engine else None),
        ]
    lines = [f"- {label}: {value.strip()}" for label, value in pairs if value and str(value).strip()]
    if not lines:
        return ""
    return "USER-PROVIDED FACTS (incorporate verbatim into the matching sections):\n" + "\n".join(
        lines
    )


@router.post("/generate-gdd", response_model=GDDGenerateResponse)
async def generate_gdd(
    request: GDDRequest, user_key: Optional[str] = Depends(user_api_key)
):
    effective = (request.prompt or "").strip()
    if not effective:
        seeds = [s.strip() for s in [request.title, request.pitch] if s and s.strip()]
        effective = " — ".join(seeds)
    if not effective:
        raise HTTPException(status_code=400, detail="Le prompt ne peut pas être vide.")

    gdd = gdd_agent
    if user_key is not None:
        logger.info("generate-gdd: using user-provided API key.")
        gdd = GDDAgent(api_key=user_key)
    doc = request.doc_type or GDDType.ONE_SHEET
    base = await gdd.generate_document(
        prompt=effective,
        doc_type=doc,
        genre=request.genre or "Survie 2D",
        engine=request.engine or "Godot 4",
        extra_context=_user_facts_block(request, doc),
    )

    # Hard overrides: user-provided one-sheet facts win over generated text.
    sheet_updates: Dict[str, Any] = {}
    if request.title:
        sheet_updates["title"] = request.title.strip()
    if request.platform:
        sheet_updates["target_systems"] = [request.platform.strip()]
    if request.audience:
        sheet_updates["target_age"] = request.audience.strip()
    if request.pitch:
        sheet_updates["story_summary"] = request.pitch.strip()
    if request.usp:
        sheet_updates["usps"] = [request.usp.strip()]
    one_sheet = base.one_sheet.model_copy(update=sheet_updates) if sheet_updates else base.one_sheet

    # Sections are gated on doc_type: stale fields from a previous form type
    # must not leak into the response (nor into downloads).
    ten_pager = (
        TenPagerSection(
            camera=request.camera,
            character=request.character,
            controls=request.controls,
            core_loop=request.core_loop,
            menu_flow=request.menu_flow,
        )
        if doc in (GDDType.TEN_PAGER, GDDType.FULL_GDD)
        and any([request.camera, request.character, request.controls, request.core_loop, request.menu_flow])
        else None
    )
    full_gdd = (
        FullGDDSection(
            lore=request.lore,
            level_design=request.level_design,
            features=request.features,
            ai_type=request.ai_type,
            physics_engine=request.physics_engine,
        )
        if doc is GDDType.FULL_GDD
        and any(
            [request.lore, request.level_design, request.features, request.ai_type, request.physics_engine]
        )
        else None
    )

    images: List[GeneratedImage] = []
    enabled = [c for c in request.visuals if c.enabled and c.count >= 1]
    if enabled:
        theme = base.visual_style_prompt or effective
        sublists = await asyncio.gather(
            *[generate_visual_prompts(theme, c.asset_type, c.count, user_key) for c in enabled]
        )
        renders = [
            _render_one(cfg, sub, i, user_key)
            for cfg, subs in zip(enabled, sublists)
            for i, sub in enumerate(subs)
        ]
        images = list(await asyncio.gather(*renders))

    return GDDGenerateResponse(
        document_type=base.document_type,
        one_sheet=one_sheet,
        beat_chart=base.beat_chart,
        visual_style_prompt=base.visual_style_prompt,
        status=base.status,
        ten_pager=ten_pager,
        full_gdd=full_gdd,
        images=images,
    )
