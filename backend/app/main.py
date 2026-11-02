from pathlib import Path

from dotenv import load_dotenv  # type: ignore

# Load backend/.env FIRST (anchored to this file, not the cwd: uvicorn may be
# started from the repo root with --app-dir) and BEFORE importing agents, which
# read their keys at construction time.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

import logging

from fastapi import Depends, FastAPI, HTTPException  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from pydantic import BaseModel  # type: ignore
from typing import Optional

from app.agents.code_agent import CodeGenAgent, CodeGenerationResponse  # type: ignore
from app.agents.asset_agent import AssetAgent, AssetGenerationResponse  # type: ignore
from app.auth import user_api_key  # type: ignore
from app.routers.gdd_router import router as gdd_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MultiModal GameArchitect API",
    description="Agentic Game Generation Engine based on Scott Rogers Framework",
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

app.include_router(gdd_router)

class CodeGenerationRequest(BaseModel):
    prompt: str
    engine: Optional[str] = "Godot 4"

class AssetGenerationRequest(BaseModel):
    prompt: str
    asset_type: Optional[str] = "sprite"
    style: Optional[str] = "pixel art"

# Instances globales des agents (le GDD vit dans app.routers.gdd_router)
code_agent = CodeGenAgent()
asset_agent = AssetAgent()

@app.get("/")
def read_root():
    return {
        "status": "online",
        "project": "MultiModal-GameArchitect",
        "framework": "Scott Rogers (Level Up!)"
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
        prompt=request.prompt,
        engine=request.engine or "Godot 4"
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
