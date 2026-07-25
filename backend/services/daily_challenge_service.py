"""
PDG-US-11: Daily Challenge & Streak Gamification
PDG-US-13: Daily Challenge reminder — in-app Streak-Warning fallback (no OS push).

A qualifying Daily Challenge = a >= 5-minute practice session (the frontend calls
`complete` when a conversation ends with duration >= REQUIRED_SECONDS). Streak state lives
on the User row. All day-boundary logic keys off the LOCAL calendar date the client sends
(derived from the session's START time, so an 11:58pm start that finishes past midnight
still counts for the start day — E-02), never the server's UTC clock.
"""

import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib.prisma_client import db
from middlewares.auth_middleware import require_auth

logger = logging.getLogger(__name__)

REQUIRED_SECONDS = 300  # exactly 5 minutes to qualify
BADGE_DAYS = [7, 30]  # milestone streak lengths that award a badge
NOTIFY_HOUR = 18  # 6:00 PM local — PDG-US-13 trigger time


class CompleteChallengeSchema(BaseModel):
    duration_seconds: float = Field(ge=0)
    local_date: str = Field(description="Session START local calendar date, YYYY-MM-DD")


def _parse(d: str) -> Optional[date]:
    try:
        return date.fromisoformat(d)
    except (ValueError, TypeError):
        return None


def _next_milestone(streak: int) -> Optional[int]:
    for d in BADGE_DAYS:
        if streak < d:
            return d
    return None


# ── Controllers ────────────────────────────────────────────────────────────────
async def complete_challenge(
    payload: CompleteChallengeSchema, user_id: str = Depends(require_auth)
):
    today = _parse(payload.local_date)
    if today is None:
        return JSONResponse(status_code=400, content={"error": "Invalid local_date"})

    # E-01: premature exit — under 5 minutes does not qualify, streak untouched.
    if payload.duration_seconds < REQUIRED_SECONDS:
        remaining = int(REQUIRED_SECONDS - payload.duration_seconds)
        return {
            "qualified": False,
            "message": f"You were so close! Complete {remaining} more seconds to finish your Daily Challenge.",
        }

    user = await db.user.find_unique(where={"id": user_id})
    last = _parse(user.lastChallengeDate) if user.lastChallengeDate else None

    # E-03: already completed today — cap at +1 per calendar day, no re-increment.
    if last == today:
        return {
            "qualified": True,
            "already_completed_today": True,
            "current_streak": user.currentStreak,
            "longest_streak": user.longestStreak,
            "newly_awarded_badges": [],
            "next_milestone": _next_milestone(user.currentStreak),
        }

    if last is not None and last == today - timedelta(days=1):
        new_streak = user.currentStreak + 1  # consecutive day
    else:
        new_streak = 1  # first ever, or a gap broke the streak

    new_longest = max(user.longestStreak, new_streak)
    newly_awarded = [d for d in BADGE_DAYS if new_streak >= d and d not in user.streakBadges]
    updated_badges = sorted(set(user.streakBadges) | set(newly_awarded))

    await db.user.update(
        where={"id": user_id},
        data={
            "currentStreak": new_streak,
            "longestStreak": new_longest,
            "lastChallengeDate": today.isoformat(),
            "streakBadges": updated_badges,
        },
    )

    return {
        "qualified": True,
        "already_completed_today": False,
        "current_streak": new_streak,
        "longest_streak": new_longest,
        "newly_awarded_badges": newly_awarded,
        "next_milestone": _next_milestone(new_streak),
        # Shareable progress card payload (PDG-US-11 reward step).
        "share_card": {
            "title": f"{new_streak}-day practice streak!",
            "subtitle": "5 minutes a day on Speeky-AI",
            "badges": updated_badges,
        },
    }


async def get_challenge_status(
    local_date: str, user_id: str = Depends(require_auth)
):
    today = _parse(local_date)
    if today is None:
        return JSONResponse(status_code=400, content={"error": "Invalid local_date"})

    user = await db.user.find_unique(where={"id": user_id})
    last = _parse(user.lastChallengeDate) if user.lastChallengeDate else None

    # A streak is still "alive" today only if the last completion was today or yesterday;
    # an older last-date means the streak has already lapsed (display 0 until they requalify).
    alive = last is not None and last >= today - timedelta(days=1)
    display_streak = user.currentStreak if alive else 0

    return {
        "completed_today": last == today,
        "current_streak": display_streak,
        "longest_streak": user.longestStreak,
        "badges": user.streakBadges,
        "next_milestone": _next_milestone(display_streak),
        "required_minutes": REQUIRED_SECONDS // 60,
    }


async def get_notification(
    local_date: str, local_hour: int, user_id: str = Depends(require_auth)
):
    """PDG-US-13 in-app decision: should a Streak-Warning banner show? True only when the
    learner hasn't completed today (E-03 pre-validation), it's past 6 PM local, and they
    have a live streak worth preserving. Copy injects the current streak for personalization."""
    today = _parse(local_date)
    if today is None:
        return JSONResponse(status_code=400, content={"error": "Invalid local_date"})

    user = await db.user.find_unique(where={"id": user_id})
    last = _parse(user.lastChallengeDate) if user.lastChallengeDate else None
    completed_today = last == today
    alive = last is not None and last >= today - timedelta(days=1)
    streak = user.currentStreak if alive else 0

    show = (not completed_today) and local_hour >= NOTIFY_HOUR and streak > 0
    if show:
        message = f"Don't lose your {streak}-day streak! 5 minutes of practice is all it takes."
    else:
        message = None

    return {
        "show_streak_warning": show,
        "current_streak": streak,
        "message": message,
    }
