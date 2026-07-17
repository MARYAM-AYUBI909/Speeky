"""
Quick manual test for US-37 (Voice-to-Text Mode Switching) and
US-38 (TTS Playback for AI Text Chat).

HOW TO RUN:
    python test_session.py

This will:
 1. Start a session in VOICE mode.
 2. Send a voice turn using the sample test.wav file.
 3. Switch to TEXT mode.
 4. Send a text turn.
 5. Play the AI's last reply out loud (US-38).
 6. Print the final hybrid scorecard.
"""

from scipy.io import wavfile
import numpy as np

from speeky.session_manager import SessionManager


def load_wav(path):
    sample_rate, audio = wavfile.read(path)
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483648.0
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    return audio, sample_rate


def main():
    print("=== US-37 & US-38 Manual Test ===\n")

    session = SessionManager()

    # --- Step 1: Voice turn ---
    print("[1] Sending a VOICE turn using test.wav ...")
    audio, sr = load_wav("test.wav")
    voice_turn = session.send_voice_turn(audio, sr)
    print("User said:", voice_turn["user_content"])
    print("AI replied:", voice_turn["ai_response"])
    print("Pronunciation score:", voice_turn["pronunciation_score"])
    print()

    # --- Step 2: Switch to text mode (US-37) ---
    print("[2] Switching mode: voice -> text ...")
    print(session.toggle_mode("text"))
    print()

    # --- Step 3: Text turn (context should still be remembered) ---
    print("[3] Sending a TEXT turn ...")
    text_result = session.send_text_turn("Can we continue in text now?")
    print(text_result)
    print()

    # --- Step 4: Play the AI's last reply out loud (US-38) ---
    print("[4] Playing AI's last reply as audio ...")
    last_reply = session.turns[-1]["ai_response"]
    play_result = session.play_ai_response(last_reply)
    print(play_result)
    print()

    # --- Step 5: Final scorecard ---
    print("[5] Final scorecard:")
    print(session.get_scorecard())


if __name__ == "__main__":
    main()
