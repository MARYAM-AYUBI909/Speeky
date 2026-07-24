import { api, ApiError } from "./api";

// ── Accent Assessment API (prefix: /api/accent-assessment) ──────────────────
// Routes from: backend/routers/accent_routes.py
// Mirrors backend/schemas/accent_schemas.py response shapes exactly.

export interface TargetPassageResponse {
  passage_id: string;
  difficulty: string;
  title: string;
  text: string;
  prompt_token: string;
}

export interface WeakPoint {
  issue: string;
  detail: string;
}

export interface AccentAssessmentResult {
  assessment_id: string;
  passage_id: string;
  status: string;
  transcript?: string | null;
  pronunciation_score: number;
  stress_score: number;
  rhythm_score: number;
  intonation_score: number;
  clarity_score: number;
  weak_points: WeakPoint[];
  warning?: string | null;
  model_used?: string | null;
}

// Shape of the 422 body returned instead of a score when the reading fails a
// liveness/quality check (RecordingRejectedSchema) — read off ApiError.body.
export interface RecordingRejected {
  status: "rejected";
  reason: string;
  message: string;
  appeal_token?: string | null;
  appeal_prompt?: string | null;
}

export interface LivenessAppealResult {
  appeal_passed: boolean;
  message: string;
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

// POST /api/accent-assessment/appeal  (multipart — appeal_token + a fresh live-repeat recording)
export function submitLivenessAppeal(appealToken: string, audio: Blob) {
  const formData = new FormData();
  formData.append("appeal_token", appealToken);
  formData.append("audio", audio, "appeal.webm");
  return api<LivenessAppealResult>("/accent-assessment/appeal", {
    method: "POST",
    body: formData,
  });
}

/** Reads the structured RecordingRejectedSchema body off a 422 ApiError, if present. */
export function rejectionFromError(err: unknown): RecordingRejected | null {
  if (!(err instanceof ApiError) || err.status !== 422 || !err.body || typeof err.body !== "object") {
    return null;
  }
  const body = err.body as Partial<RecordingRejected>;
  if (typeof body.message !== "string" || typeof body.reason !== "string") return null;
  return {
    status: "rejected",
    reason: body.reason,
    message: body.message,
    appeal_token: body.appeal_token ?? null,
    appeal_prompt: body.appeal_prompt ?? null,
  };
}
