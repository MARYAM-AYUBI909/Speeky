"use client";

import * as React from "react";
import { TrendingUp, X } from "lucide-react";
import { ApiError } from "@/lib/api";
import { dismissTroubleWord, getActiveTroubleWords, type TroubleWordEntry } from "@/lib/pronunciationCoach";

const STATUS_LABEL: Record<TroubleWordEntry["status"], string> = {
  candidate: "Watching",
  active: "Needs practice",
  mastered: "Mastered",
};

/**
 * US-75: Cross-Session Trouble Words Bank & Spaced Repetition. Real data
 * from backend/lib/pronunciation_coach/trouble_words.py via
 * /api/pronunciation-coach/trouble-words.
 *
 * Honest note: this list will be empty until a conversation turn is scored
 * for pronunciation (US-79), which itself only happens for AUDIO turns —
 * the current conversation UI is text-only, so this page's real E-03 empty
 * state is what most users will see today. See the project summary for why.
 */
export default function ProgressPage() {
  const [words, setWords] = React.useState<TroubleWordEntry[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busyKey, setBusyKey] = React.useState<string | null>(null);

  const load = React.useCallback(() => {
    getActiveTroubleWords()
      .then((data) => setWords(data.words))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load your trouble words."));
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  async function handleDismiss(patternKey: string) {
    setBusyKey(patternKey);
    try {
      await dismissTroubleWord(patternKey);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't dismiss that word.");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-serif text-2xl font-semibold text-foreground">Progress</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Words that need repeated practice, tracked across sessions.
        </p>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {words === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : words.length === 0 ? (
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-border p-12 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-secondary text-primary">
            <TrendingUp className="h-6 w-6" aria-hidden="true" />
          </span>
          <div className="flex flex-col gap-1">
            <h2 className="font-serif text-xl font-semibold text-foreground">No trouble words yet</h2>
            <p className="max-w-sm text-sm text-muted-foreground">
              Words you consistently mispronounce across separate sessions will show up here
              for focused, spaced-repetition practice.
            </p>
          </div>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {words.map((w) => (
            <li
              key={w.pattern_key}
              className="flex flex-col gap-2 rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="font-serif text-lg font-semibold text-foreground">{w.display_word}</p>
                <button
                  type="button"
                  aria-label={`Dismiss ${w.display_word}`}
                  disabled={busyKey === w.pattern_key}
                  onClick={() => handleDismiss(w.pattern_key)}
                  className="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
              <span className="w-fit rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground">
                {STATUS_LABEL[w.status]}
              </span>
              {w.related_words.length > 1 ? (
                <p className="text-xs text-muted-foreground">
                  Also: {w.related_words.filter((r) => r !== w.display_word.toLowerCase()).join(", ")}
                </p>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Missed in {w.fail_session_count} session{w.fail_session_count === 1 ? "" : "s"} · {w.correct_session_count} correct since
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
