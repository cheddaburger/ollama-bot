#!/usr/bin/env python3
import os
import asyncio
import requests
import logging
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo
import re
from ddgs import DDGS
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3:mini")
BRIEFING_TIME_STR = os.environ.get("BRIEFING_TIME", "07:00")
BRIEFING_CITY = os.environ.get("BRIEFING_CITY", "")
TIMEZONE = os.environ.get("TIMEZONE", "UTC")

_bh, _bm = map(int, BRIEFING_TIME_STR.split(":"))
TZ = ZoneInfo(TIMEZONE)

SYSTEM_PROMPT = (
    "You are a concise, helpful assistant running on a home Linux server. "
    "Keep responses short and clear since they're read on a phone. "
    "When you receive web search results as context, use them to answer accurately. "
    "If search results are provided, cite them briefly."
)

SEARCH_KEYWORDS = (
    "today", "tonight", "current", "latest", "news", "weather", "price",
    "score", "game", "right now", "this week", "recently", "2025", "2026",
    "who won", "what happened", "is there", "how much is",
)

history: dict[int, list[dict]] = {}


def needs_search(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in SEARCH_KEYWORDS)


def web_search(query: str, max_results: int = 4) -> str:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return ""
        return "\n".join(f"- {r['title']}: {r['body']}" for r in results)
    except Exception as e:
        logger.warning("Search failed: %s", e)
        return ""


def ollama_complete(messages: list[dict]) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "stream": False,
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=None)
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except Exception as e:
        logger.error("Ollama error: %s", e)
        return f"Error contacting Ollama: {e}"


def query_ollama(user_id: int, user_message: str) -> str:
    if user_id not in history:
        history[user_id] = []

    augmented_message = user_message
    if needs_search(user_message):
        logger.info("Searching web for: %s", user_message[:60])
        search_results = web_search(user_message)
        if search_results:
            augmented_message = (
                f"{user_message}\n\n[Web search results]\n{search_results}"
            )

    history[user_id].append({"role": "user", "content": augmented_message})
    reply = ollama_complete(history[user_id])
    history[user_id][-1] = {"role": "user", "content": user_message}
    history[user_id].append({"role": "assistant", "content": reply})
    return reply


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("Unauthorized.")
        return

    user_text = update.message.text
    logger.info("User %d: %s", user_id, user_text[:80])

    loop = asyncio.get_running_loop()

    async def keep_typing():
        while True:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            await asyncio.sleep(4)

    typing_task = asyncio.create_task(keep_typing())
    try:
        reply = await loop.run_in_executor(None, query_ollama, user_id, user_text)
    finally:
        typing_task.cancel()
        await asyncio.gather(typing_task, return_exceptions=True)

    await update.message.reply_text(reply)


def parse_remind_delta(time_str: str) -> timedelta | None:
    m = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', time_str.lower())
    if not m or not any(m.groups()):
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    delta = timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return delta if delta.total_seconds() > 0 else None


async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return

    args = context.args or []
    delta = parse_remind_delta(args[0]) if args else None
    message = " ".join(args[1:]) if len(args) > 1 else ""

    if delta is None or not message:
        await update.message.reply_text(
            "Usage: /remind <time> <message>\n"
            "Examples:\n"
            "  /remind 30m check the laundry\n"
            "  /remind 2h take meds\n"
            "  /remind 1h30m meeting prep"
        )
        return

    chat_id = update.effective_chat.id

    async def fire(ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await ctx.bot.send_message(chat_id=chat_id, text=f"Reminder: {message}")

    context.job_queue.run_once(fire, delta)

    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s:
        parts.append(f"{s}s")
    await update.message.reply_text(f"Reminder set for {' '.join(parts)}: {message}")


async def morning_briefing(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Running morning briefing")

    city_suffix = f" {BRIEFING_CITY}" if BRIEFING_CITY else ""
    queries = [
        "top news headlines today",
        f"weather forecast{city_suffix} today",
    ]

    parts = []
    for q in queries:
        result = web_search(q, max_results=3)
        if result:
            parts.append(result)

    if not parts:
        await context.bot.send_message(
            chat_id=ALLOWED_USER_ID,
            text="Morning briefing: couldn't fetch results today."
        )
        return

    combined = "\n\n".join(parts)
    prompt = (
        f"Give me a short morning briefing based on these search results. "
        f"Top news and weather only. 5-8 bullet points max.\n\n{combined}"
    )

    loop = asyncio.get_running_loop()
    briefing = await loop.run_in_executor(None, ollama_complete, [{"role": "user", "content": prompt}])

    now = datetime.now(TZ)
    header = f"Good morning! Briefing for {now.strftime('%A, %B %d')}:\n\n"
    await context.bot.send_message(chat_id=ALLOWED_USER_ID, text=header + briefing)


async def cmd_briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await morning_briefing(context)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    history.pop(user_id, None)
    await update.message.reply_text("Conversation history cleared.")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /search <your query>")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    results = web_search(query, max_results=5)
    if results:
        await update.message.reply_text(f"Results for: {query}\n\n{results}")
    else:
        await update.message.reply_text("No results found.")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text(
        f"Ollama ({OLLAMA_MODEL}) is ready. Just send a message.\n\n"
        "/reset — clear conversation history\n"
        "/search <query> — force a web search\n"
        "/remind <time> <msg> — set a reminder (e.g. /remind 30m check oven)\n"
        "/briefing — get your morning briefing now"
    )


def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("remind", cmd_remind))
    app.add_handler(CommandHandler("briefing", cmd_briefing))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_daily(
        morning_briefing,
        time=dtime(hour=_bh, minute=_bm, tzinfo=TZ),
    )

    logger.info("Bot started — polling Telegram...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
