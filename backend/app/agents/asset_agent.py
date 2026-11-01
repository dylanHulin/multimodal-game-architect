import base64
import logging
import os
import re

import httpx
from pydantic import BaseModel  # type: ignore
from typing import Optional

logger = logging.getLogger(__name__)


class AssetGenerationResponse(BaseModel):
    asset_type: str
    prompt_used: str
    image_url: str
    status: str


META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
MODEL_ID = "muse-image-1.0"


class _PolicyViolation(Exception):
    """Internal: Meta flagged the prompt (400 content_policy_violation)."""


# Gore/violence triggers -> neutral equivalents (case-insensitive, applied in
# order: specific multiword patterns first, then general terms).
_POLICY_REPLACEMENTS = [
    (r"blood[\s-]*red", "crimson"),
    (r"blood[\s-]*soaked|bloodstained|blood[\s-]*stained", "weathered"),
    (r"blood|bloody", "crimson mist"),
    (r"gore|gory", "stylized shading"),
    (r"corpses", "fallen figures"),
    (r"corpse", "fallen figure"),
    (r"dismembered|dismemberment|dismember", "broken"),
    (r"rotting|rotten", "weathered"),
    (r"flesh", "skin"),
    (r"killers", "shadowy hunters"),
    (r"killer", "shadowy hunter"),
    (r"\bkilling\b", "battle"),
    (r"\bkilled\b", "fallen"),
    (r"\bkills\b", "defeats"),
    (r"\bkill\b", "defeat"),
    (r"dead", "ancient"),
    (r"deaths", "ruins"),
    (r"death", "ruin"),
    (r"dying", "fading"),
    (r"\bguns\b", "retro blasters"),
    (r"\bgun\b", "retro blaster"),
    (r"\bknives\b", "tools"),
    (r"\bknife\b", "tool"),
]


def _sniff_mime(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"RIFF") and len(raw) > 11 and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/webp"


class AssetAgent:
    def __init__(self, api_key: str = None):
        self.api_key = (
            api_key or os.getenv("MUSE_IMAGE_API_KEY", "") or os.getenv("META_LLAMA_API_KEY", "")
        )
        self.url = META_RESPONSES_URL
        self.timeout = httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=10.0)

    @staticmethod
    def _extract_image_b64(data: dict) -> str | None:
        """Per Meta cookbook: the image is the base64 `result` of the `image_generation_call` item."""
        for item in data.get("output", []) or []:
            if isinstance(item, dict) and item.get("type") == "image_generation_call":
                if item.get("status") not in ("completed", None):
                    return None
                result = item.get("result")
                return result if isinstance(result, str) and result else None
        return None

    def _placeholder(self, asset_type: str, enhanced_prompt: str) -> AssetGenerationResponse:
        return AssetGenerationResponse(
            asset_type=asset_type,
            prompt_used=enhanced_prompt,
            image_url=f"https://placehold.co/512x512/png?text={asset_type.replace('_', '+')}",
            status="placeholder",
        )

    @staticmethod
    def _sanitize_prompt(prompt_text: str) -> str:
        """Soften gore/violence triggers that trip Meta's image content filter."""
        text = prompt_text
        for pattern, replacement in _POLICY_REPLACEMENTS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return (
            f"{text}, stylized game art, non-graphic, family-friendly, "
            "no blood, no gore, no realistic violence"
        )

    async def _try_generate(
        self, asset_type: str, prompt_text: str
    ) -> Optional[AssetGenerationResponse]:
        """One image attempt. Returns None on recoverable failure.

        Raises _PolicyViolation when Meta flags the prompt (400
        content_policy_violation) so the caller can retry sanitized.
        """
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {"model": MODEL_ID, "input": prompt_text}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if data.get("status") not in ("completed", None):
                raise RuntimeError(f"Meta response not completed: status={data.get('status')!r}")
            b64 = self._extract_image_b64(data)
            if not b64:
                raise RuntimeError("No image_generation_call result in Meta response.")
            raw = base64.b64decode(b64)
            if len(raw) < 100:
                raise RuntimeError("Decoded image payload suspiciously small.")
            mime = _sniff_mime(raw)
            return AssetGenerationResponse(
                asset_type=asset_type,
                prompt_used=prompt_text,
                image_url=f"data:{mime};base64,{b64}",
                status="success",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "content_policy_violation" in e.response.text:
                logger.warning("Meta Image prompt filtered by content policy; will retry sanitized.")
                raise _PolicyViolation()
            logger.error("Meta Image API HTTP %s: %s", e.response.status_code, e.response.text[:500])
            return None
        except httpx.TimeoutException:
            logger.error("Meta Image API timed out after %ss read timeout.", self.timeout.read)
            return None
        except (RuntimeError, ValueError) as e:
            logger.error("Meta Image response unusable, falling back to placeholder: %s", e)
            return None
        except Exception:
            logger.exception("Unexpected Meta Image call failure; falling back to placeholder.")
            return None

    async def generate_asset(
        self, prompt: str, asset_type: str = "sprite", style: str = "pixel art"
    ) -> AssetGenerationResponse:
        background = "transparent background" if asset_type == "sprite" else "plain neutral background"
        enhanced_prompt = (
            f"2D game asset, {asset_type.replace('_', ' ')}: {prompt}. "
            f"Art style: {style}. {background.capitalize()}, high resolution, "
            "game-ready, no text, no watermark."
        )

        if not self.api_key:
            logger.warning("MUSE_IMAGE_API_KEY missing: serving placeholder asset (no Meta call made).")
            return self._placeholder(asset_type, enhanced_prompt)

        try:
            result = await self._try_generate(asset_type, enhanced_prompt)
        except _PolicyViolation:
            logger.info("Retrying image generation with sanitized prompt.")
            try:
                result = await self._try_generate(asset_type, self._sanitize_prompt(enhanced_prompt))
            except _PolicyViolation:
                logger.warning("Sanitized prompt also filtered; serving placeholder.")
                return self._placeholder(asset_type, enhanced_prompt)
        if result is None:
            return self._placeholder(asset_type, enhanced_prompt)
        return result
