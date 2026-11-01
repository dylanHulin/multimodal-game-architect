import logging
import os

import httpx
from pydantic import BaseModel  # type: ignore
from typing import List, Optional

logger = logging.getLogger(__name__)


class CodeGenerationResponse(BaseModel):
    engine: str
    file_name: str
    language: str
    code_content: str
    status: str


META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
MODEL_ID = "muse-wonder-1.0"

ENGINE_LANGUAGE = {
    "Godot 4": ("GDScript", "player_controller.gd"),
    "Unity": ("C#", "PlayerController.cs"),
}


class CodeGenAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")
        self.url = META_RESPONSES_URL
        self.timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

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
        response.raise_for_status()
        data = response.json()
        if data.get("status") not in ("completed", None):
            raise RuntimeError(f"Meta response not completed: status={data.get('status')!r}")
        return data

    @staticmethod
    def _clean_code(raw: str) -> str:
        text = raw.strip()
        # Strip markdown fences the model may add despite instructions.
        if text.startswith("```"):
            lines = text.splitlines()[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _mock_response(self, engine: str) -> CodeGenerationResponse:
        language, file_name = ENGINE_LANGUAGE.get(engine, ("GDScript", "player_controller.gd"))
        if language == "GDScript":
            code_content = """extends CharacterBody2D

@export var speed : float = 200.0

func _physics_process(delta: float) -> void:
	var direction := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	velocity = direction * speed
	move_and_slide()
"""
        else:  # Unity C#
            code_content = """using UnityEngine;

public class PlayerController : MonoBehaviour
{
    [SerializeField] private float speed = 5f;
    private Vector2 moveInput;
    private Rigidbody2D rb;

    void Start()
    {
        rb = GetComponent<Rigidbody2D>();
    }

    void Update()
    {
        moveInput.x = Input.GetAxisRaw("Horizontal");
        moveInput.y = Input.GetAxisRaw("Vertical");
    }

    void FixedUpdate()
    {
        rb.MovePosition(rb.position + moveInput.normalized * speed * Time.fixedDeltaTime);
    }
}
"""
        return CodeGenerationResponse(
            engine=engine,
            file_name=file_name,
            language=language,
            code_content=code_content,
            status="mock",
        )

    async def generate_script(self, prompt: str, engine: str = "Godot 4") -> CodeGenerationResponse:
        language, file_name = ENGINE_LANGUAGE.get(engine, ("GDScript", "player_controller.gd"))

        if not self.api_key:
            logger.warning("META_LLAMA_API_KEY missing: serving mock code (no Meta call made).")
            return self._mock_response(engine)

        code_prompt = (
            f"Generate a complete, ready-to-use {language} script for the {engine} game engine "
            f"implementing the following gameplay feature: '{prompt}'.\n"
            f"Rules: output CODE ONLY for a single file named {file_name}. No markdown fences, "
            "no explanations, no prose outside the code. The code must compile and follow "
            f"{engine} best practices."
        )

        try:
            data = await self._call_meta_api(code_prompt)
        except httpx.HTTPStatusError as e:
            logger.error("Meta API HTTP %s: %s", e.response.status_code, e.response.text[:500])
            return self._mock_response(engine)
        except httpx.TimeoutException:
            logger.error("Meta API timed out after %ss read timeout.", self.timeout.read)
            return self._mock_response(engine)
        except Exception:
            logger.exception("Unexpected Meta API call failure; falling back to mock code.")
            return self._mock_response(engine)

        try:
            code = self._clean_code(self._extract_output_text(data))
            if len(code) < 20:
                raise ValueError("Model returned no usable code.")
            return CodeGenerationResponse(
                engine=engine,
                file_name=file_name,
                language=language,
                code_content=code,
                status="success",
            )
        except Exception:
            logger.exception("Meta code output unusable; falling back to mock.")
            return self._mock_response(engine)
