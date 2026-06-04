import os
import logging
from datetime import datetime, time
import pytz

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

from db import (
    init_db, log_meal, log_workout,
    get_today_meals, get_today_workouts, get_today_totals,
    undo_last_meal, undo_last_workout, clear_today,
    save_oura_token, get_oura_token, get_all_active_users
)
from ai import parse_meal, parse_workout, looks_like_workout, looks_like_question, answer_question
from oura import get_oura_calories

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUMMARY_HOUR = int(os.environ.get("SUMMARY_HOUR", "21"))
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Singapore")

DAILY_TARGETS = {
    "calories": 1300,
    "protein": 82,
    "carbs": 130,
    "fat": 45,
}


def make_bar(val, target, width=10):
    pct = min(val / target, 1.0) if target else 0
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


def format_summary(totals: dict, meals: list, workouts: list, title="📊 Today's Summary") -> str:
    cal = totals["calories"]
    pro = totals["protein"]
    carbs = totals["carbs"]
    fat = totals["fat"]
    burned = totals["burned"]
    net = totals["net_calories"]

    effective_target = DAILY_TARGETS["calories"] + burned
    over = net > DAILY_TARGETS["calories"]
    diff = net - DAILY_TARGETS["calories"]

    status = "🚨 OVER LIMIT" if over else "✅ ON TRACK"
    cal_line = (
        f"⚠️ +{abs(round(diff))} kcal over target"
        if over else
        f"✅ {abs(round(diff))} kcal remaining"
    )

    # Meals list
    meal_lines = ""
    for m in meals:
        meal_lines += f"\n  • {m['food_name']} — {round(m['calories'])}kcal"

    # Workouts list
    workout_lines = ""
    for w in workouts:
        src = "🔵 Oura" if w["source"] == "oura" else "💪"
        workout_lines += f"\n  {src} {w['description']} (-{round(w['calories_burned'])}kcal)"

    # Macro bars
    bars = ""
    for label, val, target in [
        ("Calories", cal,  DAILY_TARGETS["calories"]),
        ("Protein ", pro,  DAILY_TARGETS["protein"]),
        ("Carbs   ", carbs, DAILY_TARGETS["carbs"]),
        ("Fat     ", fat,  DAILY_TARGETS["fat"]),
    ]:
        over_m = " ⚠️" if val > target else ""
        bars += f"\n{label}: {make_bar(val,target)} {round(val)}/{target}{over_m}"

    burned_line = f"\n🔥 Burned:   {round(burned)} kcal (budget +{round(burned)})" if burned > 0 else ""
    net_line = f"\n⚖️  Net:      {round(net)} / {DAILY_TARGETS['calories']} kcal" if burned > 0 else ""

    # Advice
    advice = ""
    if over:
        advice = f"\n\n💡 You're {round(diff)} kcal over. Lighter dinner tomorrow or an extra workout!"
    elif diff < -300:
        advice = f"\n\n💡 {abs(round(diff))} kcal left — consider a protein snack."
    if pro < DAILY_TARGETS["protein"] * 0.8:
        advice += f"\n⚠️ Protein low ({round(pro)}g/{DAILY_TARGETS['protein']}g). Add eggs, chicken or tofu."

    return (
        f"{title}\n"
        f"{'─' * 28}\n"
        f"Status: {status}\n"
        f"{cal_line}"
        f"{bars}"
        f"{burned_line}"
        f"{net_line}\n"
        f"\n🍽 Food:{meal_lines if meal_lines else ' none logged'}"
        f"\n\n🏃 Workouts:{workout_lines if workout_lines else ' none logged'}"
        f"{advice}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hey! I'm *FuelBot* — your personal macro & fitness tracker.\n\n"
        "Just tell me what you ate:\n"
        "_2 kaya toast, 2 eggs and 1 kopi c siew dai_\n\n"
        "Or log a workout:\n"
        "_45 min run_ or _1 hour gym_\n\n"
        "*Commands:*\n"
        "/summary — today's full breakdown\n"
        "/sync — pull calories burned from Oura\n"
        "/oura <token> — connect your Oura ring\n"
        "/undo — remove last logged meal\n"
        "/undoworkout — remove last logged workout\n"
        "/clear — reset today's log\n"
        "/targets — see your daily goals\n\n"
        "🎯 Daily goal: *1,300 kcal net*\n"
        "_(51kg, 160cm — goal: -2kg in 2 months)_",
        parse_mode="Markdown"
    )


async def targets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 *Your Daily Targets*\n"
        "──────────────────────\n"
        f"🔥 Calories: {DAILY_TARGETS['calories']} kcal\n"
        f"💪 Protein:  {DAILY_TARGETS['protein']}g\n"
        f"🌾 Carbs:    {DAILY_TARGETS['carbs']}g\n"
        f"🥑 Fat:      {DAILY_TARGETS['fat']}g\n\n"
        "Workouts add to your budget — burn 300 kcal and you get 300 extra kcal to eat.\n\n"
        "_Based on: 51kg, 160cm, ~300 kcal deficit for fat loss_",
        parse_mode="Markdown"
    )


async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    meals = get_today_meals(user_id)
    workouts = get_today_workouts(user_id)
    totals = get_today_totals(user_id)

    if not meals and not workouts:
        await update.message.reply_text("Nothing logged today yet. Tell me what you ate or what workout you did! 🍽")
        return

    text = format_summary(totals, meals, workouts)
    await update.message.reply_text(f"```\n{text}\n```", parse_mode="Markdown")


async def undo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    removed = undo_last_meal(user_id)
    if removed:
        await update.message.reply_text(f"↩️ Removed meal: *{removed}*", parse_mode="Markdown")
    else:
        await update.message.reply_text("No meals to undo.")


async def undoworkout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    removed = undo_last_workout(user_id)
    if removed:
        await update.message.reply_text(f"↩️ Removed workout: *{removed}*", parse_mode="Markdown")
    else:
        await update.message.reply_text("No manual workouts to undo.")


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    clear_today(user_id)
    await update.message.reply_text("🗑 Today's log (meals + workouts) has been cleared.")


async def oura_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "To connect Oura:\n\n"
            "1. Go to https://cloud.ouraring.com/personal-access-tokens\n"
            "2. Create a Personal Access Token\n"
            "3. Send it here: `/oura YOUR_TOKEN_HERE`\n\n"
            "_Your token is stored securely and only used to fetch your activity data._",
            parse_mode="Markdown"
        )
        return

    token = context.args[0].strip()
    # Validate the token works
    try:
        result = await get_oura_calories(token)
        save_oura_token(user_id, token)
        if result:
            await update.message.reply_text(
                f"✅ *Oura connected!*\n\n"
                f"Today's data:\n{result['summary']}\n\n"
                f"Use /sync anytime to pull your latest activity.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "✅ *Oura connected!* No activity data for today yet — check back later.\nUse /sync to pull data anytime.",
                parse_mode="Markdown"
            )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Oura connect error: {e}")
        await update.message.reply_text("❌ Couldn't connect to Oura. Check your token and try again.")


async def sync_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = get_oura_token(user_id)

    if not token:
        await update.message.reply_text(
            "You haven't connected Oura yet.\nUse /oura to get setup instructions.",
        )
        return

    thinking = await update.message.reply_text("🔄 Syncing with Oura...")

    try:
        result = await get_oura_calories(token)
    except ValueError as e:
        await thinking.edit_text(f"❌ {e}")
        return
    except Exception as e:
        logger.error(f"Oura sync error: {e}")
        await thinking.edit_text("❌ Couldn't reach Oura. Try again in a moment.")
        return

    if not result or result["active_calories"] == 0:
        await thinking.edit_text("No Oura activity data for today yet. Try again after your workout!")
        return

    burned = result["active_calories"]
    log_workout(
        user_id,
        description=f"Oura: {result['steps']:,} steps · score {result['score']}",
        calories_burned=burned,
        source="oura"
    )

    totals = get_today_totals(user_id)
    net = totals["net_calories"]
    remaining = DAILY_TARGETS["calories"] - net
    over = net > DAILY_TARGETS["calories"]

    status = (
        f"⚠️ Still {abs(round(remaining))} kcal *over* even after workout."
        if over else
        f"✅ *{round(remaining)} kcal remaining* after workout bonus."
    )

    await thinking.edit_text(
        f"🔵 *Oura synced!*\n\n"
        f"{result['summary']}\n\n"
        f"Your calorie budget increased by *+{round(burned)} kcal*\n"
        f"{status}",
        parse_mode="Markdown"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Route: question → coach, workout → fitness log, else → meal log
    if looks_like_question(text):
        await handle_question(update, context, text, user_id)
    elif looks_like_workout(text):
        await handle_workout(update, context, text, user_id)
    else:
        await handle_meal(update, context, text, user_id)


async def handle_question(update, context, text, user_id):
    thinking = await update.message.reply_text("🤔 Let me check your log...")
    try:
        meals = get_today_meals(user_id)
        workouts = get_today_workouts(user_id)
        totals = get_today_totals(user_id)
        reply = await answer_question(text, meals, workouts, totals, DAILY_TARGETS, ANTHROPIC_API_KEY)
        await thinking.edit_text(reply)
    except Exception as e:
        logger.error(f"Question handler error: {e}")
        await thinking.edit_text("❌ Couldn't answer that right now. Try again!")


async def handle_meal(update, context, text, user_id):
    thinking = await update.message.reply_text("⏳ Calculating macros...")
    try:
        meals_parsed = await parse_meal(text, ANTHROPIC_API_KEY)
    except Exception as e:
        logger.error(f"Meal parse error: {e}")
        await thinking.edit_text("❌ Couldn't parse that. Try again or be more specific.")
        return

    if not meals_parsed:
        await thinking.edit_text("❌ Couldn't identify any food items. Try again!")
        return

    for meal in meals_parsed:
        log_meal(user_id, meal)

    totals = get_today_totals(user_id)
    net = totals["net_calories"]
    burned = totals["burned"]
    over = net > DAILY_TARGETS["calories"]
    remaining = DAILY_TARGETS["calories"] - net

    this_cal = sum(m["calories"] for m in meals_parsed)
    this_pro = sum(m["protein"] for m in meals_parsed)
    this_carbs = sum(m["carbs"] for m in meals_parsed)
    this_fat = sum(m["fat"] for m in meals_parsed)

    items_text = ""
    for m in meals_parsed:
        items_text += f"\n• {m['food_name']}: {round(m['calories'])}kcal | P:{m['protein']}g C:{m['carbs']}g F:{m['fat']}g"

    burned_note = f"\n_(Includes +{round(burned)} kcal workout bonus)_" if burned > 0 else ""
    status_line = (
        f"⚠️ *OVER by {abs(round(remaining))} kcal!* Try to keep dinner light."
        if over else
        f"✅ *{round(remaining)} kcal remaining* today"
    )

    await thinking.edit_text(
        f"✅ *Logged!*{items_text}\n\n"
        f"*This meal:* {round(this_cal)} kcal | P:{round(this_pro)}g C:{round(this_carbs)}g F:{round(this_fat)}g\n\n"
        f"*Net today:* {round(net)} / {DAILY_TARGETS['calories']} kcal{burned_note}\n"
        f"{status_line}",
        parse_mode="Markdown"
    )


async def handle_workout(update, context, text, user_id):
    thinking = await update.message.reply_text("💪 Logging workout...")
    try:
        result = await parse_workout(text, ANTHROPIC_API_KEY)
    except Exception as e:
        logger.error(f"Workout parse error: {e}")
        await thinking.edit_text("❌ Couldn't parse that workout. Try something like '30 min run' or '1 hour gym'.")
        return

    log_workout(user_id, result["description"], result["calories_burned"], source="manual")

    totals = get_today_totals(user_id)
    net = totals["net_calories"]
    remaining = DAILY_TARGETS["calories"] - net
    over = net > DAILY_TARGETS["calories"]

    status_line = (
        f"⚠️ Still *{abs(round(remaining))} kcal over* — keep meals light."
        if over else
        f"✅ *{round(remaining)} kcal remaining* (after workout bonus)"
    )

    await thinking.edit_text(
        f"💪 *Workout logged!*\n"
        f"{result['description']}\n"
        f"🔥 Burned: *{round(result['calories_burned'])} kcal*\n\n"
        f"Your budget increased — net calories today: *{round(net)} / {DAILY_TARGETS['calories']} kcal*\n"
        f"{status_line}\n\n"
        f"_Use /sync to replace this with your actual Oura data._",
        parse_mode="Markdown"
    )


async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    users = get_all_active_users()
    for user_id in users:
        try:
            meals = get_today_meals(user_id)
            workouts = get_today_workouts(user_id)
            totals = get_today_totals(user_id)
            if not meals and not workouts:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="🌙 End of day — nothing logged today. Fresh start tomorrow! 💪"
                )
            else:
                text = format_summary(totals, meals, workouts, title="🌙 End of Day Summary")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"```\n{text}\n```",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Failed to send summary to {user_id}: {e}")


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary_cmd))
    app.add_handler(CommandHandler("targets", targets_cmd))
    app.add_handler(CommandHandler("undo", undo_cmd))
    app.add_handler(CommandHandler("undoworkout", undoworkout_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("oura", oura_cmd))
    app.add_handler(CommandHandler("sync", sync_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    tz = pytz.timezone(TIMEZONE)
    summary_time = time(hour=SUMMARY_HOUR, minute=0, tzinfo=tz)
    app.job_queue.run_daily(send_daily_summary, time=summary_time)

    logger.info("FuelBot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
