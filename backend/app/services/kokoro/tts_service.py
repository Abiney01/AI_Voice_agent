import asyncio
import io
import logging
import re
from typing import Optional

import numpy as np
import soundfile as sf

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── TTS Text Sanitiser ───────────────────────────────────────────────────────
# Strips formatting characters that should never be spoken aloud.
# Converts currency symbols to spoken equivalents.
# Removes emoji, markdown, bullet points, JSON artifacts, and code blocks.

# Phase 0: Convert "Item - ₹NNN" or "Item – ₹NNN" to "Item for NNN rupees"
# This handles the common menu item price pattern before generic currency substitution.
_DASH_PRICE_RE = re.compile(
    r"([A-Za-z][^₹\n]*?)\s*[-–—]\s*₹\s*([\d,]+(?:\.\d{1,2})?)"
)

# Mapping of currency / special symbols to their spoken form
_CURRENCY_MAP = [
    (re.compile(r"₹\s*([\d,]+(?:\.\d{1,2})?)"), r"\1 rupees"),   # ₹299 → 299 rupees
    (re.compile(r"Rs\.?\s*([\d,]+(?:\.\d{1,2})?)", re.I), r"\1 rupees"),
    (re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)"), r"\1 dollars"),
    (re.compile(r"€\s*([\d,]+(?:\.\d{1,2})?)"), r"\1 euros"),
]

# Common abbreviation / shorthand expansions for natural speech
_ABBREV_MAP = [
    (re.compile(r"\bqty\b", re.I), "quantity"),
    (re.compile(r"\bpls\b", re.I), "please"),
    (re.compile(r"\bw/\b"), "with"),
    (re.compile(r"\bw/o\b"), "without"),
    (re.compile(r"\bveg\b", re.I), "vegetarian"),
    (re.compile(r"\bno\.\s*(\d+)", re.I), r"number \1"),
    (re.compile(r"\bapprox\b", re.I), "approximately"),
    (re.compile(r"\bmin\b", re.I), "minutes"),
    (re.compile(r"\bthanks\b", re.I), "thank you"),
]

# Patterns stripped entirely (order matters)
_STRIP_PATTERNS = [
    re.compile(r"```[\s\S]*?```"),           # code blocks
    re.compile(r"`[^`]+`"),                  # inline code
    re.compile(r"^#{1,6}\s+", re.M),        # markdown headings
    re.compile(r"\*{1,3}([^*]+)\*{1,3}"),   # bold / italic → keep text
    re.compile(r"_{1,2}([^_]+)_{1,2}"),     # underscore emphasis → keep text
    re.compile(r"\[([^\]]+)\]\([^)]+\)"),   # markdown links → keep label
    re.compile(r"^[\-\*\+•\u2022\u2023\u25E6]\s+", re.M),  # bullet symbols
    re.compile(r"^\d+[.):]\s+", re.M),      # numbered list prefixes
    re.compile(r"^>+\s*", re.M),            # blockquotes
    re.compile(r"~~([^~]+)~~"),              # strikethrough → keep text
    re.compile(r"---+|===+"),               # horizontal rules
    re.compile(r"\{[^{}]+\}"),              # JSON fragments / template vars
    re.compile(r"<[^>]+>"),                 # HTML / XML tags
]

# Emoji: strip via broad Unicode ranges
_EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\u200d\ufe0f]+",
    flags=re.UNICODE,
)

# Repeated punctuation that causes unnatural pauses (e.g. "!!!" → "!")
_REPEAT_PUNCT_RE = re.compile(r"([!?.]){2,}")

# Ellipsis to natural pause word
_ELLIPSIS_RE = re.compile(r"\.{2,}|\u2026")


def sanitize_for_tts(text: str) -> str:
    """
    Convert LLM output into clean, natural speech text.

    Pipeline:
      0. Convert "Item - ₹NNN" → "Item for NNN rupees" (natural menu price reading)
      1. Apply currency substitutions (₹, $, €, Rs.)
      2. Expand common abbreviations (qty, pls, w/, etc.)
      3. Strip markdown / JSON / HTML formatting
      4. Strip emoji
      5. Convert ellipsis → natural pause phrasing
      6. Collapse repeated punctuation
      7. Collapse whitespace

    Returns clean text ready for Kokoro TTS synthesis.
    """
    # 0. Convert dash-price pattern: "Chicken Biryani - ₹299" → "Chicken Biryani for 299 rupees"
    text = _DASH_PRICE_RE.sub(lambda m: f"{m.group(1).strip()} for {m.group(2)} rupees", text)

    # 1. Apply currency substitutions first (before stripping symbols)
    for pattern, replacement in _CURRENCY_MAP:
        text = pattern.sub(replacement, text)

    # 2. Expand abbreviations for natural speech
    for pattern, replacement in _ABBREV_MAP:
        text = pattern.sub(replacement, text)

    # 3. Apply strip patterns (some keep inner text via group(1))
    for pattern in _STRIP_PATTERNS:
        # Patterns with a capture group keep the inner text
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1), text)
        else:
            text = pattern.sub(" ", text)

    # 4. Strip emoji
    text = _EMOJI_RE.sub("", text)

    # 5. Convert ellipsis to a natural pause (comma + space)
    text = _ELLIPSIS_RE.sub(", ", text)

    # 6. Collapse repeated punctuation (e.g. "!!!" → "!")
    text = _REPEAT_PUNCT_RE.sub(r"\1", text)

    # 7. Collapse multiple spaces / newlines into a single space
    text = re.sub(r"\s+", " ", text).strip()

    return text


_kokoro_model = None


def get_kokoro_model():
    """Load and cache the Kokoro ONNX TTS model (called once at startup). Supports v1.0 and v0.19."""
    global _kokoro_model
    if _kokoro_model is None:
        try:
            import os
            from kokoro_onnx import Kokoro

            # Detect v1.0 or v0.19 files
            model_file = "kokoro-v1.0.onnx" if os.path.exists("kokoro-v1.0.onnx") else "kokoro-v0_19.onnx"
            voices_file = "voices-v1.0.bin" if os.path.exists("voices-v1.0.bin") else "voices.bin"

            if not os.path.exists(model_file) or not os.path.exists(voices_file):
                logger.warning(
                    f"Kokoro model files not found ({model_file}, {voices_file}). "
                    "TTS synthesis will return silence until downloaded."
                )
                return None

            logger.info(f"Loading Kokoro ONNX TTS model ({model_file}, {voices_file})...")
            _kokoro_model = Kokoro(model_file, voices_file)
            logger.info("Kokoro TTS model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Kokoro model: {e}")
            _kokoro_model = None
    return _kokoro_model


async def synthesize_speech(
    text: str,
    voice: Optional[str] = None,
    speed: float = 0.92,
) -> bytes:
    """
    Convert text to speech using Kokoro ONNX (non-blocking).

    Voice: af_heart — warm, expressive, natural-sounding female voice.
    Speed: 0.92 — slightly slower than default for warmer, more natural delivery
           with proper emphasis. Avoids the robotic rush of 1.0x speed.

    Text is sanitised before synthesis to strip markdown, emoji, currency
    symbols (replaced with spoken equivalents), and other formatting that
    should never be spoken aloud.

    Kokoro ONNX inference is CPU-bound. Running it in a thread-pool executor
    prevents blocking the asyncio event loop for all other concurrent requests.
    Returns WAV audio bytes, or a short silence on failure.
    """
    # Sanitise before passing to the TTS model
    clean_text = sanitize_for_tts(text)
    if not clean_text.strip():
        return _generate_silence()

    # Fall back to configured setting from .env
    voice = voice or get_settings().kokoro_voice
    model = get_kokoro_model()

    if model is None:
        logger.warning("Kokoro model not available, returning silence")
        return _generate_silence()

    logger.info(f"TTS synthesis | voice={voice} speed={speed} | text={clean_text[:80]!r}")

    try:
        def _do_synthesize():
            """Synchronous TTS inference — runs inside the thread executor."""
            return model.create(
                clean_text,
                voice=voice,
                speed=speed,
                lang=settings.kokoro_lang,
            )

        loop = asyncio.get_running_loop()
        samples, sample_rate = await loop.run_in_executor(None, _do_synthesize)

        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format="WAV")
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.error(f"Kokoro TTS error: {e}")
        return _generate_silence()


def _generate_silence(duration_seconds: float = 0.5, sample_rate: int = 22050) -> bytes:
    """Generate a short silence WAV as a fallback."""
    silence = np.zeros(int(duration_seconds * sample_rate), dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, silence, sample_rate, format="WAV")
    buf.seek(0)
    return buf.read()
