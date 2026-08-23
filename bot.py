import os
import re
import time
import math
import asyncio
import sqlite3
import pathlib
import requests
from datetime import datetime
from urllib.parse import quote
from flask import Flask
from threading import Thread
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestUsers,
    KeyboardButtonRequestChat,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set!")

ADMIN_ID = 8300271033


IA_BASE = "https://osint.invalidayushh.workers.dev"
IA_KEY = "Rack"
IA_NUM_URL = IA_BASE + "/num?key=" + IA_KEY + "&q={number}"
IA_ADHAR_URL = IA_BASE + "/adhar?key=" + IA_KEY + "&q={aadhar}"
ROOTX_TG_NUM_URL = "https://rootx-osint.in/?type=tg_num&key=abror&query={term}"
TG_NUM_FALLBACK_URL = "https://api.igfollows.site/TG/index.php?type=user&key=OGGYxKRISH&term={term}"
IA_IFSC_URL = IA_BASE + "/ifsc?key=" + IA_KEY + "&q={code}"
IA_INSTA_URL = IA_BASE + "/insta?key=" + IA_KEY + "&q={username}"
IA_PAK_URL = IA_BASE + "/pak?key=" + IA_KEY + "&q={number}"
IA_VEH_URL = IA_BASE + "/veh?key=" + IA_KEY + "&q={veh}"
IA_FAMILYINFO_URL = IA_BASE + "/familyinfo?key=" + IA_KEY + "&q={aadhar}"
IA_LEAK_URL = IA_BASE + "/leak?key=" + IA_KEY + "&q={query}"

VEHINFO_URL = "https://vehicleinfo-byrack.vercel.app/api?search={reg}"

IA_ID_URL    = IA_BASE + "/id?key="    + IA_KEY + "&q={query}"
IA_VNUM_URL  = IA_BASE + "/vnum?key="  + IA_KEY + "&q={vnum}"
IA_FFLIKE_URL  = IA_BASE + "/fflike?key="  + IA_KEY + "&region={region}&uid={uid}"
IA_FFVISIT_URL = IA_BASE + "/ffvisit?key=" + IA_KEY + "&region={region}&uid={uid}"
TRUECALLER_URL = "https://whocalled.in/api/truecaller/lookup?phone={phone}&api_key=tc_bot_key_7c41be29fb38a20d40fa8201"
RACK_TRUECALLER_URL = "https://rack-72au.onrender.com/truecaller?q={phone}"
RACK_DNS_URL = "https://rack-72au.onrender.com/dns-lookup?q={query}"

CHANNEL_USERNAME = "@racksun19"
CHANNEL_LINK = "https://t.me/racksun19"
GROUP_USERNAME = "@racksungroup"
GROUP_LINK = "https://t.me/racksungroup"
GROUP2_USERNAME = "@rackcraft"
GROUP2_LINK = "https://t.me/rackcraft"
CHANNEL2_USERNAME = "@weaying"
CHANNEL2_LINK = "https://t.me/WEAYing"

IP_API_URL = "https://ip-dwy8.onrender.com/api/rackipapi?ip={ip}"

WEATHER_URL = "https://rack-weather.vercel.app/api/weather/{city}"
AQI_URL = "https://rack-aqiinfos.vercel.app/api/aqi/{city}"
PINCODE_URL = "https://rack-pincodeapi.vercel.app/api?search={pincode}"

COOLDOWN_SECONDS = 1

maintenance_mode = False
user_last_request = {}

LEAK_PAGE_CACHE = {}
LEAK_CACHE_ORDER = []
LEAK_CACHE_LIMIT = 300
_leak_cache_seq = 0

LEAK_DAILY_LIMIT = 5
leak_daily_usage = {}  # user_id -> (date_str, count)


def check_and_use_leak_quota(user_id):
    """Returns (allowed, remaining_after). Admin is exempt."""
    if is_admin(user_id):
        return True, LEAK_DAILY_LIMIT
    today = datetime.now().strftime("%Y-%m-%d")
    date_str, count = leak_daily_usage.get(user_id, (today, 0))
    if date_str != today:
        date_str, count = today, 0
    if count >= LEAK_DAILY_LIMIT:
        leak_daily_usage[user_id] = (date_str, count)
        return False, 0
    count += 1
    leak_daily_usage[user_id] = (date_str, count)
    return True, LEAK_DAILY_LIMIT - count

_DATA_DIR = pathlib.Path("/data")
_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = str(_DATA_DIR / "bot.db")


FREE_NUM_LIMIT = 15
FREE_TG_LIMIT = 10
FREE_VEH_LIMIT = 5


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id           INTEGER PRIMARY KEY,
            first_name        TEXT,
            username          TEXT,
            join_date         TEXT,
            search_count      INTEGER DEFAULT 0,
            num_searches_today  INTEGER DEFAULT 0,
            tg_searches_today   INTEGER DEFAULT 0,
            last_search_date  TEXT DEFAULT ''
        )
    """)
    for col, default in [
        ("num_searches_today",    "0"),
        ("tg_searches_today",     "0"),
        ("aadhar_searches_today", "0"),
        ("veh_searches_today",    "0"),
        ("last_search_date",      "''"),
        ("is_banned",             "0"),
        ("ban_reason",            "''"),
        ("is_muted",              "0"),
        ("mute_reason",           "''"),
        ("warn_count",            "0"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT DEFAULT {default}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def track_user(user_id, first_name=None, username=None):
    if not user_id:
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        join_date = datetime.now().strftime("%d %b %Y")
        c.execute(
            "INSERT INTO users (user_id, first_name, username, join_date) VALUES (?,?,?,?)",
            (user_id, first_name or "", username or "", join_date),
        )
    else:
        c.execute(
            "UPDATE users SET first_name=?, username=? WHERE user_id=?",
            (first_name or "", username or "", user_id),
        )
    conn.commit()
    conn.close()


def increment_search(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET search_count = search_count + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_user_info_db(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, username, join_date, search_count, is_banned, ban_reason, is_muted, mute_reason FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row


def get_stats_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT SUM(search_count) FROM users")
    searches = c.fetchone()[0] or 0
    today = datetime.now().strftime("%d %b %Y")
    c.execute("SELECT COUNT(*) FROM users WHERE join_date=?", (today,))
    today_joined = c.fetchone()[0]
    conn.close()
    return total, searches, today_joined


def get_all_user_ids_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def is_admin(user_id):
    return user_id == ADMIN_ID


async def check_admin(update, context):
    user_id = update.effective_user.id
    chat = update.effective_chat
    if chat and chat.type in ("group", "supergroup"):
        try:
            member = await context.bot.get_chat_member(chat.id, user_id)
            if member.status in ("administrator", "creator"):
                return True
        except Exception:
            pass
    return is_admin(user_id)




def check_and_reset_daily(user_id):
    today = datetime.now().strftime("%d %b %Y")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_search_date FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if row and row[0] != today:
        c.execute(
            "UPDATE users SET num_searches_today=0, tg_searches_today=0, aadhar_searches_today=0, veh_searches_today=0, last_search_date=? WHERE user_id=?",
            (today, user_id),
        )
        conn.commit()
    elif row and not row[0]:
        c.execute("UPDATE users SET last_search_date=? WHERE user_id=?", (today, user_id))
        conn.commit()
    conn.close()


def get_daily_counts(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT num_searches_today, tg_searches_today, aadhar_searches_today FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return (row[0] or 0, row[1] or 0, row[2] or 0) if row else (0, 0, 0)


def increment_num_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET num_searches_today = num_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def increment_tg_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET tg_searches_today = tg_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_daily_aadhar_count(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT aadhar_searches_today FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] or 0 if row else 0


def increment_aadhar_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET aadhar_searches_today = aadhar_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def get_daily_veh_count(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT veh_searches_today FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] or 0 if row else 0


def increment_veh_daily(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET veh_searches_today = veh_searches_today + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


async def resolve_target_id(update, context, args, with_reason=False):
    """
    Returns (target_id, reason, error_msg).
    Supports: reply to message, @username, numeric UID.
    If with_reason=True, remaining args after target are joined as reason.
    """
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_id = update.message.reply_to_message.from_user.id
        reason = " ".join(args) if (with_reason and args) else ""
        return target_id, reason, None

    if not args:
        return None, "", "no_args"

    first = args[0]

    if first.startswith("@"):
        try:
            chat = await context.bot.get_chat(first)
            target_id = chat.id
        except Exception:
            return None, "", "❌ *Username not found!*\n\n`" + first + "` — ye username galat hai ya private hai."
        reason = " ".join(args[1:]) if (with_reason and len(args) > 1) else ""
        return target_id, reason, None

    if first.lstrip("-").isdigit():
        target_id = int(first)
        reason = " ".join(args[1:]) if (with_reason and len(args) > 1) else ""
        return target_id, reason, None

    return None, "", "invalid"


def check_cooldown(user_id):
    now = time.time()
    if user_id in user_last_request:
        elapsed = now - user_last_request[user_id]
        if elapsed < COOLDOWN_SECONDS:
            remaining = math.ceil(COOLDOWN_SECONDS - elapsed)
            return False, max(1, remaining)
    user_last_request[user_id] = now
    return True, 0


async def fetch_json(url, timeout=5):
    loop = asyncio.get_event_loop()
    def _get():
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    return await loop.run_in_executor(None, _get)


def clean_address(addr):
    if not addr:
        return "None"
    if "!" in addr:
        parts = []
        for p in addr.split("!"):
            p = p.strip()
            if p and p != ".":
                parts.append(p)
        if parts:
            return ", ".join(parts)
        return "None"
    cleaned = " ".join(addr.split())
    return cleaned if cleaned else "None"


def val(v):
    if v is None or str(v).strip() == "":
        return "None"
    return str(v).strip()


async def delete_msg(context, chat_id, msg_id):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass


RESULT_DELETE_SECONDS = 120
_result_cleanup_tasks = set()


def schedule_result_cleanup(context, chat_id, message_ids):
    """Delete lookup result messages after two minutes and notify the chat."""
    ids = [message_id for message_id in message_ids if message_id]
    if not ids:
        return

    async def _cleanup():
        await asyncio.sleep(RESULT_DELETE_SECONDS)
        for message_id in ids:
            await delete_msg(context, chat_id, message_id)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🗑️ Message Deleted Successfully",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    task = asyncio.create_task(_cleanup())
    _result_cleanup_tasks.add(task)
    task.add_done_callback(_result_cleanup_tasks.discard)


async def send_expiring_lookup_message(update, context, text, **kwargs):
    """Send a lookup status/result message that expires after two minutes."""
    sent = await update.message.reply_text(text, **kwargs)
    schedule_result_cleanup(context, update.message.chat_id, [sent.message_id])
    return sent


async def log_error_to_admin(context, error_info):
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="🐛 *Bot Error:*\n\n`" + str(error_info) + "`",
            parse_mode="Markdown",
        )
    except Exception:
        pass


flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "Bot is Alive!"


def run_flask():
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()




async def is_member(user_id, context):
    allowed = ["member", "administrator", "creator"]
    not_allowed = ["left", "kicked"]
    try:
        ch = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if ch.status not in allowed:
            return False
    except Exception:
        return False
    try:
        ch2 = await context.bot.get_chat_member(chat_id=CHANNEL2_USERNAME, user_id=user_id)
        if ch2.status not in allowed:
            return False
    except Exception:
        return False
    try:
        gr = await context.bot.get_chat_member(chat_id=GROUP_USERNAME, user_id=user_id)
        if gr.status in not_allowed:
            return False
    except Exception:
        pass
    try:
        gr2 = await context.bot.get_chat_member(chat_id=GROUP2_USERNAME, user_id=user_id)
        if gr2.status not in allowed:
            return False
    except Exception:
        return False
    return True


async def send_join_message(update, context):
    user = update.message.from_user
    first_name = user.first_name or "User"
    join_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel 1", url=CHANNEL_LINK)],
        [InlineKeyboardButton("📢 Join Channel 2", url=CHANNEL2_LINK)],
        [InlineKeyboardButton("👥 Join Group", url=GROUP_LINK)],
        [InlineKeyboardButton("👥 Join Rackcraft", url=GROUP2_LINK)],
        [InlineKeyboardButton("✅ I have Joined", callback_data="check_joined")],
    ])
    text = (
        "⚠️ *Hello " + first_name + "!*\n\n"
        "Join our channels and group to use this bot.\n\n"
        "1️⃣ Join Channel 1: @racksun19\n"
        "2️⃣ Join Channel 2: @WEAYing\n"
        "3️⃣ Join Group: @racksungroup\n\n"
        "4️⃣ Join Rackcraft Group: @rackcraft\n\n"
        "After joining all, click *I have Joined* button."
    )
    sent = await update.message.reply_text(text, reply_markup=join_button, parse_mode="Markdown")
    context.user_data["join_msg_id"] = sent.message_id


async def delete_join_message(context, chat_id):
    msg_id = context.user_data.get("join_msg_id")
    if not msg_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
    context.user_data.pop("join_msg_id", None)
    await context.bot.send_message(
        chat_id=chat_id,
        text="✅ *You have successfully joined our channel!*\n\nYou can now use the bot freely. Send /start to begin.",
        parse_mode="Markdown",
    )


async def check_joined_callback(update, context):
    query = update.callback_query
    user = query.from_user
    track_user(user.id, user.first_name, user.username)
    member_ok = await is_member(user.id, context)
    if not member_ok:
        await query.answer("❌ You have not joined yet! Please join first.", show_alert=True)
        return
    await query.message.delete()
    context.user_data.pop("join_msg_id", None)
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="✅ *You have successfully joined our channel!*\n\nYou can now use the bot freely. Send /start to begin.",
        parse_mode="Markdown",
    )


def main_menu_markup():
    btn_user = KeyboardButton(text="User", request_users=KeyboardButtonRequestUsers(request_id=1, max_quantity=1))
    btn_group = KeyboardButton(text="Group", request_chat=KeyboardButtonRequestChat(request_id=2, chat_is_channel=False))
    btn_channel = KeyboardButton(text="Channel", request_chat=KeyboardButtonRequestChat(request_id=3, chat_is_channel=True))
    return ReplyKeyboardMarkup([[btn_user, btn_group, btn_channel]], resize_keyboard=True)


async def show_main_menu(update, context, header=None):
    user_id = update.message.from_user.id
    parts = []
    if header:
        parts.append(header + "\n\n")
    parts.append("*Welcome To @kihoebot*\n\n")
    parts.append("*Your ID :* `" + str(user_id) + "`\n\n")
    parts.append("Send me a Telegram username or number to look up.\n")
    parts.append("Example: @username or 1234567890\n\n")
    parts.append("Or use the buttons below to get User/Group/Channel ID:")
    await update.message.reply_text("".join(parts), reply_markup=main_menu_markup(), parse_mode="Markdown")


async def guard(update, context):
    """
    Common guard: returns True if user can proceed, False otherwise.
    Checks: maintenance mode, ban, channel membership, rate limit.
    """
    global maintenance_mode
    user = update.message.from_user
    user_id = user.id

    if maintenance_mode and user_id != ADMIN_ID:
        await update.message.reply_text(
            "🔧 *Bot is under maintenance.*\n\nPlease try again after some time.",
            parse_mode="Markdown",
        )
        return False

    track_user(user_id, user.first_name, user.username)

    if not await is_member(user_id, context):
        await send_join_message(update, context)
        return False

    await delete_join_message(context, update.message.chat_id)
    return True


async def guard_with_cooldown(update, context):
    """Guard + rate limit check."""
    ok = await guard(update, context)
    if not ok:
        return False
    allowed, remaining = check_cooldown(update.message.from_user.id)
    if not allowed:
        await update.message.reply_text(
            "⏳ *Too fast!* Please wait *" + str(remaining) + " second(s)* before next request.",
            parse_mode="Markdown",
        )
        return False
    return True


async def start(update, context):
    if not await guard(update, context):
        return
    context.user_data.clear()
    await show_main_menu(update, context)



async def settings_command(update, context):
    if not await guard(update, context):
        return
    settings_text = (
        "⚙️ *Settings*\n\n"
        "*What this bot can do:*\n\n"
        "📱 *Username / UID Lookup*\n"
        "Send any @username or numeric ID to get details instantly\n\n"
        "📞 *Phone Number Lookup*\n"
        "Use `/num <number>` to fetch name, address, circle, email\n\n"
        "🪪 *Aadhar Lookup*\n"
        "Use `/aadhar <12-digit number>` to fetch linked mobile, address, email\n\n"
        "👨‍👩‍👧‍👦 *Family Info Lookup*\n"
        "Use `/familyinfo <12-digit Aadhar>` to fetch family member details\n\n"
        "🔓 *Leak Search*\n"
        "Use `/leak <email/phone/username>` to search leaked databases\n\n"
        "🌐 *IP Address Lookup*\n"
        "Use `/ip <IPv4 address>` to fetch location, ISP, VPN/proxy, fraud risk\n\n"
        "🚗 *Vehicle Lookup*\n"
        "Use `/veh <plate number>` to fetch vehicle owner info\n\n"
        "🚘 *Vehicle Info (RTO)*\n"
        "Use `/vehinfo <reg number>` for detailed RTO vehicle & insurance info\n\n"
        "📞 *Truecaller Lookup*\n"
        "Use `/true <number with country code>` to fetch caller ID\n\n"
        "🔎 *Telegram ID Lookup*\n"
        "Use `/id <username or UID>` to check TG ID, bot, premium, scam status\n\n"
        "🚗 *Vehicle Number Lookup*\n"
        "Use `/vnum <plate number>` for full owner, engine, insurance & blacklist info\n\n"
        "🌐 *DNS Lookup*\n"
        "Use `/dns <domain>` to fetch DNS records (A, AAAA, MX, TXT, NS, etc)\n\n"
        "🌤 *Weather Lookup*\n"
        "Use `/weather <city>` to get live weather, humidity, wind, UV index\n\n"
        "🌫 *AQI Lookup*\n"
        "Use `/aqi <city>` to get air quality, pollutants, health advice\n\n"
        "📮 *Pincode Lookup*\n"
        "Use `/pincode <code>` to get district, state, post offices info\n\n"
        "🎮 *Free Fire Likes*\n"
        "Use `/fflike <region> <uid>` to check likes before/after/given\n\n"
        "🎮 *Free Fire Visits*\n"
        "Use `/ffvisit <region> <uid>` to check profile visit stats\n\n"
        "👥 *User / Group / Channel ID*\n"
        "Use the buttons below to get IDs easily\n\n"
        "📝 *Report Issue*\n"
        "Use `/report <message>` to report any bot issue to admin\n\n"
        "⚡ *Fast and Automatic*\n"
        "No extra commands needed for basic lookups\n\n"
        "❓ *Help Guide*\n"
        "Use /help to see full instructions\n\n"
        "—\n\n"
        "_Thanks for using this bot._"
    )
    await update.message.reply_text(settings_text, parse_mode="Markdown")



async def help_command(update, context):
    if not await guard(update, context):
        return
    help_text = (
        "🤖 *Welcome to @kihoebot Help*\n\n"
        "Here is how to use this bot:\n\n"
        "📱 *Telegram Username / UID Lookup*\n"
        "  Just send the username or UID directly in chat.\n"
        "  No command needed.\n\n"
        "  Examples:\n"
        "   • `@username`\n"
        "   • `1234567890`\n\n"
        "📞 *Phone Number Lookup*\n"
        "  Use the /num command followed by the number.\n\n"
        "  Example:\n"
        "   • `/num 9876543210`\n\n"
        "🪪 *Aadhar Lookup*\n"
        "  Use the /aadhar command followed by 12-digit Aadhar.\n\n"
        "  Example:\n"
        "   • `/aadhar 652507323571`\n\n"
        "🚗 *Vehicle Lookup*\n"
        "  Use the /veh command followed by vehicle plate number.\n\n"
        "  Example:\n"
        "   • `/veh HR36AD4511`\n\n"
        "👤 *Your Info*\n"
        "  Use /info to see your profile and stats.\n\n"
        "📝 *Report an Issue*\n"
        "  Use the /report command followed by your message.\n"
        "  Your report will be sent directly to the admin.\n\n"
        "  Example:\n"
        "   • `/report Bot is not responding properly`\n\n"
        "🏦 *IFSC Code Lookup*\n"
        "  Use /ifsc followed by the bank IFSC code.\n\n"
        "  Example:\n"
        "   • `/ifsc SBIN0001234`\n\n"
        "📸 *Instagram Lookup*\n"
        "  Use /insta followed by the Instagram username.\n\n"
        "  Example:\n"
        "   • `/insta instagram`\n\n"
        "🇵🇰 *Pakistan Number Lookup*\n"
        "  Use /pak followed by the Pakistan mobile number.\n\n"
        "  Example:\n"
        "   • `/pak 03001234567`\n\n"
        "👨‍👩‍👧‍👦 *Family Info Lookup*\n"
        "  Use /familyinfo followed by 12-digit Aadhar number.\n\n"
        "  Example:\n"
        "   • `/familyinfo 652507323571`\n\n"
        "🔓 *Leak Search*\n"
        "  Use /leak followed by an email, phone number, or username.\n\n"
        "  Example:\n"
        "   • `/leak example@gmail.com`\n\n"
        "🚘 *Vehicle Info (RTO)*\n"
        "  Use /vehinfo followed by a vehicle registration number.\n\n"
        "  Example:\n"
        "   • `/vehinfo RJ14CV0002`\n\n"
        "📞 *Truecaller Lookup*\n"
        "  Use /true followed by a number with country code (no + or spaces).\n\n"
        "  Example:\n"
        "   • `/true 919306387163`\n\n"
        "🌐 *IP Address Lookup*\n"
        "  Use /ip followed by any IPv4 address.\n\n"
        "  Example:\n"
        "   • `/ip 106.192.134.155`\n\n"
        "🔎 *Telegram ID Lookup*\n"
        "  Use /id followed by a username or numeric UID.\n\n"
        "  Example:\n"
        "   • `/id ayush`\n"
        "   • `/id 3016488253`\n\n"
        "🚗 *Vehicle Number Lookup*\n"
        "  Use /vnum followed by a vehicle registration number.\n\n"
        "  Example:\n"
        "   • `/vnum MH01AB1234`\n\n"
        "🌤 *Weather Lookup*\n"
        "  Use /weather followed by a city name.\n\n"
        "  Example:\n"
        "   • `/weather Delhi`\n\n"
        "🌫 *AQI Lookup*\n"
        "  Use /aqi followed by a city name.\n\n"
        "  Example:\n"
        "   • `/aqi Mumbai`\n\n"
        "📮 *Pincode Lookup*\n"
        "  Use /pincode followed by an Indian pincode.\n\n"
        "  Example:\n"
        "   • `/pincode 411001`\n\n"
        "🎮 *Free Fire Likes*\n"
        "  Use /fflike followed by region and UID.\n\n"
        "  Example:\n"
        "   • `/fflike ind 123456789`\n\n"
        "🎮 *Free Fire Visits*\n"
        "  Use /ffvisit followed by region and UID.\n\n"
        "  Example:\n"
        "   • `/ffvisit ind 123456789`\n\n"
        "📋 *Available Commands*\n"
        "  /start       — Start the bot\n"
        "  /num         — Phone number lookup\n"
        "  /aadhar      — Aadhar lookup\n"
        "  /familyinfo  — Family info via Aadhar\n"
        "  /leak        — Leak database search\n"
        "  /veh         — Vehicle lookup\n"
        "  /vehinfo     — Detailed RTO vehicle info\n"
        "  /true        — Truecaller lookup\n"
        "  /ip          — IP address lookup\n"
        "  /ifsc        — Bank IFSC code lookup\n"
        "  /insta       — Instagram profile lookup\n"
        "  /pak         — Pakistan number lookup\n"
        "  /id          — Telegram ID lookup\n"
        "  /vnum        — Vehicle number full info\n"
        "  /weather     — Live weather report\n"
        "  /aqi         — Air quality & pollutants\n"
        "  /pincode     — Pincode / post office info\n"
        "  /fflike      — Free Fire likes info\n"
        "  /ffvisit     — Free Fire visit stats\n"
        "  /dns         — DNS records lookup\n"
        "  /report      — Report an issue to admin\n"
        "  /settings    — Show bot features\n"
        "  /help        — Show this help message"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def grouphelp_command(update, context):
    if not await guard(update, context):
        return
    text = (
        "🛡 *@kihoebot — Group Admin Commands*\n\n"
        "These commands can be used by group admins.\n"
        "You can use them by replying to a message, or with @username or User ID.\n\n"

        "━━━━━━━━━━━━━━━\n"
        "⚠️ *WARN COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "2 warnings = *auto-ban*\n\n"
        "`/warn` — Give a warning to a user\n"
        "`/warns` — Check how many warnings a user has\n"
        "`/resetwarn` — Reset all warnings of a user\n\n"
        "*How to use /warn:*\n"
        "• Reply to their message → `/warn spamming`\n"
        "• By username → `/warn @john rules tod raha tha`\n"
        "• By User ID → `/warn 98877655 sending adult content`\n"
        "• Without reason → `/warn` _(reply to message)_\n\n"
        "*How to use /warns:*\n"
        "• Reply to their message → `/warns`\n"
        "• By username → `/warns @john`\n"
        "• By User ID → `/warns 98877655`\n\n"
        "*How to use /resetwarn:*\n"
        "• Reply to their message → `/resetwarn`\n"
        "• By username → `/resetwarn @john`\n"
        "• By User ID → `/resetwarn 98877655`\n\n"

        "━━━━━━━━━━━━━━━\n"
        "🚫 *BAN COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "`/ban` — Ban a user from using the bot\n"
        "`/unban` — Remove ban from a user\n"
        "`/banlist` — See all banned users\n\n"
        "*How to use /ban:*\n"
        "• Reply to their message → `/ban was spamming`\n"
        "• By username → `/ban @john sending scam links`\n"
        "• By User ID → `/ban 98877655 abusive behaviour`\n"
        "• Without reason → `/ban` _(reply to message)_\n\n"
        "*How to use /unban:*\n"
        "• Reply to their message → `/unban`\n"
        "• By username → `/unban @john`\n"
        "• By User ID → `/unban 98877655`\n\n"

        "━━━━━━━━━━━━━━━\n"
        "🔇 *MUTE COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "`/mute` — Mute a user _(they cannot use the bot)_\n"
        "`/unmute` — Remove mute from a user\n"
        "`/mutelist` — See all muted users\n\n"
        "*How to use /mute:*\n"
        "• Reply to their message → `/mute too much spam`\n"
        "• By username → `/mute @john disturbing others`\n"
        "• By User ID → `/mute 98877655 bad language`\n"
        "• Without reason → `/mute` _(reply to message)_\n\n"
        "*How to use /unmute:*\n"
        "• Reply to their message → `/unmute`\n"
        "• By username → `/unmute @john`\n"
        "• By User ID → `/unmute 98877655`\n\n"

        "━━━━━━━━━━━━━━━\n"
        "📋 *OTHER COMMANDS*\n"
        "━━━━━━━━━━━━━━━\n\n"
        "`/info` — Check info of any user\n"
        "• Reply to their message → `/info`\n"
        "• By username → `/info @john`\n"
        "• By User ID → `/info 98877655`\n\n"
        "`/adminhelp` — Full admin command list\n\n"
        "━━━━━━━━━━━━━━━\n"
        "_Tip: Replying to a message is the easiest way — no need to type ID or username!_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")




async def stats_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    total, searches, today_joined = get_stats_db()
    msg = (
        "📊 *Bot Stats*\n\n"
        "👥 *Total Users:* `" + str(total) + "`\n"
        "📅 *Joined Today:* `" + str(today_joined) + "`\n"
        "🔍 *Total Searches:* `" + str(searches) + "`\n"
        "🔧 *Maintenance:* `" + ("ON" if maintenance_mode else "OFF") + "`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def adminhelp_command(update, context):
    user_id = update.message.from_user.id
    if not await check_admin(update, context):
        return
    text = (
        "🛡 *Admin Commands*\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📋 *ADMIN*\n"
        "━━━━━━━━━━━━━━━\n"
        "`/stats` — Bot stats\n\n"
        "`/info` — User info _(reply or ID)_\n\n"
        "`/reply` — Send message to user\n\n"
        "`/broadcast` — Broadcast to all users\n\n"
        "`/maintenance on/off` — Enable/disable maintenance\n\n"
        "━━━━━━━━━━━━━━━\n"
        "_Tip: Reply to a message and use command — no need to remember IDs!_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def maintenance_command(update, context):
    global maintenance_mode
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args:
        current = "ON" if maintenance_mode else "OFF"
        await update.message.reply_text(
            "🔧 *Maintenance Mode*\n\nCurrent: *" + current + "*\n\nUsage: `/maintenance on` or `/maintenance off`",
            parse_mode="Markdown",
        )
        return
    arg = context.args[0].lower()
    if arg == "on":
        maintenance_mode = True
        await update.message.reply_text("🔧 *Maintenance mode ON.*\n\nUsers cannot use the bot now.", parse_mode="Markdown")
    elif arg == "off":
        maintenance_mode = False
        await update.message.reply_text("✅ *Maintenance mode OFF.*\n\nBot is live again.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ *Use:* `/maintenance on` or `/maintenance off`", parse_mode="Markdown")


async def report_command(update, context):
    if not await guard(update, context):
        return
    if not context.args:
        usage = (
            "📝 *Report an Issue*\n\n"
            "*Usage:* `/report <your message>`\n\n"
            "*Example:*\n"
            "`/report Bot is not responding to username lookup`\n\n"
            "_Your message will be sent directly to the admin._"
        )
        await update.message.reply_text(usage, parse_mode="Markdown")
        return
    user = update.message.from_user
    report_text = " ".join(context.args)
    username = "@" + user.username if user.username else "N/A"
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    full_name = full_name.strip() or "Unknown"
    admin_msg = (
        "🚨 *New Report Received*\n\n"
        "*From:* " + full_name + "\n"
        "*Username:* " + username + "\n"
        "*User ID:* `" + str(user.id) + "`\n\n"
        "*Message:*\n" + report_text
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ *Report Sent Successfully!*\n\nYour message has been delivered to the admin. You will receive a response soon.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text("❌ *Failed to send report.*\nPlease try again after some time.", parse_mode="Markdown")
        await log_error_to_admin(context, "report_command: " + str(e))


async def reply_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "*Usage:* `/reply <user_id> <your message>`\n\n"
            "*Example:*\n`/reply 1234567890 Thanks, we have fixed the issue!`",
            parse_mode="Markdown",
        )
        return
    target_id = context.args[0]
    if not target_id.isdigit():
        await update.message.reply_text("❌ *Invalid User ID!*", parse_mode="Markdown")
        return
    message = " ".join(context.args[1:])
    reply_text = "💬 *Reply from Admin*\n\n" + message
    try:
        await context.bot.send_message(chat_id=int(target_id), text=reply_text, parse_mode="Markdown")
        await update.message.reply_text(
            "✅ *Reply sent successfully!*\n\n"
            "*Sent to User ID:* `" + target_id + "`\n"
            "*Message:* " + message,
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(
            "❌ *Failed to send reply.*\n\nUser may have blocked the bot or ID is wrong.\n*Error:* " + str(e),
            parse_mode="Markdown",
        )


async def num_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/num 9876543219`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    number = context.args[0].replace("+", "").replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")

    def parse_entries(rows):
        seen = set()
        result = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            key = (str(r.get("NAME") or r.get("name") or "").lower().strip(), str(r.get("MOBILE") or r.get("mobile") or ""))
            if key not in seen:
                seen.add(key)
                result.append({
                    "name":    r.get("NAME") or r.get("name"),
                    "father":  r.get("fname"),
                    "mobile":  r.get("MOBILE") or r.get("mobile"),
                    "alt":     r.get("alt"),
                    "aadhar":  r.get("id"),
                    "email":   r.get("email"),
                    "circle":  r.get("circle"),
                    "address": r.get("ADDRESS") or r.get("address"),
                })
        return result

    async def fetch_api1():
        try:
            data = await fetch_json(IA_NUM_URL.format(number=number), timeout=8)
            if isinstance(data, dict) and data.get("success"):
                raw = data.get("data", {})
                if isinstance(raw, list):
                    rows = raw
                elif isinstance(raw, dict):
                    # "data" list format
                    if "data" in raw and isinstance(raw["data"], list):
                        rows = raw["data"]
                    else:
                        # digit-key format: {"0":{...},"1":{...},...}
                        rows = [v for k, v in raw.items() if k.isdigit() and isinstance(v, dict)]
                else:
                    rows = []
                return parse_entries(rows)
        except Exception:
            pass
        return []

    entries = await fetch_api1()

    await delete_msg(context, chat_id, searching.message_id)

    if not entries:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this number.", parse_mode="Markdown")
        return

    increment_search(user_id)

    result_message_ids = []
    for i, entry in enumerate(entries, 1):
        text = (
            "*Result " + str(i) + "/" + str(len(entries)) + "*\n\n"
            "*Number:* `" + number + "`\n"
            "*Name:* `" + str(entry.get("name") or "None") + "`\n"
            "*Father:* `" + str(entry.get("father") or "None") + "`\n"
            "*Mobile:* `" + str(entry.get("mobile") or "None") + "`\n"
            "*Alt Mobile:* `" + str(entry.get("alt") or "None") + "`\n"
            "*National ID:* `" + str(entry.get("aadhar") or "None") + "`\n"
            "*Email:* `" + str(entry.get("email") or "None") + "`\n"
            "*Circle:* `" + str(entry.get("circle") or "None") + "`\n"
            "*Address:* `" + clean_address(entry.get("address")) + "`"
        )
        sent = await update.message.reply_text(text, parse_mode="Markdown")
        result_message_ids.append(sent.message_id)
    schedule_result_cleanup(context, chat_id, result_message_ids)


async def aadhar_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/aadhar 652507323571`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    aadhar = context.args[0].replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")

    def parse_aadhar_inner(inner):
        if isinstance(inner, dict):
            raw = [v for k, v in inner.items() if k.isdigit() and isinstance(v, dict)]
        elif isinstance(inner, list):
            raw = inner
        else:
            raw = []
        seen = set()
        result = []
        for r in raw:
            if not isinstance(r, dict):
                continue
            key = (str(r.get("NAME") or r.get("name") or "").lower().strip(), str(r.get("MOBILE") or r.get("mobile") or ""))
            if key not in seen:
                seen.add(key)
                result.append({
                    "name":    r.get("NAME") or r.get("name"),
                    "father":  r.get("fname"),
                    "mobile":  r.get("MOBILE") or r.get("mobile"),
                    "alt":     r.get("alt"),
                    "aadhar":  r.get("id"),
                    "email":   r.get("email"),
                    "circle":  r.get("circle"),
                    "address": r.get("ADDRESS") or r.get("address"),
                })
        return result

    async def fetch_aadhar_api1():
        try:
            data = await fetch_json(IA_ADHAR_URL.format(aadhar=aadhar), timeout=8)
            if isinstance(data, dict) and data.get("success"):
                return parse_aadhar_inner(data.get("data", {}))
        except Exception:
            pass
        return []

    entries = await fetch_aadhar_api1()

    await delete_msg(context, chat_id, searching.message_id)

    if not entries:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this Aadhar.", parse_mode="Markdown")
        return

    increment_search(user_id)

    result_message_ids = []
    for i, entry in enumerate(entries, 1):
        text = (
            "*Result " + str(i) + "/" + str(len(entries)) + "*\n\n"
            "*Aadhar:* `" + aadhar + "`\n"
            "*Name:* `" + str(entry.get("name") or "None") + "`\n"
            "*Father:* `" + str(entry.get("father") or "None") + "`\n"
            "*Mobile:* `" + str(entry.get("mobile") or "None") + "`\n"
            "*Alt Mobile:* `" + str(entry.get("alt") or "None") + "`\n"
            "*National ID:* `" + str(entry.get("aadhar") or "None") + "`\n"
            "*Email:* `" + str(entry.get("email") or "None") + "`\n"
            "*Circle:* `" + str(entry.get("circle") or "None") + "`\n"
            "*Address:* `" + clean_address(entry.get("address")) + "`"
        )
        sent = await update.message.reply_text(text, parse_mode="Markdown")
        result_message_ids.append(sent.message_id)
    schedule_result_cleanup(context, chat_id, result_message_ids)




async def veh_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/veh HR36AD4511`\n\n_Enter the vehicle plate number._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    plate = context.args[0].strip().upper().replace(" ", "")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        url = IA_VEH_URL.format(veh=plate)
        raw = await fetch_json(url, timeout=10)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "veh_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this vehicle number.", parse_mode="Markdown")
        return

    data = raw.get("data")
    if not data or (isinstance(data, str) and ("suspended" in data.lower() or "<!doctype" in data.lower())):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this vehicle number.", parse_mode="Markdown")
        return

    increment_search(user_id)

    SKIP_KEYS = {"status", "message", "msg", "error", "success", "code", "key", "developer", "attempt", "cached", "mob raw", "response code", "vnum"}
    LABEL_MAP = {
        "rc_regn_no": "Plate No", "reg_no": "Plate No",
        "rc_owner_name": "Owner Name", "owner": "Owner Name",
        "rc_father_name": "Father Name",
        "rc_present_address": "Address", "address": "Address",
        "rc_mobile_no": "Mobile",
        "rc_veh_class_desc": "Vehicle Class", "class": "Vehicle Class",
        "rc_maker_desc": "Maker", "maker": "Maker",
        "rc_model": "Model", "model": "Model",
        "rc_color": "Color", "color": "Color",
        "rc_fuel_desc": "Fuel Type", "fuel": "Fuel Type",
        "rc_regn_dt": "Reg Date", "reg_date": "Reg Date",
        "rc_fit_upto": "Fitness Upto",
        "rc_insurance_comp": "Insurance Co",
        "rc_insurance_upto": "Insurance Upto",
        "rc_financer": "Financer",
        "rc_status": "RC Status",
        "rc_pucc_upto": "PUC Upto",
        "rc_state": "State",
    }

    def flatten_veh(obj, prefix=""):
        items = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                items.update(flatten_veh(v, k))
        elif isinstance(obj, list) and len(obj) > 0:
            items.update(flatten_veh(obj[0], prefix))
        else:
            if prefix and str(obj).strip() and str(obj).lower() not in ("none", "null", "n/a", "", "0"):
                items[prefix.lower()] = str(obj).strip()
        return items

    flat = flatten_veh(data)
    lines = ["🚗 *Vehicle Info*\n\n*Plate:* `" + plate + "`"]
    for k, v in flat.items():
        if k in SKIP_KEYS:
            continue
        label = LABEL_MAP.get(k, k.replace("_", " ").title())
        lines.append("*" + label + ":* `" + v + "`")

    if len(lines) <= 1:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this vehicle number.", parse_mode="Markdown")
        return

    sent = await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def handle_users_shared(update, context):
    if not await guard(update, context):
        return
    if update.message.users_shared:
        result_message_ids = []
        for user in update.message.users_shared.users:
            sent = await update.message.reply_text("*User ID:* `" + str(user.user_id) + "`", parse_mode="Markdown")
            result_message_ids.append(sent.message_id)
        schedule_result_cleanup(context, update.message.chat_id, result_message_ids)


async def handle_chat_shared(update, context):
    if not await guard(update, context):
        return
    if update.message.chat_shared:
        sent = await update.message.reply_text("*Chat ID:* `" + str(update.message.chat_shared.chat_id) + "`", parse_mode="Markdown")
        schedule_result_cleanup(context, update.message.chat_id, [sent.message_id])


async def lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return

    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_input = update.message.text.strip()

    chat_type = update.message.chat.type
    bot_username = (await context.bot.get_me()).username

    if chat_type in ["group", "supergroup"]:
        if "@" + bot_username.lower() in user_input.lower():
            user_input = re.sub(re.escape("@" + bot_username), "", user_input, flags=re.IGNORECASE).strip()
            if not user_input:
                return

    is_username = user_input.startswith("@") and len(user_input) > 1
    digits_only = user_input.lstrip("+")
    is_number = digits_only.isdigit() and len(digits_only) >= 7

    if not is_username and not is_number:
        return

    searching = await update.message.reply_text("🔍 Searching...")

    term = user_input if is_username else digits_only

    data = None
    used_api = ""

    def _is_valid(d):
        if not d or not isinstance(d, dict):
            return False
        status = str(d.get("status", "")).lower()
        msg = str(d.get("message", "") or d.get("msg", "") or d.get("error", "")).lower()
        if status in ("false", "0", "error", "fail", "failed") or "not found" in msg or "invalid" in msg or "no data" in msg:
            return False
        # invalidayushh: success=false but result has partial data (tg_id/username) — still usable
        if d.get("success") is False:
            result = d.get("result") or d.get("data")
            if isinstance(result, dict) and (result.get("tg_id") or result.get("username")):
                return True
            return False
        # success=true but empty result
        if d.get("success") is True:
            result = d.get("result") or d.get("data")
            # RootX style: data is directly in root (has "number" or "tg_id" key)
            if not result:
                if d.get("number") or d.get("tg_id"):
                    return True
                return False
        return True

    async def _try_fetch(url):
        try:
            r = await fetch_json(url, timeout=8)
            return r if _is_valid(r) else None
        except Exception:
            return None

    # RootX TG to Number API
    data = await _try_fetch(ROOTX_TG_NUM_URL.format(term=term))
    # Retry once if failed
    if data is None:
        data = await _try_fetch(ROOTX_TG_NUM_URL.format(term=term))

    # Fallback Telegram-to-number API when the primary source returns no data.
    if data is None:
        data = await _try_fetch(
            TG_NUM_FALLBACK_URL.format(term=quote(term, safe="@"))
        )

    await delete_msg(context, chat_id, searching.message_id)

    def tg_not_found_msg(uid):
        return "*❌ Data Not Found!*\n\nNo data linked to this Telegram account."

    # Check for error / not found
    if isinstance(data, dict):
        status = str(data.get("status", "")).lower()
        msg = str(data.get("message", "") or data.get("msg", "") or data.get("error", "")).lower()
        if status in ("false", "0", "error", "fail", "failed") or "not found" in msg or "invalid" in msg or "no data" in msg:
            await send_expiring_lookup_message(update, context, tg_not_found_msg(user_id), parse_mode="Markdown")
            return
        if not data or (isinstance(data.get("data"), (list, dict)) and not data.get("data")):
            await send_expiring_lookup_message(update, context, tg_not_found_msg(user_id), parse_mode="Markdown")
            return

    increment_search(user_id)

    # Build result from whatever the API returns
    SKIP_KEYS = {
        "status", "message", "msg", "error", "success", "code", "key", "type",
        "owner", "cached", "attempt", "powered by", "time", "version",
        "powered_by", "tag", "developer", "key_expiry", "key expiry",
        "key_exp", "dev", "credit", "req_left", "req_total", "expiry",
        "response_time", "used today", "used_today", "daily limit",
        "daily_limit", "valid days", "valid_days", "expires on", "expires_on",
        "status code", "status_code", "http status", "http_status",
    }
    LABEL_MAP = {
        "number": "Number", "phone": "Number", "mobile": "Number",
        "id": "TG ID", "user_id": "TG ID", "tg_id": "TG ID", "userid": "TG ID",
        "name": "Name", "first_name": "First Name", "last_name": "Last Name",
        "username": "Username",
        "country": "Country", "country_code": "Country Code",
        "email": "Email", "dob": "DOB", "gender": "Gender",
        "operator": "Operator", "circle": "Circle", "state": "State",
    }

    def flatten(obj, prefix=""):
        items = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                items.update(flatten(v, k))
        elif isinstance(obj, list) and len(obj) > 0:
            items.update(flatten(obj[0], prefix))
        else:
            if prefix and str(obj).strip() and str(obj).lower() not in ("none", "null", "n/a", ""):
                items[prefix.lower()] = str(obj).strip()
        return items

    flat = flatten(data)
    lines = ["*Result:*\n"]
    for k, v in flat.items():
        if k in SKIP_KEYS:
            continue
        label = LABEL_MAP.get(k, k.replace("_", " ").title())
        lines.append("*" + label + ":* `" + v + "`")

    if len(lines) <= 1:
        await send_expiring_lookup_message(update, context, tg_not_found_msg(user_id), parse_mode="Markdown")
        return

    sent = await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def broadcast_command(update, context):
    user_id = update.message.from_user.id
    if user_id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "📢 *Broadcast Usage:*\n\n`/broadcast Aapka message yahan`",
            parse_mode="Markdown",
        )
        return
    message = " ".join(context.args)
    user_ids = get_all_user_ids_db()
    if not user_ids:
        await update.message.reply_text("❌ *No users found!*", parse_mode="Markdown")
        return
    status_msg = await update.message.reply_text("📤 *Broadcasting...*", parse_mode="Markdown")
    sent = 0
    failed = 0
    broadcast_text = "📢 *Message from Admin:*\n\n" + message
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(
        "✅ *Broadcast Complete!*\n\n"
        "*Total Users:* `" + str(len(user_ids)) + "`\n"
        "*Sent:* `" + str(sent) + "`\n"
        "*Failed:* `" + str(failed) + "`",
        parse_mode="Markdown",
    )




async def ifsc_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/ifsc SBIN0001234`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    code = context.args[0].strip().upper()
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        data = await fetch_json(IA_IFSC_URL.format(code=code), timeout=8)
    except Exception:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        return
    await delete_msg(context, chat_id, searching.message_id)
    if not isinstance(data, dict) or not data.get("success") or not data.get("data"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this IFSC code.", parse_mode="Markdown")
        return
    increment_search(user_id)
    d = data["data"]
    def bval(v):
        if v is True: return "✅ Yes"
        if v is False: return "❌ No"
        return str(v) if v else "N/A"
    text = (
        "🏦 *IFSC Lookup Result*\n\n"
        "*IFSC:* `" + bval(d.get("IFSC")) + "`\n"
        "*Bank:* `" + bval(d.get("BANK")) + "`\n"
        "*Branch:* `" + bval(d.get("BRANCH")) + "`\n"
        "*City:* `" + bval(d.get("CITY")) + "`\n"
        "*District:* `" + bval(d.get("DISTRICT")) + "`\n"
        "*State:* `" + bval(d.get("STATE")) + "`\n"
        "*Address:* `" + bval(d.get("ADDRESS")) + "`\n"
        "*MICR:* `" + bval(d.get("MICR")) + "`\n"
        "*Contact:* `" + bval(d.get("CONTACT")) + "`\n"
        "*NEFT:* " + bval(d.get("NEFT")) + "  "
        "*RTGS:* " + bval(d.get("RTGS")) + "  "
        "*IMPS:* " + bval(d.get("IMPS")) + "  "
        "*UPI:* " + bval(d.get("UPI"))
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def insta_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/insta username`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    username = context.args[0].strip().lstrip("@")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        data = await fetch_json(IA_INSTA_URL.format(username=username), timeout=10)
    except Exception:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        return
    await delete_msg(context, chat_id, searching.message_id)
    profile = None
    if isinstance(data, dict) and data.get("success"):
        result = data.get("result", {})
        if isinstance(result, dict):
            profile = result.get("profile")
    if not profile:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this Instagram username.", parse_mode="Markdown")
        return
    increment_search(user_id)
    def iv(v):
        return str(v) if v not in (None, "") else "N/A"
    def fmt_num(n):
        try:
            n = int(n)
            if n >= 1_000_000: return str(round(n/1_000_000, 1)) + "M"
            if n >= 1_000: return str(round(n/1_000, 1)) + "K"
            return str(n)
        except Exception:
            return str(n)
    verified = "✅ Yes" if profile.get("is_verified") else "❌ No"
    private = "🔒 Private" if profile.get("is_private") else "🌐 Public"
    bio = str(profile.get("biography") or "N/A").replace("_", "\\_").replace("*", "\\*")
    text = (
        "📸 *Instagram Lookup Result*\n\n"
        "*Username:* `@" + iv(profile.get("username")) + "`\n"
        "*Full Name:* `" + iv(profile.get("full_name")) + "`\n"
        "*User ID:* `" + iv(profile.get("id")) + "`\n"
        "*Followers:* `" + fmt_num(profile.get("followers", 0)) + "`\n"
        "*Following:* `" + fmt_num(profile.get("following", 0)) + "`\n"
        "*Posts:* `" + iv(profile.get("posts")) + "`\n"
        "*Verified:* " + verified + "\n"
        "*Account:* " + private + "\n"
        "*Bio:* " + bio
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def pak_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text("*Usage:* `/pak 03001234567`", parse_mode="Markdown")
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    number = context.args[0].replace("+", "").replace(" ", "").replace("-", "")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        data = await fetch_json(IA_PAK_URL.format(number=number), timeout=8)
    except Exception:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        return
    await delete_msg(context, chat_id, searching.message_id)
    entries = []
    if isinstance(data, dict) and data.get("success"):
        result = data.get("result", {})
        if isinstance(result, dict):
            inner = result.get("data", {})
            if isinstance(inner, dict):
                rows = inner.get("data", {})
                if isinstance(rows, dict):
                    results_list = rows.get("results", [])
                    if isinstance(results_list, list):
                        entries = results_list
                elif isinstance(rows, list):
                    entries = rows
    if not entries:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this Pakistan number.", parse_mode="Markdown")
        return
    increment_search(user_id)
    result_message_ids = []
    for i, entry in enumerate(entries, 1):
        def pv(v): return str(v) if v not in (None, "") else "None"
        text = (
            "*Result " + str(i) + "/" + str(len(entries)) + "*\n\n"
            "*Number:* `" + number + "`\n"
            "*Name:* `" + pv(entry.get("name") or entry.get("NAME")) + "`\n"
            "*Address:* `" + pv(entry.get("address") or entry.get("ADDRESS")) + "`\n"
            "*Operator:* `" + pv(entry.get("operator") or entry.get("circle")) + "`"
        )
        sent = await update.message.reply_text(text, parse_mode="Markdown")
        result_message_ids.append(sent.message_id)
    schedule_result_cleanup(context, chat_id, result_message_ids)


async def ip_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/ip 106.192.134.155`\n\n_Enter any IPv4 address._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    ip = context.args[0].strip()
    searching = await update.message.reply_text("🔍 Searching IP info...")
    try:
        data = await fetch_json(IP_API_URL.format(ip=ip), timeout=12)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "ip_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(data, dict) or str(data.get("status", "")).lower() != "success":
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this IP.", parse_mode="Markdown")
        return

    increment_search(user_id)

    results = data.get("results", {})

    def gv(*keys):
        for src in results.values():
            if not isinstance(src, dict):
                continue
            for k in keys:
                v = src.get(k)
                if v and str(v).strip() and str(v).lower() not in ("none", "null", "n/a", ""):
                    return str(v).strip()
        return "None"

    s1 = results.get("source_1_ipapi_com", {})
    s4 = results.get("source_4_ipwhois", {})
    s5 = results.get("source_5_ipinfo_io", {})
    s8 = results.get("source_8_mega_enterprise_intel", {})
    s9 = results.get("source_9_fraud_risk_score", {})
    s10 = results.get("source_10_vehicle_rto_intel", {})

    city    = gv("city")
    region  = gv("region")
    country = s1.get("country") or gv("country")
    isp     = s1.get("isp") or s4.get("isp") or gv("isp")
    loc     = s5.get("loc") or "None"
    zipcode = s1.get("zip") or gv("postal", "zip") or "None"
    ip_type = s4.get("type") or s9.get("connection_type") or "None"
    timezone = s8.get("timezone_name") or gv("timezone") or "None"
    is_vpn  = s8.get("is_vpn_or_proxy") or "None"
    is_mobile = s8.get("is_mobile_data") or "None"
    is_hosting = s8.get("is_hosting_server") or "None"
    fraud   = s9.get("fraud_risk_score") or "None"
    is_tor  = s9.get("is_tor_network") or "None"
    currency = s8.get("currency_name") or gv("currency_code") or "None"
    veh_state = s10.get("detected_region_state") or "None"
    veh_prefix = s10.get("expected_vehicle_plate_prefix") or "None"

    text = (
        "🌐 *IP Lookup Result*\n\n"
        "*IP:* `" + ip + "`\n"
        "*Type:* `" + ip_type + "`\n\n"
        "📍 *Location*\n"
        "*City:* `" + city + "`\n"
        "*Region:* `" + region + "`\n"
        "*Country:* `" + country + "`\n"
        "*ZIP:* `" + zipcode + "`\n"
        "*Coordinates:* `" + loc + "`\n"
        "*Timezone:* `" + timezone + "`\n\n"
        "📡 *Network*\n"
        "*ISP:* `" + isp + "`\n"
        "*Currency:* `" + currency + "`\n\n"
        "🔐 *Security*\n"
        "*VPN/Proxy:* `" + is_vpn + "`\n"
        "*Mobile Data:* `" + is_mobile + "`\n"
        "*Hosting Server:* `" + is_hosting + "`\n"
        "*Tor Network:* `" + is_tor + "`\n"
        "*Fraud Risk:* `" + fraud + "`\n\n"
        "🚗 *RTO Intel*\n"
        "*State:* `" + veh_state + "`\n"
        "*Vehicle Prefix:* `" + veh_prefix + "`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def familyinfo_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/familyinfo 652507323571`\n\n_Enter 12-digit Aadhar number._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    aadhar = context.args[0].replace(" ", "").replace("-", "")
    if len(aadhar) != 12 or not aadhar.isdigit():
        await update.message.reply_text("*❌ Invalid Aadhar!*\n\nPlease enter a valid 12-digit Aadhar number.", parse_mode="Markdown")
        return

    searching = await update.message.reply_text("🔍 Searching family info...")
    try:
        raw = await fetch_json(IA_FAMILYINFO_URL.format(aadhar=aadhar), timeout=12)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "familyinfo_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo family info found for this Aadhar.", parse_mode="Markdown")
        return

    data = raw.get("data") or raw.get("result")
    if not data:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo family info found for this Aadhar.", parse_mode="Markdown")
        return

    increment_search(user_id)

    SKIP_KEYS = {"status", "message", "msg", "error", "success", "code", "key", "developer", "attempt", "cached"}
    LABEL_MAP = {
        "name": "Name", "fname": "Father Name", "mobile": "Mobile",
        "alt": "Alt Mobile", "id": "Aadhar", "email": "Email",
        "address": "Address", "circle": "Circle", "dob": "DOB",
        "gender": "Gender", "state": "State", "district": "District",
        "pincode": "Pincode", "relation": "Relation",
    }

    def flatten_family(obj, prefix=""):
        items = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                items.update(flatten_family(v, k))
        elif isinstance(obj, list) and len(obj) > 0:
            for i, item in enumerate(obj):
                sub = flatten_family(item, prefix)
                for sk, sv in sub.items():
                    items[sk + "_" + str(i) if sk in items else sk] = sv
        else:
            if prefix and str(obj).strip() and str(obj).lower() not in ("none", "null", "n/a", "", "0"):
                items[prefix.lower()] = str(obj).strip()
        return items

    if isinstance(data, list):
        members = data
    elif isinstance(data, dict):
        members = data.get("members") or data.get("family") or data.get("results") or [data]
    else:
        members = []

    result_message_ids = []
    if members and isinstance(members, list) and len(members) > 0:
        for i, member in enumerate(members, 1):
            flat = flatten_family(member)
            lines = ["👨‍👩‍👧‍👦 *Family Info — Member " + str(i) + "/" + str(len(members)) + "*\n\n*Aadhar:* `" + aadhar + "`"]
            for k, v in flat.items():
                if any(k.startswith(sk) for sk in SKIP_KEYS):
                    continue
                base_key = k.split("_")[0] if "_" in k else k
                label = LABEL_MAP.get(base_key, k.replace("_", " ").title())
                lines.append("*" + label + ":* `" + v + "`")
            if len(lines) > 1:
                sent = await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
                result_message_ids.append(sent.message_id)
    else:
        flat = flatten_family(data)
        lines = ["👨‍👩‍👧‍👦 *Family Info*\n\n*Aadhar:* `" + aadhar + "`"]
        for k, v in flat.items():
            if k in SKIP_KEYS:
                continue
            label = LABEL_MAP.get(k, k.replace("_", " ").title())
            lines.append("*" + label + ":* `" + v + "`")
        if len(lines) <= 1:
            await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo family info found for this Aadhar.", parse_mode="Markdown")
            return
        sent = await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        result_message_ids.append(sent.message_id)
    schedule_result_cleanup(context, chat_id, result_message_ids)


def _leak_cache_put(user_id, query, pages):
    global _leak_cache_seq
    _leak_cache_seq += 1
    key = str(_leak_cache_seq)
    LEAK_PAGE_CACHE[key] = {"user_id": user_id, "query": query, "pages": pages}
    LEAK_CACHE_ORDER.append(key)
    while len(LEAK_CACHE_ORDER) > LEAK_CACHE_LIMIT:
        old_key = LEAK_CACHE_ORDER.pop(0)
        LEAK_PAGE_CACHE.pop(old_key, None)
    return key


def build_leak_page(user_id, query, pages, page_index):
    key = _leak_cache_put(user_id, query, pages)
    total = len(pages)
    text = pages[page_index] + "_Page " + str(page_index + 1) + "/" + str(total) + "_"
    buttons = [
        InlineKeyboardButton("⬅️", callback_data="leakpg:" + key + ":" + str(page_index - 1) if page_index > 0 else "leakpg:noop"),
        InlineKeyboardButton(str(page_index + 1) + "/" + str(total), callback_data="leakpg:noop"),
        InlineKeyboardButton("➡️", callback_data="leakpg:" + key + ":" + str(page_index + 1) if page_index < total - 1 else "leakpg:noop"),
    ]
    return text, InlineKeyboardMarkup([buttons])


async def leak_page_callback(update, context):
    query_cb = update.callback_query
    data = query_cb.data or ""
    if data == "leakpg:noop":
        await query_cb.answer()
        return
    try:
        _, key, page_str = data.split(":", 2)
        page_index = int(page_str)
    except Exception:
        await query_cb.answer()
        return

    entry = LEAK_PAGE_CACHE.get(key)
    if not entry:
        await query_cb.answer("⚠️ This result has expired. Please run /leak again.", show_alert=True)
        return
    if query_cb.from_user.id != entry["user_id"]:
        await query_cb.answer("⚠️ Only the person who searched can navigate this.", show_alert=True)
        return

    pages = entry["pages"]
    if page_index < 0 or page_index >= len(pages):
        await query_cb.answer()
        return

    total = len(pages)
    text = pages[page_index] + "_Page " + str(page_index + 1) + "/" + str(total) + "_"
    buttons = [
        InlineKeyboardButton("⬅️", callback_data="leakpg:" + key + ":" + str(page_index - 1) if page_index > 0 else "leakpg:noop"),
        InlineKeyboardButton(str(page_index + 1) + "/" + str(total), callback_data="leakpg:noop"),
        InlineKeyboardButton("➡️", callback_data="leakpg:" + key + ":" + str(page_index + 1) if page_index < total - 1 else "leakpg:noop"),
    ]
    try:
        await query_cb.edit_message_text(text, reply_markup=InlineKeyboardMarkup([buttons]), parse_mode="Markdown")
    except Exception:
        pass
    await query_cb.answer()


async def vehinfo_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/vehinfo RJ14CV0002`\n\n_Enter the vehicle registration number._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    reg = context.args[0].strip().upper().replace(" ", "")

    searching = await update.message.reply_text("🔍 Searching vehicle database...")
    try:
        raw = await fetch_json(VEHINFO_URL.format(reg=reg), timeout=15)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "vehinfo_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    resp = raw.get("response") if isinstance(raw, dict) else None
    if not isinstance(resp, dict) or not resp:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this vehicle number.", parse_mode="Markdown")
        return

    increment_search(user_id)

    rto = resp.get("rtoData") or {}
    insurance_status = "✅ Active" if resp.get("insuranceExpired") is False else "⚠️ Expired"

    text = (
        "🚗 *Vehicle Information*\n"
        "*Reg Number:* `" + val(resp.get("regNo")) + "`\n"
        "*RTO:* `" + val(rto.get("rtoName")) + " (" + val(rto.get("rtoCode")) + ")` — `" + val(rto.get("statename")) + "`\n\n"
        "👤 *Owner Details*\n"
        "• *Name:* `" + val(resp.get("owner")) + "`\n"
        "• *Present Address:* `" + val(resp.get("presentAddress")) + "`\n"
        "• *Permanent Address:* `" + val(resp.get("permAddress")) + "`\n"
        "• *Financer:* `" + val(resp.get("financerName")) + "`\n\n"
        "🚘 *Vehicle Details*\n"
        "• *Manufacturer:* `" + val(resp.get("manufacturer")) + "`\n"
        "• *Model:* `" + val(resp.get("vehicle")) + " (" + val(resp.get("variant")) + ")`\n"
        "• *Class:* `" + val(resp.get("vehicleClass")) + "`\n"
        "• *Fuel Type:* `" + val(resp.get("fuelType")) + "` | `" + val(resp.get("cubicCapacity")) + " cc`\n"
        "• *Seat Capacity:* `" + val(resp.get("seatCapacity")) + "`\n"
        "• *Chassis No:* `" + val(resp.get("chassis")) + "`\n"
        "• *Engine No:* `" + val(resp.get("engine")) + "`\n"
        "• *Registration Date:* `" + val(resp.get("regDate")) + "`\n\n"
        "🛡 *Insurance & PUCC*\n"
        "• *Insurer:* `" + val(resp.get("insuranceCompanyName")) + "`\n"
        "• *Policy No:* `" + val(resp.get("insurancePolicyNumber")) + "`\n"
        "• *Valid Upto:* `" + val(resp.get("insuranceUpto")) + "`\n"
        "• *Status:* " + insurance_status + "\n"
        "• *PUCC No:* `" + val(resp.get("puccNumber")) + "`\n"
        "• *PUCC Valid Upto:* `" + val(resp.get("puccValidUpto")) + "`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def true_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/true 919306387163`\n\n_Enter the number with country code, no + or spaces._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    phone = context.args[0].strip().replace("+", "").replace(" ", "")

    searching = await update.message.reply_text("🔍 Looking up caller ID...")

    async def fetch_truecaller_api1():
        try:
            return await fetch_json(TRUECALLER_URL.format(phone=phone), timeout=15)
        except Exception:
            return None

    async def fetch_truecaller_api2():
        try:
            return await fetch_json(RACK_TRUECALLER_URL.format(phone=phone), timeout=15)
        except Exception:
            return None

    raw1, raw2 = await asyncio.gather(fetch_truecaller_api1(), fetch_truecaller_api2())

    await delete_msg(context, chat_id, searching.message_id)

    record = raw1.get("record") if isinstance(raw1, dict) else None
    rack_data = raw2.get("data") if isinstance(raw2, dict) and raw2.get("success") else None

    # Need at least one source to have data
    has_api1 = isinstance(record, dict) and record.get("name")
    has_api2 = isinstance(rack_data, dict) and rack_data

    if not has_api1 and not has_api2:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo caller info found for this number.", parse_mode="Markdown")
        return

    increment_search(user_id)

    display_number = phone
    if not display_number.startswith("+"):
        display_number = "+" + display_number
    wa_link = "https://wa.me/" + display_number
    tg_link = "https://t.me/" + display_number

    # Skip internal/watermark keys from rack API
    RACK_SKIP = {"owner", "admin", "Number"}

    lines = ["┏━━━━━━━━━━━━━━━━━┓", "┃  📞 *Truecaller Lookup*", "┗━━━━━━━━━━━━━━━━━┛", ""]
    lines.append("*Number:* `" + display_number + "` 🇮🇳")
    lines.append("")

    # --- Section 1: Basic Info (from whocalled.in) ---
    if has_api1:
        lines.append("🔍 *Basic Info*")
        lines.append("• *Name:* `" + val(record.get("name")) + "`")
        if val(record.get("circle")) != "None":
            lines.append("• *Carrier:* `" + val(record.get("circle")) + "`")
        if val(record.get("email")) != "None":
            lines.append("• *Email:* `" + val(record.get("email")) + "`")
        if val(record.get("address")) != "None":
            lines.append("• *Address:* `" + val(record.get("address")) + "`")
        lines.append("")

    # --- Section 2: Advanced Info (from rack-72au) ---
    if has_api2:
        # Priority fields shown first
        PRIORITY_KEYS = [
            "Owner Name", "Owner Address", "Connection", "SIM Card",
            "Mobile State", "Country", "Hometown", "Language",
            "Mobile Locations", "Tower Locations", "Reference City",
            "IMEI Number", "IP Address", "MAC Address",
            "Tracker ID", "Tracking History", "Complaints",
        ]
        lines.append("📡 *Advanced Info*")
        shown = set()
        for k in PRIORITY_KEYS:
            v = rack_data.get(k)
            if v and k not in RACK_SKIP:
                lines.append("• *" + k + ":* `" + str(v) + "`")
                shown.add(k)
        # Any remaining keys not in priority list
        for k, v in rack_data.items():
            if k not in shown and k not in RACK_SKIP and v:
                lines.append("• *" + k + ":* `" + str(v) + "`")
        lines.append("")

    lines.append("[💬 WhatsApp](" + wa_link + ") | [✈️ Telegram](" + tg_link + ")")

    sent = await update.message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def leak_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/leak <email/phone/username>`\n\n_Example:_ `/leak example@gmail.com`",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    query = context.args[0].strip()

    allowed, remaining = check_and_use_leak_quota(user_id)
    if not allowed:
        await update.message.reply_text(
            "*⛔ Daily Limit Reached!*\n\n"
            "You can use `/leak` only *" + str(LEAK_DAILY_LIMIT) + " times per day*.\n"
            "Please try again tomorrow.",
            parse_mode="Markdown",
        )
        return

    searching = await update.message.reply_text("🔍 Searching leaked databases...")
    try:
        raw = await fetch_json(IA_LEAK_URL.format(query=query), timeout=20)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "leak_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo leaked records found for `" + query + "`.", parse_mode="Markdown")
        return

    result = raw.get("result") or {}
    records = result.get("data") if isinstance(result, dict) else None
    if not isinstance(records, list) or not records:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo leaked records found for `" + query + "`.", parse_mode="Markdown")
        return

    increment_search(user_id)

    LABEL_MAP = {
        "email": "Email", "password": "Password", "phone": "Phone",
        "link": "Link", "encrypted_password": "Password Hash",
        "nick": "Nickname", "surname": "Surname", "address": "Address",
        "city": "City", "postal_code": "Postal Code", "country": "Country",
        "gender": "Gender", "the_date_of_registration": "Registered On",
        "the_name_of_the_father": "Father's Name", "category": "Category",
        "state": "State",
    }

    def clean_val(v):
        s = str(v).replace("`", "'").replace("\\", "").strip()
        if len(s) > 250:
            s = s[:250] + "…"
        return s

    MAX_ENTRIES_PER_SOURCE = 15  # keep any single source block from dominating a page

    current_source = "Unknown Source"
    blocks = []
    entry_lines = []
    entry_extra_count = 0

    def flush_entry():
        if entry_lines:
            block = "📂 *Source:* `" + current_source + "`\n" + "\n".join(entry_lines)
            if entry_extra_count > 0:
                block += "\n_...+" + str(entry_extra_count) + " more from this source_"
            blocks.append(block)

    for rec in records:
        if not isinstance(rec, dict):
            continue
        if "content" in rec and len(rec) == 1:
            flush_entry()
            entry_lines = []
            entry_extra_count = 0
            current_source = clean_val(rec["content"]).strip("[] ")
            continue
        lines = []
        for k, v in rec.items():
            if k == "content" or v in (None, ""):
                continue
            label = LABEL_MAP.get(k, k.replace("_", " ").title())
            lines.append("• *" + label + ":* `" + clean_val(v) + "`")
        if lines:
            if len(entry_lines) >= MAX_ENTRIES_PER_SOURCE:
                entry_extra_count += 1
            else:
                entry_lines.append("\n".join(lines))
    flush_entry()

    if not blocks:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo leaked records found for `" + query + "`.", parse_mode="Markdown")
        return

    header = (
        "🔓 *Leak Search Result*\n"
        "*Query:* `" + clean_val(query) + "`\n"
        "*Total Matches:* `" + str(len(records)) + "`\n\n"
    )

    # Split all blocks into pages (each page fits Telegram's message limit).
    # A page is only flushed once it actually contains a block, so we never
    # send an empty "header-only" page even if the first block is large.
    pages = []
    chunk = header
    chunk_has_block = False
    for block in blocks:
        piece = block + "\n\n"
        if chunk_has_block and len(chunk) + len(piece) > 3800:
            pages.append(chunk)
            chunk = header + piece
            chunk_has_block = True
        else:
            chunk += piece
            chunk_has_block = True
    if chunk_has_block:
        pages.append(chunk)
    if not pages:
        pages = [header]

    text, markup = build_leak_page(update.message.from_user.id, query, pages, 0)
    sent = await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def id_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/id ayush` _or_ `/id 3016488253`\n\n_Enter a Telegram username or numeric ID._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    query = context.args[0].strip().lstrip("@")
    searching = await update.message.reply_text("🔍 Searching...")
    try:
        raw = await fetch_json(IA_ID_URL.format(query=query), timeout=10)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "id_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo Telegram data found for this query.", parse_mode="Markdown")
        return

    data = (raw.get("result") or {}).get("data") or {}
    if not data or not data.get("id"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo Telegram data found for this query.", parse_mode="Markdown")
        return

    increment_search(user_id)

    def bool_label(v):
        if v is True:
            return "Yes"
        if v is False:
            return "No"
        return val(v)

    text = (
        "*Telegram ID Lookup*\n\n"
        "*Query:* `" + query + "`\n"
        "*TG ID:* `" + val(data.get("id")) + "`\n"
        "*Bot:* `" + bool_label(data.get("is_bot")) + "`\n"
        "*Premium:* `" + bool_label(data.get("is_premium")) + "`\n"
        "*Verified:* `" + bool_label(data.get("is_verified")) + "`\n"
        "*Scam:* `" + bool_label(data.get("is_scam")) + "`\n"
        "*Fake:* `" + bool_label(data.get("is_fake")) + "`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def vnum_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/vnum MH01AB1234`\n\n_Enter the vehicle registration number._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    vnum = context.args[0].strip().upper().replace(" ", "")
    searching = await update.message.reply_text("🔍 Searching vehicle database...")
    try:
        raw = await fetch_json(IA_VNUM_URL.format(vnum=vnum), timeout=12)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "vnum_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this vehicle number.", parse_mode="Markdown")
        return

    data = (raw.get("result") or {}).get("data") or {}
    if not data:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this vehicle number.", parse_mode="Markdown")
        return

    increment_search(user_id)

    text = (
        "🚗 *Vehicle Lookup*\n\n"
        "*Reg Number:* `" + val(data.get("registration_number")) + "`\n"
        "*Status:* `" + val(data.get("status")) + "`\n\n"
        "👤 *Owner Details*\n"
        "*Owner Name:* `" + val(data.get("owner_name")) + "`\n"
        "*Mobile:* `" + val(data.get("mobile")) + "`\n"
        "*Owner Count:* `" + val(data.get("owner_count")) + "`\n"
        "*Present Address:* `" + val(data.get("present")) + "`\n"
        "*Permanent Address:* `" + val(data.get("permanent")) + "`\n"
        "*Financed:* `" + val(data.get("financed")) + "`\n\n"
        "🚘 *Vehicle Details*\n"
        "*Manufacturer:* `" + val(data.get("manufacturer")) + "`\n"
        "*Model:* `" + val(data.get("model")) + "` | *Variant:* `" + val(data.get("variant")) + "`\n"
        "*Class:* `" + val(data.get("vehicle_class")) + "`\n"
        "*Fuel Type:* `" + val(data.get("fuel_type")) + "`\n"
        "*Engine Capacity:* `" + val(data.get("engine_capacity")) + "`\n"
        "*Seating:* `" + val(data.get("seating_capacity")) + "`\n"
        "*Engine No:* `" + val(data.get("engine_no")) + "`\n"
        "*Chassis No:* `" + val(data.get("chassis_no")) + "`\n"
        "*Manufacturing:* `" + val(data.get("manufacturing")) + "`\n"
        "*Reg Date:* `" + val(data.get("registration_date")) + "`\n"
        "*RTO:* `" + val(data.get("rto")) + "`\n\n"
        "🛡 *Insurance*\n"
        "*Company:* `" + val(data.get("company")) + "`\n"
        "*Policy No:* `" + val(data.get("policy_no")) + "`\n"
        "*Valid Till:* `" + val(data.get("valid_till")) + "`\n\n"
        "⚠️ *Blacklist:* `" + val(data.get("blacklist_status")) + "`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def fflike_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "*Usage:* `/fflike ind 123456789`\n\n_Region: ind / br / sg / ru / id / tw / us / vn / th / me / pk / bd_",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    region = context.args[0].strip().lower()
    uid = context.args[1].strip()
    searching = await update.message.reply_text("🔍 Fetching Free Fire data...")
    try:
        raw = await fetch_json(IA_FFLIKE_URL.format(region=region, uid=uid), timeout=15)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "fflike_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo data found for this Free Fire UID.", parse_mode="Markdown")
        return

    data = (raw.get("result") or {}).get("data") or {}
    if not data:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo data found for this Free Fire UID.", parse_mode="Markdown")
        return

    increment_search(user_id)

    text = (
        "🎮 *Free Fire — Like Info*\n\n"
        "*Player:* `" + val(data.get("player")) + "`\n"
        "*UID:* `" + val(data.get("uid")) + "`\n"
        "*Region:* `" + val(data.get("region")) + "`\n\n"
        "*Likes Before:* `" + val(data.get("before")) + "`\n"
        "*Likes After:* `" + val(data.get("after")) + "`\n"
        "*Likes Given:* `" + val(data.get("given")) + "`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def ffvisit_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "*Usage:* `/ffvisit ind 123456789`\n\n_Region: ind / br / sg / ru / id / tw / us / vn / th / me / pk / bd_",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    region = context.args[0].strip().lower()
    uid = context.args[1].strip()
    searching = await update.message.reply_text("🔍 Fetching Free Fire data...")
    try:
        raw = await fetch_json(IA_FFVISIT_URL.format(region=region, uid=uid), timeout=15)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "ffvisit_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo data found for this Free Fire UID.", parse_mode="Markdown")
        return

    data = (raw.get("result") or {}).get("data") or {}
    if not data:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo data found for this Free Fire UID.", parse_mode="Markdown")
        return

    increment_search(user_id)

    text = (
        "🎮 *Free Fire — Visit Info*\n\n"
        "*Player:* `" + val(data.get("player")) + "`\n"
        "*UID:* `" + val(data.get("uid")) + "`\n"
        "*Region:* `" + val(data.get("region")) + "`\n\n"
        "*Visits Success:* `" + val(data.get("success")) + "`\n"
        "*Visits Failed:* `" + val(data.get("failed")) + "`\n"
        "*Response Time:* `" + val(data.get("response")) + "`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


PROMO_PATTERNS = re.compile(
    r"(https?://\S+|www\.\S+|t\.me/\S+|"
    r"bit\.ly/\S+|tinyurl\.com/\S+|cutt\.ly/\S+|"
    r"join\s+(our|my|this)|subscribe|follow\s+(us|me|our)|"
    r"check\s+out|click\s+(here|link)|free\s+(coins|money|gift|reward|points)|"
    r"earn\s+money|make\s+money|invest\s+now|limited\s+offer|"
    r"dm\s+(me|us)|inbox\s+(me|us)|contact\s+(me|us)|whatsapp\s+(me|us))",
    re.IGNORECASE,
)


async def anti_spam(update, context):
    msg = update.message
    if not msg:
        return

    chat = msg.chat
    if not chat or chat.type not in ("group", "supergroup"):
        return

    user = msg.from_user
    if not user:
        return

    user_id = user.id

    # Exempt bot owner
    if user_id == ADMIN_ID:
        return

    # Exempt group admins
    try:
        member = await context.bot.get_chat_member(chat.id, user_id)
        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    # Allow bot commands, shared User/Group/Channel ID actions, and direct
    # lookup inputs. Everything else in the group is removed.
    if msg.users_shared or msg.chat_shared:
        return

    text = (msg.text or "").strip()
    is_command = bool(text.startswith("/"))
    is_lookup_input = (
        (text.startswith("@") and len(text) > 1)
        or (text.lstrip("+").isdigit() and len(text.lstrip("+")) >= 7)
    )
    if is_command or text in ("User", "Group", "Channel") or is_lookup_input:
        return

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=msg.message_id)
    except Exception:
        pass


async def weather_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/weather Delhi`\n\n_Enter any city name._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    city = " ".join(context.args).strip()
    searching = await update.message.reply_text("🔍 Fetching weather...")
    try:
        raw = await fetch_json(WEATHER_URL.format(city=city), timeout=12)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "weather_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo weather data found for this city.", parse_mode="Markdown")
        return

    data = raw.get("data") or {}
    city_info = data.get("city") or {}
    cur = data.get("current") or {}

    if not cur:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo weather data found for this city.", parse_mode="Markdown")
        return

    increment_search(user_id)

    weather_desc = (cur.get("weather") or {}).get("description") or "None"
    weather_icon = (cur.get("weather") or {}).get("icon") or ""
    temp = cur.get("temperature") or {}
    atm = cur.get("atmosphere") or {}
    wind = cur.get("wind") or {}
    precip = cur.get("precipitation") or {}
    uv = cur.get("uv") or {}

    city_name = val(city_info.get("name"))
    state = val(city_info.get("state"))
    country = val(city_info.get("country"))

    text = (
        "🌤 *Weather Report*\n\n"
        "*City:* `" + city_name + "`\n"
        "*State:* `" + state + "`\n"
        "*Country:* `" + country + "`\n\n"
        "🌡 *Current Conditions*\n"
        "*Weather:* `" + weather_desc + "`\n"
        "*Temperature:* `" + val(temp.get("actual_c")) + "°C (feels like " + val(temp.get("feels_like_c")) + "°C)`\n\n"
        "💧 *Atmosphere*\n"
        "*Humidity:* `" + val(atm.get("humidity_percent")) + "% (" + val(atm.get("humidity_level")) + ")`\n"
        "*Cloud Cover:* `" + val(atm.get("cloud_cover_percent")) + "%`\n"
        "*Visibility:* `" + val(atm.get("visibility_m")) + " m (" + val(atm.get("visibility_level")) + ")`\n"
        "*Pressure:* `" + val(atm.get("pressure_msl_hpa")) + " hPa`\n\n"
        "💨 *Wind*\n"
        "*Speed:* `" + val(wind.get("speed_kmh")) + " km/h`\n"
        "*Gusts:* `" + val(wind.get("gusts_kmh")) + " km/h`\n"
        "*Direction:* `" + val(wind.get("direction_label")) + " (" + val(wind.get("direction_deg")) + "°)`\n\n"
        "🌧 *Precipitation*\n"
        "*Total:* `" + val(precip.get("total_mm")) + " mm`\n"
        "*Rain:* `" + val(precip.get("rain_mm")) + " mm`\n\n"
        "☀️ *UV Index:* `" + val(uv.get("uv_index")) + " (" + val(uv.get("risk_level")) + ")`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def aqi_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/aqi Delhi`\n\n_Enter any city name._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    city = " ".join(context.args).strip()
    searching = await update.message.reply_text("🔍 Fetching AQI data...")
    try:
        raw = await fetch_json(AQI_URL.format(city=city), timeout=12)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "aqi_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo AQI data found for this city.", parse_mode="Markdown")
        return

    data = raw.get("data") or {}
    city_info = data.get("city") or {}
    us_aqi = data.get("us_aqi") or {}
    eu_aqi = data.get("european_aqi") or {}
    pollutants = data.get("pollutants") or {}
    uv = data.get("uv") or {}

    if not us_aqi:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo AQI data found for this city.", parse_mode="Markdown")
        return

    increment_search(user_id)

    city_name = val(city_info.get("name"))
    state = val(city_info.get("state"))
    country = val(city_info.get("country"))

    us_val = val(us_aqi.get("value"))
    us_level = val(us_aqi.get("level"))
    us_desc = val(us_aqi.get("description"))
    us_advice = val(us_aqi.get("health_advice"))
    eu_val = val(eu_aqi.get("value"))
    eu_level = val(eu_aqi.get("level"))

    bd = us_aqi.get("breakdown") or {}

    def pval(key):
        p = pollutants.get(key) or {}
        v = p.get("value")
        u = p.get("unit") or ""
        return (val(v) + " " + u).strip() if v is not None else "None"

    text = (
        "🌫 *Air Quality Report*\n\n"
        "*City:* `" + city_name + "`\n"
        "*State:* `" + state + "`\n"
        "*Country:* `" + country + "`\n\n"
        "📊 *AQI Index*\n"
        "*US AQI:* `" + us_val + " — " + us_level + "`\n"
        "*EU AQI:* `" + eu_val + " — " + eu_level + "`\n\n"
        "⚠️ *Health Info*\n"
        "*Status:* `" + us_desc + "`\n"
        "*Advice:* `" + us_advice + "`\n\n"
        "🧪 *Pollutants*\n"
        "*PM2.5:* `" + pval("pm2_5") + "`\n"
        "*PM10:* `" + pval("pm10") + "`\n"
        "*CO:* `" + pval("carbon_monoxide") + "`\n"
        "*NO2:* `" + pval("nitrogen_dioxide") + "`\n"
        "*SO2:* `" + pval("sulphur_dioxide") + "`\n"
        "*O3:* `" + pval("ozone") + "`\n"
        "*Dust:* `" + pval("dust") + "`\n\n"
        "☀️ *UV Index:* `" + val(uv.get("uv_index")) + " (" + val(uv.get("risk_level")) + ")`"
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def pincode_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/pincode 411001`\n\n_Enter a valid Indian pincode._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    pincode = context.args[0].strip()
    searching = await update.message.reply_text("🔍 Searching pincode...")
    try:
        raw = await fetch_json(PINCODE_URL.format(pincode=pincode), timeout=10)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "pincode_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or raw.get("status") != "success":
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this pincode.", parse_mode="Markdown")
        return

    records = raw.get("records") or []
    if not records:
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo information found for this pincode.", parse_mode="Markdown")
        return

    increment_search(user_id)

    total = val(raw.get("total_records_found"))
    first = records[0]
    district = val(first.get("district"))
    state = val(first.get("state"))
    country = val(first.get("country"))
    region = val(first.get("region"))
    division = val(first.get("division"))
    circle = val(first.get("circle"))

    offices = []
    for r in records:
        name = val(r.get("office_name"))
        btype = val(r.get("branch_type"))
        delivery = val(r.get("delivery_status"))
        offices.append("• `" + name + "` | " + btype + " | " + delivery)

    office_text = "\n".join(offices[:10])
    if len(records) > 10:
        office_text += "\n...and " + str(len(records) - 10) + " more"

    text = (
        "📮 *Pincode Info*\n\n"
        "*Pincode:* `" + pincode + "`\n"
        "*District:* `" + district + "`\n"
        "*State:* `" + state + "`\n"
        "*Country:* `" + country + "`\n"
        "*Region:* `" + region + "`\n"
        "*Division:* `" + division + "`\n"
        "*Circle:* `" + circle + "`\n"
        "*Total Post Offices:* `" + total + "`\n\n"
        "🏢 *Post Offices*\n"
        + office_text
    )
    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])


async def dns_lookup(update, context):
    if not await guard_with_cooldown(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "*Usage:* `/dns google.com`\n\n_Enter a domain name to fetch its DNS records._",
            parse_mode="Markdown",
        )
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    query = context.args[0].strip()

    searching = await update.message.reply_text("🔍 Fetching DNS records...")
    try:
        raw = await fetch_json(RACK_DNS_URL.format(query=query), timeout=15)
    except Exception as e:
        await delete_msg(context, chat_id, searching.message_id)
        await update.message.reply_text("*Server Error!*\n\nRequest failed. Please try again later.", parse_mode="Markdown")
        await log_error_to_admin(context, "dns_lookup: " + str(e))
        return

    await delete_msg(context, chat_id, searching.message_id)

    if not isinstance(raw, dict) or not raw.get("success"):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo DNS records found for `" + query + "`.", parse_mode="Markdown")
        return

    data = raw.get("data", {})
    if not isinstance(data, dict):
        await send_expiring_lookup_message(update, context, "*❌ Data Not Found!*\n\nNo DNS records found for `" + query + "`.", parse_mode="Markdown")
        return

    STATUS_MAP = {0: "✅ NOERROR", 1: "❌ FORMERR", 2: "❌ SERVFAIL", 3: "❌ NXDOMAIN", 4: "❌ NOTIMP", 5: "❌ REFUSED"}
    TYPE_MAP = {1: "A", 2: "NS", 5: "CNAME", 6: "SOA", 15: "MX", 16: "TXT", 28: "AAAA", 33: "SRV", 65: "HTTPS", 257: "CAA", 255: "ANY"}
    SKIP_KEYS = {"owner", "admin"}

    status_code = data.get("Status", -1)
    status_text = STATUS_MAP.get(status_code, "Unknown (" + str(status_code) + ")")

    answers = data.get("Answer", [])
    authority = data.get("Authority", [])
    comment = data.get("Comment", "")

    if not answers and not authority:
        await send_expiring_lookup_message(update, context, "*❌ No Records Found!*\n\nDomain `" + query + "` returned no DNS records.\n*Status:* " + status_text, parse_mode="Markdown")
        return

    increment_search(user_id)

    lines = [
        "┏━━━━━━━━━━━━━━━━━┓",
        "┃  🌐 *DNS Lookup*",
        "┗━━━━━━━━━━━━━━━━━┛",
        "",
        "*Domain:* `" + query + "`",
        "*Status:* " + status_text,
        "",
    ]

    # Group Answer records by type
    if answers:
        groups = {}
        for rec in answers:
            if not isinstance(rec, dict):
                continue
            rtype = TYPE_MAP.get(rec.get("type"), "TYPE" + str(rec.get("type", "?")))
            groups.setdefault(rtype, []).append(rec)

        for rtype, recs in groups.items():
            lines.append("📌 *" + rtype + " Records*")
            for rec in recs:
                ttl = rec.get("TTL", "")
                rdata = str(rec.get("data", "")).strip()
                if rdata:
                    lines.append("• `" + rdata + "` _(TTL: " + str(ttl) + "s)_")
            lines.append("")

    # Authority section (if no answers)
    if authority and not answers:
        lines.append("📋 *Authority Records*")
        for rec in authority:
            if not isinstance(rec, dict):
                continue
            rtype = TYPE_MAP.get(rec.get("type"), "TYPE" + str(rec.get("type", "?")))
            rdata = str(rec.get("data", "")).strip()
            ttl = rec.get("TTL", "")
            if rdata:
                lines.append("• *" + rtype + ":* `" + rdata + "` _(TTL: " + str(ttl) + "s)_")
        lines.append("")

    if comment:
        lines.append("💬 *Note:* _" + comment.strip() + "_")

    text = "\n".join(lines)
    # Telegram message limit 4096 chars
    if len(text) > 4096:
        text = text[:4090] + "\n_..._"

    sent = await update.message.reply_text(text, parse_mode="Markdown")
    schedule_result_cleanup(context, chat_id, [sent.message_id])



if __name__ == "__main__":
    init_db()
    keep_alive()
    print("Flask Server Started!")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("num", num_lookup))
    app.add_handler(CommandHandler("aadhar", aadhar_lookup))
    app.add_handler(CommandHandler("veh", veh_lookup))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("grouphelp", grouphelp_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("reply", reply_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("ifsc", ifsc_lookup))
    app.add_handler(CommandHandler("insta", insta_lookup))
    app.add_handler(CommandHandler("pak", pak_lookup))
    app.add_handler(CommandHandler("ip", ip_lookup))
    app.add_handler(CommandHandler("familyinfo", familyinfo_lookup))
    app.add_handler(CommandHandler("leak", leak_lookup))
    app.add_handler(CallbackQueryHandler(leak_page_callback, pattern="^leakpg:"))
    app.add_handler(CommandHandler("vehinfo", vehinfo_lookup))
    app.add_handler(CommandHandler("true", true_lookup))
    app.add_handler(CommandHandler("weather", weather_lookup))
    app.add_handler(CommandHandler("aqi", aqi_lookup))
    app.add_handler(CommandHandler("pincode", pincode_lookup))
    app.add_handler(CommandHandler("id", id_lookup))
    app.add_handler(CommandHandler("vnum", vnum_lookup))
    app.add_handler(CommandHandler("fflike", fflike_lookup))
    app.add_handler(CommandHandler("ffvisit", ffvisit_lookup))
    app.add_handler(CommandHandler("dns", dns_lookup))
    app.add_handler(CommandHandler("adminhelp", adminhelp_command))
    app.add_handler(CommandHandler("maintenance", maintenance_command))
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="check_joined"))
    app.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, handle_users_shared))
    app.add_handler(MessageHandler(filters.StatusUpdate.CHAT_SHARED, handle_chat_shared))
    app.add_handler(MessageHandler(
        filters.ALL & filters.ChatType.GROUPS,
        anti_spam,
        block=False,
    ), group=-1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup))
    print("Bot is Online!")
    app.run_polling()
