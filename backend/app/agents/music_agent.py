"""Concept-music agent: text-to-music via Replicate-hosted Meta MusicGen.

Model ``meta/musicgen`` (Meta, open weights, CC-BY NC): async predictions
(create -> poll -> download). Trimming is pure-stdlib PCM slicing; MP3
encoding uses ``lameenc`` when installed (pip install lameenc).

Auth: server-side REPLICATE_API_TOKEN by default, or the caller's own
Replicate key (BYOK via the X-Replicate-Key header). The Meta BYOK Bearer
token is a different service and must never be used here.
"""

import asyncio
import logging
import os
import struct
import time
from typing import List, Optional, Tuple

import httpx
from pydantic import BaseModel  # type: ignore

REPLICATE_API = "https://api.replicate.com/v1"
REPLICATE_MODEL = "meta/musicgen"
# Pinned version (latest, 2024-03-28): the models/.../predictions route 404s
# for this model, so predictions are created version-based instead.
REPLICATE_MUSICGEN_VERSION = os.getenv(
    "REPLICATE_MUSICGEN_VERSION",
    "671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb",
)
# 'large' (mono, fast) by default for interactive use; 'stereo-large' for
# quality via REPLICATE_MUSIC_VERSION.
REPLICATE_MUSIC_VERSION = os.getenv("REPLICATE_MUSIC_VERSION", "large")

try:
    import lameenc  # type: ignore

    HAS_LAMEENC = True
except ImportError:
    lameenc = None  # type: ignore
    HAS_LAMEENC = False

logger = logging.getLogger(__name__)


class MusicGenerationResponse(BaseModel):
    status: str  # success | error
    audio_base64: str = ""
    sample_rate: int = 0
    channels: int = 0
    duration_sec: float = 0.0
    prompt_used: str = ""
    error: Optional[str] = None


class Mp3ConversionResponse(BaseModel):
    status: str  # success | error
    audio_base64: str = ""
    error: Optional[str] = None


def _find_data_chunk(wav: bytes) -> Tuple[int, int, int, int]:
    """Return (num_channels, sample_rate, data_offset, data_len).

    Raises ValueError on non-PCM16 WAV.
    """
    if len(wav) < 44 or not wav.startswith(b"RIFF") or wav[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    offset = 12
    fmt_info = None
    data_info = None
    while offset + 8 <= len(wav):
        chunk_id = wav[offset:offset + 4]
        chunk_len = struct.unpack("<I", wav[offset + 4:offset + 8])[0]
        if chunk_id == b"fmt ":
            if chunk_len < 16:
                raise ValueError("bad fmt chunk")
            audio_fmt, channels, sample_rate = struct.unpack("<HHI", wav[offset + 8:offset + 16])
            bits = struct.unpack("<H", wav[offset + 22:offset + 24])[0]
            if audio_fmt != 1 or bits != 16 or channels not in (1, 2):
                raise ValueError("only mono/stereo PCM16 WAV supported")
            fmt_info = (channels, sample_rate)
        elif chunk_id == b"data":
            data_info = (offset + 8, chunk_len)
        offset += 8 + chunk_len + (chunk_len % 2)
        if fmt_info and data_info:
            break
    if not fmt_info or not data_info:
        raise ValueError("WAV missing fmt/data chunk")
    channels, sample_rate = fmt_info
    data_offset, data_len = data_info
    data_len = min(data_len, len(wav) - data_offset)
    return channels, sample_rate, data_offset, data_len


def trim_wav(wav: bytes, max_seconds: float) -> Tuple[bytes, int, int, float]:
    """Trim (or keep) a PCM16 WAV to max_seconds, channels preserved.

    Returns (wav, sample_rate, channels, duration). Raises ValueError.
    """
    channels, sample_rate, data_offset, data_len = _find_data_chunk(wav)
    frame_bytes = channels * 2
    total_frames = data_len // frame_bytes
    keep_frames = min(total_frames, int(sample_rate * max_seconds))
    if keep_frames <= 0:
        raise ValueError("empty audio")
    raw = wav[data_offset:data_offset + keep_frames * frame_bytes]
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(raw))
        + b"WAVEfmt "
        + struct.pack(
            "<IHHIIHH", 16, 1, channels, sample_rate, sample_rate * frame_bytes,
            frame_bytes, 16,
        )
        + b"data"
        + struct.pack("<I", len(raw))
    )
    return header + raw, sample_rate, channels, keep_frames / sample_rate


def crossfade_loop_wav(wav: bytes) -> bytes:
    """Make a PCM16 WAV loop seamlessly (equal-power tail/head crossfade).

    The last N frames blend the fading tail with the head of the track, so
    wrapping to frame 0 is continuous. Length, channels and rate unchanged.
    Returns the input untouched when too short to crossfade safely.
    """
    channels, sample_rate, data_offset, data_len = _find_data_chunk(wav)
    frame_bytes = channels * 2
    total = data_len // frame_bytes
    span = min(int(sample_rate * 1.5), total // 4)
    if span < 100:
        return wav
    import math

    raw = bytearray(wav[data_offset:data_offset + total * frame_bytes])
    tail_start = (total - span) * frame_bytes
    for i in range(span):
        t = i / span
        gain_out = math.cos(t * math.pi / 2) ** 2
        gain_in = math.sin(t * math.pi / 2) ** 2
        for ch in range(channels):
            off_tail = tail_start + i * frame_bytes + ch * 2
            off_head = i * frame_bytes + ch * 2
            tail = struct.unpack_from("<h", raw, off_tail)[0]
            head = struct.unpack_from("<h", raw, off_head)[0]
            mixed = int(round(tail * gain_out + head * gain_in))
            struct.pack_into("<h", raw, off_tail, max(-32768, min(32767, mixed)))
    return wav[:data_offset] + bytes(raw) + wav[data_offset + total * frame_bytes:]


def wav_to_mp3(wav: bytes) -> bytes:
    """Encode a PCM16 mono/stereo WAV to MP3. Raises RuntimeError without lameenc."""
    if not HAS_LAMEENC or lameenc is None:
        raise RuntimeError("lameenc not installed")
    channels, sample_rate, data_offset, data_len = _find_data_chunk(wav)
    pcm = wav[data_offset:data_offset + data_len]
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(128)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(channels)
    encoder.set_quality(2)
    return encoder.encode(pcm) + encoder.flush()


class MusicAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("REPLICATE_API_TOKEN", "")
        self.timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; multimodal-game-architect/1.0)",
        }

    async def _create_prediction(
        self, client: httpx.AsyncClient, prompt: str, duration: int
    ) -> str:
        resp = await client.post(
            f"{REPLICATE_API}/predictions",
            headers=self._headers(),
            json={
                "version": REPLICATE_MUSICGEN_VERSION,
                "input": {
                    "prompt": prompt,
                    "duration": duration,
                    "model_version": REPLICATE_MUSIC_VERSION,
                },
            },
        )
        if resp.status_code == 401:
            raise RuntimeError("Clé Replicate invalide.")
        if resp.status_code == 402:
            raise RuntimeError("Compte Replicate sans crédit : ajoutez la facturation.")
        if resp.status_code == 429:
            raise RuntimeError("Replicate surchargé, réessayez dans une minute.")
        if resp.status_code in (403, 404):
            # Replicate sometimes masks auth failures as 403/404 on this route:
            # disambiguate with a free account check before reporting.
            try:
                probe = await client.get(f"{REPLICATE_API}/account", headers=self._headers())
            except Exception:
                probe = None
            if probe is not None and probe.status_code == 401:
                raise RuntimeError("Clé Replicate invalide.")
            raise RuntimeError(
                f"Modèle {REPLICATE_MODEL} inaccessible (HTTP {resp.status_code})."
            )
        try:
            resp.raise_for_status()
            prediction_id = resp.json().get("id")
        except Exception:
            raise RuntimeError(f"Replicate indisponible (HTTP {resp.status_code}).")
        if not prediction_id:
            raise RuntimeError("Replicate : prédiction non créée.")
        return str(prediction_id)

    async def _await_output(self, client: httpx.AsyncClient, prediction_id: str) -> str:
        deadline = time.monotonic() + 480.0
        while True:
            resp = await client.get(
                f"{REPLICATE_API}/predictions/{prediction_id}", headers=self._headers()
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status == "succeeded":
                output = data.get("output")
                if isinstance(output, list):
                    output = output[0] if output else None
                if not isinstance(output, str) or not output.startswith("http"):
                    raise RuntimeError("Replicate : audio manquant.")
                return output
            if status in ("failed", "canceled"):
                detail = str(data.get("error") or status)[:200]
                raise RuntimeError(f"MusicGen : prédiction {detail}.")
            if time.monotonic() > deadline:
                raise RuntimeError("MusicGen : délai dépassé (8 min).")
            await asyncio.sleep(4)

    async def generate_music(
        self, prompt: str, style: str = "", duration_sec: float = 10.0
    ) -> MusicGenerationResponse:
        """Generate a concept track. Never raises: failures become status=error."""
        base = f"{prompt.strip()}, {style.strip()}" if style.strip() else prompt.strip()
        # MusicGen loves fade-outs: forbid them so the crossfade below has matter.
        full_prompt = f"{base}, seamless loop, steady tempo, no intro, no outro, no fade out"
        if not full_prompt:
            return MusicGenerationResponse(status="error", error="Prompt musical vide.")
        if not self.api_key:
            logger.warning("REPLICATE_API_TOKEN missing: cannot call MusicGen.")
            return MusicGenerationResponse(
                status="error",
                error="Clé Replicate manquante : ajoutez REPLICATE_API_TOKEN au .env.",
            )
        duration = min(max(int(duration_sec), 1), 30)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                prediction_id = await self._create_prediction(client, full_prompt, duration)
                audio_url = await self._await_output(client, prediction_id)
                file_resp = await client.get(audio_url, follow_redirects=True)
                file_resp.raise_for_status()
                raw = bytes(file_resp.content)
        except httpx.TimeoutException:
            logger.error("MusicGen timed out.")
            return MusicGenerationResponse(
                status="error", error="MusicGen : délai dépassé."
            )
        except httpx.TransportError as exc:
            logger.error("MusicGen transport error: %s", exc)
            return MusicGenerationResponse(
                status="error", error="MusicGen injoignable (réseau ?)."
            )
        except Exception as exc:
            logger.error("MusicGen call failed: %s", str(exc)[:300])
            return MusicGenerationResponse(status="error", error=str(exc)[:300])
        try:
            trimmed, sample_rate, channels, actual = trim_wav(raw, duration)
            trimmed = crossfade_loop_wav(trimmed)
        except ValueError:
            logger.error("MusicGen returned invalid WAV (%d bytes).", len(raw))
            return MusicGenerationResponse(
                status="error", error="MusicGen : audio invalide reçu."
            )
        import base64 as _b64

        logger.info("MusicGen track: %.1fs @ %dHz x%d.", actual, sample_rate, channels)
        return MusicGenerationResponse(
            status="success",
            audio_base64=_b64.b64encode(trimmed).decode("ascii"),
            sample_rate=sample_rate,
            channels=channels,
            duration_sec=round(actual, 2),
            prompt_used=full_prompt,
        )


def convert_to_mp3(audio_base64: str) -> Mp3ConversionResponse:
    """Convert a base64 WAV to base64 MP3. Never raises."""
    import base64 as _b64
    import binascii

    try:
        wav = _b64.b64decode(audio_base64 or "", validate=True)
    except (binascii.Error, ValueError):
        return Mp3ConversionResponse(status="error", error="Audio base64 invalide.")
    if len(wav) > 15 * 1024 * 1024:
        return Mp3ConversionResponse(status="error", error="Audio trop lourd.")
    try:
        mp3 = wav_to_mp3(wav)
    except RuntimeError:
        return Mp3ConversionResponse(
            status="error", error="MP3 indisponible : dépendance lameenc manquante."
        )
    except ValueError as exc:
        return Mp3ConversionResponse(status="error", error=f"MP3 impossible : {exc}.")
    return Mp3ConversionResponse(status="success", audio_base64=_b64.b64encode(mp3).decode("ascii"))


# Re-exported for route/test patching convenience.
__all__ = [
    "MusicAgent",
    "MusicGenerationResponse",
    "Mp3ConversionResponse",
    "convert_to_mp3",
    "crossfade_loop_wav",
    "trim_wav",
    "wav_to_mp3",
    "HAS_LAMEENC",
]
