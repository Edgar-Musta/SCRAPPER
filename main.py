import os
import shutil
import psutil
import asyncio
import re
from datetime import datetime
from time import time
from pyrogram.enums import ParseMode
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import PhoneCodeInvalid, PhoneCodeExpired

from config import PyroConf
from logger import LOGGER

from helpers.files import get_readable_file_size, get_readable_time
from helpers.msg import getChatMsgID, get_parsed_msg, apply_caption_rules, is_private_link
from helpers.jobs import execute_batch, execute_autoforward, handle_download, track_task, get_running_tasks
from helpers.keyboards import get_start_keyboard, get_caption_keyboard, get_filter_keyboard
from helpers.lifecycle import load_expiry, save_expiry, get_days_remaining, format_expiry, lifecycle_checker
from helpers.auth import (
    start_saved_clients, stop_all_clients,
    get_user_client, start_login_flow,
    process_phone, process_code, process_password,
    cancel_login, logout_user, is_logging_in, get_login_state,
)

bot = Client(
    "media_bot",
    api_id=PyroConf.API_ID,
    api_hash=PyroConf.API_HASH,
    bot_token=PyroConf.BOT_TOKEN,
    workers=100,
    parse_mode=ParseMode.HTML,
    max_concurrent_transmissions=PyroConf.MAX_CONCURRENT_TRANSMISSIONS,
    sleep_threshold=60,
)

# Global fallback session (optional — only used if SESSION_STRING is in .env)
global_user = (
    Client(
        "user_session",
        workers=100,
        session_string=PyroConf.SESSION_STRING,
        max_concurrent_transmissions=PyroConf.MAX_CONCURRENT_TRANSMISSIONS,
        sleep_threshold=60,
    )
    if PyroConf.SESSION_STRING
    else None
)

BATCH_JOBS = {}
WAITING_FOR_DEST = {}
WAITING_FOR_CAPTION_RULE = {}
LINK_CACHE = {}
FILTER_STATE = {}


def get_client_for_user(user_id: int, link: str = None) -> Client | None:
    """Return the best available client for the request.

    • Public channel links (t.me/username/…)  → bot client, no login required.
    • Private channel links (t.me/c/…)        → per-user client or global session.
      Returns None when the private link has no available user session.
    """
    if link is not None and not is_private_link(link):
        return bot  # Public channel — bot can access it directly
    return get_user_client(user_id) or global_user


# ─── Caption setup helper ─────────────────────────────────────────────────────

async def trigger_caption_setup(bot: Client, user: Client, message: Message, job: dict, requester_id: int = None):
    sample_caption = ""
    for msg_id in range(job["start_id"], min(job["start_id"] + 5, job["end_id"] + 1)):
        try:
            msg_obj = await user.get_messages(chat_id=job["start_chat"], message_ids=msg_id)
            if msg_obj and not getattr(msg_obj, "empty", True):
                raw_text = msg_obj.caption or msg_obj.text
                if raw_text and len(raw_text.strip()) > 50 and '\n' in raw_text:
                    sample_caption = await get_parsed_msg(msg_obj)
                    break
        except Exception:
            continue

    job["caption_rules"] = []

    if sample_caption:
        user_id = requester_id or (message.from_user.id if hasattr(message, "from_user") and message.from_user else message.chat.id)
        job["sample_caption"] = sample_caption
        WAITING_FOR_CAPTION_RULE[user_id] = job
        job["original_message_id"] = message.id

        preview_caption = apply_caption_rules(sample_caption, job["caption_rules"])
        display_cap = preview_caption[:300] + ("..." if len(preview_caption) > 300 else "")
        if not display_cap: display_cap = "[Caption is empty]"

        text = (
            f"<b>Caption Preview:</b>\n\n<code>{display_cap}</code>\n\n"
            "🔄 To clean up a caption, reply to this message with the exact text you'd like to remove!\n\n"
            f"<blockquote>🎯 <b>Active Rules:</b> 0 applied</blockquote>"
        )

        msg = await message.reply(text, reply_markup=get_caption_keyboard(message.id), parse_mode=ParseMode.HTML)
        job["menu_message_id"] = msg.id
    else:
        job["caption_rules"] = ["keep"]
        if job["job_type"] == "batch":
            await track_task(execute_batch(bot, user, job["original_message"], job))
        else:
            await track_task(execute_autoforward(bot, user, job["original_message"], job))


# ─── Auth commands ────────────────────────────────────────────────────────────

@bot.on_message(filters.command("login") & filters.private)
async def login_command(_, message: Message):
    user_id = message.from_user.id
    if get_user_client(user_id):
        return await message.reply(
            "✅ You already have an active session.\n"
            "Use /logout first if you want to switch accounts."
        )
    await cancel_login(user_id)
    start_login_flow(user_id)
    await message.reply(
        "📱 <b>Login</b>\n\n"
        "Please send your phone number in international format.\n"
        "Example: <code>+256712345678</code>\n\n"
        "Send /cancel to abort.",
        parse_mode=ParseMode.HTML,
    )


@bot.on_message(filters.command("logout") & filters.private)
async def logout_command(_, message: Message):
    user_id = message.from_user.id
    if not get_user_client(user_id):
        return await message.reply("❌ You don't have a personal session to log out from.")
    await logout_user(user_id)
    await message.reply("✅ Logged out successfully. Use /login to sign in again.")


@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(_, message: Message):
    user_id = message.from_user.id
    if is_logging_in(user_id):
        await cancel_login(user_id)
        await message.reply("❌ Login cancelled.")
    else:
        await message.reply("Nothing to cancel.")


# ─── Info commands ────────────────────────────────────────────────────────────

@bot.on_message(filters.command("start") & filters.private)
async def start(_, message: Message):
    user_id = message.from_user.id
    has_session = bool(get_user_client(user_id) or global_user)
    session_line = (
        "✅ <b>You are logged in</b> — public and private channels are both accessible."
        if has_session
        else (
            "🌐 <b>Public channels work without login.</b>\n"
            "🔐 For private channels/groups, use /login first."
        )
    )
    welcome_text = (
        "🤖 <b>Welcome to Save Restricted Bot!</b>\n\n"
        "I can help you download media from restricted channels and set up auto-forwarding. 🚀\n\n"
        f"{session_line}\n\n"
        "⚙️ <b>How to use:</b>\n"
        "• Paste any <b>public</b> Telegram post link directly — no login needed.\n"
        "• Paste a <b>private</b> channel link after using /login.\n"
        "• Use <code>/help</code> to see advanced commands.\n\n"
        "⚠️ For private channels, your account must already be a member."
    )
    await message.reply(welcome_text, disable_web_page_preview=True, parse_mode=ParseMode.HTML)


@bot.on_message(filters.command("help") & filters.private)
async def help_command(_, message: Message):
    help_text = (
        "💡 <b>Bot Commands</b>\n\n"
        "🌐 <b>Public Channels</b>\n"
        "• No login needed — just paste the link.\n\n"
        "🔐 <b>Private Channels / Groups</b>\n"
        "• <code>/login</code> — Connect your Telegram account\n"
        "• <code>/logout</code> — Remove your session\n"
        "• <code>/cancel</code> — Abort a login in progress\n\n"
        "📥 <b>Single Posts</b>\n"
        "• Paste any restricted post link directly in the chat.\n\n"
        "📦 <b>Batch Downloads</b>\n"
        "• Type <code>/batch &lt;start_url&gt;</code> to initiate a batch download.\n\n"
        "⚡ <b>Auto-Forwarding</b>\n"
        "• Type <code>/autoforward &lt;from_chat_link&gt;</code> to initiate autoforward process.\n\n"
        "⚙️ <b>System Controls</b>\n"
        "• <code>/stop</code> — Cancel active tasks\n"
        "• <code>/stats</code> — Check bot performance\n"
        "• <code>/logs</code> — View system logs\n\n"
        "🔒 <b>Note:</b> For private channels, your account must be a member of the source chat."
    )
    await message.reply(help_text, disable_web_page_preview=True, parse_mode=ParseMode.HTML)


# ─── Download commands ────────────────────────────────────────────────────────

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(bot: Client, message: Message):
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 2 or not args[1].startswith("https://t.me/"):
        return await message.reply(
            "🚀 <b>Batch Download</b>\n\n<blockquote><code>/batch start_link</code></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    link = args[1]
    if not get_client_for_user(user_id, link):
        return await message.reply(
            "🔐 <b>Login Required</b>\n\n"
            "This link is from a <b>private channel or group</b>.\n"
            "Use /login to connect your Telegram account, then try again.",
            parse_mode=ParseMode.HTML,
        )
    LINK_CACHE[user_id] = link
    await message.reply(
        "🔗 Send the <b>ending post link</b> to establish the range.",
        parse_mode=ParseMode.HTML,
    )
    WAITING_FOR_DEST[user_id] = {"action": "wait_batch_end"}


@bot.on_message(filters.command("autoforward") & filters.private)
async def auto_forward_init(bot: Client, message: Message):
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 2 or not args[1].startswith("https://t.me/"):
        return await message.reply(
            "🚀 <b>Auto-Forward</b>\n\n<blockquote><code>/autoforward &lt;start_link&gt;</code></blockquote>",
            parse_mode=ParseMode.HTML,
        )
    link = args[1]
    if not get_client_for_user(user_id, link):
        return await message.reply(
            "🔐 <b>Login Required</b>\n\n"
            "This link is from a <b>private channel or group</b>.\n"
            "Use /login to connect your Telegram account, then try again.",
            parse_mode=ParseMode.HTML,
        )
    LINK_CACHE[user_id] = link
    WAITING_FOR_DEST[user_id] = {"action": "wait_auto_end"}
    await message.reply(
        "🔗 Send the <b>ending post link</b> to establish the range.",
        parse_mode=ParseMode.HTML,
    )


# ─── Callback handlers ────────────────────────────────────────────────────────

@bot.on_callback_query(filters.regex(r"^menu_(single|batch|auto)$"))
async def main_menu_callback(bot: Client, callback_query: CallbackQuery):
    action = callback_query.matches[0].group(1)
    user_id = callback_query.from_user.id

    if user_id not in LINK_CACHE:
        return await callback_query.answer("Session expired. Please send the link again.", show_alert=True)

    link = LINK_CACHE[user_id]
    user_client = get_client_for_user(user_id, link)
    if not user_client:
        return await callback_query.answer(
            "🔐 Private channel detected. Please /login first.",
            show_alert=True,
        )

    await callback_query.message.delete()

    if action == "single":
        await track_task(handle_download(bot, user_client, callback_query.message, link))
        LINK_CACHE.pop(user_id, None)

    elif action == "batch":
        WAITING_FOR_DEST[user_id] = {"action": "wait_batch_end"}
        await callback_query.message.reply(
            "🔗 Send the <b>ending post link</b> to establish the range.",
            parse_mode=ParseMode.HTML,
        )

    elif action == "auto":
        WAITING_FOR_DEST[user_id] = {"action": "wait_auto_end"}
        await callback_query.message.reply(
            "🔗 Send the <b>ending post link</b> to establish the range.",
            parse_mode=ParseMode.HTML,
        )


@bot.on_callback_query(filters.regex(r"^filter_([a-z]+)_(\d+)$"))
async def filter_menu_callback(bot: Client, callback_query: CallbackQuery):
    selection = callback_query.matches[0].group(1)
    msg_id = int(callback_query.matches[0].group(2))

    if msg_id not in BATCH_JOBS:
        return await callback_query.answer("Session expired.", show_alert=True)

    job = BATCH_JOBS[msg_id]
    current_filters = FILTER_STATE.get(msg_id, [])

    if selection == "all":
        job["filter_type"] = ["all"]
        FILTER_STATE.pop(msg_id, None)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Bot Chat", callback_data=f"batch_bot_{msg_id}"),
             InlineKeyboardButton("Channel/Topic", callback_data=f"batch_chan_{msg_id}")]
        ])
        return await callback_query.message.edit_text("Where do you want to forward media?", reply_markup=keyboard)

    if selection == "done":
        job["filter_type"] = current_filters if current_filters else ["all"]
        FILTER_STATE.pop(msg_id, None)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Bot Chat", callback_data=f"batch_bot_{msg_id}"),
             InlineKeyboardButton("Channel/Topic", callback_data=f"batch_chan_{msg_id}")]
        ])
        return await callback_query.message.edit_text("Where do you want to forward media?", reply_markup=keyboard)

    if "all" in current_filters:
        current_filters.remove("all")

    if selection in current_filters:
        current_filters.remove(selection)
    else:
        current_filters.append(selection)

    if len(current_filters) >= 4:
        current_filters = []

    FILTER_STATE[msg_id] = current_filters
    await callback_query.message.edit_reply_markup(reply_markup=get_filter_keyboard(current_filters, msg_id))


@bot.on_callback_query(filters.regex(r"^batch_(bot|chan)_(\d+)$"))
async def batch_destination_callback(bot: Client, callback_query: CallbackQuery):
    action, msg_id = callback_query.matches[0].groups()
    msg_id = int(msg_id)
    user_id = callback_query.from_user.id

    if msg_id not in BATCH_JOBS:
        return await callback_query.answer("Batch process has expired.", show_alert=True)

    job = BATCH_JOBS.pop(msg_id)

    # Resolve client using the stored source link so public jobs never need login
    source_link = job.get("source_link", "")
    user_client = get_client_for_user(user_id, source_link)
    if not user_client:
        return await callback_query.answer("🔐 Please /login first.", show_alert=True)

    await callback_query.message.delete()

    if action == "bot":
        job["target_chat"] = callback_query.message.chat.id
        job["target_topic"] = None
        await trigger_caption_setup(bot, user_client, callback_query.message, job, requester_id=user_id)
    elif action == "chan":
        WAITING_FOR_DEST[user_id] = job
        await job["original_message"].reply("🔗 Send a post link from the target channel/topic.")


@bot.on_callback_query(filters.regex(r"^cap_(rmlast|done)_(\d+)$"))
async def caption_rule_callback(bot: Client, callback_query: CallbackQuery):
    action, msg_id = callback_query.matches[0].groups()
    user_id = callback_query.from_user.id

    if user_id not in WAITING_FOR_CAPTION_RULE:
        return await callback_query.answer("Session expired or invalid.", show_alert=True)

    job = WAITING_FOR_CAPTION_RULE[user_id]

    # Resolve client using the stored source link
    source_link = job.get("source_link", "")
    user_client = get_client_for_user(user_id, source_link)
    if not user_client:
        return await callback_query.answer("🔐 Please /login first.", show_alert=True)

    if action == "done":
        WAITING_FOR_CAPTION_RULE.pop(user_id)
        await callback_query.message.delete()
        if job["job_type"] == "batch":
            await track_task(execute_batch(bot, user_client, job["original_message"], job))
        else:
            await track_task(execute_autoforward(bot, user_client, job["original_message"], job))
        return

    if action == "rmlast":
        job["caption_rules"].append("rm_last")
        await callback_query.answer("✅ Rule Added!", show_alert=False)

    rules_count = len(job["caption_rules"])
    preview_caption = apply_caption_rules(job['sample_caption'], job["caption_rules"])
    display_cap = preview_caption[:300] + ("..." if len(preview_caption) > 300 else "")
    if not display_cap: display_cap = "[Caption is empty]"

    text = (
        f"<b>Caption Preview:</b>\n\n<code>{display_cap}</code>\n\n"
        "🔄 To clean up a caption, reply to this message with the exact text you'd like to remove!\n\n"
        f"<blockquote>🎯 <b>Active Rules:</b> {rules_count} applied</blockquote>"
    )

    try:
        await callback_query.message.edit_text(text, reply_markup=get_caption_keyboard(job['original_message_id']), parse_mode=ParseMode.HTML)
    except Exception:
        pass


# ─── Main message handler ─────────────────────────────────────────────────────

@bot.on_message(filters.private & filters.text & ~filters.command(
    ["start", "help", "stats", "logs", "stop", "autoforward", "batch", "login", "logout", "cancel",
     "setexpiry", "lifecycle"]
))
async def handle_any_message(bot: Client, message: Message):
    user_id = message.from_user.id

    # ── Login flow (highest priority) ──────────────────────────────────────────
    if is_logging_in(user_id):
        state = get_login_state(user_id)

        if state == "phone":
            phone = message.text.strip()
            if not phone.startswith("+"):
                return await message.reply(
                    "❌ Phone number must start with <code>+</code> and include country code.\n"
                    "Example: <code>+256712345678</code>",
                    parse_mode=ParseMode.HTML,
                )
            status = await message.reply("⏳ Sending OTP...")
            try:
                await process_phone(user_id, phone)
                await status.edit(
                    "📩 OTP sent to your Telegram app.\n\nPlease enter the code:\n"
                    "<i>(You can send it as-is or with spaces, e.g. <code>12345</code> or <code>1 2 3 4 5</code>)</i>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                await cancel_login(user_id)
                await status.edit(f"❌ Failed to send OTP: <code>{e}</code>\n\nSend /login to try again.", parse_mode=ParseMode.HTML)

        elif state == "code":
            code = message.text.strip().replace(" ", "")
            try:
                result = await process_code(user_id, code)
                if result == "password":
                    await message.reply("🔐 Two-step verification is enabled.\n\nPlease enter your 2FA password:")
                else:
                    me = await get_user_client(user_id).get_me()
                    name = me.first_name or me.username or str(user_id)
                    await message.reply(
                        f"✅ <b>Logged in as {name}!</b>\n\n"
                        "You can now paste any restricted post link to get started.",
                        parse_mode=ParseMode.HTML,
                    )
            except PhoneCodeInvalid:
                await message.reply("❌ Invalid code. Please try again:")
            except PhoneCodeExpired:
                await cancel_login(user_id)
                await message.reply("❌ Code expired. Send /login to start over.")
            except Exception as e:
                await cancel_login(user_id)
                await message.reply(f"❌ Error: <code>{e}</code>\n\nSend /login to try again.", parse_mode=ParseMode.HTML)

        elif state == "password":
            try:
                await process_password(user_id, message.text)
                me = await get_user_client(user_id).get_me()
                name = me.first_name or me.username or str(user_id)
                await message.reply(
                    f"✅ <b>Logged in as {name}!</b>\n\n"
                    "You can now paste any restricted post link to get started.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                await cancel_login(user_id)
                await message.reply("❌ Wrong password. Send /login to try again.")
        return

    # ── Destination / range selection ──────────────────────────────────────────
    if user_id in WAITING_FOR_DEST:
        # Resolve client based on the start link (public → bot, private → user session)
        start_link = LINK_CACHE.get(user_id, "")
        user_client = get_client_for_user(user_id, start_link)
        if not user_client:
            WAITING_FOR_DEST.pop(user_id, None)
            return await message.reply(
                "🔐 <b>Login Required</b>\n\n"
                "This is a private channel. Use /login first.",
                parse_mode=ParseMode.HTML,
            )

        job = WAITING_FOR_DEST.pop(user_id)

        if "action" in job:
            end_link = message.text

            try:
                start_chat, start_id, _ = getChatMsgID(start_link)
                end_chat, end_id, _ = getChatMsgID(end_link)
            except Exception as e:
                return await message.reply(f"<b>❌ Error parsing links:\n{e}</b>", parse_mode=ParseMode.HTML)

            if start_chat != end_chat:
                return await message.reply("<b>❌ Both links must be from the same channel.</b>", parse_mode=ParseMode.HTML)
            if start_id > end_id:
                return await message.reply("<b>❌ Invalid range.</b>", parse_mode=ParseMode.HTML)

            if job["action"] == "wait_batch_end":
                BATCH_JOBS[message.id] = {
                    "start_chat": start_chat,
                    "start_id": start_id,
                    "end_id": end_id,
                    "prefix": start_link.rsplit("/", 1)[0],
                    "job_type": "batch",
                    "original_message": message,
                    "source_link": start_link,   # ← stored so callbacks can resolve the right client
                }
                FILTER_STATE[message.id] = []
                await message.reply(
                    "🎬 <b>Select media types to download:</b>",
                    reply_markup=get_filter_keyboard([], message.id),
                    parse_mode=ParseMode.HTML,
                )

            elif job["action"] == "wait_auto_end":
                auto_job = {
                    "start_chat": start_chat,
                    "start_id": start_id,
                    "end_id": end_id,
                    "job_type": "autoforward",
                    "original_message": message,
                    "source_link": start_link,   # ← stored so callbacks can resolve the right client
                }
                WAITING_FOR_DEST[user_id] = auto_job
                await message.reply("🔗 Send a post link from the target channel/topic.")
            return

        try:
            target_chat_id, target_msg_id, target_topic_id = getChatMsgID(message.text)
            job["target_chat"] = target_chat_id
            job["target_topic"] = target_topic_id
            await trigger_caption_setup(bot, user_client, message, job)
        except Exception as e:
            await message.reply(f"<b>❌ Error parsing target link:\n{e}</b>", parse_mode=ParseMode.HTML)
        return

    # ── Caption rule input ─────────────────────────────────────────────────────
    if user_id in WAITING_FOR_CAPTION_RULE:
        job = WAITING_FOR_CAPTION_RULE[user_id]

        new_rule = f"remove_text:{message.text}"
        if new_rule in job["caption_rules"]:
            await message.reply("⚠️ This text is already in the removal list!")
            return

        job["caption_rules"].append(new_rule)
        rules_count = len(job["caption_rules"])
        preview_caption = apply_caption_rules(job['sample_caption'], job["caption_rules"])
        display_cap = preview_caption[:300] + ("..." if len(preview_caption) > 300 else "")
        if not display_cap: display_cap = "[Caption is empty]"

        text = (
            f"<b>Caption Preview:</b>\n\n<code>{display_cap}</code>\n\n"
            "🔄 To clean up a caption, reply to this message with the exact text you'd like to remove!\n\n"
            f"<blockquote>🎯 <b>Active Rules:</b> {rules_count} applied</blockquote>"
        )

        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=job["menu_message_id"],
                text=text,
                reply_markup=get_caption_keyboard(job['original_message_id']),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        await message.reply(
            "✅ <b>Text rule added.</b> You can add more text to remove, or click <b>Start</b> on the menu.",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── Telegram link pasted ───────────────────────────────────────────────────
    if re.search(r"t\.me\/", message.text):
        link = message.text.strip()
        user_client = get_client_for_user(user_id, link)

        if not user_client:
            # Only private links (t.me/c/...) reach here without a client
            return await message.reply(
                "🔐 <b>Login Required</b>\n\n"
                "This link is from a <b>private channel or group</b>.\n\n"
                "Use /login to connect your Telegram account, then paste the link again.",
                parse_mode=ParseMode.HTML,
            )

        LINK_CACHE[user_id] = link
        await message.reply(
            "⚙️ <b>How do you want to proceed?</b>",
            reply_markup=get_start_keyboard(),
            parse_mode=ParseMode.HTML,
        )


# ─── Lifecycle commands (owner only) ─────────────────────────────────────────

@bot.on_message(filters.command("setexpiry") & filters.private)
async def set_expiry_command(_, message: Message):
    if message.from_user.id != PyroConf.OWNER_ID:
        return await message.reply("❌ This command is restricted to the bot owner.")

    args = message.text.split()
    if len(args) < 2:
        return await message.reply(
            "📅 <b>Set Server Expiry Date</b>\n\n"
            "Usage: <code>/setexpiry YYYY-MM-DD</code>\n"
            "Example: <code>/setexpiry 2026-07-15</code>",
            parse_mode=ParseMode.HTML,
        )

    date_str = args[1].strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return await message.reply(
            "❌ Invalid format. Use <code>YYYY-MM-DD</code>\n"
            "Example: <code>/setexpiry 2026-07-15</code>",
            parse_mode=ParseMode.HTML,
        )

    save_expiry(date_str)
    days = get_days_remaining(date_str)
    day_word = "day" if days == 1 else "days"
    await message.reply(
        f"✅ <b>Expiry date saved.</b>\n\n"
        f"📅 Date: <b>{format_expiry(date_str)}</b>\n"
        f"⏳ <b>{days} {day_word} remaining.</b>\n\n"
        f"I'll remind you when 5 or fewer days are left.",
        parse_mode=ParseMode.HTML,
    )


@bot.on_message(filters.command("lifecycle") & filters.private)
async def lifecycle_status_command(_, message: Message):
    if message.from_user.id != PyroConf.OWNER_ID:
        return await message.reply("❌ This command is restricted to the bot owner.")

    expiry_str = load_expiry()
    if not expiry_str:
        return await message.reply(
            "❌ <b>No expiry date set.</b>\n\n"
            "Use <code>/setexpiry YYYY-MM-DD</code> to set one.",
            parse_mode=ParseMode.HTML,
        )

    days = get_days_remaining(expiry_str)
    formatted = format_expiry(expiry_str)

    if days is None:
        status = "❓ <b>Unknown</b>"
    elif days < 0:
        status = f"🚨 <b>EXPIRED</b> ({abs(days)} day(s) ago)"
    elif days == 0:
        status = "🚨 <b>Expires TODAY</b>"
    elif days <= 5:
        day_word = "day" if days == 1 else "days"
        status = f"⚠️ <b>{days} {day_word} remaining</b>"
    else:
        status = f"✅ <b>{days} days remaining</b>"

    await message.reply(
        f"📅 <b>Server Lifecycle Status</b>\n\n"
        f"Expiry date: <b>{formatted}</b>\n"
        f"Status: {status}",
        parse_mode=ParseMode.HTML,
    )


# ─── System commands ──────────────────────────────────────────────────────────

@bot.on_message(filters.command("stats") & filters.private)
async def stats(_, message: Message):
    currentTime = get_readable_time(time() - PyroConf.BOT_START_TIME)

    def get_sys_stats():
        t, u, f = shutil.disk_usage(".")
        return (
            get_readable_file_size(t), get_readable_file_size(f),
            get_readable_file_size(psutil.net_io_counters().bytes_sent),
            get_readable_file_size(psutil.net_io_counters().bytes_recv),
            psutil.cpu_percent(interval=0.5), psutil.virtual_memory().percent,
            psutil.disk_usage("/").percent, round(psutil.Process(os.getpid()).memory_info()[0] / 1024**2),
        )

    total, free, sent, recv, cpuUsage, memory, disk, proc_mem = await asyncio.to_thread(get_sys_stats)

    await message.reply(
        "<b>Bot's Live and Running Successfully.</b>\n\n"
        f"<b>Uptime:</b> {currentTime} | <b>Mem:</b> {proc_mem} MiB\n"
        f"<b>Free Disk:</b> {free} of {total}\n"
        f"<b>Traffic:</b> 🔼 {sent} | 🔽 {recv}\n"
        f"<b>System:</b> CPU: {cpuUsage}% | RAM: {memory}% | DISK: {disk}%",
        parse_mode=ParseMode.HTML,
    )


@bot.on_message(filters.command("logs") & filters.private)
async def logs(_, message: Message):
    if os.path.exists("logs.txt"):
        await message.reply_document(document="logs.txt", caption="<b>Logs</b>", parse_mode=ParseMode.HTML)
    else:
        await message.reply("<b>Not exists</b>", parse_mode=ParseMode.HTML)


@bot.on_message(filters.command("stop") & filters.private)
async def cancel_all_tasks(_, message: Message):
    cancelled = 0
    for task in list(get_running_tasks()):
        if not task.done():
            task.cancel()
            cancelled += 1
    await message.reply(f"<b>Cancelled {cancelled} running task(s).</b>", parse_mode=ParseMode.HTML)


# ─── Entry point ──────────────────────────────────────────────────────────────

async def run():
    if os.path.exists("downloads"):
        try:
            shutil.rmtree("downloads")
        except Exception as e:
            LOGGER(__name__).error(f"Failed to clean downloads directory: {e}")
    os.makedirs("downloads", exist_ok=True)

    LOGGER(__name__).info("Bot Started!")

    await bot.start()
    await start_saved_clients()

    if global_user:
        try:
            await global_user.start()
            LOGGER(__name__).info("Global user session started.")
        except Exception as e:
            LOGGER(__name__).warning(f"Global user session failed to start: {e}")

    # Start lifecycle reminder if an owner is configured
    if PyroConf.OWNER_ID:
        asyncio.create_task(lifecycle_checker(bot, PyroConf.OWNER_ID))
        LOGGER(__name__).info("Lifecycle checker started.")

    try:
        await idle()
    finally:
        await stop_all_clients()
        if global_user:
            try:
                await global_user.stop()
            except Exception:
                pass
        await bot.stop()
        LOGGER(__name__).info("Bot Stopped.")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        traceback.print_exc()
        LOGGER(__name__).error(f"Bot Crashed: {e}")
