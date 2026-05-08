import sys
sys.path.insert(0, ".")
from ai.client import AIClient, _last_json

ai = AIClient()
print(f"Available: {ai.available}  |  URL: {ai.base_url}")
if not ai.available:
    print("Server offline.")
    sys.exit()

print("\n--- Test 1: plain JSON request ---")
result = ai.complete_json(
    "You are a game designer API. Output only JSON.",
    'Give me a boss name. JSON: {"name": "...", "lore": "..."}',
    max_tokens=900,
)
print(f"JSON result: {result}")

print("\n--- Test 2: boss profile (same as game) ---")
from ai.director import AIDirector
director = AIDirector(ai)
profile = director.generate_boss_profile(1)
print(f"Boss name : {profile.get('name')}")
print(f"Abilities : {profile.get('abilities')}")
print(f"AI-generated: {'The Ashen Warden' not in profile.get('name','')}")
