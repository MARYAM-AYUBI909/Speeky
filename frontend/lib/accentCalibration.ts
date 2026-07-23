import { api } from "./api";

// ── Accent Calibration API (prefix: /api/users) ──────────────────────────────
// Routes from: backend/routers/user_routes.py
// GET  /api/users/me/accent-preference
// PATCH /api/users/me/accent-preference
// POST /api/accent-assessment/sub-dialect-dispute

export interface AccentPreferenceResponse {
  accent_model_preference: "generic_global" | "south_asian_pakistani";
  sub_dialect_preference?: "broad_regional" | "punjabi" | "sindhi" | "pashto" | null;
  is_accent_suspended?: boolean;
  liveness_flag_count?: number;
}

export interface UpdateAccentPreferenceInput {
  accent_model_preference: "generic_global" | "south_asian_pakistani";
  sub_dialect_preference?: "broad_regional" | "punjabi" | "sindhi" | "pashto" | null;
}

export interface SubDialectDisputeResult {
  status: string;
  message: string;
}

// GET /api/users/me/accent-preference
export function getAccentPreference() {
  return api<AccentPreferenceResponse>("/users/me/accent-preference");
}

// PATCH /api/users/me/accent-preference
export function updateAccentPreference(data: UpdateAccentPreferenceInput) {
  return api<AccentPreferenceResponse>("/users/me/accent-preference", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// POST /api/accent-assessment/sub-dialect-dispute
export function submitSubDialectDispute(reason?: string) {
  return api<SubDialectDisputeResult>("/accent-assessment/sub-dialect-dispute", {
    method: "POST",
    body: JSON.stringify({ dispute_reason: reason }),
  });
}
