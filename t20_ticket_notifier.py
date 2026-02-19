import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler, MessageHandler, Updater, filters

BOOKMYSHOW_MATCH_URL = os.getenv(
    "MATCH_URL",
    "https://in.bookmyshow.com/sports/super-8-match-8-icc-men-s-t20-wc-2026/ET00474264",
)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
POLL_INTERVAL = max(20, int(os.getenv("POLL_INTERVAL_SECONDS", "120")))
PORT = int(os.getenv("PORT", "8080"))

CURRENT_EVENT_URL = BOOKMYSHOW_MATCH_URL
CURRENT_EVENT_STATE = None
BOT_RUNNING = True

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TicketNotifier/3.0; +https://railway.app)",
    "Accept-Language": "en-US,en;q=0.9",
}
SESSION = requests.Session()
SESSION.headers.update(REQUEST_HEADERS)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/ready"):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Health server listening on 0.0.0.0:{PORT}")
    server.serve_forever()


def fetch_static(url: str) -> str:
    response = SESSION.get(url, timeout=12)
    response.raise_for_status()
    return response.text


def parse_event_info(html: str):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else "Event"
    full_text = soup.get_text(separator=" ")
    text = full_text.lower()

    price_match = re.search(r"(₹|rs|lkr|usd)\s?[0-9,.]+", full_text, re.IGNORECASE)
    price = price_match.group(0) if price_match else None

    if re.search(r"\b(buy|book tickets|tickets available|available for booking|filling fast)\b", text):
        status, emoji, available = "Available", "✅", True
    elif re.search(r"\b(coming soon|not yet open|register for alerts)\b", text):
        status, emoji, available = "Coming Soon", "⏳", False
    elif re.search(r"\b(sold out|no tickets)\b", text):
        status, emoji, available = "Sold Out", "❌", False
    else:
        status, emoji, available = "Unknown", "❔", False

    return {
        "title": title,
        "available": available,
        "status": status,
        "status_emoji": emoji,
        "link": CURRENT_EVENT_URL,
        "price": price,
    }


def format_status_message(info, force_alert=False):
    price_line = f"<b>Price:</b> {info['price']}\n" if info["price"] else ""

    if info["available"]:
        message = (
            "🎟️ <b>Tickets FOUND — Available to book!</b>\n"
            f"<b>Event:</b> {info['title']}\n"
            f"<b>Status:</b> {info['status']} {info['status_emoji']}\n"
            f"{price_line}"
            f"<a href=\"{info['link']}\">Book Now</a>"
        )
        should_send = True
    else:
        message = (
            "🚫 <b>No tickets found / Coming soon</b>\n"
            f"<b>Event:</b> {info['title']}\n"
            f"<b>Status:</b> {info['status']} {info['status_emoji']}\n"
            f"{price_line}"
            f"<a href=\"{info['link']}\">Check here</a>"
        )
        should_send = force_alert

    return should_send, message


def notify_status(context: CallbackContext, info, force_alert=False):
    should_send, message = format_status_message(info, force_alert=force_alert)
    if not should_send:
        return
    context.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


def check_event_loop(context: CallbackContext):
    global CURRENT_EVENT_STATE, BOT_RUNNING

    while BOT_RUNNING:
        try:
            html = fetch_static(CURRENT_EVENT_URL)
            info = parse_event_info(html)
        except Exception as exc:
            print(f"Fetch/parse error: {exc}")
            info = {
                "title": "Event",
                "available": False,
                "status": "Unknown",
                "status_emoji": "❔",
                "link": CURRENT_EVENT_URL,
                "price": None,
            }

        available = info["available"]
        if available != CURRENT_EVENT_STATE:
            CURRENT_EVENT_STATE = available
            notify_status(context, info, force_alert=True)

        time.sleep(POLL_INTERVAL)


def start(update: Update, context: CallbackContext):
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        update.message.reply_text("Sorry, you are not authorized to control this bot.")
        return

    update.message.reply_text(
        "Welcome! 🔔 I will notify when tickets are available.\n"
        f"Currently watching:\n{CURRENT_EVENT_URL}\n\n"
        "Commands:\n"
        "/change_event - Change the event link\n"
        "/status - Show current event status"
    )


def status(update: Update, context: CallbackContext):
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    try:
        html = fetch_static(CURRENT_EVENT_URL)
        info = parse_event_info(html)
    except Exception:
        info = {
            "title": "Event",
            "available": False,
            "status": "Unknown",
            "status_emoji": "❔",
            "link": CURRENT_EVENT_URL,
            "price": None,
        }
    notify_status(context, info, force_alert=True)


def change_event(update: Update, context: CallbackContext):
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    context.user_data["awaiting_url"] = True
    update.message.reply_text(
        "Please send the new BookMyShow event URL in your next message. Send /cancel to abort."
    )


def receive_message(update: Update, context: CallbackContext):
    global CURRENT_EVENT_URL, CURRENT_EVENT_STATE

    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return

    if context.user_data.get("awaiting_url", False):
        url = update.message.text.strip()
        if url.lower().startswith("http"):
            CURRENT_EVENT_URL = url
            CURRENT_EVENT_STATE = None
            context.user_data["awaiting_url"] = False
            update.message.reply_text(f"✅ Event updated! Now watching:\n{url}")
        else:
            update.message.reply_text("❌ Invalid URL. Please send a valid BookMyShow event link.")


def cancel(update: Update, context: CallbackContext):
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    context.user_data["awaiting_url"] = False
    update.message.reply_text("URL change canceled.")


def run_bot_once():
    global BOT_RUNNING

    if not TELEGRAM_TOKEN or TELEGRAM_CHAT_ID == 0:
        raise ValueError("Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID environment variables.")

    BOT_RUNNING = True
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("status", status))
    dispatcher.add_handler(CommandHandler("change_event", change_event))
    dispatcher.add_handler(CommandHandler("cancel", cancel))
    dispatcher.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message))

    thread = threading.Thread(target=check_event_loop, args=(dispatcher,), daemon=True)
    thread.start()

    print(f"Bot running! Watching: {CURRENT_EVENT_URL}")
    updater.start_polling(drop_pending_updates=True)
    updater.idle()


def run_bot_forever():
    while True:
        try:
            run_bot_once()
        except Exception as exc:
            print(f"Bot crashed: {exc}. Restarting in 10s.")
            time.sleep(10)


if __name__ == "__main__":
    threading.Thread(target=run_bot_forever, daemon=True).start()
    try:
        start_health_server()
    finally:
        BOT_RUNNING = False
        SESSION.close()
