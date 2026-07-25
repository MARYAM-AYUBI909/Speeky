from fastapi import APIRouter

from services.daily_challenge_service import (
    complete_challenge,
    get_challenge_status,
    get_notification,
)

router = APIRouter()

# PDG-US-11: Daily Challenge & Streak Gamification
router.add_api_route("/complete", complete_challenge, methods=["POST"])
router.add_api_route("/status", get_challenge_status, methods=["GET"])
# PDG-US-13: in-app Streak-Warning decision (OS-push fallback)
router.add_api_route("/notification", get_notification, methods=["GET"])
