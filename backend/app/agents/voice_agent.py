"""Muse Voice Transcribe agent: speech-to-text for voice dictation.

Batch file mode per https://dev.meta.ai/docs/speech-to-text : multipart upload
of a RIFF/WAVE file (mono 16-bit PCM, 16 or 24 kHz) to
``POST /v1/asr/transcribe``. The frontend records the microphone and encodes
the WAV itself, so this module needs no audio dependency.
"""

import json
import logging
import os
import uuid
from typing import List, Optional

import httpx
from pydantic import BaseModel  # type: ignore

ASR_TRANSCRIBE_URL = "https://api.meta.ai/v1/asr/transcribe"
ASR_MODEL_ID = "muse-voice-transcribe-1.0"


class TranscriptTurn(BaseModel):
    turn_id: int = 0
    start_ms: int = 0
    end_ms: int = 0
    transcript: str = ""
    speaker: Optional[str] = None


class VoiceTranscribeResponse(BaseModel):
    status: str  # success | error
    transcript: str = ""
    turns: List[TranscriptTurn] = []
    duration_ms: int = 0
    error: Optional[str] = None


logger = logging.getLogger(__name__)


class VoiceAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("META_LLAMA_API_KEY", "")
        self.url = ASR_TRANSCRIBE_URL
        self.timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

    async def transcribe(self, wav_bytes: bytes) -> VoiceTranscribeResponse:
        """Transcribe WAV bytes. Never raises: failures become status=error."""
        if not self.api_key:
            logger.warning("META_LLAMA_API_KEY missing: cannot call Muse Voice.")
            return VoiceTranscribeResponse(
                status="error", error="Clé API Meta manquante : transcription impossible."
            )
        session_id = uuid.uuid4().hex
        request_part = json.dumps(
            {"mode": "ENDPOINTING", "model": ASR_MODEL_ID, "audioEncoding": "WAV"}
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.url}?sessionId={session_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data={"request": request_part},
                    files={"audio": ("dictation.wav", wav_bytes, "audio/wav")},
                )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("Voice API HTTP %s: %s", exc.response.status_code, exc.response.text[:500])
            return VoiceTranscribeResponse(
                status="error", error=f"Transcription : HTTP {exc.response.status_code}."
            )
        except httpx.TimeoutException:
            logger.error("Voice API timed out.")
            return VoiceTranscribeResponse(status="error", error="Transcription : délai dépassé.")
        except Exception:
            logger.exception("Unexpected Voice call failure.")
            return VoiceTranscribeResponse(
                status="error", error="Transcription : appel impossible."
            )

        if not isinstance(data, dict):
            return VoiceTranscribeResponse(status="error", error="Transcription : réponse invalide.")
        transcript = data.get("transcript", "")
        if not isinstance(transcript, str):
            transcript = ""
        turns: List[TranscriptTurn] = []
        raw_turns = data.get("turns", [])
        if isinstance(raw_turns, list):
            for item in raw_turns:
                if not isinstance(item, dict):
                    continue
                try:
                    turns.append(
                        TranscriptTurn(
                            turn_id=int(item.get("turnId", 0)),
                            start_ms=int(item.get("startMs", 0)),
                            end_ms=int(item.get("endMs", 0)),
                            transcript=str(item.get("transcript", "")),
                            speaker=item.get("speaker"),
                        )
                    )
                except (TypeError, ValueError):
                    continue
        try:
            duration_ms = int(data.get("audioDurationMs", 0))
        except (TypeError, ValueError):
            duration_ms = 0
        return VoiceTranscribeResponse(
            status="success", transcript=transcript, turns=turns, duration_ms=duration_ms
        )
