"use client";

import * as React from "react";
import {
  Room,
  RoomEvent,
  Track,
  createLocalAudioTrack,
  type LocalAudioTrack,
} from "livekit-client";
import { ApiError } from "./api";

export interface VoiceTokenResult {
  url: string;
  token: string;
  room: string;
}

/**
 * Shared LiveKit voice-in hook: connects to a per-session LiveKit room, publishes the
 * mic, and forwards transcripts the voice_agent/ worker sends back over the data
 * channel (topic "voice_transcript") to `onTranscript` — never auto-sends, callers
 * decide what text state the transcript fills. Mirrors the logic that originally lived
 * inline in the Conversation session page, generalized for Scenarios/Coaching/Interview
 * Coach to reuse.
 */
export function useLiveKitVoice(
  fetchToken: () => Promise<VoiceTokenResult>,
  onTranscript: (text: string) => void,
) {
  const [isVoiceActive, setIsVoiceActive] = React.useState(false);
  const [isConnectingVoice, setIsConnectingVoice] = React.useState(false);
  const [voiceStatus, setVoiceStatus] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const roomRef = React.useRef<Room | null>(null);
  const microphoneTrackRef = React.useRef<LocalAudioTrack | null>(null);
  const onTranscriptRef = React.useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  const startVoice = React.useCallback(async () => {
    if (roomRef.current) return;

    setError(null);
    setIsConnectingVoice(true);
    setVoiceStatus("Connecting voice...");

    // Local reference (not the ref) so the catch block can clean up a room that
    // connected but failed a later step (e.g. mic publish) — roomRef itself is only
    // set once the whole sequence succeeds, so relying on roomRef here would leak an
    // orphaned, still-connected room under this user's identity on any partial failure.
    let room: Room | null = null;

    try {
      const voiceData = await fetchToken();
      room = new Room();

      room.on(RoomEvent.Disconnected, (reason) => {
        console.log("[voice] room disconnected, reason:", reason);
        setIsVoiceActive(false);
        setVoiceStatus("Voice disconnected.");
      });

      room.on(RoomEvent.ParticipantConnected, (p) => {
        console.log("[voice] participant joined room:", p.identity);
      });

      // reason=1 (CLIENT_INITIATED) only tells us the JS SDK sent the leave — not WHY.
      // These catch every path that could trigger it: our own code (logged with a stack
      // so we can see which call site), a failed auto-reconnect, or the mic track itself
      // dying (device/permission issue).
      room.on(RoomEvent.Reconnecting, () => console.warn("[voice] reconnecting..."));
      room.on(RoomEvent.Reconnected, () => console.log("[voice] reconnected"));
      room.on(RoomEvent.SignalReconnecting, () => console.warn("[voice] signal reconnecting..."));
      room.on(RoomEvent.MediaDevicesError, (e) => console.error("[voice] media device error:", e));
      room.on(RoomEvent.LocalTrackUnpublished, (pub) =>
        console.warn("[voice] local track unpublished:", pub.trackSid, "reason unknown"),
      );

      // Logged unconditionally (not just on topic match) so a topic/payload mismatch
      // shows up in devtools instead of silently doing nothing.
      room.on(RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
        console.log("[voice] data received", {
          topic,
          from: participant?.identity,
          bytes: payload.length,
        });
        if (topic !== "voice_transcript") return;
        try {
          const { text } = JSON.parse(new TextDecoder().decode(payload));
          if (!text) return;
          onTranscriptRef.current(text);
          setVoiceStatus("Heard you — review and hit Send.");
        } catch (err) {
          console.error("Failed to parse voice transcript payload:", err);
        }
      });

      await room.connect(voiceData.url, voiceData.token);
      console.log("[voice] connected to room", voiceData.room, "state:", room.state);

      const microphoneTrack = await createLocalAudioTrack();
      microphoneTrack.mediaStreamTrack.addEventListener("ended", () =>
        console.error("[voice] mic MediaStreamTrack ended unexpectedly (device lost/revoked?)"),
      );
      await room.localParticipant.publishTrack(microphoneTrack, {
        source: Track.Source.Microphone,
      });
      console.log("[voice] mic track published, sid:", microphoneTrack.sid);

      roomRef.current = room;
      microphoneTrackRef.current = microphoneTrack;

      setIsVoiceActive(true);
      setVoiceStatus("Voice connected. Microphone is active.");
    } catch (err) {
      console.error("[voice] failed to start voice:", err);

      microphoneTrackRef.current?.stop();
      microphoneTrackRef.current = null;
      roomRef.current = null;

      if (room) {
        console.trace("[voice] disconnect call site: startVoice catch block");
        await room.disconnect();
      }

      setIsVoiceActive(false);
      setVoiceStatus("Could not start voice.");
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't connect to voice mode. Check microphone permission and try again.",
      );
    } finally {
      setIsConnectingVoice(false);
    }
  }, [fetchToken]);

  const stopVoice = React.useCallback(async () => {
    console.trace("[voice] disconnect call site: stopVoice (manual or auto)");
    setVoiceStatus("Stopping voice...");
    try {
      if (microphoneTrackRef.current) {
        microphoneTrackRef.current.stop();
        microphoneTrackRef.current = null;
      }
      if (roomRef.current) {
        await roomRef.current.disconnect();
        roomRef.current = null;
      }
    } finally {
      setIsVoiceActive(false);
      setVoiceStatus("Voice stopped.");
    }
  }, []);

  React.useEffect(() => {
    // Best-effort: a hard page reload/close skips React's async unmount cleanup below,
    // which can leave the room connected server-side under this user's identity — the
    // next "Start Voice" then races that zombie connection. pagehide fires reliably
    // before unload (including bfcache navigations), so disconnect there too.
    function disconnectNow() {
      microphoneTrackRef.current?.stop();
      microphoneTrackRef.current = null;
      const room = roomRef.current;
      roomRef.current = null;
      if (room) {
        console.trace("[voice] disconnect call site: unmount/pagehide cleanup");
        void room.disconnect();
      }
    }
    window.addEventListener("pagehide", disconnectNow);
    return () => {
      window.removeEventListener("pagehide", disconnectNow);
      disconnectNow();
    };
  }, []);

  return { isVoiceActive, isConnectingVoice, voiceStatus, error, startVoice, stopVoice };
}
