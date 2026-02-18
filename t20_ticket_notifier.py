import os
import time
import re
import requests
from bs4 import BeautifulSoup
from telegram import Bot

# Config (set these as environment variables for safety)
BOOKMYSHOW_MATCH_URL = os.getenv("MATCH_URL",
    "https://in.bookmyshow.com/sports/super-8-match-8-icc-men-s-t20-wc-2026/ET00474264")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "<your-telegram-bot-token>")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "<your-chat-id>")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "180"))  # 3 minutes default

bot = Bot(token=TELEGRAM_TOKEN)

def fetch_static(url):
    """Try a simple GET and parse HTML for availability keywords."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TicketNotifier/1.0; +https://example.com/bot)"
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.text

def parse_availability_from_html(html):
    """Return True if 'buy' or 'available' appears, False if 'coming soon' or 'sold out'."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator=" ").lower()
    # keywords to signal availability (tweak if you see different wording)
    if re.search(r"\b(buy|book tickets|tickets available|available for booking|filling fast)\b", text):
        return True
    if re.search(r"\b(coming soon|sold out|register for alerts)\b"))
        return False
    # fallback: if page mentions "Login to book" or ticket prices, treat as available-ish
    if "login to book" in text or re.search(r"\b(₹|rs|lkr|usd)\b", text):
        return True
    return False

def notify_available(url):
    message = f"🎟️ Match 8 (Super 8) — Ticket availability changed!\nCheck here: {url}"
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

def main():
    print("Starting notifier for Match 8:", BOOKMYSHOW_MATCH_URL)
    last_state = None
    while True:
        try:
            html = fetch_static(BOOKMYSHOW_MATCH_URL)
            available = parse_availability_from_html(html)
        except Exception as e:
            print("Fetch/parse error:", e)
            available = None

        if available is not None and available != last_state:
            last_state = available
            state_text = "AVAILABLE" if available else "NOT AVAILABLE"
            print(time.strftime("%Y-%m-%d %H:%M:%S"), state_text)
            if available:
                notify_available(BOOKMYSHOW_MATCH_URL)

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()