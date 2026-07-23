"use client";

import * as React from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Info,
  Loader2,
  Lock,
  Mic,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import {
  getTargetPassage,
  submitLivenessAppeal,
  submitPassageAssessment,
  type AccentAssessmentResult,
  type TargetPassageResponse,
} from "@/lib/accentAssessment";

export default function AccentAssessmentPage() {
  const [passageData, setPassageData] = React.useState<TargetPassageResponse | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isRecording, setIsRecording] = React.useState(false);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [isSuspended, setIsSuspended] = React.useState(false);
  const [result, setResult] = React.useState<AccentAssessmentResult | null>(null);

  // US-80 Anti-Playback Appeal state
  const [appealData, setAppealData] = React.useState<{ appealToken: string; appealPrompt: string } | null>(null);
  const [isAppealRecording, setIsAppealRecording] = React.useState(false);
  const [isSubmittingAppeal, setIsSubmittingAppeal] = React.useState(false);
  const [appealMessage, setAppealMessage] = React.useState<string | null>(null);

  const mediaRecorderRef = React.useRef<MediaRecorder | null>(null);
  const audioChunksRef = React.useRef<Blob[]>([]);

  const loadPassage = React.useCallback(async () => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    setAppealData(null);
    setIsSuspended(false);
    try {
      const data = await getTargetPassage();
      setPassageData(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load passage.";
      if (msg.toLowerCase().includes("suspended")) {
        setIsSuspended(true);
      } else {
        setError(msg);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadPassage();
  }, [loadPassage]);

  const handleStartRecording = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        await handleAssessPassageAudio(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch (err) {
      setError("Microphone permission denied or unsupported.");
    }
  };

  const handleStopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleAssessPassageAudio = async (blob: Blob) => {
    if (!passageData) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("prompt_token", passageData.prompt_token);
      formData.append("audio", blob, "accent_passage.webm");

      const res = await submitPassageAssessment(passageData.passage_id, formData);
      setResult(res);

      if (res.appeal_token && res.appeal_prompt) {
        setAppealData({ appealToken: res.appeal_token, appealPrompt: res.appeal_prompt });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Assessment failed.";
      if (msg.toLowerCase().includes("playback") || msg.toLowerCase().includes("stale_token")) {
        setError("Live reading required — please read the passage directly into your microphone.");
      } else if (msg.toLowerCase().includes("incomplete")) {
        setError("The reading appears incomplete — please read the entire passage in one take.");
      } else if (msg.toLowerCase().includes("quiet") || msg.toLowerCase().includes("noise") || msg.toLowerCase().includes("distortion")) {
        setError("Recording too quiet, noisy, or distorted. Please retake in a quiet environment.");
      } else {
        setError(msg);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // US-80 Live Repeat Appeal recording
  const handleStartAppealRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const reader = new FileReader();
        reader.onloadend = async () => {
          const base64 = (reader.result as string).split(",")[1];
          await handleSendAppeal(base64);
        };
        reader.readAsDataURL(blob);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsAppealRecording(true);
    } catch (err) {
      setError("Microphone permission denied for appeal.");
    }
  };

  const handleStopAppealRecording = () => {
    if (mediaRecorderRef.current && isAppealRecording) {
      mediaRecorderRef.current.stop();
      setIsAppealRecording(false);
    }
  };

  const handleSendAppeal = async (audioBase64: string) => {
    if (!passageData || !appealData) return;
    setIsSubmittingAppeal(true);
    setAppealMessage(null);
    try {
      const res = await submitLivenessAppeal({
        passage_id: passageData.passage_id,
        appeal_token: appealData.appealToken,
        audio_data: audioBase64,
      });
      if (res.status === "approved") {
        setAppealMessage("Appeal approved! Your assessment has been verified.");
        if (res.assessment_result) {
          setResult(res.assessment_result);
        }
        setAppealData(null);
      } else {
        setAppealMessage(res.message || "Appeal failed. Live reading verification required.");
      }
    } catch (err) {
      setAppealMessage("Appeal processing failed. Please try again.");
    } finally {
      setIsSubmittingAppeal(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // US-80 3+ Flags Account Suspension Notice
  if (isSuspended) {
    return (
      <div className="mx-auto flex max-w-lg flex-col items-center gap-5 rounded-2xl border border-danger/30 bg-danger/10 p-8 text-center shadow-sm">
        <ShieldAlert className="h-12 w-12 text-danger" />
        <h1 className="font-serif text-2xl font-semibold text-foreground">
          Assessment Access Suspended
        </h1>
        <p className="text-sm text-muted-foreground">
          Assessment access is temporarily suspended pending support review due to multiple unverified recordings.
        </p>
        <Button href="/dashboard" size="sm" variant="outline">
          Return to Dashboard
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
          Accent Assessment
        </h1>
        <p className="text-sm text-muted-foreground">
          Read the passage aloud to measure rhythm, stress, intonation, and clarity.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-foreground">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <span>{error}</span>
        </div>
      )}

      {/* Randomized Live Passage */}
      {passageData && !result && (
        <div className="rounded-2xl border border-border bg-surface-elevated p-8 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Passage ({passageData.word_count} words)
            </span>
            <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
              Live Token Active
            </span>
          </div>

          <p className="mt-4 font-serif text-lg leading-relaxed text-foreground">
            "{passageData.passage}"
          </p>

          <div className="mt-8 flex flex-col items-center gap-4">
            <button
              onClick={isRecording ? handleStopRecording : handleStartRecording}
              disabled={isSubmitting}
              className={cn(
                "flex h-20 w-20 items-center justify-center rounded-full transition-all shadow-md",
                isRecording
                  ? "bg-danger text-white animate-pulse"
                  : "bg-primary text-primary-foreground hover:scale-105"
              )}
            >
              {isSubmitting ? (
                <Loader2 className="h-8 w-8 animate-spin" />
              ) : (
                <Mic className="h-8 w-8" />
              )}
            </button>
            <p className="text-sm text-muted-foreground">
              {isRecording
                ? "Recording passage... Tap when finished"
                : isSubmitting
                ? "Analyzing rhythm & stress patterns..."
                : "Read the full passage into your microphone"}
            </p>
          </div>
        </div>
      )}

      {/* US-80 False Positive Appeal Modal / Card */}
      {appealData && (
        <div className="flex flex-col gap-4 rounded-2xl border border-warning/30 bg-warning/10 p-6 text-foreground">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-6 w-6 text-warning shrink-0 mt-0.5" />
            <div>
              <h3 className="font-semibold text-foreground">Liveness Appeal Verification</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Your recording was flagged for audio verification. Repeat the short verification prompt below to clear the flag:
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-warning/20 bg-surface p-4 font-serif text-base font-medium">
            "{appealData.appealPrompt}"
          </div>

          {appealMessage && (
            <p className="text-xs font-medium text-primary">{appealMessage}</p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <Button
              size="sm"
              variant={isAppealRecording ? "danger" : "default"}
              loading={isSubmittingAppeal}
              onClick={isAppealRecording ? handleStopAppealRecording : handleStartAppealRecording}
            >
              {isAppealRecording ? "Stop & Submit Appeal" : "Record Short Verification"}
            </Button>
          </div>
        </div>
      )}

      {/* Assessment Results View */}
      {result && (
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-serif text-xl font-semibold text-foreground">
                Accent Profile Results
              </h2>
              <p className="text-xs text-muted-foreground">
                Model: {result.model_used || "Standard Phonetic Model"}
              </p>
            </div>
            <span className="text-3xl font-bold text-primary">
              {result.overall_score}%
            </span>
          </div>

          {/* 5 Sub-Metric Score Cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.pronunciation_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Pronunciation</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.stress_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Word Stress</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.rhythm_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Rhythm</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.intonation_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Intonation</div>
            </div>
            <div className="rounded-xl border border-border bg-surface p-3 text-center">
              <div className="text-lg font-bold text-foreground">{result.clarity_score}%</div>
              <div className="text-[11px] text-muted-foreground uppercase tracking-wide">Clarity</div>
            </div>
          </div>

          {/* ACC-US-14 Unmapped Accent Default Clarity Banner */}
          {result.warning && (
            <div className="flex items-start gap-2.5 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-xs font-medium text-primary">
              <Info className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{result.warning}</span>
            </div>
          )}

          {/* Detected Weak Points */}
          {result.weak_points && result.weak_points.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-foreground">Identified Target Areas</h3>
              <div className="mt-3 grid gap-2">
                {result.weak_points.map((wp, idx) => (
                  <div key={idx} className="rounded-xl border border-border bg-surface p-3 text-xs">
                    <strong className="text-primary uppercase tracking-wide">{wp.issue}: </strong>
                    <span className="text-muted-foreground">{wp.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="outline" onClick={loadPassage}>
              <RefreshCw className="mr-1.5 h-4 w-4" /> Try Another Passage
            </Button>
            <Button href="/dashboard/progress/targeted-drills">
              Practice Targeted Exercises
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
