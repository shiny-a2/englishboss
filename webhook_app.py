import os, json, time, requests
from flask import Flask, request, jsonify
from datetime import datetime, timezone
import db
from srs import schedule_next

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)
db.init_db()

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    requests.post(f"{API}/sendMessage", data=payload, timeout=15)

def home_kb():
    return {"inline_keyboard": [[{"text": "🏠 Home", "callback_data": "home"}]]}

def main_menu_kb():
    return {"inline_keyboard": [
        [{"text": "📚 Vocabulary", "callback_data": "menu_vocab"},
         {"text": "🧩 Grammar", "callback_data": "menu_grammar"}],
        [{"text": "🎧 Listening", "callback_data": "menu_listening"},
         {"text": "🎙️ Voice ↔ Translate", "callback_data": "menu_voice"}],
        [{"text": "🗓️ Review (SRS)", "callback_data": "menu_review"}],
        [{"text": "⚙️ Settings", "callback_data": "menu_settings"}]
    ]}

@app.route("/webhook/" + (BOT_TOKEN or "no-token"), methods=["POST"])
def webhook():
    upd = request.get_json(force=True, silent=True) or {}
    # Callback query
    if "callback_query" in upd:
        cq = upd["callback_query"]
        data = cq.get("data")
        chat_id = cq["message"]["chat"]["id"]
        if data == "home":
            requests.post(f"{API}/editMessageText", data={
                "chat_id": chat_id,
                "message_id": cq["message"]["message_id"],
                "text": "Home",
                "reply_markup": json.dumps(main_menu_kb())
            }, timeout=15)
            return jsonify(ok=True)
        if data == "menu_voice":
            requests.post(f"{API}/editMessageText", data={
                "chat_id": chat_id, "message_id": cq["message"]["message_id"],
                "text": "Send a voice message (FA/EN). I’ll transcribe and translate.",
                "reply_markup": json.dumps(home_kb())
            }, timeout=15)
            return jsonify(ok=True)
        if data == "menu_vocab":
            requests.post(f"{API}/editMessageText", data={
                "chat_id": chat_id, "message_id": cq["message"]["message_id"],
                "text": "Upload CSV then reply #import, or use /import_sample.",
                "reply_markup": json.dumps(home_kb())
            }, timeout=15)
            return jsonify(ok=True)
        if data == "menu_review":
            # Trigger review by sending /review command (not implemented as command; we can send hint)
            send_message(chat_id, "For webhook MVP, send any text to continue review flow (TBD).", reply_markup=home_kb())
            return jsonify(ok=True)
        requests.post(f"{API}/answerCallbackQuery", data={"callback_query_id": cq["id"]}, timeout=15)
        return jsonify(ok=True)

    msg = upd.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    user = msg.get("from", {})
    if not chat_id:
        return jsonify(ok=True)

    if "text" in msg and msg["text"].startswith("/start"):
        db.upsert_user(user.get("id"), user.get("username"))
        send_message(chat_id, "Welcome to English Boss. Choose a section:", reply_markup=main_menu_kb())
        return jsonify(ok=True)

    # Simple echo for now; full SRS via webhook can be added similarly to main.py
    if "text" in msg:
        txt = msg["text"]
        if txt == "#import":
            send_message(chat_id, "CSV import via webhook demo not implemented in this minimal app.", reply_markup=home_kb())
        else:
            send_message(chat_id, f"You said: {txt}", reply_markup=home_kb())
        return jsonify(ok=True)

    # Voice handling (download file → transcribe → translate)
    if "voice" in msg:
        file_id = msg["voice"]["file_id"]
        # getFile
        r = requests.get(f"{API}/getFile", params={"file_id": file_id}, timeout=15).json()
        file_path = r.get("result", {}).get("file_path", "")
        if not file_path:
            send_message(chat_id, "Cannot fetch voice file.", reply_markup=home_kb()); return jsonify(ok=True)
        audio_bytes = requests.get(f"{FILE_API}/{file_path}", timeout=30).content
        transcript = client.audio.transcriptions.create(model="gpt-4o-transcribe", file=("voice.ogg", audio_bytes)).text.strip()
        has_fa = any('\u0600' <= ch <= '\u06FF' for ch in transcript)
        target = "en" if has_fa else "fa"
        tr = client.chat.completions.create(model="gpt-4o-mini", messages=[
            {"role":"system","content":"Translate between Persian and English naturally."},
            {"role":"user","content":f"Translate to {target} :\n{transcript}"}
        ]).choices[0].message.content.strip()
        send_message(chat_id, f"📝 {transcript}\n\n🌐 {tr}", reply_markup=home_kb())
        return jsonify(ok=True)

    return jsonify(ok=True)

# Passenger needs 'application'
application = app
