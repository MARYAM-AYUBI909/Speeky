import requests
from speeky.interview_persona_engine import PersonaEngine, PERSONAS

pe = PersonaEngine()

user_message = "Tell me about a time you failed at something."

for persona_id in PERSONAS:
    pe.select_persona(persona_id)
    tone_prompt = pe.get_effective_prompt(user_message)

    print(f"\n{'='*50}")
    print(f"PERSONA: {PERSONAS[persona_id]['name']}")
    print(f"{'='*50}")

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.1:8b",
                "system": tone_prompt,
                "prompt": user_message,
                "stream": False
            },
            timeout=180
        )
        ai_reply = response.json().get("response", "")
        print("AI Reply:", ai_reply)
    except Exception as e:
        print("Error:", e)