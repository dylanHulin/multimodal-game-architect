import os
from enum import Enum
from pydantic import BaseModel
from typing import List, Optional

class GDDType(str, Enum):
    ONE_SHEET = "one_sheet"
    TEN_PAGER = "ten_pager"
    BEAT_CHART = "beat_chart"
    FULL_GDD = "full_gdd"

# --- 1. Structure One-Sheet ---
class OneSheetData(BaseModel):
    title: str
    target_systems: List[str]
    target_age: str
    esrb_rating: str
    story_summary: str
    gameplay_modes: List[str]
    usps: List[str]  # Unique Selling Points (5 max)
    competitive_products: List[str]

# --- 2. Structure Beat Chart ---
class BeatChartLevel(BaseModel):
    level_name: str
    progression_focus: str
    mechanics_introduced: List[str]
    enemies_introduced: List[str]
    estimated_play_time: str

# --- 3. Structure globale du GDD ---
class GameDesignDocumentResponse(BaseModel):
    document_type: GDDType
    one_sheet: Optional[OneSheetData] = None
    beat_chart: Optional[List[BeatChartLevel]] = None
    visual_style_prompt: str

class GDDAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")

    async def generate_document(
        self, 
        prompt: str, 
        doc_type: GDDType = GDDType.ONE_SHEET,
        genre: str = "Survie 2D", 
        engine: str = "Godot 4"
    ) -> GameDesignDocumentResponse:
        
        # Prototype de données structurées selon la méthodologie de Scott Rogers
        one_sheet = OneSheetData(
            title=f"Project: {prompt[:20]}...",
            target_systems=[engine, "PC"],
            target_age="12+",
            esrb_rating="T (Teen)",
            story_summary=f"Un jeu de type {genre} où le joueur doit : {prompt}",
            gameplay_modes=["Solo Story Mode", "Endless Survival"],
            usps=[
                "Mécanique d'interaction dynamique",
                "Gestion d'inventaire en temps réel",
                "Génération procédurale des menaces",
                "Style visuel rétro immersif",
                "Progression rapide des compétences"
            ],
            competitive_products=["Hordes", "RimWorld", "Don't Starve"]
        )

        beat_chart = [
            BeatChartLevel(
                level_name="Niveau 1 : Tacticien Débutant",
                progression_focus="Apprentissage des contrôles de base et collecte",
                mechanics_introduced=["Déplacement", "Recolte de bois/nourriture"],
                enemies_introduced=["Ennemi de base (Zombie lent)"],
                estimated_play_time="5 min"
            ),
            BeatChartLevel(
                level_name="Niveau 2 : L'Invasion",
                progression_focus="Gestion du stress et de la défense",
                mechanics_introduced=["Construction de barricade", "Attaque à distance"],
                enemies_introduced=["Ennemi rapide"],
                estimated_play_time="10 min"
            )
        ]

        return GameDesignDocumentResponse(
            document_type=doc_type,
            one_sheet=one_sheet,
            beat_chart=beat_chart if doc_type in [GDDType.BEAT_CHART, GDDType.FULL_GDD] else None,
            visual_style_prompt=f"2D {genre} game asset sprite sheet, {prompt}, high quality pixel art"
        )