import json
import os
import asyncio
from datetime import datetime, date
from pyrogram.enums import ParseMode
from logger import LOGGER

LIFECYCLE_FILE = "lifecycle.json"
CHECK_INTERVAL = 86400  # check once every 24 hours


# ─── Storage ──────────────────────────────────────────────────────────────────

def load_expiry() -> str | None:
    """Read the stored expiry date string (YYYY-MM-DD), or None if not set."""
    if os.path.exists(LIFECYCLE_FILE):
        try:
            with open(LIFECYCLE_FILE) as f:
                return json.load(f).get("expiry_date")
        except Exception:
            return None
    return None


def save_expiry(date_str: str):
    """Persist the expiry date to disk."""
    with open(LIFECYCLE_FILE, "w") as f:
        json.dump({"expiry_date": date_str}, f)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_days_remaining(date_str: str) -> int | None:
    """Return the number of days until expiry (negative = already expired)."""
    try:
        expiry = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (expiry - date.today()).days
    except Exception:
        return None


def format_expiry(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    except Exception:
        return date_str


# ─── Background checker ───────────────────────────────────────────────────────

async def lifecycle_checker(bot, owner_ids: list[int]):
    """
    Runs as a background task.
    Waits 10 s after startup so the bot is fully ready, then checks once every
    24 hours. Sends a DM to every owner when ≤5 days remain (or already expired).
    """
    await asyncio.sleep(10)  # let the bot fully start before first check

    while True:
        try:
            expiry_str = load_expiry()
            if expiry_str and owner_ids:
                days_left = get_days_remaining(expiry_str)
                formatted  = format_expiry(expiry_str)

                if days_left is not None and days_left < 0:
                    for oid in owner_ids:
                        try:
                            await bot.send_message(
                                oid,
                                "🚨 <b>Server Lifecycle — EXPIRED</b>\n\n"
                                f"Your subscription expired on <b>{formatted}</b>.\n"
                                "Please renew immediately to avoid downtime.\n\n"
                                "Once renewed, update the date:\n"
                                "<code>/setexpiry YYYY-MM-DD</code>",
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception as e:
                            LOGGER(__name__).error(f"Lifecycle msg to {oid} failed: {e}")

                elif days_left is not None and days_left <= 5:
                    day_word = "day" if days_left == 1 else "days"
                    for oid in owner_ids:
                        try:
                            await bot.send_message(
                                oid,
                                "⚠️ <b>Server Lifecycle Reminder</b>\n\n"
                                f"Your subscription expires in <b>{days_left} {day_word}</b>.\n"
                                f"📅 Expiry date: <b>{formatted}</b>\n\n"
                                "Renew soon to keep the bot running without interruption.",
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception as e:
                            LOGGER(__name__).error(f"Lifecycle msg to {oid} failed: {e}")

        except Exception as e:
            LOGGER(__name__).error(f"Lifecycle checker error: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

