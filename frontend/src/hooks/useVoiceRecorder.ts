import { useState, useCallback, useRef } from 'react';
import { transcribeAudio } from '../services/api';

type RecorderState = 'idle' | 'recording' | 'processing';

export function useVoiceRecorder(onTranscript: (text: string) => void) {
  const [state, setState] = useState<RecorderState>('idle');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        setState('processing');
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        try {
          const { transcript } = await transcribeAudio(blob);
          if (transcript.trim()) onTranscript(transcript);
        } catch (err) {
          console.error('Transcription failed:', err);
        } finally {
          setState('idle');
        }
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setState('recording');
    } catch (err) {
      console.error('Mic access failed:', err);
      setState('idle');
    }
  }, [onTranscript]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop();
    }
  }, []);

  const toggleRecording = useCallback(() => {
    if (state === 'idle') startRecording();
    else if (state === 'recording') stopRecording();
  }, [state, startRecording, stopRecording]);

  return { state, toggleRecording };
}
