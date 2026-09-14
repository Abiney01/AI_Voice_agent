import io
import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.services.kokoro.tts_service import synthesize_speech
from app.services.whisper.stt_service import transcribe_audio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/transcribe", summary="Transcribe audio to text")
async def transcribe(
    audio: UploadFile = File(..., description="Audio file (WAV, WebM, MP3, etc.)")
):
    """
    Upload audio and receive the transcribed text.
    Supports any format that ffmpeg can handle.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file")

    transcript = await transcribe_audio(audio_bytes)
    return {"transcript": transcript, "filename": audio.filename}


@router.post("/synthesize", summary="Convert text to speech")
async def synthesize(
    text: str,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
):
    """
    Convert text to WAV audio using Kokoro ONNX TTS.
    Returns audio/wav binary stream.
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    audio_bytes = await synthesize_speech(text, voice=voice, speed=speed if speed is not None else 0.92)
    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": 'attachment; filename="response.wav"'},
    )
