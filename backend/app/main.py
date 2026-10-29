from fastapi import FastAPI, HTTPException # type: ignore
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from pydantic import BaseModel # type: ignore
from typing import List, Optional

app = FastAPI(
    title="MultiModal GameArchitect API",
    description="Agentic Game Generation Engine for Meta AI Developer Hackathon",
    version="0.1.0"
)

# Configuration CORS pour permettre au frontend de communiquer avec le backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modèle Pydantic pour la requête initiale
class GameConceptRequest(BaseModel):
    prompt: str
    genre: Optional[str] = "Survie 2D"
    engine: Optional[str] = "Godot 4"  # ou "Unity"

@app.get("/")
def read_root():
    return {
        "status": "online",
        "project": "MultiModal-GameArchitect",
        "hackathon": "Meta AI Developer Hackathon 2026"
    }

@app.post("/api/v1/generate-concept")
async def generate_concept(request: GameConceptRequest):
    if not request.prompt:
        raise HTTPException(status_code=400, detail="Le prompt ne peut pas être vide.")
    
    # Mock temporaire avant d'intégrer le vrai appel LLM Llama
    return {
        "title": f"Projet : {request.prompt[:20]}...",
        "engine": request.engine,
        "gdd": {
            "summary": f"Game Design Document généré pour : {request.prompt}",
            "core_loop": "Explorer -> Récolter -> Survivre -> Améliorer",
            "mechanics": ["Déplacement 2D Top-Down", "Gestion de ressources", "IA ennemie basique"]
        },
        "status": "ready_for_code_generation"
    }