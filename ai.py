import httpx
import json


MEAL_SYSTEM_PROMPT = """You are a nutrition expert specialising in Singaporean and Asian food.

When given a description of food eaten, return ONLY a JSON array of objects. Each object represents one distinct food item and must have these keys:
- food_name (string): clear name including quantity, e.g. "2x Kaya Toast", "1x Kopi C Siew Dai"
- calories (number): kcal
- protein (number): grams
- carbs (number): grams
- fat (number): grams

Rules:
- Split combined meals into individual items
- Account for quantities mentioned (e.g. "2 eggs" = double the macros)
- Use realistic values for local Singapore hawker food
- No markdown, no explanation — only the raw JSON array

Example output:
[
  {"food_name": "2x Kaya Toast", "calories": 280, "protein": 6, "carbs": 42, "fat": 10},
  {"food_name": "2x Soft Boiled Egg", "calories": 144, "protein": 12, "carbs": 1, "fat": 10},
  {"food_name": "1x Kopi C Siew Dai", "calories": 60, "protein": 2, "carbs": 8, "fat": 2}
]"""


WORKOUT_SYSTEM_PROMPT = """You are a fitness expert. When given a workout description, return ONLY a JSON object with:
- description (string): clean workout summary, e.g. "30 min run (moderate pace)"
- calories_burned (number): estimated kcal burned
- duration_minutes (number): duration if mentioned, else estimate

Base estimates on a 51kg female doing moderate-intensity exercise.
No markdown, no explanation — only the raw JSON object.

Example:
{"description": "30 min run (moderate pace)", "calories_burned": 210, "duration_minutes": 30}"""


async def _call_claude(system: str, user_text: str, api_key: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "system": system,
                "messages": [{"role": "user", "content": user_text}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
    raw = data["content"][0]["text"].strip()
    return raw.replace("```json", "").replace("```", "").strip()


async def parse_meal(text: str, api_key: str) -> list[dict]:
    raw = await _call_claude(MEAL_SYSTEM_PROMPT, text, api_key)
    return json.loads(raw)


async def parse_workout(text: str, api_key: str) -> dict:
    raw = await _call_claude(WORKOUT_SYSTEM_PROMPT, text, api_key)
    return json.loads(raw)


WORKOUT_KEYWORDS = [
    "run", "ran", "walk", "walked", "gym", "workout", "exercise", "swim", "swam",
    "cycle", "cycling", "hiit", "yoga", "pilates", "cardio", "weights", "lifting",
    "training", "jog", "jogged", "class", "zumba", "crossfit", "spin", "rowing",
    "climbed", "stairs", "min ", "mins ", "minutes", "hour", "km", "miles",
]


def looks_like_workout(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in WORKOUT_KEYWORDS)
