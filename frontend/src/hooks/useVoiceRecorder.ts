import { useState, useCallback, useRef, useEffect } from 'react';
import { transcribeAudio } from '../services/api';
import { LLM_PAUSE_THRESHOLD_MS, VOICE_ACTIVITY_THRESHOLD } from '../config/constants';

type RecorderState = 'idle' | 'recording' | 'processing';

export function useVoiceRecorder(onTranscript: (text: string) => void) {
  const [state, setState] = useState<RecorderState>('idle');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const isProcessingRef = useRef<boolean>(false);
  const hasSpokenRef = useRef<boolean>(false);

  /** Clear any pending silence timer and audio monitoring */
  const clearMonitoring = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      try {
        audioContextRef.current.close();
      } catch {
        void 0;
      }
      audioContextRef.current = null;
    }
    analyserRef.current = null;
  }, []);

  const stopRecording = useCallback(() => {
    clearMonitoring();
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      try {
        mediaRecorderRef.current.stop();
      } catch {
        void 0;
      }
    }
  }, [clearMonitoring]);

  const startRecording = useCallback(async () => {
    // Prevent overlapping recordings
    if (state === 'recording' || state === 'processing') return;

    clearMonitoring();
    isProcessingRef.current = false;
    hasSpokenRef.current = false;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // Set up AudioContext + AnalyserNode for real-time speech/silence detection
      const AudioCtxClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioCtx = new AudioCtxClass();
      audioContextRef.current = audioCtx;

      const sourceNode = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      sourceNode.connect(analyser);
      analyserRef.current = analyser;

      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        clearMonitoring();
        stream.getTracks().forEach((t) => t.stop());

        // Guard against duplicate processing/race conditions
        if (isProcessingRef.current) return;
        isProcessingRef.current = true;

        setState('processing');
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        try {
          const { transcript } = await transcribeAudio(blob);
          if (transcript.trim()) {
            onTranscript(transcript);
          }
        } catch (err) {
          console.error('Transcription failed:', err);
        } finally {
          setState('idle');
          isProcessingRef.current = false;
        }
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setState('recording');

      // Monitor voice activity and trigger silence timer after speech
      const checkAudioLevel = () => {
        if (!analyserRef.current || mediaRecorderRef.current?.state !== 'recording') return;

        const buffer = new Float32Array(analyserRef.current.fftSize);
        analyserRef.current.getFloatTimeDomainData(buffer);

        // Compute Root-Mean-Square (RMS) amplitude
        let sum = 0;
        for (let i = 0; i < buffer.length; i++) {
          sum += buffer[i] * buffer[i];
        }
        const rms = Math.sqrt(sum / buffer.length);

        if (rms > VOICE_ACTIVITY_THRESHOLD) {
          // User is actively speaking — cancel any pending silence timer
          hasSpokenRef.current = true;
          if (silenceTimerRef.current) {
            clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = null;
          }
        } else if (hasSpokenRef.current) {
          // User was speaking, but now silence is detected
          // Start the silence timer if not already active
          if (!silenceTimerRef.current) {
            silenceTimerRef.current = setTimeout(() => {
              // LLM_PAUSE_THRESHOLD_MS of silence elapsed! Proceed with LLM response
              stopRecording();
            }, LLM_PAUSE_THRESHOLD_MS);
          }
        }

        animFrameRef.current = requestAnimationFrame(checkAudioLevel);
      };

      animFrameRef.current = requestAnimationFrame(checkAudioLevel);
    } catch (err) {
      console.error('Mic access failed:', err);
      clearMonitoring();
      setState('idle');
    }
  }, [clearMonitoring, onTranscript, state, stopRecording]);

  const toggleRecording = useCallback(() => {
    if (state === 'idle') {
      startRecording();
    } else if (state === 'recording') {
      stopRecording();
    }
  }, [state, startRecording, stopRecording]);

  // Clean up on component unmount
  useEffect(() => {
    return () => {
      clearMonitoring();
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, [clearMonitoring]);

  return { state, toggleRecording };
}
