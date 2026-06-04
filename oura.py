import httpx
from datetime import date


OURA_API_BASE = "https://api.ouraring.com/v2"


async def get_oura_calories(token: str) -> dict | None:
    """
    Fetches today's active calories burned from Oura Ring API v2.
    Returns dict with active_calories, total_calories, and a summary string.
    Returns None if the request fails.
    """
    today = date.today().isoformat()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{OURA_API_BASE}/usercollection/daily_activity",
            headers={"Authorization": f"Bearer {token}"},
            params={"start_date": today, "end_date": today},
        )

        if resp.status_code == 401:
            raise ValueError("Invalid or expired Oura token. Please re-connect with /oura <token>")

        resp.raise_for_status()
        data = resp.json()

    documents = data.get("data", [])
    if not documents:
        return None

    day = documents[0]
    active_calories = day.get("active_calories", 0)
    total_calories = day.get("total_calories", 0)
    steps = day.get("steps", 0)
    activity_score = day.get("score", None)

    lines = []
    if activity_score:
        lines.append(f"Activity score: {activity_score}/100")
    lines.append(f"Steps: {steps:,}")
    lines.append(f"Active calories burned: {active_calories} kcal")
    lines.append(f"Total calories burned: {total_calories} kcal")

    return {
        "active_calories": active_calories,
        "total_calories": total_calories,
        "steps": steps,
        "score": activity_score,
        "summary": "\n".join(lines),
    }
