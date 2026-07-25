"use client";

import * as React from "react";
import { Flame, Share2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  getDailyChallengeStatus,
  type DailyChallengeStatus,
} from "@/lib/dailyChallenge";

// PDG-US-11: Daily Challenge & Streak. Shows the live streak, today's status, earned
// milestone badges, and a shareable card once the day's 5-minute challenge is done.
export function DailyChallengeCard() {
  const [status, setStatus] = React.useState<DailyChallengeStatus | null>(null);

  React.useEffect(() => {
    getDailyChallengeStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  async function handleShare() {
    if (!status) return;
    const text = `I'm on a ${status.current_streak}-day practice streak on Speeky-AI! 🔥`;
    try {
      if (navigator.share) {
        await navigator.share({ title: "Speeky-AI streak", text });
      } else {
        await navigator.clipboard.writeText(text);
      }
    } catch {
      // user cancelled the share sheet — nothing to do
    }
  }

  if (!status) return null;

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-warning/15 text-warning">
            <Flame className="h-5 w-5" aria-hidden="true" />
          </span>
          <div>
            <h2 className="font-serif text-lg font-semibold text-foreground">
              Daily Challenge
            </h2>
            <p className="text-sm text-muted-foreground">
              {status.current_streak > 0
                ? `${status.current_streak}-day streak · longest ${status.longest_streak}`
                : `Practice ${status.required_minutes} minutes to start a streak`}
            </p>
          </div>
        </div>

        {status.completed_today ? (
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded-full bg-success/10 px-3 py-1 text-sm font-medium text-success">
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              Done today
            </span>
            <Button size="sm" variant="outline" onClick={handleShare}>
              <Share2 className="h-4 w-4" aria-hidden="true" />
              Share
            </Button>
          </div>
        ) : (
          <Button href="/dashboard/conversation" size="sm">
            Start {status.required_minutes}-min Challenge
          </Button>
        )}
      </div>

      {status.badges.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {status.badges.map((d) => (
            <span
              key={d}
              className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-primary"
            >
              🏅 {d}-day badge
            </span>
          ))}
          {status.next_milestone ? (
            <span className="text-xs text-muted-foreground">
              Next: {status.next_milestone}-day badge
            </span>
          ) : null}
        </div>
      ) : status.next_milestone ? (
        <p className="mt-4 text-xs text-muted-foreground">
          Reach a {status.next_milestone}-day streak to earn your first badge.
        </p>
      ) : null}
    </div>
  );
}
