/**
 * Voice recording and conversational silence thresholds.
 */

// Duration of silence (in milliseconds) before automatically ending voice recording
// and submitting the audio to the AI concierge for processing.
export const LLM_PAUSE_THRESHOLD_MS = 2000;

// Audio energy (RMS) threshold for detecting voice activity vs background silence.
export const VOICE_ACTIVITY_THRESHOLD = 0.02;
