import asyncio
import logging
import os
import tempfile
from typing import Optional

from faster_whisper import WhisperModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_whisper_model: Optional[WhisperModel] = None


def get_whisper_model() -> Optional[WhisperModel]:
    """Load and cache the Whisper model (called once at startup)."""
    global _whisper_model
    if _whisper_model is None:
        try:
            logger.info(
                f"Loading Faster-Whisper model: {settings.whisper_model_size} "
                f"(device={settings.whisper_device}, compute={settings.whisper_compute_type})"
            )
            _whisper_model = WhisperModel(
                settings.whisper_model_size,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                local_files_only=False,
            )
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            _whisper_model = None
    return _whisper_model


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> str:
    """
    Transcribe audio bytes to text using Faster-Whisper (non-blocking).

    Whisper inference is CPU-bound and can take 1-10 seconds. Running it in a
    thread-pool executor prevents blocking the asyncio event loop for all other
    concurrent requests.

    Performance notes:
    - beam_size=1 uses greedy decoding: 30-50% faster than beam_size=5 with
      negligible accuracy loss on restaurant-domain vocabulary.
    - Model is loaded before the temp file is created so that if loading
      raises an exception no temp file is leaked.
    """
    # Load model FIRST — if unavailable, exit early without creating temp files.
    model = get_whisper_model()
    if model is None:
        logger.warning("Whisper model not available, returning empty transcript")
        return ""

    # Write to a temp file — Faster-Whisper requires a file path for ffmpeg decoding.
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        def _do_transcribe():
            """Synchronous transcription — runs inside the thread executor."""
            segments, info = model.transcribe(
                tmp_path,
                language=language,
                beam_size=1,          # greedy — ~40% faster, minimal accuracy loss
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            # Materialize the generator inside the thread
            text = " ".join(seg.text.strip() for seg in segments)
            return text.strip(), info

        loop = asyncio.get_running_loop()
        transcript, info = await loop.run_in_executor(None, _do_transcribe)

        logger.info(
            f"Transcribed ({info.language}, {info.duration:.1f}s): {transcript[:100]}"
        )
        return transcript
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return ""
    finally:
        os.unlink(tmp_path)
