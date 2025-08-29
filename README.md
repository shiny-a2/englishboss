# English Boss — Telegram Bot (MVP)
A scalable language‑learning bot with:
- **SRS (Leitner)** vocabulary reviews (FA⇄EN) up to C2
- **Voice → Text → Translate** via OpenAI Audio + Chat
- Import from CSV
- Inline menus with **Home/Back** everywhere

## Quick start
1) Create a Telegram bot via **@BotFather** → get the token
2) Copy `.env.example` to `.env` and fill values
3) Python 3.10+:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```
4) In the bot: `/start` → **Vocabulary** → **Review (SRS)**
5) If empty, run `/import_sample` to seed a small CEFR deck

### Commands
- `/start` – main menu
- `/help` – quick help
- `/import_sample` – import ~40 demo words (A1–B1)
- Upload a **CSV** to import (headers below) and reply: `#import`

### CSV format (datasets/cefr_vocab_en_fa_sample.csv)
```csv
level,en,fa,pos,synonyms,examples
A1,book,کتاب,noun,volume;work,"This is a good book.|این یک کتاب خوب است."
A1,go,رفتن,verb,move;travel,"I go to school.|من به مدرسه می‌روم."
```
- `synonyms`: semicolon‑separated; `examples`: pairs separated by `|`

### SRS boxes & intervals
Boxes: 1→5 with intervals **0d, 1d, 3d, 7d, 14d** (configurable in `srs.py`).

---

## Deploy notes (shared cPanel)
Shared cPanel isn't ideal for long‑running bots (polling). Use **webhook** mode with a small Flask app:
- Create a Python App (Passenger) in cPanel → Python 3.10+
- Upload this project, install `requirements.txt` in the app's virtualenv
- Set `passenger_wsgi.py` (provided) to expose `application`
- Set your webhook to: `https://YOUR_DOMAIN/YOUR_APP_PATH/webhook/TELEGRAM_BOT_TOKEN`
  (use `/setWebhook` via Telegram API)
- Caveats: on some shared hosts apps sleep when idle; ensure outbound HTTPS is allowed to `api.telegram.org` and OpenAI.

See `webhook_app.py` + `passenger_wsgi.py` for a minimal webhook receiver
that reuses the same database and SRS logic.
