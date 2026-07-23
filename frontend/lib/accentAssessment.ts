import { api } from "./api";

// ── Accent Assessment API (prefix: /api/accent-assessment) ──────────────────
// Routes from: backend/routers/accent_routes.py

export interface TargetPassageResponse {
  passage_id: string;
  passage: string;
  prompt_token: string;
  word_count: number;
}

export interface WeakPoint {
  issue: string;
  detail: string;
}

export interface AccentAssessmentResult {
  assessment_id: string;
  passage_id: string;
  overall_score: number;
  pronunciation_score: number;
  stress_score: number;
  rhythm_score: number;
  intonation_score: number;
  clarity_score: number;
  weak_points: WeakPoint[];
  exercises: string[];
  warning?: string | null;
  model_used?: string;
  liveness_appeal_available?: boolean;
  appeal_token?: string | null;
  appeal_prompt?: string | null;
}

export interface LivenessAppealInput {
  passage_id: string;
  appeal_token: string;
  audio_data: string; // Base64
}

export interface LivenessAppealResult {
  status: "approved" | "rejected";
  message: string;
  assessment_result?: AccentAssessmentResult;
}

// GET /api/accent-assessment/passages
export function getTargetPassage() {
  return api<TargetPassageResponse>("/accent-assessment/passages");
}

// POST /api/accent-assessment/passages/{passage_id}/assessments  (multipart)
export function submitPassageAssessment(passageId: string, formData: FormData) {
  return api<AccentAssessmentResult>(`/accent-assessment/passages/${passageId}/assessments`, {
    method: "POST",
    body: formData,
  });
}

// POST /api/accent-assessment/appeal
export function submitLivenessAppeal(data: LivenessAppealInput) {
  return api<LivenessAppealResult>("/accent-assessment/appeal", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
