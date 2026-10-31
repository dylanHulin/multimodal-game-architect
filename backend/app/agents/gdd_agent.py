import os
import httpx # type: ignore
from enum import Enum
from pydantic import BaseModel # type: ignore
from typing import List, Optional

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
    document_type: GDDType
    one_sheet: OneSheetData
    beat_chart: Optional[List[BeatChartLevel]] = None
    visual_style_prompt: str

class GDDAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")
        self.url = "https://api.meta.ai/v1/responses"

    async def generate_document(
        self, 
        prompt: str, 
        doc_type: GDDType = GDDType.ONE_SHEET,
        genre: str = "Survie 2D", 
        engine: str = "Godot 4"
    ) -> GameDesignDocumentResponse:
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Payload officiel selon la documentation Meta API
        payload = {
            "model": "muse-wonder-1.0",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Génère un concept de jeu vidéo basé sur ce besoin : '{prompt}'. Genre: {genre}, Moteur: {engine}."
                        }
                    ]
                }
            ],
            "stream": False,
        }

        # Appel HTTP asynchrone si la clé API est configurée
        if self.api_key and self.api_key != "ta_cle_meta_ou_fireworks_ici":
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(self.url, headers=headers, json=payload, timeout=30.0)
                    if response.status_code == 200:
                        meta_response = response.json()
                        # Extraire le texte de réponse renvoyé par l'API Meta
                        # text_output = meta_response['output'][0]['content'][0]['text']
            except Exception as e:
                print(f"Erreur lors de l'appel Meta API : {e}")

        # Structure Scott Rogers
        one_sheet = OneSheetData(
            title=f"Project: {prompt[:25]}...",
            target_systems=[engine, "PC"],
            target_age="12+",
            esrb_rating="T (Teen)",
            story_summary=f"Un jeu de type {genre} centré sur : {prompt}.",
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
                mechanics_introduced=["Déplacement", "Récolte de ressources"],
                enemies_introduced=["Ennemi de base (Zombie)"],
                estimated_play_time="5 min"
            ),
            BeatChartLevel(
                level_name="Niveau 2 : L'Invasion",
                progression_focus="Gestion de la défense et combat",
                mechanics_introduced=["Construction de barricade", "Attaque à distance"],
                enemies_introduced=["Ennemi rapide"],
                estimated_play_time="10 min"
            )
        ]

        return GameDesignDocumentResponse(
            document_type=doc_type,
            one_sheet=one_sheet,
            beat_chart=beat_chart if doc_type in [GDDType.BEAT_CHART, GDDType.FULL_GDD] else None,
            visual_style_prompt=f"2D {genre} game asset sprite sheet, {prompt}, pixel art style"
        )