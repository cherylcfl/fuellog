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
                "model": "claude-haiku-4-5-20251001",
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


async def parse_meal_from_photo(image_bytes: bytes, mime_type: str, caption: str, api_key: str) -> list[dict]:
    import base64
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = (
        f"The user sent a photo of their meal{f' with caption: {caption}' if caption else ''}. "
        "Identify all visible food items and estimate macros for each."
    )

    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1000,
                "system": MEAL_SYSTEM_PROMPT,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_b64,
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        }
                    ]
                }],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    raw = data["content"][0]["text"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


import re

WORKOUT_KEYWORDS = [
    "run", "ran", "walk", "walked", "gym", "workout", "exercise", "swim", "swam",
    "cycle", "cycling", "hiit", "yoga", "pilates", "cardio", "weights", "lifting",
    "training", "jog", "jogged", "zumba", "crossfit", "spin", "rowing",
    "climbed", "stairs", "km", "miles",
]

# These only count as workout if they appear as whole words
WORKOUT_WORD_KEYWORDS = [
    "run", "ran", "walk", "walked", "swim", "swam", "jog", "jogged",
    "gym", "workout", "exercise", "cycle", "cycling", "cardio",
    "weights", "lifting", "training", "hiit", "yoga", "pilates",
    "zumba", "crossfit", "spin", "rowing",
]

# These require a number before them to count
WORKOUT_UNIT_KEYWORDS = ["min", "mins", "minutes", "hour", "hours", "km", "miles", "steps"]


def looks_like_workout(text: str) -> bool:
    lower = text.lower()
    # Check whole-word workout keywords
    for kw in WORKOUT_WORD_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            return True
    # Check unit keywords only when preceded by a number (e.g. "30 min", "5km")
    for kw in WORKOUT_UNIT_KEYWORDS:
        if re.search(rf"\d+\s*{re.escape(kw)}\b", lower):
            return True
    return False


QUESTION_KEYWORDS = [
    "how much", "how many", "what should", "what can", "what's left",
    "whats left", "am i on track", "did i", "have i", "should i",
    "suggest", "recommend", "what to eat", "help me", "advice",
    "remaining", "left for", "good for", "tips", "idea", "ideas",
    "can i eat", "is it okay", "is it fine", "what if", "how do",
    "best food", "best meal", "high protein", "low calorie", "low carb",
    "?",
]


def looks_like_question(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in QUESTION_KEYWORDS)


async def answer_question(question: str, meals: list, workouts: list, totals: dict,
                           targets: dict, api_key: str) -> str:
    # Build a context summary of the user's day
    meal_lines = "\n".join(
        f"  - {m['food_name']}: {round(m['calories'])}kcal, P:{m['protein']}g, C:{m['carbs']}g, F:{m['fat']}g"
        for m in meals
    ) or "  (nothing logged yet)"

    workout_lines = "\n".join(
        f"  - {w['description']}: -{round(w['calories_burned'])}kcal burned"
        for w in workouts
    ) or "  (no workouts logged yet)"

    burned = totals.get("burned", 0)
    net = totals.get("net_calories", totals["calories"])

    context = f"""User profile: Female, 51kg, 160cm. Goal: lose 2-3kg in 2 months.

Daily targets:
- Calories: {targets['calories']} kcal (net)
- Protein: {targets['protein']}g
- Carbs: {targets['carbs']}g
- Fat: {targets['fat']}g

Today's food log:
{meal_lines}

Today's workouts:
{workout_lines}

Today's totals:
- Calories eaten: {round(totals['calories'])} kcal
- Calories burned: {round(burned)} kcal
- Net calories: {round(net)} / {targets['calories']} kcal
- Protein: {round(totals['protein'])}g / {targets['protein']}g
- Carbs: {round(totals['carbs'])}g / {targets['carbs']}g
- Fat: {round(totals['fat'])}g / {targets['fat']}g"""

    system = """You are FuelBot, a friendly personal nutrition coach and fitness advisor.
You have access to the user's meal log, workout log, and daily macro targets for today.
Answer their question in a helpful, encouraging, concise way.
Keep replies short — max 3 to 4 lines. No long paragraphs.
When suggesting food, prioritise Singapore hawker options.
Be specific with numbers when relevant. Never be preachy.
Use a warm, casual tone. Use emojis liberally to keep it fun and easy to scan.
Format lists with emojis as bullet points instead of dashes."""

    user_msg = f"{context}\n\nUser question: {question}"
    return await _call_claude(system, user_msg, api_key)
