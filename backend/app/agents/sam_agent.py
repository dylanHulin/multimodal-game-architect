"""SAM 3.1 cutout agent: segment a named concept and return binary masks.

Uses the Meta Responses API (same envelope/keys as the other agents) with
model ``sam-3.1``: one streamed call carrying a noun-phrase prompt plus the
image. The SSE event stream is parsed with Meta's official ``meta_sam_parser``
package (``pip install meta-sam-parser``).

The frontend composites the masks over the image (canvas) into a transparent
PNG, so this module needs no imaging dependency: masks are returned as raw
0/1 bytes (base64) with their raster dimensions.
"""

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel  # type: ignore

try:
    import meta_sam_parser
except ImportError:  # pragma: no cover - genuinely missing dependency
    meta_sam_parser = None  # type: ignore[assignment]

META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
SAM_MODEL_ID = "sam-3.1"


class CutoutBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class CutoutMask(BaseModel):
    width: int
    height: int
    data_base64: str


class CutoutResponse(BaseModel):
    status: str  # success | no_match | error
    concept: str = ""
    image_width: int = 0
    image_height: int = 0
    boxes: List[CutoutBox] = []
    masks: List[CutoutMask] = []
    error: Optional[str] = None


logger = logging.getLogger(__name__)


async def records_from_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run the official parser over raw SSE event dicts.

    Returns [{object_id, box, mask_w, mask_h, mask_bytes}]. Never raises:
    unparseable streams yield [].
    """
    if meta_sam_parser is None:
        logger.warning("meta-sam-parser not installed: cannot decode SAM masks.")
        return []

    async def gen():
        for event in events:
            yield event

    try:
        parsed = meta_sam_parser.parse_responses_stream(
            gen(), meta_sam_parser.image_segmentation_format()
        )
        result = await parsed.final_result()
    except Exception:
        logger.exception("SAM stream parsing failed.")
        return []

    boxes: Dict[Any, Dict[str, int]] = {}
    masks: Dict[Any, Dict[str, Any]] = {}
    for record in result.records or []:
        name = type(record).__name__
        if name == "SegmentationBoxRecord":
            boxes[record.object_id] = {
                "x1": int(record.left),
                "y1": int(record.top),
                "x2": int(record.right),
                "y2": int(record.bottom),
            }
        elif name == "SegmentationMaskRecord":
            try:
                raster = bytes(meta_sam_parser.decode_mask_to_raster(record.mask))
            except Exception:
                logger.warning("Skipping SAM mask with undecodable payload.")
                continue
            if len(raster) != record.mask.width * record.mask.height:
                logger.warning("Skipping SAM mask with short raster.")
                continue
            masks[record.object_id] = {
                "mask_w": int(record.mask.width),
                "mask_h": int(record.mask.height),
                "mask_bytes": raster,
                "bounds": {
                    "x1": int(record.bounds.left),
                    "y1": int(record.bounds.top),
                    "x2": int(record.bounds.right),
                    "y2": int(record.bounds.bottom),
                },
            }
    out: List[Dict[str, Any]] = []
    for object_id, mask in masks.items():
        out.append(
            {
                "object_id": object_id,
                "box": boxes.get(object_id, mask["bounds"]),
                "mask_w": mask["mask_w"],
                "mask_h": mask["mask_h"],
                "mask_bytes": mask["mask_bytes"],
            }
        )
    return out


class SamAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")
        self.url = META_RESPONSES_URL
        self.timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

    async def _call_sam_events(
        self, image_data_url: str, concept: str
    ) -> List[Dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": SAM_MODEL_ID,
            "stream": True,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": concept},
                        {"type": "input_image", "image_url": image_data_url},
                    ],
                }
            ],
        }
        events: List[Dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", self.url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread())[:1000].decode("utf-8", "replace")
                    raise httpx.HTTPStatusError(
                        f"SAM HTTP {resp.status_code}: {body}",
                        request=None,  # type: ignore[arg-type]
                        response=resp,  # type: ignore[arg-type]
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        evt = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(evt, dict):
                        events.append(evt)
        logger.info("SAM stream collected %d events.", len(events))
        return events

    async def cutout_masks(self, image_data_url: str, concept: str = "character") -> CutoutResponse:
        """Segment `concept` in the image. Never raises: failures become status."""
        concept = (concept or "").strip() or "character"
        if meta_sam_parser is None:
            return CutoutResponse(
                status="error",
                concept=concept,
                error="Détourage indisponible : dépendance meta-sam-parser manquante.",
            )
        if not self.api_key:
            logger.warning("META_LLAMA_API_KEY missing: cannot call SAM 3.1.")
            return CutoutResponse(
                status="error",
                concept=concept,
                error="Clé API Meta manquante : détourage impossible.",
            )
        try:
            events = await self._call_sam_events(image_data_url, concept)
        except httpx.HTTPStatusError as exc:
            logger.error("SAM API HTTP error: %s", str(exc)[:500])
            return CutoutResponse(status="error", concept=concept, error=f"SAM : {exc}"[:300])
        except httpx.TimeoutException:
            logger.error("SAM API timed out.")
            return CutoutResponse(status="error", concept=concept, error="SAM : délai dépassé.")
        except Exception:
            logger.exception("Unexpected SAM call failure.")
            return CutoutResponse(status="error", concept=concept, error="SAM : appel impossible.")

        records = await records_from_events(events)
        if not records:
            return CutoutResponse(status="no_match", concept=concept)
        return CutoutResponse(
            status="success",
            concept=concept,
            boxes=[CutoutBox(**r["box"]) for r in records],
            masks=[
                CutoutMask(
                    width=r["mask_w"],
                    height=r["mask_h"],
                    data_base64=base64.b64encode(r["mask_bytes"]).decode("ascii"),
                )
                for r in records
            ],
        )
