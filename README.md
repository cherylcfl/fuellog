# FuelBot — Telegram Macro + Fitness Tracker
### Setup Guide (~15 minutes)

---

## Step 1: Create your Telegram Bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` → follow prompts
3. Save the token it gives you (your `BOT_TOKEN`)

---

## Step 2: Get your Anthropic API Key

1. Go to https://console.anthropic.com → API Keys → Create Key
2. Save it (your `ANTHROPIC_API_KEY`)

---

## Step 3: Deploy to Railway

1. Sign up at https://railway.app
2. New Project → upload all 6 files:
   - `bot.py`, `db.py`, `ai.py`, `oura.py`, `requirements.txt`, `railway.toml`
3. In Railway → Variables tab, add:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | from BotFather |
| `ANTHROPIC_API_KEY` | from Anthropic |
| `TIMEZONE` | `Asia/Singapore` |
| `SUMMARY_HOUR` | `21` (9pm) |
| `DB_PATH` | `/data/fuelbot.db` |

4. Settings → Volumes → add volume at `/data`
5. Deploy ✅

---

## Step 4: Connect your Oura Ring (optional)

1. Go to https://cloud.ouraring.com/personal-access-tokens
2. Click **Create A New Personal Access Token**
3. Message your bot: `/oura YOUR_TOKEN_HERE`
4. Use `/sync` anytime to pull today's calories burned from Oura

---

## How to use

**Log food** — just describe it naturally:
```
2 kaya toast, 2 soft boiled eggs, kopi c siew dai
nasi lemak with chicken wing
large McDonald's fries and iced milo
```

**Log a workout** — same, just describe it:
```
45 min run
1 hour gym, legs day
30 min swim
```
The bot auto-detects whether it's food or a workout.

**Commands:**
| Command | What it does |
|---------|-------------|
| `/summary` | Full day breakdown — food, workouts, net calories |
| `/sync` | Pull today's calories burned from Oura |
| `/oura <token>` | Connect your Oura ring |
| `/targets` | See your daily goals |
| `/undo` | Remove last logged meal |
| `/undoworkout` | Remove last logged workout |
| `/clear` | Wipe today's entire log |

---

## How workouts affect your budget

Burning calories adds to your daily budget:
- Daily target: **1,300 kcal**
- You log a 45 min run → bot estimates **~315 kcal burned**
- Your new budget: **1,615 kcal**
- Net calories = food eaten − burned

With Oura connected, `/sync` replaces the manual estimate with your actual Oura active calories.

---

## Your Daily Targets

| Macro | Target |
|-------|--------|
| Calories | 1,300 kcal net |
| Protein | 82g |
| Carbs | 130g |
| Fat | 45g |

*Based on: 51kg, 160cm, goal -2kg in 2 months*

---

## File structure
```
fuelbot/
├── bot.py           # Commands, message routing, daily summary scheduler
├── db.py            # SQLite — meals, workouts, users, Oura tokens
├── ai.py            # Claude API — parses food and workout descriptions
├── oura.py          # Oura Ring API integration
├── requirements.txt
└── railway.toml
```
