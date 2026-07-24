"use client";

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  HelpCircle,
  Loader2,
  Mic,
  RefreshCw,
  Volume2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";
import {
  assessPronunciation,
  fetchPronunciationTts,
  getTargetSentence,
  type PronunciationAssessResult,
  type TargetSentenceResponse,
} from "@/lib/pronunciation";
import { getAccentPreference } from "@/lib/accentCalibration";

export default function PronunciationCoachPage() {
  const [sentenceData, setSentenceData] = React.useState<TargetSentenceResponse | null>(null);
  const [accentModel, setAccentModel] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isRecording, setIsRecording] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<PronunciationAssessResult | null>(null);

  // Word TTS player state
  const [selectedWord, setSelectedWord] = React.useState<string | null>(null);
  const [ttsSpeed, setTtsSpeed] = React.useState<"normal" | "slow">("normal");
  const [isPlayingTts, setIsPlayingTts] = React.useState(false);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null);
  const audioChunksRef = React.useRef<Blob[]>([]);

  const loadSentence = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    setSelectedWord(null);
    try {
      const [data, pref] = await Promise.allSettled([
        getTargetSentence(),
        getAccentPreference(),
      ]);
      if (data.status === "fulfilled") setSentenceData(data.value);
      else throw new Error("Failed to load target sentence.");
      if (pref.status === "fulfilled") setAccentModel(pref.value.accent_model_preference);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load target sentence.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => { loadSentence(); }, [loadSentence]);

  const handleStartRecording = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        await handleAssessAudio(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      setError("Microphone permission denied or unsupported.");
    }
  };

  const handleStopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleAssessAudio = async (blob: Blob) => {
    if (!sentenceData) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("sentence_id", sentenceData.sentence_id);
      formData.append("prompt_token", sentenceData.prompt_token);
      formData.append("audio", blob, "pronunciation.webm");
      const res = await assessPronunciation(formData);
      setResult(res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Assessment failed.";
      if (err instanceof ApiError && err.status === 403 && msg.toLowerCase().includes("suspended")) {
        setError(msg);
      } else if (msg.toLowerCase().includes("multiple voices")) {
        setError("Multiple voices detected. Try again in a quiet place.");
      } else if (msg.toLowerCase().includes("stale") || msg.toLowerCase().includes("reused")) {
        setError("Your reading session expired. Loading a fresh sentence…");
        loadSentence();
      } else {
        setError(msg);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePlayWordTts = async (word: string, speed: "normal" | "slow") => {
    setSelectedWord(word);
    setTtsSpeed(speed);
    setIsPlayingTts(true);
    try {
      const blob = await fetchPronunciationTts(word, speed);
      const audioUrl = URL.createObjectURL(blob);
      if (audioRef.current) {
        audioRef.current.src = audioUrl;
        void audioRef.current.play();
        audioRef.current.onended = () => URL.revokeObjectURL(audioUrl);
      }
    } catch {
      setError("Failed to play correct pronunciation.");
    } finally {
      setIsPlayingTts(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <audio ref={audioRef} className="hidden" />

      <div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Pronunciation Coach
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Read the sentence aloud for instant word-level feedback.
        </p>
      </div>

      {/* PRN-US-10: Local Accent Calibration Notice */}
      {accentModel === "south_asian_pakistani" && (
        <div className="flex items-center gap-2 rounded-xl border border-primary/20 bg-primary/5 px-4 py-2.5 text-xs font-medium text-primary">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Calibrated for South Asian / Pakistani English pronunciation tolerances.
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-foreground">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <span>{error}</span>
        </div>
      )}

      {/* Target Sentence Card */}
      {sentenceData && (
        <div className="rounded-2xl border border-border bg-surface-elevated p-8 shadow-sm">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            Read This Sentence Aloud
          </span>
          <p className="mt-4 font-serif text-2xl font-medium leading-relaxed text-foreground">
            {sentenceData.text}
          </p>

          {/* Record Button */}
          <div className="mt-8 flex flex-col items-center gap-4">
            <button
              onClick={isRecording ? handleStopRecording : handleStartRecording}
              disabled={isSubmitting}
              aria-label={isRecording ? "Stop recording" : "Start recording"}
              className={cn(
                "flex h-20 w-20 items-center justify-center rounded-full transition-all shadow-lg",
                isRecording
                  ? "bg-danger text-white animate-pulse"
                  : "bg-primary text-primary-foreground hover:scale-105 active:scale-95"
              )}
            >
              {isSubmitting ? <Loader2 className="h-8 w-8 animate-spin" /> : <Mic className="h-8 w-8" />}
            </button>
            <p className="text-sm text-muted-foreground">
              {isRecording ? "Recording… tap to stop" : isSubmitting ? "Analyzing…" : "Tap to record"}
            </p>
          </div>
        </div>
      )}

      {/* Word-Level Feedback Results */}
      {result && (
        <div className="flex flex-col gap-5 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="font-serif text-xl font-semibold text-foreground">Your Assessment</h2>
            <span className="text-3xl font-extrabold text-primary">{result.overall_score}%</span>
          </div>

          {/* Word badges */}
          <div>
            <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              Tap a word to hear the correct pronunciation
            </span>
            <div className="mt-3 flex flex-wrap gap-2">
              {result.word_results.map((w, idx) => {
                const styles: Record<string, string> = {
                  correct: "bg-success/10 text-success border-success/30",
                  stress_error: "bg-warning/10 text-warning border-warning/30",
                  mispronounced: "bg-danger/10 text-danger border-danger/30",
                  skipped: "bg-muted text-muted-foreground border-border",
                };
                const labels: Record<string, string> = {
                  correct: "",
                  stress_error: " (stress)",
                  mispronounced: " (mispronounced)",
                  skipped: " (missed)",
                };
                return (
                  <button
                    key={idx}
                    onClick={() => handlePlayWordTts(w.word, ttsSpeed)}
                    className={cn(
                      "flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm font-medium transition-all hover:scale-105",
                      styles[w.status] ?? styles.correct
                    )}
                    title={`${w.word}${labels[w.status] ?? ""}`}
                  >
                    {w.word}
                    <Volume2 className="h-3 w-3 opacity-60" />
                  </button>
                );
              })}
            </div>
          </div>

          {/* TTS speed toggle for selected word */}
          {selectedWord && (
            <div className="flex items-center justify-between rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm">
              <span className="flex items-center gap-2">
                <Volume2 className="h-4 w-4 text-primary" />
                Hear: <strong>"{selectedWord}"</strong>
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant={ttsSpeed === "normal" ? "primary" : "outline"}
                  onClick={() => handlePlayWordTts(selectedWord, "normal")}
                  disabled={isPlayingTts}
                >
                  Normal
                </Button>
                <Button
                  size="sm"
                  variant={ttsSpeed === "slow" ? "primary" : "outline"}
                  onClick={() => handlePlayWordTts(selectedWord, "slow")}
                  disabled={isPlayingTts}
                >
                  Slow
                </Button>
              </div>
            </div>
          )}

          {/* ACC-US-11 warning: STT breakdown fallback / accent-calibration model notices */}
          {result.warning && (
            <div className="flex items-start gap-2.5 rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm text-foreground">
              <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              {result.warning}
            </div>
          )}

          {/* PRN-US-10 E-03: Heavy stuttering / disfluency pacing tip */}
          {result.disfluency_detected && (
            <div className="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-foreground">
              <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              Heavy pausing or stuttering detected — try reading the sentence once through at a slower, steady pace before recording again.
            </div>
          )}

          {/* Background speech interference notice */}
          {result.background_voice_detected && (
            <div className="flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-foreground">
              <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              Background speech was detected during scoring — for the most accurate feedback, retry in a quiet space.
            </div>
          )}

          <Button variant="outline" className="self-end" onClick={loadSentence}>
            <RefreshCw className="mr-1.5 h-4 w-4" /> Next Sentence
          </Button>
        </div>
      )}
    </div>
  );
}
