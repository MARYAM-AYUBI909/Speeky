import { api } from "./api";

// PDG-US-11 / PDG-US-13. All day-boundary logic keys off the LOCAL calendar date the
// client sends (YYYY-MM-DD), so the backend never has to guess the user's timezone.

/** Local calendar date as YYYY-MM-DD. Pass a session's start time to honor E-02 (a
 *  session started before midnight counts for the day it began). Defaults to now. */
export function localDate(d: Date = new Date()): string {
  // en-CA formats as YYYY-MM-DD; do it via parts to avoid any locale surprise.
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export interface DailyChallengeStatus {
  completed_today: boolean;
  current_streak: number;
  longest_streak: number;
  badges: number[];
  next_milestone: number | null;
  required_minutes: number;
}

export interface CompleteChallengeResult {
  qualified: boolean;
  message?: string;
  already_completed_today?: boolean;
  current_streak?: number;
  longest_streak?: number;
  newly_awarded_badges?: number[];
  next_milestone?: number | null;
  share_card?: { title: string; subtitle: string; badges: number[] };
}

export interface StreakNotification {
  show_streak_warning: boolean;
  current_streak: number;
  message: string | null;
}

export function getDailyChallengeStatus() {
  return api<DailyChallengeStatus>(
    `/daily-challenge/status?local_date=${localDate()}`
  );
}

export function completeDailyChallenge(durationSeconds: number, startedAt?: Date) {
  return api<CompleteChallengeResult>("/daily-challenge/complete", {
    method: "POST",
    body: JSON.stringify({
      duration_seconds: durationSeconds,
      local_date: localDate(startedAt ?? new Date()),
    }),
  });
}

export function getStreakNotification() {
  const now = new Date();
  return api<StreakNotification>(
    `/daily-challenge/notification?local_date=${localDate(now)}&local_hour=${now.getHours()}`
  );
}
