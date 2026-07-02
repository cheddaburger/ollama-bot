# Ollama Telegram Bot

A private Telegram bot that runs a local LLM via [Ollama](https://ollama.com) on a home Linux server. It supports multi-turn conversation, automatic web search for real-time questions, scheduled morning briefings, and reminders — all through Telegram on your phone.

## Features

- **Local LLM chat** — powered by Ollama (default: `phi3:mini`), no cloud API needed
- **Smart web search** — automatically searches DuckDuckGo when your message contains time-sensitive keywords (news, weather, prices, scores, etc.)
- **Conversation history** — maintains per-user context across messages
- **Morning briefing** — daily scheduled message with top news headlines and local weather, summarized by the LLM
- **Reminders** — set one-off reminders with flexible time syntax
- **Private by design** — only responds to a single authorized Telegram user ID
- **Runs as a systemd service** — auto-starts on boot and restarts on failure

## Commands

| Command | Description |
|---|---|
| `/start` | Show help and confirm the bot is running |
| `/reset` | Clear conversation history |
| `/search <query>` | Force a web search and return raw results |
| `/remind <time> <message>` | Set a reminder (e.g. `/remind 30m check the oven`) |
| `/briefing` | Trigger the morning briefing on demand |

**Reminder time format:** `1h30m`, `45m`, `2h`, `90s` — any combination of hours, minutes, and seconds.

## Tech Stack

- **Python 3.11+**
- [`python-telegram-bot`](https://github.com/python-telegram-bot/python-telegram-bot) — Telegram Bot API wrapper with job queue
- [`requests`](https://docs.python-requests.org/) — Ollama HTTP API calls
- [`ddgs`](https://github.com/deedy5/ddgs) — privacy-respecting web search
- **Ollama** — local LLM inference server

## Setup

### Prerequisites

- A Linux machine with [Ollama](https://ollama.com) installed and a model pulled (e.g. `ollama pull phi3:mini`)
- A [Telegram bot token](https://core.telegram.org/bots/tutorial#getting-ready) from @BotFather
- Your Telegram user ID (message @userinfobot to get it)

### Installation

1. Clone the repo and install dependencies:

```bash
git clone https://github.com/your-username/ollama-bot.git
cd ollama-bot
pip install "python-telegram-bot[job-queue]" requests ddgs
```

2. Create a `.env` file:

```env
TELEGRAM_TOKEN=your_bot_token_here
ALLOWED_USER_ID=123456789
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=phi3:mini
BRIEFING_TIME=07:00
BRIEFING_CITY=New York
TIMEZONE=America/New_York
```

3. Run the bot:

```bash
python3 bot.py
```

### Run as a systemd Service (Linux)

Copy the service file and enable it to run on boot:

```bash
sudo cp ollama-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ollama-bot
```

Check status:

```bash
sudo systemctl status ollama-bot
journalctl -u ollama-bot -f
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | required | Bot token from @BotFather |
| `ALLOWED_USER_ID` | required | Your Telegram user ID (bot is private) |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `phi3:mini` | Model name to use for inference |
| `BRIEFING_TIME` | `07:00` | Daily briefing time (24h format) |
| `BRIEFING_CITY` | *(empty)* | City name appended to weather search |
| `TIMEZONE` | `UTC` | IANA timezone for the briefing schedule |

## How It Works

1. You send a message to the bot on Telegram.
2. The bot checks if the message contains time-sensitive keywords. If so, it silently runs a DuckDuckGo search and appends the results as context.
3. The augmented message is sent to Ollama's `/api/chat` endpoint along with the conversation history.
4. The LLM reply is sent back to you. Only your original message (without search results) is stored in history to keep context clean.

Each morning at the configured time, the bot fetches news headlines and a weather forecast, summarizes them with the LLM, and pushes the briefing to your chat.

## License

MIT
