from pathlib import Path

from dotenv import load_dotenv  # type: ignore

# Load backend/.env FIRST (anchored to this file, not the cwd: uvicorn may be
# started from the repo root with --app-dir) and BEFORE importing agents, which
# read their keys at construction time.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

import asyncio
import base64
import binascii
import logging

import httpx  # type: ignore
from fastapi import Depends, FastAPI, HTTPException  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from pydantic import BaseModel  # type: ignore
from typing import Optional

from app.agents.code_agent import CodeGenAgent, CodeGenerationResponse  # type: ignore
from app.security import RateLimitMiddleware, is_safe_fetch_url  # type: ignore
from app.agents.asset_agent import AssetAgent, AssetGenerationResponse  # type: ignore
from app.agents.music_agent import (  # type: ignore
    Mp3ConversionResponse,
    MusicAgent,
    MusicGenerationResponse,
    convert_to_mp3,
)
from app.agents.sam_agent import CutoutResponse, SamAgent  # type: ignore
from app.agents.voice_agent import VoiceAgent, VoiceTranscribeResponse  # type: ignore
from app.auth import replicate_api_key, user_api_key  # type: ignore
from app.routers.gdd_router import router as gdd_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MultiModal GameArchitect API",
    description="Agentic Game Generation Engine for game design documents",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(gdd_router)

class CodeGenerationRequest(BaseModel):
    prompt: str
    engine: Optional[str] = "Godot 4"

class AssetGenerationRequest(BaseModel):
    prompt: str
    asset_type: Optional[str] = "sprite"
    style: Optional[str] = "pixel art"

class CutoutRequest(BaseModel):
    image_url: str
    concept: Optional[str] = "character"

class TranscribeRequest(BaseModel):
    audio_base64: str

class MusicGenerationRequest(BaseModel):
    prompt: str
    style: Optional[str] = ""
    duration_sec: Optional[float] = 10.0

class Mp3ConversionRequest(BaseModel):
    audio_base64: str

# Instances globales des agents (le GDD vit dans app.routers.gdd_router)
code_agent = CodeGenAgent()
asset_agent = AssetAgent()
sam_agent = SamAgent()
voice_agent = VoiceAgent()
music_agent = MusicAgent()

@app.get("/")
def read_root():
    return {
        "status": "online",
        "project": "MultiModal-GameArchitect",
        "framework": "Game Design Pipeline"
    }

@app.post("/api/v1/generate-code", response_model=CodeGenerationResponse)
async def generate_code(
    request: CodeGenerationRequest, user_key: Optional[str] = Depends(user_api_key)
):
    if not request.prompt:
        raise HTTPException(status_code=400, detail="Le prompt ne peut pas être vide.")

    agent = code_agent
    if user_key is not None:
        logger.info("generate-code: using user-provided API key.")
        agent = CodeGenAgent(api_key=user_key)
    return await agent.generate_script(
        prompt=(request.prompt or "")[:4000],
        engine=(request.engine or "Godot 4")[:60]
    )

@app.post("/api/v1/generate-asset", response_model=AssetGenerationResponse)
async def generate_asset(
    request: AssetGenerationRequest, user_key: Optional[str] = Depends(user_api_key)
):
    if not request.prompt:
        raise HTTPException(status_code=400, detail="Le prompt ne peut pas être vide.")

    agent = asset_agent
    if user_key is not None:
        logger.info("generate-asset: using user-provided API key.")
        agent = AssetAgent(api_key=user_key)
    return await agent.generate_asset(
        prompt=request.prompt,
        asset_type=request.asset_type or "sprite",
        style=request.style or "pixel art",
    )

@app.post("/api/v1/cutout", response_model=CutoutResponse)
async def cutout(request: CutoutRequest, user_key: Optional[str] = Depends(user_api_key)):
    concept = (request.concept or "character").strip() or "character"
    if len(concept) > 60:
        return CutoutResponse(status="error", concept=concept[:60], error="Concept trop long (60 max).")
    data_url = request.image_url or ""
    if not data_url.startswith("data:"):
        if not data_url.startswith(("http://", "https://")) or not is_safe_fetch_url(data_url):
            return CutoutResponse(status="error", concept=concept, error="image_url invalide.")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0)) as client:
                resp = await client.get(data_url, follow_redirects=True)
            resp.raise_for_status()
            raw = resp.content
        except Exception as exc:
            logger.warning("cutout: could not fetch image_url: %s", exc)
            return CutoutResponse(status="error", concept=concept, error="Image distante illisible.")
        if len(raw) > 10 * 1024 * 1024:
            return CutoutResponse(status="error", concept=concept, error="Image trop lourde (10 Mo max).")
        mime = (resp.headers.get("content-type") or "image/png").split(";")[0].strip() or "image/png"
        if not mime.startswith("image/"):
            return CutoutResponse(status="error", concept=concept, error="URL distante : pas une image.")
        data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    if len(data_url) > 15 * 1024 * 1024:
        return CutoutResponse(status="error", concept=concept, error="Image trop lourde.")

    agent = sam_agent
    if user_key is not None:
        logger.info("cutout: using user-provided API key.")
        agent = SamAgent(api_key=user_key)
    return await agent.cutout_masks(data_url, concept)

@app.post("/api/v1/transcribe", response_model=VoiceTranscribeResponse)
async def transcribe(request: TranscribeRequest, user_key: Optional[str] = Depends(user_api_key)):
    try:
        wav = base64.b64decode(request.audio_base64 or "", validate=True)
    except (binascii.Error, ValueError):
        return VoiceTranscribeResponse(status="error", error="Audio base64 invalide.")
    if len(wav) > 6 * 1024 * 1024:
        return VoiceTranscribeResponse(status="error", error="Audio trop long (6 Mo max).")
    if len(wav) < 44 or not wav.startswith(b"RIFF") or wav[8:12] != b"WAVE":
        return VoiceTranscribeResponse(status="error", error="Format WAV requis.")

    agent = voice_agent
    if user_key is not None:
        logger.info("transcribe: using user-provided API key.")
        agent = VoiceAgent(api_key=user_key)
    return await agent.transcribe(wav)

# NOTE: music generation is billed to Replicate: server token by default, or
# the caller's own key (BYOK via X-Replicate-Key). The Meta BYOK Bearer token
# is a different service and is never used here.
@app.post("/api/v1/generate-music", response_model=MusicGenerationResponse)
async def generate_music(
    request: MusicGenerationRequest, rep_key: Optional[str] = Depends(replicate_api_key)
):
    if not (request.prompt or "").strip():
        raise HTTPException(status_code=400, detail="Le prompt ne peut pas être vide.")
    agent = music_agent
    if rep_key is not None:
        logger.info("generate-music: using caller-provided Replicate key.")
        agent = MusicAgent(api_key=rep_key)
    return await agent.generate_music(
        prompt=(request.prompt or "").strip()[:500],
        style=(request.style or "").strip()[:120],
        duration_sec=request.duration_sec or 10.0,
    )

@app.post("/api/v1/music-to-mp3", response_model=Mp3ConversionResponse)
async def music_to_mp3(request: Mp3ConversionRequest):
    return await asyncio.to_thread(convert_to_mp3, request.audio_base64)
