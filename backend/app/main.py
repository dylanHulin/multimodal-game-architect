from fastapi import FastAPI, HTTPException  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from pydantic import BaseModel  # type: ignore
from typing import Optional

from app.agents.gdd_agent import GDDAgent, GDDType, GameDesignDocumentResponse
from app.agents.code_agent import CodeGenAgent, CodeGenerationResponse  # type: ignore

app = FastAPI(
    title="MultiModal GameArchitect API",
    description="Agentic Game Generation Engine based on Scott Rogers Framework",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GameConceptRequest(BaseModel):
    prompt: str
    doc_type: Optional[GDDType] = GDDType.ONE_SHEET
    genre: Optional[str] = "Survie 2D"
    engine: Optional[str] = "Godot 4"

class CodeGenerationRequest(BaseModel):
    prompt: str
    engine: Optional[str] = "Godot 4"

# Instance globale de l'agent
gdd_agent = GDDAgent()
code_agent = CodeGenAgent()

@app.get("/")
def read_root():
    return {
        "status": "online",
        "project": "MultiModal-GameArchitect",
        "framework": "Scott Rogers (Level Up!)"
    }

@app.post("/api/v1/generate-gdd", response_model=GameDesignDocumentResponse)
async def generate_gdd(request: GameConceptRequest):
    if not request.prompt:
        raise HTTPException(status_code=400, detail="Le prompt ne peut pas être vide.")
    
    result = await gdd_agent.generate_document(
        prompt=request.prompt,
        doc_type=request.doc_type,
        genre=request.genre,
        engine=request.engine
    )

@app.post("/api/v1/generate-code", response_model=CodeGenerationResponse)
async def generate_code(request: CodeGenerationRequest):
    if not request.prompt:
        raise HTTPException(status_code=400, detail="Le prompt ne peut pas être vide.")
    
    return await code_agent.generate_script(
        prompt=request.prompt,
        engine=request.engine or "Godot 4"
    )
    return result