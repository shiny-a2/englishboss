from __future__ import annotations
import asyncio
import csv
import io
import os
from datetime import datetime, timezone
from dataclasses import dataclass

from dotenv import load_dotenv
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup)
from telegram.ext import (Application, CommandHandler, MessageHandler, CallbackQueryHandler,
                          ContextTypes, filters)
from rapidfuzz import fuzz
from openai import OpenAI

import db
from srs import schedule_next

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEFAULT_TZ = os.getenv("DEFAULT_TIMEZONE", "America/Chicago")

client = OpenAI(api_key=OPENAI_API_KEY)

# --- UI helpers ---
HOME_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]])

def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📚 Vocabulary", callback_data="menu_vocab"),
         InlineKeyboardButton("🧩 Grammar", callback_data="menu_grammar")],
        [InlineKeyboardButton("🎧 Listening", callback_data="menu_listening"),
         InlineKeyboardButton("🎙️ Voice ↔ Translate", callback_data="menu_voice")],
        [InlineKeyboardButton("🗓️ Review (SRS)", callback_data="menu_review")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")]
    ]
    return InlineKeyboardMarkup(rows)

# --- Session state ---
from typing import List
from typing import Dict
@dataclass
class QuizItem:
    word_id: int
    prompt: str
    expected: List[str]
    direction: str  # "fa2en" or "en2fa"

user_sessions: Dict[int, QuizItem] = {}

# --- OpenAI helpers ---
async def transcribe_audio_bytes(b: bytes, filename: str = "audio.ogg") -> str:
    # Uses Audio API: gpt-4o-transcribe or whisper-1
    file_obj = (filename, b)
    transcript = client.audio.transcriptions.create(
        model="gpt-4o-transcribe",
        file=file_obj,
    )
    return transcript.text.strip()

async def translate_text(text: str, target_lang: str = "en") -> str:
    with open("prompts/translate_system.md", "r", encoding="utf-8") as f:
        system_prompt = f.read()
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Translate to {target_lang}:\n{text}"}
    ]
    resp = client.chat.completions.create(model="gpt-4o-mini", messages=msgs)
    return resp.choices[0].message.content.strip()

# --- Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.init_db()
    db.upsert_user(user.id, user.username, DEFAULT_TZ)
    await update.message.reply_text(
        f"سلام {user.first_name or ''}! Welcome to English Boss.\nChoose a section:",
        reply_markup=main_menu()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Use /start for the main menu. Send a voice in *Voice ↔ Translate*.\n"
        "To import your own CSV, send the file and reply with `#import`.\n"
        "Use the *Review (SRS)* section for spaced repetition.",
        parse_mode="Markdown"
    )

async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "home":
        await q.edit_message_text("Home", reply_markup=main_menu())
        return
    if data == "menu_voice":
        await q.edit_message_text(
            "Send a *voice message* (Persian or English). I’ll transcribe and translate.",
            reply_markup=HOME_KB, parse_mode="Markdown")
        return
    if data == "menu_review":
        await start_review(update, context, q.message.chat_id)
        return
    if data == "menu_vocab":
        await q.edit_message_text(
            "Vocabulary deck: Use /import_sample or upload CSV then reply `#import`.\nThen go to *Review (SRS)*.",
            reply_markup=HOME_KB, parse_mode="Markdown")
        return
    if data in ("menu_grammar", "menu_listening", "menu_settings"):
        await q.edit_message_text("Coming soon — after MVP. Use Vocabulary + SRS for now.", reply_markup=HOME_KB)
        return

async def start_review(update: Update | None, context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None) -> None:
    user_id = update.effective_user.id if update else chat_id
    due = db.get_due_words(user_id, limit=1)
    if not due:
        target = update.callback_query.message if update and update.callback_query else None
        if target:
            await target.edit_text("Nothing due now. Import sample with /import_sample.", reply_markup=HOME_KB)
        else:
            await context.bot.send_message(chat_id=user_id, text="Nothing due now. Import sample with /import_sample.", reply_markup=HOME_KB)
        return
    row = due[0]
    direction = "fa2en"
    prompt = f"معنی انگلیسیِ: {row['fa']}"
    expected = [e.strip().lower() for e in ([row['en']] + ((row['synonyms'] or '').split(';') if row['synonyms'] else []))]
    user_sessions[user_id] = QuizItem(word_id=row['word_id'], prompt=prompt, expected=expected, direction=direction)
    await context.bot.send_message(chat_id=user_id, text=f"{prompt}", reply_markup=HOME_KB)

async def on_text_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if update.message.text == "#import":
        await import_last_csv(update, context)
        return
    if user_id not in user_sessions:
        return
    item = user_sessions[user_id]
    answer = (update.message.text or "").strip().lower()
    score = max(fuzz.ratio(answer, exp) for exp in item.expected) if item.expected else 0
    success = score >= 80
    current_box = db.get_user_word_box(user_id, item.word_id)
    outcome = schedule_next(current_box, success)
    db.update_review(user_id, item.word_id, outcome.new_box, outcome.next_due.isoformat(), success)

    if success:
        await update.message.reply_text(f"✅ Correct ({score}%). Next box → {outcome.new_box}")
    else:
        exp_show = ', '.join(dict.fromkeys(item.expected))
        await update.message.reply_text(f"❌ Not quite ({score}%). Answer: {exp_show}. Box reset → 1")
    user_sessions.pop(user_id, None)
    await start_review(None, context, chat_id=user_id)

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    v = update.message.voice or update.message.audio
    if not v:
        return
    f = await context.bot.get_file(v.file_id)
    bio = await f.download_as_bytearray()
    text = await transcribe_audio_bytes(bytes(bio), filename="voice.ogg")
    has_persian = any('\u0600' <= ch <= '\u06FF' for ch in text)
    target = "en" if has_persian else "fa"
    translated = await translate_text(text, target_lang=target)
    await update.message.reply_text(f"📝 {text}\n\n🌐 {translated}", reply_markup=HOME_KB)

# --- Import helpers ---
async def import_last_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("Reply to a CSV file with the text `#import`.")
        return
    doc = update.message.reply_to_message.document
    if not doc.file_name.lower().endswith('.csv'):
        await update.message.reply_text("Please attach a .csv file.")
        return
    file = await context.bot.get_file(doc.file_id)
    data = await file.download_as_bytearray()
    reader = csv.DictReader(io.StringIO(bytes(data).decode('utf-8')))
    count = 0
    for row in reader:
        wid = db.insert_word(row)
        db.ensure_user_word(update.effective_user.id, wid, datetime.now(timezone.utc).isoformat())
        count += 1
    await update.message.reply_text(f"Imported {count} words. Go to Review (SRS).", reply_markup=HOME_KB)

async def import_sample(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    path = os.path.join("datasets", "cefr_vocab_en_fa_sample.csv")
    if not os.path.exists(path):
        await update.message.reply_text("Sample dataset missing.")
        return
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        for row in reader:
            wid = db.insert_word(row)
            db.ensure_user_word(update.effective_user.id, wid, datetime.now(timezone.utc).isoformat())
            count += 1
    await update.message.reply_text(f"Imported {count} words. Open Review (SRS).", reply_markup=HOME_KB)

# --- App entry ---
async def run() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    db.init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("import_sample", import_sample))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_reply))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))

    print("Bot is running…")
    await app.run_polling(close_loop=False)

if __name__ == "__main__":
    asyncio.run(run())
