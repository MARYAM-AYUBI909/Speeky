"""LiveKit worker for AI Conversation Practice's voice mode.

Room-naming contract: the LiveKit room name IS the conversation session_id
(see conversation_service._start_session: session["room_name"] = session_id,
and livekit_tokens.mint_room_token(session["room_name"], ...) — the frontend
joins that exact room with the token from POST /conversation/sessions/{id}/voice-token).

This worker auto-dispatches to every room a participant joins (default LiveKit
agent dispatch — no per-session launch needed). For each subscribed audio track
it runs Silero VAD to find speech segments, transcribes each segment locally
with faster-whisper, and sends results over the room's LiveKit data channel:

    topic="voice_transcript", payload={"text": "..."}   — final transcript
    topic="voice_status",     payload={"status": "speaking"|"idle"}  — live state

The frontend (see ConversationSessionPage's RoomEvent.DataReceived handler)
appends transcript text into the message input box — the user reviews/edits it
and hits Send, reusing the existing POST /conversation/sessions/{id}/messages
path. The status packets drive a pulsing mic dot so the user sees when speech
is being detected. This worker never calls the backend directly and never
auto-sends on the user's behalf.
"""

import asyncio
import io
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from faster_whisper import WhisperModel
from livekit import rtc
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents import vad as agents_vad
from livekit.plugins import silero

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")

# ── Full-mode acoustic extraction reuses the backend's proven prosody/level code ──────
# The worker runs from voice_agent/, so put backend/ on the path to import the same
# prosody_engine / audio_io the recording_engine pipeline uses — no duplicated DSP, and
# full-mode features match the base64-upload path exactly (verified on harvard.wav).
_BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

try:
    import numpy as np  # noqa: E402
    from lib import audio_io, prosody_engine, vad_engine  # noqa: E402
    from lib.speech_config import load_speech_config  # noqa: E402

    _FULL_OK = True
except Exception:  # parselmouth/numpy not installed in this env -> full mode degrades
    _FULL_OK = False

model = WhisperModel("base", device="cpu", compute_type="int8")

# model.transcribe() is synchronous/CPU-bound; run it off the event loop so it never
# blocks the agent's WebRTC keepalives (a blocked loop for the several seconds
# transcription takes was tipping the LiveKit connection into a client-initiated
# disconnect mid-session). max_workers=1 also serializes calls onto one shared model
# instance, which isn't guaranteed safe for concurrent inference.
_executor = ThreadPoolExecutor(max_workers=1)


def transcribe(frame: rtc.AudioFrame) -> str:
    # Hand faster-whisper a WAV file-like object (via to_wav_bytes(), which correctly tags the frame's real sample rate .
    # Silero's VAD event frame is at the track's native rate, e.g. 48kHz, NOT the 16kHz Silero resamples to internally for its own inference) instead of a raw ndarray.
    wav_bytes = frame.to_wav_bytes()
    # temperature=0: single decode pass. faster-whisper's default temperature-fallback
    # ladder retries up to 6x on low-confidence audio, turning one utterance into a
    # 7-10s+ block — the user reviews/edits the transcript before sending anyway, so a
    # rougher single-pass result beats a more "accurate" one that misses the latency budget.
    segments, _info = model.transcribe(io.BytesIO(wav_bytes), beam_size=5, temperature=0)
    return " ".join(seg.text.strip() for seg in segments).strip()


def transcribe_full(frame: rtc.AudioFrame) -> dict:
    """FULL mode: transcript + word timings + prosody + input level for one utterance.

    Same signals the recording_engine base64 path produces, computed here from the raw
    utterance waveform so Public Speaking gets real WPM / tone / clarity without shipping
    audio to the backend. Falls back to transcript-only if the DSP deps are unavailable.
    """
    wav_bytes = frame.to_wav_bytes()
    segments, _info = model.transcribe(
        io.BytesIO(wav_bytes), beam_size=5, temperature=0, word_timestamps=True
    )
    text_parts, word_timings = [], []
    for seg in segments:
        text_parts.append(seg.text.strip())
        for w in (seg.words or []):
            word_timings.append(
                {"word": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)}
            )
    text = " ".join(text_parts).strip()

    features = {"word_timings": word_timings}
    if _FULL_OK:
        try:
            cfg = load_speech_config()
            decoded = audio_io.decode_audio_bytes(wav_bytes, cfg.audio_sample_rate)
            waveform, sr = decoded.waveform, decoded.sample_rate
            prosody = prosody_engine.analyze(waveform, sr)
            # Clarity needs SNR. The utterance still carries the inter-word/-sentence gaps
            # silero left in, so estimate the noise floor from those — same VAD-based method
            # recording_engine uses on the full clip (voice_agent/agent.py stays in parity).
            vad_result = vad_engine.detect_speech_segments(waveform, sr, cfg)
            _noise_floor, snr_db = vad_engine.estimate_noise_and_snr(waveform, sr, vad_result)
            features.update(
                {
                    "duration_seconds": round(decoded.duration_seconds, 3),
                    "avg_db": round(audio_io.rms_dbfs(waveform), 2),
                    "pitch_range_semitones": round(float(prosody.pitch_range_semitones), 2),
                    "snr_db": round(float(snr_db), 1),
                }
            )
        except Exception:
            logger.exception("full-mode acoustic extraction failed; sending transcript only")

    return {"text": text, "features": features}


async def publish_transcript(room: rtc.Room, text: str, features: dict | None = None) -> None:
    if not text:
        return
    body = {"text": text}
    if features is not None:
        body["features"] = features  # full mode: word timings + prosody + level
    payload = json.dumps(body).encode("utf-8")
    try:
        await room.local_participant.publish_data(payload, reliable=True, topic="voice_transcript")
        logger.info("Sent transcript to frontend: %r (full=%s)", text, features is not None)
    except Exception:
        logger.exception("Failed to publish transcript over data channel")


async def publish_status(room: rtc.Room, status: str) -> None:
    """Send a speaking/idle hint so the frontend can show a live mic indicator."""
    payload = json.dumps({"status": status}).encode("utf-8")
    try:
        await room.local_participant.publish_data(payload, reliable=False, topic="voice_status")
    except Exception:
        pass  # best-effort — status hints are non-critical


async def process_audio(track: rtc.Track, identity: str, vad: silero.VAD, room: rtc.Room, mode: str):
    audio_stream = rtc.AudioStream(track)
    vad_stream = vad.stream()
    full = mode == "full"

    async def forward_frames():
        async for event in audio_stream:
            vad_stream.push_frame(event.frame)
        vad_stream.end_input()

    async def read_vad_events():
        async for event in vad_stream:
            if event.type == agents_vad.VADEventType.START_OF_SPEECH:
                logger.info("Speech STARTED (%s)", identity)
                await publish_status(room, "speaking")
            elif event.type == agents_vad.VADEventType.END_OF_SPEECH:
                await publish_status(room, "idle")
                # Silero's END_OF_SPEECH event carries the whole utterance as a single
                # already-combined frame (see livekit/plugins/silero/vad.py's
                # _copy_speech_buffer) — no need to concatenate multiple frames.
                if full:
                    result = await asyncio.get_running_loop().run_in_executor(
                        _executor, transcribe_full, event.frames[0]
                    )
                    logger.info("Speech ENDED (%s) [full]: %r", identity, result["text"])
                    await publish_transcript(room, result["text"], result["features"])
                else:
                    text = await asyncio.get_running_loop().run_in_executor(
                        _executor, transcribe, event.frames[0]
                    )
                    logger.info("Speech ENDED (%s): %r", identity, text)
                    await publish_transcript(room, text)

    await asyncio.gather(forward_frames(), read_vad_events())


def _participant_mode(participant: rtc.RemoteParticipant) -> str:
    """Read the pipeline mode the caller requested from its participant metadata (stamped
    by livekit_tokens.mint_room_token). Defaults to transcript."""
    try:
        meta = json.loads(participant.metadata or "{}")
        return "full" if meta.get("mode") == "full" else "transcript"
    except Exception:
        return "transcript"


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    logger.info("Connected to room: %s", ctx.room.name)

    vad = silero.VAD.load()

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(track: rtc.Track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            mode = _participant_mode(participant)
            logger.info("Subscribed to audio from %s (mode=%s)", participant.identity, mode)
            asyncio.create_task(process_audio(track, participant.identity, vad, ctx.room, mode))

    # Drain tracks that were already published before this worker joined.
    # track_subscribed only fires for future subscriptions — without this loop
    # any mic the browser published before the agent connected is silently missed.
    for participant in ctx.room.remote_participants.values():
        mode = _participant_mode(participant)
        for publication in participant.track_publications.values():
            if publication.track and publication.track.kind == rtc.TrackKind.KIND_AUDIO:
                logger.info("Processing pre-existing audio from %s (mode=%s)", participant.identity, mode)
                asyncio.create_task(
                    process_audio(publication.track, participant.identity, vad, ctx.room, mode)
                )

    await asyncio.Event().wait()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
