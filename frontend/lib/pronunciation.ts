import { api, API_URL, ApiError } from "./api";

// ── Pronunciation Coach API (prefix: /api/pronunciation-coach) ──────────────
// Mirrors backend/schemas/pronunciation_schemas.py response shapes exactly.

export interface TargetSentenceResponse {
  sentence_id: string;
  difficulty: string;
  text: string;
  focus_sounds: string[];
  prompt_token: string;
}

export interface WordResult {
  word: string;
  target_index: number;
  status: "correct" | "stress_error" | "mispronounced" | "skipped";
  confidence?: number | null;
}

export interface PronunciationAssessResult {
  attempt_id: string;
  sentence_id: string;
  target_text: string;
  transcript: string;
  overall_score: number;
  word_results: WordResult[];
  attempt_count: number;
  background_voice_detected: boolean;
  disfluency_detected: boolean;
  accent_profile?: string | null;
  warning?: string | null;
  model_used?: string | null;
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

// GET /api/pronunciation-coach/words/{word}/audio?speed=normal|slow — returns a
// raw audio/wav body on success (not JSON), so this fetches manually rather
// than through the api() JSON helper (mirrors lib/conversation.ts's synthesizeSpeech).
export async function fetchPronunciationTts(
  word: string,
  speed: "normal" | "slow" = "normal"
): Promise<Blob> {
  const response = await fetch(
    `${API_URL}/pronunciation-coach/words/${encodeURIComponent(word)}/audio?speed=${speed}`,
    { credentials: "include" }
  );
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ApiError(data?.error ?? "Correct pronunciation audio unavailable", response.status, data);
  }
  return response.blob();
}
