"use client";

import * as React from "react";
import Link from "next/link";
import { AlertTriangle, ArrowRight, Lock, TrendingDown, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  getAccentProgressTracker,
  type AccentProgressTrackerData,
} from "@/lib/accentProgress";
import { cn } from "@/lib/utils";

/** ACC-US-12: Accent Progress Tracker - Month-Over-Month Matrix Visualization. */
export function AccentProgressTracker() {
  const [trackerData, setTrackerData] = React.useState<AccentProgressTrackerData | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);

  const loadTracker = React.useCallback(() => {
    setIsLoading(true);
    getAccentProgressTracker()
      .then(setTrackerData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load accent progress."))
      .finally(() => setIsLoading(false));
  }, []);

  React.useEffect(() => {
    loadTracker();
  }, [loadTracker]);

  if (isLoading) {
    return (
      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <p className="text-sm text-muted-foreground">Loading your accent progress matrix...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
        <p className="text-sm text-danger">{error}</p>
      </div>
    );
  }

  if (!trackerData) return null;

  const months = trackerData.months || [];
  const month1 = months.find((m) => m.month === 1);
  const month3 = months.find((m) => m.month === 3);

  const metricKeys: { key: keyof typeof month1; label: string }[] = [
    { key: "pronunciation", label: "Pronunciation" },
    { key: "word_stress", label: "Word Stress" },
    { key: "intonation", label: "Intonation" },
    { key: "clarity", label: "Clarity" },
  ];

  return (
    <div className="rounded-2xl border border-border bg-surface-elevated p-6 shadow-sm">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="font-serif text-xl font-semibold text-foreground">Accent Progress Tracker</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Month-over-month comparison across the four accent sub-metrics.
          </p>
        </div>
        <Link href="/dashboard/progress/targeted-drills">
          <Button type="button" size="sm" variant="outline">
            Targeted Exercises <ArrowRight className="ml-1 h-3.5 w-3.5" />
          </Button>
        </Link>
      </div>

      {/* ACC-US-12 E-01: Insufficient Historical Data Locked Columns Banner */}
      {trackerData.is_insufficient_data && (
        <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-info/30 bg-info/10 px-4 py-3 text-sm text-foreground">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <span>{trackerData.message || "Keep practicing! Future month comparisons will unlock after 30 days."}</span>
        </div>
      )}

      {/* Month-over-Month Matrix Table */}
      <div className="mt-6 overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[440px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border bg-surface text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              <th className="sticky left-0 z-10 bg-surface px-4 py-3">Sub-Metric</th>
              <th className="px-4 py-3">Month 1 (Baseline)</th>
              <th className="px-4 py-3">Month 3 (Current)</th>
              <th className="px-4 py-3">Trend</th>
            </tr>
          </thead>
          <tbody>
            {metricKeys.map((item) => {
              const m1Val = month1 ? (month1[item.key] as number | null) : null;
              const m3Val = month3 ? (month3[item.key] as number | null) : null;
              const isLocked = month3?.is_locked ?? trackerData.is_insufficient_data;
              const isRegressed = trackerData.regressed_metrics.includes(item.key);

              return (
                <tr
                  key={item.key}
                  className={cn(
                    "border-b border-border last:border-b-0",
                    isRegressed ? "bg-warning/10" : ""
                  )}
                >
                  <td className="sticky left-0 z-10 bg-surface-elevated px-4 py-3 font-medium text-foreground">
                    {item.label}
                  </td>
                  {/* ACC-US-12 E-03: Missing sub-metric displays N/A (not 0) */}
                  <td className="px-4 py-3 text-foreground">
                    {m1Val !== null ? `${m1Val}%` : <span className="text-muted-foreground">N/A</span>}
                  </td>
                  <td className="px-4 py-3">
                    {isLocked ? (
                      <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Lock className="h-3.5 w-3.5" /> Locked (Future Month)
                      </span>
                    ) : m3Val !== null ? (
                      <span className="font-semibold text-foreground">{m3Val}%</span>
                    ) : (
                      <span className="text-muted-foreground">N/A</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {isLocked ? (
                      <span className="text-xs text-muted-foreground">—</span>
                    ) : isRegressed ? (
                      <span className="flex items-center gap-1 text-xs font-semibold text-warning">
                        <TrendingDown className="h-3.5 w-3.5 text-warning" /> Regressed
                      </span>
                    ) : m3Val && m1Val && m3Val > m1Val ? (
                      <span className="flex items-center gap-1 text-xs font-semibold text-success">
                        <TrendingUp className="h-3.5 w-3.5 text-success" /> Improved
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">Steady</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ACC-US-12 E-02: Score Regression Soft Warning + Targeted Exercises CTA */}
      {trackerData.regressed_metrics.length > 0 && trackerData.cta_suggestion && (
        <div className="mt-4 flex flex-col gap-3 rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-foreground">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <p className="font-medium text-foreground">{trackerData.cta_suggestion}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Targeted drills help isolate specific phonemes and restore peak clarity.
              </p>
            </div>
          </div>
          <Link href="/dashboard/progress/targeted-drills" className="self-end">
            <Button size="xs" variant="outline">
              Start Targeted Drills
            </Button>
          </Link>
        </div>
      )}
    </div>
  );
}
