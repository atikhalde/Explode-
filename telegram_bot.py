#!/usr/bin/env python3
"""
telegram_bot.py - Telegram delivery + alert de-duplication state.
Reads TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from env (GitHub Secrets).
If creds are missing -> dry-run mode: messages are printed, not sent.
"""
import json, os
from pathlib import Path
import requests

STATE_PATH = Path(__file__).parent / "state" / "alerts_state.json"

def _creds():
    return os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")

def send(text, parse_html=True):
    token, chat = _creds()
    if not token or not chat:
        print("\n--- [DRY-RUN] telegram message ---")
        print(text)
        print("----------------------------------\n")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json=dict(chat_id=chat, text=text[:4000],
                                    parse_mode="HTML" if parse_html else None,
                                    disable_web_page_preview=True), timeout=15)
        if r.status_code != 200:
            print(f"[telegram] HTTP {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        print(f"[telegram] error: {e}")
        return False

def load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}

def save_state(st):
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=0))

def already_alerted(st, symbol, bar_date, score, realert_delta=10):
    """Dedupe: one alert per symbol per day; re-alert only if score jumped +10."""
    prev = st.get(symbol)
    if not prev or prev.get("date") != bar_date:
        return False
    return score < prev.get("score", 0) + realert_delta

def mark_alerted(st, symbol, bar_date, score):
    st[symbol] = {"date": bar_date, "score": score}
