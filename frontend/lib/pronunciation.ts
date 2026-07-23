import { api } from "./api";

// ── Pronunciation Coach API (prefix: /api/pronunciation-coach) ──────────────

export interface TargetSentenceResponse {
  sentence_id: string;
  sentence: string;
  prompt_token: string;
  difficulty?: string;
  category?: string;
}

export interface WordResult {
  word: string;
  status: "correct" | "stress_error" | "mispronounced" | "skipped";
  confidence?: number;
}

export interface PronunciationAssessResult {
  session_id: string;
  sentence_id: string;
  overall_score: number;
  word_results: WordResult[];
  warning?: string | null;
  pacing_tip?: string | null;
  calibrated_for_local_accent?: boolean;
}

export interface PronunciationTtsResponse {
  audio_base64: string;
  mime_type: string;
  speed: "normal" | "slow";
}

// GET /api/pronunciation-coach/sentences
export function getTargetSentence() {
  return api<TargetSentenceResponse>("/pronunciation-coach/sentences");
}

// POST /api/pronunciation-coach/sentences/{sentence_id}/attempts  (multipart)
export function assessPronunciation(formData: FormData) {
  return api<PronunciationAssessResult>("/pronunciation-coach/sentences/" + (formData.get("sentence_id") as string) + "/attempts", {
    method: "POST",
    body: formData,
  });
}

// GET /api/pronunciation-coach/words/{word}/audio?speed=normal|slow
export function fetchPronunciationTts(word: string, speed: "normal" | "slow" = "normal") {
  return api<PronunciationTtsResponse>(`/pronunciation-coach/words/${encodeURIComponent(word)}/audio?speed=${speed}`);
}
