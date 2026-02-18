import os
import time
import re
import threading
import requests
from bs4 import BeautifulSoup
from telegram import Bot, Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

BOOKMYSHOW_MATCH_URL = os.getenv("MATCH_URL", "https://in.bookmyshow.com/sports/super-8-match-8-icc-men-s-t20-wc-2026/ET00474264")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "<your-telegram-bot-token>")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", 0))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "180"))

CURRENT_EVENT_URL = BOOKMYSHOW_MATCH_URL
CURRENT_EVENT_STATE = None
bot_running = True

def fetch_static(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TicketNotifier/2.0; +https://example.com/bot)"
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.text

def parse_event_info(html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else "Event"
    text = soup.get_text(separator=" ").lower()
    # Prices if present
    price_match = re.search(r'(₹|rs|lkr|usd) ?[0-9,.]+', soup.get_text())
    price = price_match.group(0) if price_match else None
    # Detect availability and describe status
    if re.search(r"\b(buy|book tickets|tickets available|available for booking|filling fast)\b", text):
        status = "Available"
        status_emoji = "✅"
        available = True
    elif re.search(r"\b(coming soon|not yet open|register for alerts)\b", text):
        status = "Coming Soon"
        status_emoji = "⏳"
        available = False
    elif re.search(r"\b(sold out|no tickets)\b", text):
        status = "Sold Out"
        status_emoji = "❌"
        available = False
    else:
        # fallback
        status = "Unknown"
        status_emoji = "❔"
        available = False
    return {
        "title": title,
        "available": available,
        "status": status,
        "status_emoji": status_emoji,
        "link": CURRENT_EVENT_URL,
        "price": price
    }

def notify_status(context: CallbackContext, info, just_found=False):
    if info["available"]:
        message = (
            f"🎟️ <b>Tickets FOUND — Available to book!</b>\n"
            f"<b>Event:</b> {info['title']}\n"
            f"<b>Status:</b> {info['status']} {info['status_emoji']}\n"
            + (f"<b>Price:</b> {info['price']}\n" if info['price'] else "")
            f"<a href=\"{info['link']}\">Book Now</a>\n"
            "More info: Tickets are available on BookMyShow."
        )
    else:
        message = (
            "🚫 <b>No tickets found / Coming soon</b>\n"
            f"<b>Event:</b> {info['title']}\n"
            f"<b>Status:</b> {info['status']} {info['status_emoji']}\n"
            + (f"<b>Price:</b> {info['price']}\n" if info['price'] else "")
            f"<a href=\"{info['link']}\">Check here</a>\n"
            f"More info: {'Event not yet open or sold out.' if info['status'] != 'Unknown' else 'Event not found.'}"
        )
    if just_found or not info["available"]:
        context.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode=ParseMode.HTML, disable_web_page_preview=False
        )

def check_event_loop(context: CallbackContext):
    global CURRENT_EVENT_URL, bot_running, CURRENT_EVENT_STATE
    while bot_running:
        try:
            html = fetch_static(CURRENT_EVENT_URL)
            info = parse_event_info(html)
            available = info["available"]
        except Exception as e:
            print("Fetch/parse error:", e)
            info = {"title": "Event", "available": False, "status": "Unknown", "status_emoji": "❔", "link": CURRENT_EVENT_URL, "price": None}
            available = False

        # Only notify on state change
        if available != CURRENT_EVENT_STATE:
            CURRENT_EVENT_STATE = available
            notify_status(context, info, just_found=True)
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
            "title": "Event", "available": False, "status": "Unknown", "status_emoji": "❔",
            "link": CURRENT_EVENT_URL, "price": None
        }
    notify_status(context, info, just_found=False)

def change_event(update: Update, context: CallbackContext):
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    update.message.reply_text(
        "Please send the new BookMyShow event URL in your next message. Send /cancel to abort."
    )
    context.user_data["awaiting_url"] = True

def receive_message(update: Update, context: CallbackContext):
    if update.effective_chat.id != TELEGRAM_CHAT_ID:
        return
    if context.user_data.get("awaiting_url", False):
        url = update.message.text.strip()
        if url.lower().startswith("http"):
            global CURRENT_EVENT_URL, CURRENT_EVENT_STATE
            CURRENT_EVENT_URL = url
            CURRENT_EVENT_STATE = None  # Reset so notification triggers on new event
            context.user_data["awaiting_url"] = False
            update.message.reply_text(f"✅ Event updated! Now watching:\n{url}")
        else:
            update.message.reply_text("❌ Invalid URL. Please send a valid BookMyShow event link.")

def cancel(update: Update, context: CallbackContext):
    if update.effective_chat.id == TELEGRAM_CHAT_ID:
        context.user_data["awaiting_url"] = False
        update.message.reply_text("URL change canceled.")

def main():
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("status", status))
    dispatcher.add_handler(CommandHandler("change_event", change_event))
    dispatcher.add_handler(CommandHandler("cancel", cancel))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, receive_message))

    context = updater.job_queue._dispatcher
    thread = threading.Thread(target=check_event_loop, args=(context,), daemon=True)
    thread.start()

    print(f"Bot running! Watching: {CURRENT_EVENT_URL}")
    updater.start_polling()
    updater.idle()
    global bot_running
    bot_running = False

if __name__ == "__main__":
    main()