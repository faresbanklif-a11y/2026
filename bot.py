#المطور  @og4_z
# تم برمجة البوت من قبل @og4_z
# لا تغير الحقوق
import os
import re
import html
import json
import time
import random
import logging
import sqlite3
import asyncio
import shutil
import traceback
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    InputFile,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
from telegram.error import (
    BadRequest, Forbidden, TelegramError, NetworkError, TimedOut, RetryAfter,
)
BOT_TOKEN ="8667257420:AAEpcdOeiK1q5t6PDqg_pU1Ry5Tmi5nV-7c"
BOT_USERNAME     = "Pdolcibot"   # 
SUPPORT_USERNAME = "og4_z"        
SUPER_ADMINS     = [8018653004]          
DB_PATH = "bot_data.db"
DEFAULTS = {
    "invite_reward":        "999",
    "transfer_fee_percent": "10",
    "likes_min_qty":        "10",
    "likes_max_qty":        "200",
    "daily_gift_points":    "50",
    "daily_gift_bonus":     "10",
    "daily_gift_max_streak":"7",
    "rate_limit_seconds":   "1",       # ثانية بين كل رسالتين
    "maintenance":          "0",       # 0 / 1
    "force_join":           "0",       # 0 / 1
    "vip_price_stars":      "150",
    "verify_price_points":  "5000",
    "lottery_ticket_cost":  "50",
    "lottery_jackpot_pct":  "70",      # نسبة المجموع التي تُمنح للفائز
    "shop_gem_to_points":   "100",     # 1 جوهرة = 100 نقطة
    "welcome_bonus":        "20",      # نقاط ترحيب لأول مرة
}

# ==========================================================
#                       تهيئة اللوج
# ==========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")
logging.getLogger("httpx").setLevel(logging.WARNING)

# ==========================================================
#                     قاعدة البيانات
# ==========================================================

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


DB = db_connect()


USER_COLUMNS_MIGRATIONS = [
    ("orders_count",  "INTEGER DEFAULT 0"),
    ("spent_total",   "INTEGER DEFAULT 0"),
    ("gems",          "INTEGER DEFAULT 0"),
    ("vip_expiry",    "TEXT"),
    ("infinite_vip",  "INTEGER DEFAULT 0"),
    ("invited_by",    "INTEGER"),
    ("invites_count", "INTEGER DEFAULT 0"),
    ("verified",      "INTEGER DEFAULT 0"),
    ("banned",        "INTEGER DEFAULT 0"),
    ("phone",         "TEXT"),
    ("last_seen",     "TEXT"),
]


def db_migrate() -> None:
    """يضيف الأعمدة المفقودة للقواعد القديمة دون أي خطأ."""
    try:
        cols = {r["name"] for r in DB.execute("PRAGMA table_info(users)").fetchall()}
    except Exception:
        return
    for name, decl in USER_COLUMNS_MIGRATIONS:
        if name not in cols:
            try:
                DB.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
                logger.info(f"migrated users.{name}")
            except Exception as e:
                logger.warning(f"migrate fail {name}: {e}")
    DB.commit()


def db_init() -> None:
    cur = DB.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id        INTEGER PRIMARY KEY,
        username       TEXT,
        first_name     TEXT,
        points         INTEGER DEFAULT 0,
        gems           INTEGER DEFAULT 0,
        vip_expiry     TEXT,
        infinite_vip   INTEGER DEFAULT 0,
        invited_by     INTEGER,
        invites_count  INTEGER DEFAULT 0,
        verified       INTEGER DEFAULT 0,
        banned         INTEGER DEFAULT 0,
        joined_at      TEXT DEFAULT CURRENT_TIMESTAMP,
        last_seen      TEXT,
        phone          TEXT,
        orders_count   INTEGER DEFAULT 0,
        spent_total    INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS menu_buttons (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        label       TEXT NOT NULL UNIQUE,
        action      TEXT NOT NULL,    -- e.g. services, charge, invite, settings, updates, terms, infinite, funding, daily, profile, shop, lottery, leaderboard, myorders, achievements, custom
        payload     TEXT,             -- نص للعرض إن كان action=custom
        active      INTEGER DEFAULT 1,
        sort_order  INTEGER DEFAULT 0,
        row_pos     INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS sections (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        emoji       TEXT DEFAULT '📦',
        active      INTEGER DEFAULT 1,
        sort_order  INTEGER DEFAULT 0,
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS section_services (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id  INTEGER NOT NULL,
        title       TEXT NOT NULL,
        cost        INTEGER NOT NULL,
        active      INTEGER DEFAULT 1,
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS mandatory_channels (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        channel     TEXT NOT NULL,
        title       TEXT,
        reward      INTEGER DEFAULT 0,
        required    INTEGER DEFAULT 0,   -- 1 = اشتراك إجباري قبل الاستخدام
        active      INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS earned_channels (
        user_id    INTEGER,
        channel_id INTEGER,
        PRIMARY KEY(user_id, channel_id)
    );

    CREATE TABLE IF NOT EXISTS transfer_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id     INTEGER,
        to_id       INTEGER,
        amount      INTEGER,
        fee         INTEGER,
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS charge_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        amount      INTEGER,
        method      TEXT,
        status      TEXT DEFAULT 'pending',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS orders (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     INTEGER,
        kind        TEXT,
        service_id  INTEGER,
        target      TEXT,
        quantity    INTEGER,
        cost        INTEGER,
        status      TEXT DEFAULT 'pending',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS daily_gifts (
        user_id      INTEGER PRIMARY KEY,
        last_claim   TEXT,
        streak       INTEGER DEFAULT 0,
        total_claims INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS coupons (
        code        TEXT PRIMARY KEY,
        reward      INTEGER NOT NULL,
        max_uses    INTEGER DEFAULT 1,
        used_count  INTEGER DEFAULT 0,
        active      INTEGER DEFAULT 1,
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS coupon_uses (
        code     TEXT,
        user_id  INTEGER,
        used_at  TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(code, user_id)
    );

    CREATE TABLE IF NOT EXISTS lottery_tickets (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER,
        round_id   TEXT,
        cost       INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS achievements (
        user_id  INTEGER,
        code     TEXT,
        unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id, code)
    );

    CREATE TABLE IF NOT EXISTS stars_packages (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        points INTEGER NOT NULL,
        stars  INTEGER NOT NULL,
        active INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0
    );
    """)
    DB.commit()
    db_migrate()
    seed_defaults()
    seed_menu()
    seed_sections()
    seed_stars_packages()


def seed_defaults() -> None:
    for k, v in DEFAULTS.items():
        DB.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v)
        )
    DB.commit()


def seed_menu() -> None:
    if DB.execute("SELECT COUNT(*) c FROM menu_buttons").fetchone()["c"] > 0:
        return
    items = [
        ("📮 قسم رشق الخدمات",       "services",     None, 0, 0),
        ("🎁 الهدية اليومية",        "daily",        None, 1, 0),
        ("👤 ملفي الشخصي",           "profile",      None, 1, 1),
        ("💰 شحن أو شراء نقاط",      "charge",       None, 2, 0),
        ("🛒 المتجر",                "shop",         None, 2, 1),
        ("🔑 جمع النقاط",            "settings",     None, 3, 0),
        ("🔗 رابط الدعوة",           "invite",       None, 3, 1),
        ("🎰 يانصيب",                "lottery",      None, 4, 0),
        ("🏆 لوحة الشرف",            "leaderboard",  None, 4, 1),
        ("🎟 استخدام كوبون",         "coupon",       None, 5, 0),
        ("📦 طلباتي",                "myorders",     None, 5, 1),
        ("🏅 إنجازاتي",              "achievements", None, 6, 0),
        ("🌍 تحديثات البوت",         "updates",      None, 6, 1),
        ("📜 الشروط والخصوصية",      "terms",        None, 7, 0),
        ("🤯 تمويل حقيقي",           "funding",      None, 7, 1),
        ("🔥 نقاط لا نهائية +999",   "infinite",     None, 8, 0),
    ]
    for label, action, payload, row_pos, sort in items:
        DB.execute(
            "INSERT OR IGNORE INTO menu_buttons(label, action, payload, row_pos, sort_order) "
            "VALUES(?,?,?,?,?)",
            (label, action, payload, row_pos, sort),
        )
    DB.commit()


def seed_sections() -> None:
    if DB.execute("SELECT COUNT(*) c FROM sections").fetchone()["c"] > 0:
        return
    defaults = [
        ("لايكات", "❤️", 1),
        ("أعضاء", "👥", 2),
        ("مشاهدات", "👁", 3),
        ("تصويتات", "📨", 4),
        ("صور", "🖼", 5),
        ("ريأكشن", "🔥", 6),
    ]
    for name, emoji, order in defaults:
        DB.execute(
            "INSERT OR IGNORE INTO sections(name, emoji, sort_order) VALUES(?,?,?)",
            (name, emoji, order),
        )
    DB.commit()


def seed_stars_packages() -> None:
    if DB.execute("SELECT COUNT(*) c FROM stars_packages").fetchone()["c"] > 0:
        return
    pkgs = [(100, 10, 1), (500, 45, 2), (1000, 80, 3), (5000, 350, 4), (10000, 650, 5)]
    for p, s, o in pkgs:
        DB.execute(
            "INSERT INTO stars_packages(points, stars, sort_order) VALUES(?,?,?)",
            (p, s, o),
        )
    DB.commit()


# ----------- إعدادات حية -----------

def cfg(key: str, default: str = "") -> str:
    r = DB.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def cfg_int(key: str, default: int = 0) -> int:
    try:
        return int(cfg(key, str(default)))
    except ValueError:
        return default


def cfg_set(key: str, value: str) -> None:
    DB.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    DB.commit()


# ==========================================================
#                      أدوات المستخدمين
# ==========================================================

def row_get(row: Optional[sqlite3.Row], key: str, default=None):
    if row is None:
        return default
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def user_get(user_id: int) -> Optional[sqlite3.Row]:
    return DB.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def user_ensure(update_user) -> sqlite3.Row:
    uid = update_user.id
    uname = (update_user.username or "").strip()
    fname = (update_user.first_name or "").strip()
    lname = (getattr(update_user, "last_name", "") or "").strip()
    full_name = (fname + " " + lname).strip() or "مستخدم"
    now = datetime.now().isoformat(timespec="seconds")

    row = user_get(uid)
    if row is None:
        DB.execute(
            "INSERT INTO users(user_id, username, first_name, last_seen, points) "
            "VALUES(?,?,?,?,?)",
            (uid, uname, full_name, now, cfg_int("welcome_bonus", 0)),
        )
        DB.commit()
    else:
        DB.execute(
            "UPDATE users SET username=?, first_name=?, last_seen=? WHERE user_id=?",
            (uname, full_name, now, uid),
        )
        DB.commit()
    return user_get(uid)


def user_add_points(uid: int, amount: int) -> None:
    DB.execute("UPDATE users SET points = points + ? WHERE user_id=?", (amount, uid))
    DB.commit()


def user_add_gems(uid: int, amount: int) -> None:
    DB.execute("UPDATE users SET gems = gems + ? WHERE user_id=?", (amount, uid))
    DB.commit()


def user_is_vip(row: sqlite3.Row) -> bool:
    if not row:
        return False
    if row_get(row, "infinite_vip", 0):
        return True
    exp = row_get(row, "vip_expiry")
    if exp:
        try:
            return datetime.fromisoformat(exp) > datetime.now()
        except Exception:
            return False
    return False


def user_vip_days_left(row: sqlite3.Row) -> str:
    if not row:
        return "❌ لا يوجد"
    if row_get(row, "infinite_vip", 0):
        return "♾️ لا نهائي"
    exp = row_get(row, "vip_expiry")
    if exp:
        try:
            d = datetime.fromisoformat(exp)
            delta = d - datetime.now()
            if delta.total_seconds() <= 0:
                return "❌ منتهي"
            return f"{delta.days} يوم"
        except Exception:
            return "❌ لا يوجد"
    return "❌ لا يوجد"


def is_admin(uid: int) -> bool:
    if uid in SUPER_ADMINS:
        return True
    return DB.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone() is not None


def all_admins() -> List[int]:
    out = list(SUPER_ADMINS)
    for r in DB.execute("SELECT user_id FROM admins").fetchall():
        if r["user_id"] not in out:
            out.append(r["user_id"])
    return out


# ==========================================================
#                   Anti-Spam (Rate-limit)
# ==========================================================

_RATE: Dict[int, float] = {}


def rate_ok(uid: int) -> bool:
    if is_admin(uid):
        return True
    limit = cfg_int("rate_limit_seconds", 1)
    if limit <= 0:
        return True
    now = time.time()
    last = _RATE.get(uid, 0)
    if now - last < limit:
        return False
    _RATE[uid] = now
    return True


# ==========================================================
#                    الإنجازات (Achievements)
# ==========================================================

ACHIEVEMENTS = {
    "first_order":  ("🎯 أول طلب",         "أنشأت أول طلب لك."),
    "ten_orders":   ("📦 عشر طلبات",       "أنجزت 10 طلبات."),
    "first_invite": ("🎉 أول دعوة",        "دعوت أول صديق."),
    "ten_invites":  ("👥 10 دعوات",        "وصلت إلى 10 دعوات."),
    "vip_member":   ("👑 عضو VIP",         "أصبحت VIP."),
    "streak_7":     ("🔥 ستريك أسبوع",     "حافظت على الهدية اليومية 7 أيام."),
    "lottery_win":  ("🎰 فائز يانصيب",     "ربحت في اليانصيب."),
}


async def grant_achievement(context: ContextTypes.DEFAULT_TYPE, uid: int, code: str):
    if code not in ACHIEVEMENTS:
        return
    exists = DB.execute(
        "SELECT 1 FROM achievements WHERE user_id=? AND code=?", (uid, code)
    ).fetchone()
    if exists:
        return
    DB.execute("INSERT INTO achievements(user_id, code) VALUES(?,?)", (uid, code))
    DB.commit()
    title, desc = ACHIEVEMENTS[code]
    try:
        await context.bot.send_message(
            uid, f"🏅 <b>إنجاز جديد!</b>\n\n{title}\n— {desc}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


# ==========================================================
#                       النصوص والواجهات
# ==========================================================

WELCOME_TEMPLATE = (
    "🎉 أهلاً <b>{name}</b> في أقوى بوت خدمات تيليجرام!\n\n"
    "💰 نقاطك : <b>{points}</b>\n"
    "💎 جواهرك : <b>{gems}</b>\n"
    "📅 اشتراك VIP : <b>{vip}</b>\n"
    "🆔 آيدي : <code>{uid}</code>\n"
    "♻️ التقييم : {rate}\n\n"
    "📲 استخدم الأزرار أدناه للتنقّل."
)


def main_menu_kb(uid: Optional[int] = None) -> InlineKeyboardMarkup:
    """قائمة رئيسية بأزرار شفافة (Inline) داخل الرسالة."""
    rows: Dict[int, List[Tuple[int, int, str]]] = {}
    for r in DB.execute(
        "SELECT id, label, row_pos, sort_order FROM menu_buttons "
        "WHERE active=1 ORDER BY row_pos, sort_order, id"
    ).fetchall():
        rows.setdefault(r["row_pos"], []).append(
            (r["sort_order"], r["id"], r["label"])
        )
    kb: List[List[InlineKeyboardButton]] = []
    for rp in sorted(rows.keys()):
        kb.append([
            InlineKeyboardButton(lbl, callback_data=f"mn:{bid}")
            for _, bid, lbl in sorted(rows[rp])
        ])
    if not kb:
        kb = [[InlineKeyboardButton("🔄 إعادة", callback_data="mn:home")]]
    kb.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="mn:home")])
    if uid is not None and is_admin(uid):
        kb.append([InlineKeyboardButton("🛠 الإدارة", callback_data="adm:menu")])
    return InlineKeyboardMarkup(kb)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="mn:home")]
    ])


# ==========================================================
#                         /start
# ==========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    row = user_ensure(user)

    # رابط الدعوة
    args = context.args or []
    if args:
        m = re.match(r"^invite_(\d+)$", args[0])
        if m and not row_get(row, "invited_by"):
            inviter_id = int(m.group(1))
            if inviter_id != user.id and user_get(inviter_id):
                reward = cfg_int("invite_reward", 999)
                DB.execute("UPDATE users SET invited_by=? WHERE user_id=?",
                           (inviter_id, user.id))
                DB.execute(
                    "UPDATE users SET invites_count = invites_count + 1, "
                    "points = points + ? WHERE user_id=?",
                    (reward, inviter_id),
                )
                DB.commit()
                inv_count = (user_get(inviter_id) or {"invites_count": 0})["invites_count"]
                if inv_count == 1:
                    await grant_achievement(context, inviter_id, "first_invite")
                if inv_count >= 10:
                    await grant_achievement(context, inviter_id, "ten_invites")
                try:
                    await context.bot.send_message(
                        inviter_id,
                        f"🎉 انضم مستخدم جديد عبر دعوتك!\n➕ <b>+{reward}</b> نقطة.",
                        parse_mode=ParseMode.HTML,
                    )
                except (Forbidden, BadRequest):
                    pass
                row = user_get(user.id)

    if row_get(row, "banned", 0):
        await update.effective_message.reply_text("🚫 تم حظرك من استخدام البوت.")
        return

    # الصيانة
    if cfg_int("maintenance", 0) and not is_admin(user.id):
        await update.effective_message.reply_text(
            "🛠 البوت في وضع الصيانة حالياً.\nالرجاء المحاولة لاحقاً."
        )
        return

    # الاشتراك الإجباري
    if cfg_int("force_join", 0) and not is_admin(user.id):
        ok, kb = await check_forced_join(context, user.id)
        if not ok:
            await update.effective_message.reply_text(
                "📢 يجب الاشتراك في القنوات التالية أولاً ثم اضغط (✅ تحقق):",
                reply_markup=kb,
            )
            return

    rate = "✅ موثق" if row_get(row, "verified", 0) else "🔻 لم يتم التحقق"
    text = WELCOME_TEMPLATE.format(
        name=html.escape(row_get(row, "first_name", "صديق")),
        points=row_get(row, "points", 0) or 0,
        gems=row_get(row, "gems", 0) or 0,
        vip=user_vip_days_left(row),
        uid=user.id,
        rate=rate,
    )
    # إزالة الكيبورد العادي القديم إن وُجد (نسخة سابقة)
    try:
        from telegram import ReplyKeyboardRemove
        await update.effective_message.reply_text("ㅤ", reply_markup=ReplyKeyboardRemove())
    except Exception:
        pass
    await update.effective_message.reply_text(text, reply_markup=main_menu_kb(user.id),
                                    parse_mode=ParseMode.HTML)


async def check_forced_join(context, uid: int) -> Tuple[bool, InlineKeyboardMarkup]:
    chans = DB.execute(
        "SELECT * FROM mandatory_channels WHERE active=1 AND required=1"
    ).fetchall()
    missing = []
    for ch in chans:
        try:
            m = await context.bot.get_chat_member(ch["channel"], uid)
            if m.status not in ("member", "administrator", "creator"):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    kb = []
    for ch in missing:
        kb.append([InlineKeyboardButton(
            f"📢 {ch['title'] or ch['channel']}",
            url=f"https://t.me/{ch['channel'].lstrip('@')}",
        )])
    kb.append([InlineKeyboardButton("✅ تحقق", callback_data="force_join_check")])
    return (len(missing) == 0, InlineKeyboardMarkup(kb))


async def cb_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ok, kb = await check_forced_join(context, q.from_user.id)
    if ok:
        await q.edit_message_text("✅ تم التحقق! استخدم /start الآن.")
    else:
        await q.edit_message_text("⚠️ ما زلت غير مشترك في كل القنوات.", reply_markup=kb)


# ==========================================================
#                  قسم رشق خدمات تيليجرام
# ==========================================================

async def section_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sections = DB.execute(
        "SELECT * FROM sections WHERE active=1 ORDER BY sort_order, id"
    ).fetchall()
    if not sections:
        await update.effective_message.reply_text("⚠️ لا توجد أقسام متاحة حالياً.")
        return
    kb, buf = [], []
    for s in sections:
        buf.append(InlineKeyboardButton(
            f"{s['emoji']} {s['name']}", callback_data=f"sec:{s['id']}",
        ))
        if len(buf) == 2:
            kb.append(buf); buf = []
    if buf:
        kb.append(buf)
    await update.effective_message.reply_text(
        "📮 اختر القسم:", reply_markup=InlineKeyboardMarkup(kb),
    )


async def cb_section_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sec_id = int(q.data.split(":")[1])
    sec = DB.execute("SELECT * FROM sections WHERE id=?", (sec_id,)).fetchone()
    if not sec:
        await q.edit_message_text("⚠️ القسم غير موجود.")
        return
    services = DB.execute(
        "SELECT * FROM section_services WHERE section_id=? AND active=1 ORDER BY id DESC",
        (sec_id,),
    ).fetchall()
    if not services:
        await q.edit_message_text(
            f"{sec['emoji']} <b>{html.escape(sec['name'])}</b>\n\n"
            "⚠️ لا توجد خدمات في هذا القسم.",
            parse_mode=ParseMode.HTML,
        )
        return
    kb = [
        [InlineKeyboardButton(
            f"{s['title']} — {s['cost']} نقطة",
            callback_data=f"buy_dyn:{s['id']}",
        )] for s in services
    ]
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="services_back")])
    await q.edit_message_text(
        f"{sec['emoji']} <b>{html.escape(sec['name'])}</b>\n\nاختر الخدمة:",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML,
    )


async def cb_services_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sections = DB.execute(
        "SELECT * FROM sections WHERE active=1 ORDER BY sort_order, id"
    ).fetchall()
    kb, buf = [], []
    for s in sections:
        buf.append(InlineKeyboardButton(
            f"{s['emoji']} {s['name']}", callback_data=f"sec:{s['id']}",
        ))
        if len(buf) == 2:
            kb.append(buf); buf = []
    if buf:
        kb.append(buf)
    await q.edit_message_text("📮 اختر القسم:",
                              reply_markup=InlineKeyboardMarkup(kb))


async def cb_buy_dyn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sid = int(q.data.split(":")[1])
    svc = DB.execute(
        "SELECT ss.*, s.name AS section_name, s.emoji AS section_emoji "
        "FROM section_services ss JOIN sections s ON s.id=ss.section_id "
        "WHERE ss.id=?", (sid,)
    ).fetchone()
    if not svc:
        await q.edit_message_text("⚠️ الخدمة لم تعد متوفرة.")
        return
    context.user_data["pending_order"] = {
        "kind": svc["section_name"],
        "service_id": sid,
        "cost": svc["cost"],
        "title": svc["title"],
        "step": "target",
    }
    await q.edit_message_text(
        f"{svc['section_emoji']} <b>{html.escape(svc['title'])}</b>\n"
        f"💰 التكلفة: <b>{svc['cost']}</b> نقطة لكل وحدة\n\n"
        "📨 أرسل الرابط/المعرّف الهدف:\n"
        "<i>(أو /cancel للإلغاء)</i>",
        parse_mode=ParseMode.HTML,
    )


# ==========================================================
#                     شحن أو شراء نقاط
# ==========================================================

async def section_charge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = [
        [InlineKeyboardButton("⭐ نجوم تيليجرام", callback_data="pay:stars")],
        [InlineKeyboardButton("💳 الدفع اليدوي", callback_data="pay:manual")],
        [InlineKeyboardButton("🔄 تحويل لمستخدم", callback_data="pay:transfer")],
    ]
    await update.effective_message.reply_text(
        "💰 اختر طريقة الشحن:", reply_markup=InlineKeyboardMarkup(kb),
    )


async def cb_pay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    method = q.data.split(":")[1]
    if method == "stars":
        pkgs = DB.execute(
            "SELECT * FROM stars_packages WHERE active=1 ORDER BY sort_order, id"
        ).fetchall()
        if not pkgs:
            await q.edit_message_text("⚠️ لا توجد باقات متاحة.")
            return
        kb = [[InlineKeyboardButton(
            f"{p['points']} نقطة — ⭐{p['stars']}",
            callback_data=f"stars:{p['points']}:{p['stars']}",
        )] for p in pkgs]
        await q.edit_message_text(
            "⭐ اختر باقة الشحن:", reply_markup=InlineKeyboardMarkup(kb),
        )
    elif method == "manual":
        info = cfg("manual_payment_info",
                   f"📞 تواصل مع الدعم: @{SUPPORT_USERNAME}")
        await q.edit_message_text(f"💳 الدفع اليدوي:\n\n{info}")
    elif method == "transfer":
        context.user_data["transfer_step"] = "target"
        await q.edit_message_text(
            "🔄 أرسل آيدي المستخدم الذي تريد التحويل إليه (رقم فقط):"
        )


async def cb_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    _, points, stars = q.data.split(":")
    points, stars = int(points), int(stars)
    title = f"شحن {points} نقطة"
    payload = f"charge_{q.from_user.id}_{points}_{int(time.time())}"
    try:
        await context.bot.send_invoice(
            chat_id=q.message.chat_id,
            title=title,
            description=f"إضافة {points} نقطة إلى رصيدك",
            payload=payload,
            provider_token="8667257420:AAEpcdOeiK1q5t6PDqg_pU1Ry5Tmi5nV-7c",
            currency="XTR",
            prices=[LabeledPrice(label=title, amount=stars)],
        )
    except TelegramError as e:
        logger.exception("send_invoice failed")
        await q.edit_message_text(f"⚠️ تعذر إنشاء الفاتورة: {e}")


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sp = update.message.successful_payment
    payload = sp.invoice_payload or ""
    m = re.match(r"^charge_(\d+)_(\d+)_\d+$", payload)
    if not m:
        return
    uid = int(m.group(1)); points = int(m.group(2))
    user_add_points(uid, points)
    DB.execute(
        "INSERT INTO charge_history(user_id, amount, method, status) VALUES(?,?,?,?)",
        (uid, points, "stars", "completed"),
    ); DB.commit()
    await update.effective_message.reply_text(
        f"✅ تم الدفع بنجاح! ➕ <b>{points}</b> نقطة.",
        parse_mode=ParseMode.HTML,
    )


# ==========================================================
#                      رابط الدعوة
# ==========================================================

async def section_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    row = user_ensure(user)
    me = await context.bot.get_me()
    bot_uname = me.username or BOT_USERNAME
    link = f"https://t.me/{bot_uname}?start=invite_{user.id}"
    text = (
        "🔗 <b>رابط الدعوة الخاص بك:</b>\n\n"
        f"<code>{html.escape(link)}</code>\n\n"
        f"👥 عدد دعواتك: <b>{row['invites_count']}</b>\n"
        f"🎁 المكافأة: <b>{cfg_int('invite_reward', 999)}</b> نقطة لكل دعوة"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=True)


# ==========================================================
#                  الإعدادات وجمع النقاط
# ==========================================================

async def section_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    channels = DB.execute(
        "SELECT * FROM mandatory_channels WHERE active=1"
    ).fetchall()
    if not channels:
        await update.effective_message.reply_text("🔑 لا توجد قنوات لجمع النقاط حالياً.")
        return
    text = "🔑 اشترك واجمع النقاط:\n\n"
    kb = []
    for ch in channels:
        text += f"• {ch['title'] or ch['channel']} — 🎁 {ch['reward']} نقطة\n"
        kb.append([InlineKeyboardButton(
            f"📢 {ch['title'] or ch['channel']}",
            url=f"https://t.me/{ch['channel'].lstrip('@')}",
        )])
    kb.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subs")])
    await update.effective_message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))


async def cb_check_subs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    user = q.from_user
    user_ensure(user)
    channels = DB.execute("SELECT * FROM mandatory_channels WHERE active=1").fetchall()
    earned, failed = 0, []
    for ch in channels:
        already = DB.execute(
            "SELECT 1 FROM earned_channels WHERE user_id=? AND channel_id=?",
            (user.id, ch["id"]),
        ).fetchone()
        if already:
            continue
        try:
            m = await context.bot.get_chat_member(ch["channel"], user.id)
            if m.status in ("member", "administrator", "creator"):
                user_add_points(user.id, ch["reward"])
                DB.execute(
                    "INSERT INTO earned_channels(user_id, channel_id) VALUES(?,?)",
                    (user.id, ch["id"]),
                ); DB.commit()
                earned += ch["reward"]
            else:
                failed.append(ch["title"] or ch["channel"])
        except TelegramError:
            failed.append(ch["title"] or ch["channel"])
    msg = (f"✅ ربحت {earned} نقطة.\n" if earned else "")
    if failed:
        msg += "⚠️ لم يتم التحقق:\n" + "\n".join(f"• {x}" for x in failed)
    await q.message.reply_text(msg or "ℹ️ لا جديد.")


# ==========================================================
#                         /daily
# ==========================================================

async def section_daily_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_ensure(user)
    today = datetime.now().date().isoformat()
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
    row = DB.execute("SELECT * FROM daily_gifts WHERE user_id=?", (user.id,)).fetchone()

    GIFT      = cfg_int("daily_gift_points", 50)
    BONUS     = cfg_int("daily_gift_bonus", 10)
    MAX_S     = cfg_int("daily_gift_max_streak", 7)

    if row and row_get(row, "last_claim") == today:
        nxt = datetime.combine(datetime.now().date(), datetime.min.time()) + timedelta(days=1)
        rem = nxt - datetime.now()
        await update.effective_message.reply_text(
            "🎁 <b>الهدية اليومية</b>\n\n"
            "⏳ لقد استلمت هديتك اليوم.\n"
            f"🕐 التالية بعد: <b>{rem.seconds//3600}س {(rem.seconds%3600)//60}د</b>\n"
            f"🔥 ستريك: <b>{row_get(row,'streak',0)}/{MAX_S}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    if row and row_get(row, "last_claim") == yesterday:
        new_streak = min(int(row_get(row, "streak", 0)) + 1, MAX_S)
    else:
        new_streak = 1

    bonus = (new_streak - 1) * BONUS
    reward = GIFT + bonus
    user_add_points(user.id, reward)
    if row:
        DB.execute(
            "UPDATE daily_gifts SET last_claim=?, streak=?, "
            "total_claims=COALESCE(total_claims,0)+1 WHERE user_id=?",
            (today, new_streak, user.id),
        )
    else:
        DB.execute(
            "INSERT INTO daily_gifts(user_id,last_claim,streak,total_claims) "
            "VALUES(?,?,?,1)", (user.id, today, new_streak),
        )
    DB.commit()
    if new_streak >= 7:
        await grant_achievement(context, user.id, "streak_7")
    bar = "🔥" * new_streak + "▫️" * (MAX_S - new_streak)
    await update.effective_message.reply_text(
        "🎁 <b>تم استلام الهدية!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 أساسي: <b>{GIFT}</b>\n"
        f"🔥 بونص الستريك: <b>+{bonus}</b>\n"
        f"✨ الإجمالي: <b>{reward}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📅 ستريك: <b>{new_streak}/{MAX_S}</b>\n{bar}",
        parse_mode=ParseMode.HTML,
    )


# ==========================================================
#                        المتجر 🛒
# ==========================================================

async def section_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rate = cfg_int("shop_gem_to_points", 100)
    vip_price = cfg_int("vip_price_stars", 150)
    verify_price = cfg_int("verify_price_points", 5000)
    kb = [
        [InlineKeyboardButton(
            f"💎 جوهرة → {rate} نقطة", callback_data="shop:gem2pts"
        )],
        [InlineKeyboardButton(
            f"👑 VIP أسبوع — ⭐{vip_price}", callback_data="shop:vip7"
        )],
        [InlineKeyboardButton(
            f"🛡 توثيق حساب — {verify_price} نقطة",
            callback_data="shop:verify"
        )],
    ]
    await update.effective_message.reply_text(
        "🛒 <b>المتجر</b>\nاختر منتجاً:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML,
    )


async def cb_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    user = q.from_user
    row = user_ensure(user)
    item = q.data.split(":")[1]
    if item == "gem2pts":
        if (row["gems"] or 0) < 1:
            await q.edit_message_text("⚠️ لا تملك جواهر.")
            return
        rate = cfg_int("shop_gem_to_points", 100)
        DB.execute("UPDATE users SET gems=gems-1, points=points+? WHERE user_id=?",
                   (rate, user.id)); DB.commit()
        await q.edit_message_text(f"✅ حُوّلت 💎 → +{rate} نقطة.")
    elif item == "vip7":
        title = "VIP لمدة 7 أيام"
        stars = cfg_int("vip_price_stars", 150)
        payload = f"vip7_{user.id}_{int(time.time())}"
        try:
            await context.bot.send_invoice(
                chat_id=q.message.chat_id, title=title,
                description=title, payload=payload, provider_token="",
                currency="XTR", prices=[LabeledPrice(label=title, amount=stars)],
            )
        except TelegramError as e:
            await q.edit_message_text(f"⚠️ {e}")
    elif item == "verify":
        cost = cfg_int("verify_price_points", 5000)
        if row["verified"]:
            await q.edit_message_text("✅ حسابك موثّق بالفعل.")
            return
        if row["points"] < cost:
            await q.edit_message_text(f"⚠️ تحتاج {cost} نقطة.")
            return
        DB.execute("UPDATE users SET points=points-?, verified=1 WHERE user_id=?",
                   (cost, user.id)); DB.commit()
        await q.edit_message_text("🛡 تم توثيق حسابك ✅")


async def successful_payment_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يوجّه دفعات النجوم: شحن نقاط أو شراء VIP."""
    sp = update.message.successful_payment
    payload = sp.invoice_payload or ""
    if payload.startswith("charge_"):
        await successful_payment(update, context)
        return
    if payload.startswith("vip7_"):
        m = re.match(r"^vip7_(\d+)_\d+$", payload)
        if not m:
            return
        uid = int(m.group(1))
        cur = user_get(uid)
        base = datetime.now()
        if cur and row_get(cur, "vip_expiry"):
            try:
                d = datetime.fromisoformat(cur["vip_expiry"])
                if d > base:
                    base = d
            except Exception:
                pass
        new_exp = (base + timedelta(days=7)).isoformat()
        DB.execute("UPDATE users SET vip_expiry=? WHERE user_id=?", (new_exp, uid))
        DB.commit()
        await grant_achievement(context, uid, "vip_member")
        await update.effective_message.reply_text("👑 تم تفعيل VIP لمدة 7 أيام!")


# ==========================================================
#                       الكوبونات 🎟
# ==========================================================

async def section_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["coupon_step"] = 1
    await update.effective_message.reply_text("🎟 أرسل كود الكوبون الآن:")


async def handle_coupon_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    code = (update.message.text or "").strip().upper()
    user = update.effective_user
    context.user_data.pop("coupon_step", None)
    c = DB.execute("SELECT * FROM coupons WHERE code=? AND active=1", (code,)).fetchone()
    if not c:
        await update.effective_message.reply_text("⚠️ كوبون غير صالح.")
        return
    if c["used_count"] >= c["max_uses"]:
        await update.effective_message.reply_text("⚠️ هذا الكوبون مستهلك بالكامل.")
        return
    used = DB.execute(
        "SELECT 1 FROM coupon_uses WHERE code=? AND user_id=?", (code, user.id)
    ).fetchone()
    if used:
        await update.effective_message.reply_text("⚠️ استخدمت هذا الكوبون من قبل.")
        return
    DB.execute("INSERT INTO coupon_uses(code,user_id) VALUES(?,?)", (code, user.id))
    DB.execute("UPDATE coupons SET used_count=used_count+1 WHERE code=?", (code,))
    user_add_points(user.id, c["reward"])
    DB.commit()
    await update.effective_message.reply_text(
        f"🎉 تم استخدام الكوبون!\n➕ <b>{c['reward']}</b> نقطة.",
        parse_mode=ParseMode.HTML,
    )


# ==========================================================
#                      اليانصيب 🎰
# ==========================================================

def current_round_id() -> str:
    return datetime.now().strftime("%Y-%m-%d")


async def section_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cost = cfg_int("lottery_ticket_cost", 50)
    rid = current_round_id()
    total_tickets = DB.execute(
        "SELECT COUNT(*) c FROM lottery_tickets WHERE round_id=?", (rid,)
    ).fetchone()["c"]
    pot = total_tickets * cost
    user = update.effective_user
    user_ensure(user)
    my = DB.execute(
        "SELECT COUNT(*) c FROM lottery_tickets WHERE round_id=? AND user_id=?",
        (rid, user.id),
    ).fetchone()["c"]
    kb = [
        [InlineKeyboardButton("🎫 شراء تذكرة", callback_data="lot:buy")],
        [InlineKeyboardButton("🎲 سحب الجائزة (للأدمن)", callback_data="lot:draw")],
    ]
    await update.effective_message.reply_text(
        f"🎰 <b>يانصيب اليوم</b> ({rid})\n"
        f"💰 سعر التذكرة: <b>{cost}</b> نقطة\n"
        f"🎫 عدد التذاكر اليوم: <b>{total_tickets}</b>\n"
        f"💎 الجائزة الحالية: <b>{pot * cfg_int('lottery_jackpot_pct', 70) // 100}</b> نقطة\n"
        f"🧾 تذاكرك: <b>{my}</b>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.HTML,
    )


async def cb_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    sub = q.data.split(":")[1]
    user = q.from_user
    row = user_ensure(user)
    rid = current_round_id()
    cost = cfg_int("lottery_ticket_cost", 50)
    if sub == "buy":
        if row["points"] < cost:
            await q.edit_message_text(f"⚠️ تحتاج {cost} نقطة.")
            return
        DB.execute("UPDATE users SET points=points-? WHERE user_id=?", (cost, user.id))
        DB.execute(
            "INSERT INTO lottery_tickets(user_id, round_id, cost) VALUES(?,?,?)",
            (user.id, rid, cost),
        ); DB.commit()
        await q.edit_message_text("🎫 تم شراء تذكرة! بالتوفيق 🍀")
    elif sub == "draw":
        if not is_admin(user.id):
            await q.answer("❌ للأدمن فقط", show_alert=True); return
        tickets = DB.execute(
            "SELECT * FROM lottery_tickets WHERE round_id=?", (rid,)
        ).fetchall()
        if not tickets:
            await q.edit_message_text("⚠️ لا توجد تذاكر.")
            return
        winner = random.choice(tickets)
        pot = sum(t["cost"] for t in tickets)
        prize = pot * cfg_int("lottery_jackpot_pct", 70) // 100
        user_add_points(winner["user_id"], prize)
        await grant_achievement(context, winner["user_id"], "lottery_win")
        DB.execute("DELETE FROM lottery_tickets WHERE round_id=?", (rid,))
        DB.commit()
        await q.edit_message_text(
            f"🎉 الفائز: <code>{winner['user_id']}</code>\n💰 الجائزة: <b>{prize}</b>",
            parse_mode=ParseMode.HTML,
        )
        try:
            await context.bot.send_message(
                winner["user_id"],
                f"🎉 ربحت <b>{prize}</b> نقطة في يانصيب اليوم!",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ==========================================================
#                   لوحة الشرف 🏆
# ==========================================================

async def section_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    top_p = DB.execute(
        "SELECT user_id, first_name, points FROM users WHERE banned=0 "
        "ORDER BY points DESC LIMIT 10"
    ).fetchall()
    top_i = DB.execute(
        "SELECT user_id, first_name, invites_count FROM users WHERE banned=0 "
        "ORDER BY invites_count DESC LIMIT 10"
    ).fetchall()
    txt = "🏆 <b>لوحة الشرف</b>\n\n💰 <u>أعلى النقاط:</u>\n"
    medals = ["🥇","🥈","🥉"] + ["🔹"] * 7
    for i, r in enumerate(top_p):
        txt += f"{medals[i]} {html.escape(r['first_name'] or '—')} — <b>{r['points']}</b>\n"
    txt += "\n👥 <u>أعلى الدعوات:</u>\n"
    for i, r in enumerate(top_i):
        txt += f"{medals[i]} {html.escape(r['first_name'] or '—')} — <b>{r['invites_count']}</b>\n"
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML)


# ==========================================================
#                       طلباتي 📦
# ==========================================================

async def section_myorders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    rows = DB.execute(
        "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (user.id,)
    ).fetchall()
    if not rows:
        await update.effective_message.reply_text("📭 لا توجد طلبات.")
        return
    icons = {"pending":"⏳","done":"✅","rejected":"❌","cancelled":"🚫"}
    txt = "📦 <b>آخر طلباتك:</b>\n\n"
    for r in rows:
        ic = icons.get(r["status"], "❔")
        txt += (f"{ic} #{r['id']} | {html.escape(r['kind'] or '-')}\n"
                f"   🎯 {html.escape((r['target'] or '')[:40])}\n"
                f"   x{r['quantity']} — 💰 {r['cost']}\n\n")
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML)


# ==========================================================
#                       إنجازاتي 🏅
# ==========================================================

async def section_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_ensure(user)
    got = {r["code"] for r in DB.execute(
        "SELECT code FROM achievements WHERE user_id=?", (user.id,)
    ).fetchall()}
    txt = "🏅 <b>إنجازاتك</b>\n━━━━━━━━━━━━━━━━━━\n"
    for code, (title, desc) in ACHIEVEMENTS.items():
        mark = "✅" if code in got else "🔒"
        txt += f"{mark} {title}\n   <i>{desc}</i>\n"
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML)


# ==========================================================
#                   تحديثات/شروط/تمويل/...
# ==========================================================

async def section_updates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(cfg("updates_text", "🌍 لا تحديثات حالياً."))


async def section_terms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(cfg(
        "terms_text",
        "📜 الشروط والخصوصية:\n\n"
        "1) استخدامك للبوت موافقة على الشروط.\n"
        "2) يُحظر سوء الاستخدام.\n"
        "3) قد تتغيّر الأسعار في أي وقت.",
    ))


async def section_infinite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price = cfg("infinite_price", "100")
    await update.effective_message.reply_text(
        f"🔥 نقاط لا نهائية\n💎 السعر: {price} ⭐\n\n📞 الدعم: @{SUPPORT_USERNAME}"
    )


async def section_funding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(cfg(
        "funding_text",
        f"🤯 لطلب التمويل تواصل: @{SUPPORT_USERNAME}",
    ))


async def section_custom(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          payload: str) -> None:
    await update.effective_message.reply_text(payload or "—")


# ==========================================================
#                   البروفايل /profile
# ==========================================================

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    row = user_ensure(user)
    full_name = row_get(row, "first_name") or "مستخدم"
    uname = row_get(row, "username") or ""
    uname_line = f"@{uname}" if uname else "—"
    verified = bool(row_get(row, "verified", 0))
    txt = (
        "👤 <b>الملف الشخصي</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🪪 الاسم: <b>{html.escape(full_name)}</b>\n"
        f"🔗 المعرّف: {html.escape(uname_line)}\n"
        f"🆔 آيدي: <code>{user.id}</code>\n"
        f"🛡 التوثيق: {'✅ موثّق' if verified else '🔻 غير موثّق'}\n"
        f"👑 VIP: {html.escape(user_vip_days_left(row))}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 النقاط: <b>{row_get(row,'points',0)}</b>\n"
        f"💎 الجواهر: <b>{row_get(row,'gems',0)}</b>\n"
        f"👥 الدعوات: <b>{row_get(row,'invites_count',0)}</b>\n"
        f"📦 طلباتك: <b>{row_get(row,'orders_count',0)}</b>\n"
        f"💸 إجمالي الإنفاق: <b>{row_get(row,'spent_total',0)}</b>\n"
        f"📅 الانضمام: <code>{html.escape(str(row_get(row,'joined_at') or '—'))}</code>"
    )
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML)


# ==========================================================
#                  راوتر الأزرار الديناميكية
# ==========================================================

ACTION_HANDLERS = {
    "services":     section_services,
    "charge":       section_charge,
    "invite":       section_invite,
    "settings":     section_settings,
    "updates":      section_updates,
    "terms":        section_terms,
    "infinite":     section_infinite,
    "funding":      section_funding,
    "daily":        section_daily_gift,
    "profile":      profile_cmd,
    "shop":         section_shop,
    "lottery":      section_lottery,
    "leaderboard":  section_leaderboard,
    "myorders":     section_myorders,
    "achievements": section_achievements,
    "coupon":       section_coupon,
}


async def cb_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعالج ضغطات أزرار القائمة الشفافة (Inline)."""
    q = update.callback_query
    try:
        await q.answer()
    except Exception:
        pass
    user = q.from_user
    row = user_ensure(user)
    if row_get(row, "banned", 0):
        return
    if cfg_int("maintenance", 0) and not is_admin(user.id):
        await q.message.reply_text("🛠 البوت في وضع الصيانة.")
        return
    arg = (q.data or "").split(":", 1)[1]

    if arg == "home":
        rate = "✅ موثق" if row_get(row, "verified", 0) else "🔻 لم يتم التحقق"
        text = WELCOME_TEMPLATE.format(
            name=html.escape(row_get(row, "first_name", "صديق")),
            points=row_get(row, "points", 0) or 0,
            gems=row_get(row, "gems", 0) or 0,
            vip=user_vip_days_left(row),
            uid=user.id,
            rate=rate,
        )
        try:
            await q.edit_message_text(text, reply_markup=main_menu_kb(user.id),
                                      parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.reply_text(text, reply_markup=main_menu_kb(user.id),
                                       parse_mode=ParseMode.HTML)
        return

    if not arg.isdigit():
        return
    btn = DB.execute(
        "SELECT * FROM menu_buttons WHERE id=? AND active=1", (int(arg),)
    ).fetchone()
    if not btn:
        await q.answer("⚠️ الزر غير متاح.", show_alert=True)
        return
    # نظف أي تدفق قديم
    for k in ("pending_order", "transfer_step", "coupon_step"):
        context.user_data.pop(k, None)
    action = btn["action"]
    if action == "custom":
        await section_custom(update, context, btn["payload"] or "")
        return
    h = ACTION_HANDLERS.get(action)
    if h:
        await h(update, context)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    row = user_ensure(user)
    if row["banned"]:
        return
    if not rate_ok(user.id):
        return  # تجاهل بصمت
    text = update.message.text.strip()

    # وضع الصيانة
    if cfg_int("maintenance", 0) and not is_admin(user.id):
        await update.effective_message.reply_text("🛠 البوت في وضع الصيانة.")
        return

    # تدفقات نشطة
    if context.user_data.get("pending_order"):
        await handle_order_flow(update, context); return
    if context.user_data.get("transfer_step"):
        await handle_transfer_flow(update, context); return
    if context.user_data.get("coupon_step"):
        await handle_coupon_flow(update, context); return
    if is_admin(user.id) and context.user_data.get("admin_action"):
        await handle_admin_flow(update, context); return

    if text == "🔙 رجوع للقائمة الرئيسية":
        await update.effective_message.reply_text("🏠 القائمة الرئيسية.",
                                        reply_markup=main_menu_kb(user.id))
        return

    btn = DB.execute(
        "SELECT * FROM menu_buttons WHERE label=? AND active=1", (text,)
    ).fetchone()
    if btn:
        action = btn["action"]
        if action == "custom":
            await section_custom(update, context, btn["payload"] or "")
            return
        h = ACTION_HANDLERS.get(action)
        if h:
            await h(update, context)
            return

    await update.effective_message.reply_text(
        "ℹ️ استخدم الأزرار أو /start.",
        reply_markup=main_menu_kb(user.id),
    )


# ==========================================================
#               تدفق إنشاء الطلب
# ==========================================================

async def handle_order_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    order = context.user_data.get("pending_order") or {}
    text = update.message.text.strip()
    user = update.effective_user
    row = user_ensure(user)

    if order.get("step") == "target":
        if not (text.startswith("http") or text.startswith("@") or text.startswith("t.me")):
            await update.effective_message.reply_text("⚠️ أرسل رابطاً صحيحاً أو @username.")
            return
        order["target"] = text
        order["step"] = "qty"
        context.user_data["pending_order"] = order
        await update.effective_message.reply_text("🔢 أرسل العدد المطلوب:")
        return

    if order.get("step") == "qty":
        if not text.isdigit():
            await update.effective_message.reply_text("⚠️ أرسل رقماً صحيحاً.")
            return
        qty = int(text)
        if qty <= 0:
            await update.effective_message.reply_text("⚠️ العدد > 0."); return
        total_cost = qty * int(order["cost"])
        if row["points"] < total_cost:
            await update.effective_message.reply_text(
                f"⚠️ رصيدك لا يكفي.\n💰 رصيدك: {row['points']} | المطلوب: {total_cost}"
            )
            context.user_data.pop("pending_order", None); return
        DB.execute("UPDATE users SET points=points-?, orders_count=orders_count+1, "
                   "spent_total=spent_total+? WHERE user_id=?",
                   (total_cost, total_cost, user.id))
        cur = DB.execute(
            "INSERT INTO orders(user_id, kind, service_id, target, quantity, cost, status) "
            "VALUES(?,?,?,?,?,?,?)",
            (user.id, order["kind"], order["service_id"], order["target"],
             qty, total_cost, "pending"),
        )
        oid = cur.lastrowid
        DB.commit()
        context.user_data.pop("pending_order", None)
        await update.effective_message.reply_text(
            f"✅ طلبك #{oid} تم إنشاؤه.\n⏳ بانتظار التنفيذ.\n💰 خُصم: {total_cost}"
        )
        # إنجازات
        cnt = (user_get(user.id) or {"orders_count": 0})["orders_count"]
        if cnt == 1:
            await grant_achievement(context, user.id, "first_order")
        if cnt >= 10:
            await grant_achievement(context, user.id, "ten_orders")
        # إشعار الأدمن مع أزرار
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ تنفيذ", callback_data=f"ord:done:{oid}"),
            InlineKeyboardButton("❌ رفض",  callback_data=f"ord:reject:{oid}"),
        ]])
        for aid in all_admins():
            try:
                await context.bot.send_message(
                    aid,
                    f"🆕 طلب #{oid}\n👤 {user.id} (@{user.username or '-'})\n"
                    f"📌 {order['kind']} — {order.get('title','')}\n"
                    f"🎯 {order['target']}\n🔢 {qty} | 💰 {total_cost}",
                    reply_markup=kb,
                )
            except (Forbidden, BadRequest):
                pass


async def cb_order_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    _, action, oid = q.data.split(":")
    oid = int(oid)
    o = DB.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        await q.edit_message_text("⚠️ الطلب غير موجود."); return
    if action == "done":
        DB.execute("UPDATE orders SET status='done' WHERE id=?", (oid,)); DB.commit()
        try:
            await context.bot.send_message(
                o["user_id"], f"✅ تم تنفيذ طلبك #{oid} بنجاح."
            )
        except Exception: pass
        await q.edit_message_text(q.message.text + f"\n\n✅ تم التنفيذ بواسطة {q.from_user.id}")
    elif action == "reject":
        DB.execute("UPDATE orders SET status='rejected' WHERE id=?", (oid,))
        # إعادة النقاط
        DB.execute("UPDATE users SET points=points+? WHERE user_id=?",
                   (o["cost"], o["user_id"]))
        DB.commit()
        try:
            await context.bot.send_message(
                o["user_id"],
                f"❌ تم رفض طلبك #{oid} وأُعيدت {o['cost']} نقطة لرصيدك.",
            )
        except Exception: pass
        await q.edit_message_text(q.message.text + f"\n\n❌ مرفوض بواسطة {q.from_user.id}")


# ==========================================================
#                     تدفق تحويل النقاط
# ==========================================================

async def handle_transfer_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    step = context.user_data.get("transfer_step")
    text = update.message.text.strip()
    user = update.effective_user
    row = user_ensure(user)
    fee_pct = cfg_int("transfer_fee_percent", 10)

    if step == "target":
        if not text.isdigit():
            await update.effective_message.reply_text("⚠️ آيدي رقمي فقط."); return
        tid = int(text)
        if tid == user.id:
            await update.effective_message.reply_text("⚠️ لا يمكنك التحويل لنفسك."); return
        if not user_get(tid):
            await update.effective_message.reply_text("⚠️ المستخدم غير مسجل."); return
        context.user_data["transfer_target"] = tid
        context.user_data["transfer_step"] = "amount"
        await update.effective_message.reply_text(
            f"💰 رصيدك: {row['points']}\n"
            f"🔢 أرسل المبلغ (عمولة {fee_pct}%):"
        )
        return

    if step == "amount":
        if not text.isdigit():
            await update.effective_message.reply_text("⚠️ رقم فقط."); return
        amount = int(text)
        if amount <= 0:
            await update.effective_message.reply_text("⚠️ > 0."); return
        fee = max(1, amount * fee_pct // 100)
        total = amount + fee
        if row["points"] < total:
            await update.effective_message.reply_text(
                f"⚠️ غير كافٍ. المطلوب: {total} (تحويل {amount} + {fee})"
            )
            context.user_data.pop("transfer_step", None)
            context.user_data.pop("transfer_target", None)
            return
        tid = context.user_data["transfer_target"]
        DB.execute("UPDATE users SET points=points-? WHERE user_id=?", (total, user.id))
        DB.execute("UPDATE users SET points=points+? WHERE user_id=?", (amount, tid))
        DB.execute("INSERT INTO transfer_history(from_id,to_id,amount,fee) VALUES(?,?,?,?)",
                   (user.id, tid, amount, fee))
        DB.commit()
        context.user_data.pop("transfer_step", None)
        context.user_data.pop("transfer_target", None)
        await update.effective_message.reply_text(f"✅ تم تحويل {amount} إلى {tid}.\n💸 العمولة: {fee}")
        try:
            await context.bot.send_message(tid, f"🎁 استلمت {amount} نقطة من {user.id}!")
        except Exception:
            pass


# ==========================================================
#                       لوحة الأدمن 🛠
# ==========================================================

ADMIN_MENU_TEXT = "🛠 <b>لوحة تحكم الأدمن</b>\nاختر الإجراء:"


def admin_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📊 إحصائيات شاملة", callback_data="adm:stats")],
        [InlineKeyboardButton("🗂 إدارة الأقسام",   callback_data="secm:list"),
         InlineKeyboardButton("📲 إدارة الأزرار",   callback_data="menm:list")],
        [InlineKeyboardButton("📢 إدارة القنوات",   callback_data="chm:list"),
         InlineKeyboardButton("⭐ باقات النجوم",     callback_data="pkm:list")],
        [InlineKeyboardButton("🎟 الكوبونات",        callback_data="cpm:list"),
         InlineKeyboardButton("⚙️ الإعدادات الحية", callback_data="cfg:list")],
        [InlineKeyboardButton("👥 إدارة الأدمن",    callback_data="adm:admins"),
         InlineKeyboardButton("🔎 بحث مستخدم",      callback_data="adm:search")],
        [InlineKeyboardButton("💎 إضافة نقاط",      callback_data="adm:add_points"),
         InlineKeyboardButton("➖ خصم نقاط",         callback_data="adm:sub_points")],
        [InlineKeyboardButton("💠 إضافة جواهر",     callback_data="adm:add_gems"),
         InlineKeyboardButton("👑 منح VIP",          callback_data="adm:add_vip")],
        [InlineKeyboardButton("❌ إزالة VIP",       callback_data="adm:rem_vip"),
         InlineKeyboardButton("🛡 توثيق/إلغاء",     callback_data="adm:toggle_verify")],
        [InlineKeyboardButton("🚫 حظر",             callback_data="adm:ban"),
         InlineKeyboardButton("✅ فك حظر",          callback_data="adm:unban")],
        [InlineKeyboardButton("📣 إذاعة عامة",      callback_data="adm:broadcast"),
         InlineKeyboardButton("📦 طلبات معلقة",     callback_data="adm:pending")],
        [InlineKeyboardButton("📜 الشروط",          callback_data="adm:set_terms"),
         InlineKeyboardButton("🌍 التحديثات",       callback_data="adm:set_updates")],
        [InlineKeyboardButton("💳 الدفع اليدوي",    callback_data="adm:set_manual"),
         InlineKeyboardButton("💾 نسخة احتياطية",   callback_data="adm:backup")],
        [InlineKeyboardButton(
            f"{'🟢 الصيانة:OFF' if not cfg_int('maintenance') else '🔴 الصيانة:ON'}",
            callback_data="adm:toggle_maint"),
         InlineKeyboardButton(
            f"{'🟢 إجباري:OFF' if not cfg_int('force_join') else '🔴 إجباري:ON'}",
            callback_data="adm:toggle_force"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("🚫 للأدمن فقط.")
        return
    await update.effective_message.reply_text(ADMIN_MENU_TEXT, reply_markup=admin_kb(),
                                    parse_mode=ParseMode.HTML)


async def cb_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    action = q.data.split(":")[1]

    if action == "stats":
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).isoformat()
        total = DB.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        new_today = DB.execute(
            "SELECT COUNT(*) c FROM users WHERE joined_at >= ?", (today,)
        ).fetchone()["c"]
        new_week = DB.execute(
            "SELECT COUNT(*) c FROM users WHERE joined_at >= ?", (week_ago,)
        ).fetchone()["c"]
        vip = DB.execute(
            "SELECT COUNT(*) c FROM users WHERE infinite_vip=1 OR "
            "(vip_expiry IS NOT NULL AND vip_expiry > ?)",
            (now.isoformat(),),
        ).fetchone()["c"]
        banned = DB.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
        verified = DB.execute("SELECT COUNT(*) c FROM users WHERE verified=1").fetchone()["c"]
        orders_p = DB.execute("SELECT COUNT(*) c FROM orders WHERE status='pending'").fetchone()["c"]
        orders_d = DB.execute("SELECT COUNT(*) c FROM orders WHERE status='done'").fetchone()["c"]
        sum_pts = DB.execute("SELECT COALESCE(SUM(points),0) s FROM users").fetchone()["s"]
        sum_gems = DB.execute("SELECT COALESCE(SUM(gems),0) s FROM users").fetchone()["s"]
        sec_cnt = DB.execute("SELECT COUNT(*) c FROM sections").fetchone()["c"]
        svc_cnt = DB.execute("SELECT COUNT(*) c FROM section_services").fetchone()["c"]
        await q.edit_message_text(
            f"📊 <b>إحصائيات شاملة</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👥 المستخدمون: <b>{total}</b>\n"
            f"🆕 اليوم: <b>{new_today}</b> | الأسبوع: <b>{new_week}</b>\n"
            f"👑 VIP: <b>{vip}</b> | 🛡 موثق: <b>{verified}</b>\n"
            f"🚫 محظور: <b>{banned}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📦 طلبات معلقة: <b>{orders_p}</b> | منفذة: <b>{orders_d}</b>\n"
            f"🗂 أقسام: <b>{sec_cnt}</b> | 🛒 خدمات: <b>{svc_cnt}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💰 إجمالي النقاط: <b>{sum_pts}</b>\n"
            f"💎 إجمالي الجواهر: <b>{sum_gems}</b>",
            reply_markup=admin_kb(), parse_mode=ParseMode.HTML,
        )
        return

    if action == "toggle_maint":
        cfg_set("maintenance", "0" if cfg_int("maintenance") else "1")
        await q.edit_message_text(ADMIN_MENU_TEXT, reply_markup=admin_kb(),
                                  parse_mode=ParseMode.HTML)
        return
    if action == "toggle_force":
        cfg_set("force_join", "0" if cfg_int("force_join") else "1")
        await q.edit_message_text(ADMIN_MENU_TEXT, reply_markup=admin_kb(),
                                  parse_mode=ParseMode.HTML)
        return

    if action == "backup":
        try:
            bpath = f"/tmp/backup_{int(time.time())}.db"
            shutil.copy(DB_PATH, bpath)
            with open(bpath, "rb") as f:
                await context.bot.send_document(
                    q.from_user.id, document=InputFile(f, filename="bot_data.db"),
                    caption="💾 نسخة احتياطية",
                )
            os.remove(bpath)
            await q.answer("✅ أُرسلت", show_alert=False)
        except Exception as e:
            await q.edit_message_text(f"⚠️ {e}", reply_markup=admin_kb())
        return

    if action == "admins":
        admins = DB.execute("SELECT user_id FROM admins").fetchall()
        txt = "👥 <b>قائمة الأدمن</b>\n\n"
        txt += "💎 سوبر:\n" + "\n".join(f"• <code>{x}</code>" for x in SUPER_ADMINS) + "\n\n"
        if admins:
            txt += "🛠 إضافيين:\n" + "\n".join(f"• <code>{a['user_id']}</code>" for a in admins)
        else:
            txt += "ℹ️ لا أدمن إضافي."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة", callback_data="adm:add_admin"),
             InlineKeyboardButton("🗑 حذف",   callback_data="adm:del_admin")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")],
        ])
        await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    if action == "menu":
        await q.edit_message_text(ADMIN_MENU_TEXT, reply_markup=admin_kb(),
                                  parse_mode=ParseMode.HTML)
        return

    if action == "pending":
        rows = DB.execute(
            "SELECT * FROM orders WHERE status='pending' ORDER BY id DESC LIMIT 20"
        ).fetchall()
        if not rows:
            await q.edit_message_text("📦 لا طلبات معلقة.", reply_markup=admin_kb())
            return
        txt = "📦 <b>الطلبات المعلقة:</b>\n\n"
        for r in rows:
            txt += (f"#{r['id']} | {r['kind']} | uid={r['user_id']}\n"
                    f"🎯 {html.escape((r['target'] or '')[:50])}\n"
                    f"x{r['quantity']} | 💰 {r['cost']}\n\n")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ إنهاء طلب برقم", callback_data="adm:done_order")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")],
        ])
        await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML)
        return

    prompts = {
        "search":         ("🔎 أرسل آيدي أو @username:",                       "search"),
        "user_info":      ("🔎 أرسل آيدي:",                                    "user_info"),
        "add_points":     ("💎 أرسل: user_id|amount",                          "add_points"),
        "sub_points":     ("➖ أرسل: user_id|amount",                           "sub_points"),
        "add_gems":       ("💠 أرسل: user_id|amount",                           "add_gems"),
        "add_vip":        ("👑 أرسل: user_id|days  (0 = لا نهائي)",             "add_vip"),
        "rem_vip":        ("❌ أرسل آيدي:",                                    "rem_vip"),
        "toggle_verify":  ("🛡 أرسل آيدي للتبديل:",                            "toggle_verify"),
        "ban":            ("🚫 أرسل آيدي للحظر:",                              "ban"),
        "unban":          ("✅ أرسل آيدي لفك الحظر:",                          "unban"),
        "broadcast":      ("📣 أرسل نص الإذاعة الآن:",                          "broadcast"),
        "set_terms":      ("📜 أرسل نص الشروط الجديد:",                         "set_terms"),
        "set_updates":    ("🌍 أرسل نص التحديثات الجديد:",                      "set_updates"),
        "set_manual":     ("💳 أرسل تعليمات الدفع اليدوي:",                    "set_manual"),
        "done_order":     ("✅ أرسل ID الطلب:",                                "done_order"),
        "add_admin":      ("➕ أرسل آيدي الأدمن الجديد:",                       "add_admin"),
        "del_admin":      ("🗑 أرسل آيدي الأدمن للحذف:",                       "del_admin"),
    }
    p = prompts.get(action)
    if p:
        context.user_data["admin_action"] = p[1]
        await q.edit_message_text(p[0])


async def handle_admin_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    action = context.user_data.pop("admin_action", None)
    text = update.message.text.strip()
    if not action:
        return
    try:
        if action == "search":
            if text.isdigit():
                r = user_get(int(text))
            else:
                t = text.lstrip("@")
                r = DB.execute("SELECT * FROM users WHERE username=?", (t,)).fetchone()
            if not r:
                await update.effective_message.reply_text("⚠️ لم يُعثر."); return
            await update.effective_message.reply_text(
                f"👤 <code>{r['user_id']}</code>\n"
                f"@{r['username'] or '-'} | {html.escape(r['first_name'] or '')}\n"
                f"💰 {r['points']} | 💎 {r['gems']}\n"
                f"👑 {user_vip_days_left(r)} | 🛡 {'✅' if r['verified'] else '❌'}\n"
                f"👥 دعوات: {r['invites_count']} | 📦 طلبات: {r['orders_count']}\n"
                f"🚫 محظور: {bool(r['banned'])}\n"
                f"📅 {r['joined_at']}",
                parse_mode=ParseMode.HTML,
            )

        elif action in ("add_points", "sub_points", "add_gems"):
            uid, amt = text.split("|", 1); uid, amt = int(uid), int(amt)
            if action == "add_points":   user_add_points(uid, amt)
            elif action == "sub_points": user_add_points(uid, -amt)
            else:                        user_add_gems(uid, amt)
            await update.effective_message.reply_text("✅ تم.")
        elif action == "add_vip":
            uid, days = text.split("|", 1); uid, days = int(uid), int(days)
            if days == 0:
                DB.execute("UPDATE users SET infinite_vip=1 WHERE user_id=?", (uid,))
            else:
                exp = (datetime.now() + timedelta(days=days)).isoformat()
                DB.execute("UPDATE users SET vip_expiry=? WHERE user_id=?", (exp, uid))
            DB.commit()
            await grant_achievement(context, uid, "vip_member")
            await update.effective_message.reply_text("👑 تم.")
        elif action == "rem_vip":
            DB.execute("UPDATE users SET infinite_vip=0, vip_expiry=NULL WHERE user_id=?",
                       (int(text),)); DB.commit()
            await update.effective_message.reply_text("❌ تم.")
        elif action == "toggle_verify":
            DB.execute("UPDATE users SET verified = 1 - verified WHERE user_id=?",
                       (int(text),)); DB.commit()
            await update.effective_message.reply_text("🛡 تم التبديل.")
        elif action == "ban":
            DB.execute("UPDATE users SET banned=1 WHERE user_id=?", (int(text),)); DB.commit()
            await update.effective_message.reply_text("🚫 تم.")
        elif action == "unban":
            DB.execute("UPDATE users SET banned=0 WHERE user_id=?", (int(text),)); DB.commit()
            await update.effective_message.reply_text("✅ تم.")
        elif action == "broadcast":
            users = DB.execute("SELECT user_id FROM users WHERE banned=0").fetchall()
            ok, fail = 0, 0
            await update.effective_message.reply_text(f"📣 إذاعة لـ {len(users)} مستخدم...")
            for u in users:
                try:
                    await context.bot.send_message(u["user_id"], text); ok += 1
                    await asyncio.sleep(0.05)
                except RetryAfter as ra:
                    await asyncio.sleep(ra.retry_after + 1)
                    try:
                        await context.bot.send_message(u["user_id"], text); ok += 1
                    except Exception: fail += 1
                except Exception: fail += 1
            await update.effective_message.reply_text(f"📣 ✅ {ok} | ❌ {fail}")
        elif action == "set_terms":
            cfg_set("terms_text", text); await update.effective_message.reply_text("✅ تم.")
        elif action == "set_updates":
            cfg_set("updates_text", text); await update.effective_message.reply_text("✅ تم.")
        elif action == "set_manual":
            cfg_set("manual_payment_info", text); await update.effective_message.reply_text("✅ تم.")
        elif action == "done_order":
            oid = int(text)
            o = DB.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            if not o: await update.effective_message.reply_text("⚠️ غير موجود."); return
            DB.execute("UPDATE orders SET status='done' WHERE id=?", (oid,)); DB.commit()
            try: await context.bot.send_message(o["user_id"], f"✅ تم تنفيذ طلبك #{oid}")
            except Exception: pass
            await update.effective_message.reply_text("✅ تم.")
        elif action == "add_admin":
            DB.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (int(text),))
            DB.commit()
            await update.effective_message.reply_text("✅ تمت الإضافة.")
        elif action == "del_admin":
            DB.execute("DELETE FROM admins WHERE user_id=?", (int(text),)); DB.commit()
            await update.effective_message.reply_text("🗑 تم.")

        # ---- إدارة الأقسام ----
        elif action == "secm_add":
            parts = [x.strip() for x in text.split("|", 1)]
            name = parts[0]; emoji = parts[1] if len(parts) > 1 and parts[1] else "📦"
            if not name: await update.effective_message.reply_text("⚠️ فارغ."); return
            try:
                mx = DB.execute("SELECT COALESCE(MAX(sort_order),0) m FROM sections").fetchone()["m"]
                DB.execute("INSERT INTO sections(name,emoji,sort_order) VALUES(?,?,?)",
                           (name, emoji, mx + 1)); DB.commit()
                await update.effective_message.reply_text(f"✅ {emoji} {name}")
            except sqlite3.IntegrityError:
                await update.effective_message.reply_text("⚠️ موجود.")
        elif action == "secm_rename":
            sec_id = context.user_data.pop("secm_target", None)
            if not sec_id: return
            parts = [x.strip() for x in text.split("|", 1)]
            name = parts[0]; emoji = parts[1] if len(parts) > 1 and parts[1] else "📦"
            DB.execute("UPDATE sections SET name=?, emoji=? WHERE id=?",
                       (name, emoji, sec_id)); DB.commit()
            await update.effective_message.reply_text("✅ تم.")
        elif action == "secm_addsvc":
            sec_id = context.user_data.pop("secm_target", None)
            if not sec_id: return
            title, cost = text.split("|", 1)
            DB.execute("INSERT INTO section_services(section_id,title,cost) VALUES(?,?,?)",
                       (sec_id, title.strip(), int(cost))); DB.commit()
            await update.effective_message.reply_text("✅ تمت إضافة الخدمة.")
        elif action == "secm_delsvc":
            context.user_data.pop("secm_target", None)
            DB.execute("DELETE FROM section_services WHERE id=?", (int(text),)); DB.commit()
            await update.effective_message.reply_text("🗑 تم.")
        elif action == "secm_editsvc":
            svc_id = context.user_data.pop("secm_target", None)
            if not svc_id: return
            title, cost = text.split("|", 1)
            DB.execute("UPDATE section_services SET title=?, cost=? WHERE id=?",
                       (title.strip(), int(cost), svc_id)); DB.commit()
            await update.effective_message.reply_text("✅ تم تعديل الخدمة.")

        # ---- الأزرار الديناميكية ----
        elif action == "menm_add":
            parts = [x.strip() for x in text.split("|", 2)]
            if len(parts) < 2:
                await update.effective_message.reply_text("⚠️ صيغة: التسمية|الأكشن|payload?")
                return
            label, act = parts[0], parts[1]
            payload = parts[2] if len(parts) > 2 else None
            try:
                mx = DB.execute("SELECT COALESCE(MAX(row_pos),0) m FROM menu_buttons").fetchone()["m"]
                DB.execute(
                    "INSERT INTO menu_buttons(label,action,payload,row_pos) VALUES(?,?,?,?)",
                    (label, act, payload, mx + 1),
                ); DB.commit()
                await update.effective_message.reply_text("✅ تم.")
            except sqlite3.IntegrityError:
                await update.effective_message.reply_text("⚠️ التسمية مكررة.")
        elif action == "menm_edit":
            bid = context.user_data.pop("menm_target", None)
            if not bid: return
            parts = [x.strip() for x in text.split("|", 2)]
            label = parts[0]; act = parts[1] if len(parts) > 1 else None
            payload = parts[2] if len(parts) > 2 else None
            if act:
                DB.execute("UPDATE menu_buttons SET label=?, action=?, payload=? WHERE id=?",
                           (label, act, payload, bid))
            else:
                DB.execute("UPDATE menu_buttons SET label=? WHERE id=?", (label, bid))
            DB.commit()
            await update.effective_message.reply_text("✅ تم.")

        # ---- القنوات ----
        elif action == "chm_add":
            parts = [x.strip() for x in text.split("|", 3)]
            if len(parts) < 3:
                await update.effective_message.reply_text("⚠️ صيغة: @القناة|العنوان|المكافأة|إجباري(0/1)")
                return
            ch, title, reward = parts[0], parts[1], int(parts[2])
            req = int(parts[3]) if len(parts) > 3 else 0
            if not ch.startswith("@") and not ch.startswith("-100"):
                ch = "@" + ch.lstrip("@")
            DB.execute(
                "INSERT INTO mandatory_channels(channel,title,reward,required) VALUES(?,?,?,?)",
                (ch, title, reward, req),
            ); DB.commit()
            await update.effective_message.reply_text("✅ تم.")
        elif action == "chm_del":
            DB.execute("DELETE FROM mandatory_channels WHERE id=?", (int(text),)); DB.commit()
            await update.effective_message.reply_text("🗑 تم.")

        # ---- باقات النجوم ----
        elif action == "pkm_add":
            p, s = text.split("|", 1)
            DB.execute("INSERT INTO stars_packages(points,stars) VALUES(?,?)",
                       (int(p), int(s))); DB.commit()
            await update.effective_message.reply_text("✅ تم.")
        elif action == "pkm_del":
            DB.execute("DELETE FROM stars_packages WHERE id=?", (int(text),)); DB.commit()
            await update.effective_message.reply_text("🗑 تم.")

        # ---- الكوبونات ----
        elif action == "cpm_add":
            parts = [x.strip() for x in text.split("|", 2)]
            code = parts[0].upper()
            reward = int(parts[1])
            uses = int(parts[2]) if len(parts) > 2 else 1
            DB.execute(
                "INSERT OR REPLACE INTO coupons(code,reward,max_uses,active) VALUES(?,?,?,1)",
                (code, reward, uses),
            ); DB.commit()
            await update.effective_message.reply_text(f"✅ كوبون: <code>{code}</code>",
                                            parse_mode=ParseMode.HTML)
        elif action == "cpm_del":
            DB.execute("DELETE FROM coupons WHERE code=?", (text.upper(),)); DB.commit()
            await update.effective_message.reply_text("🗑 تم.")

        # ---- إعدادات حية ----
        elif action == "cfg_set":
            key = context.user_data.pop("cfg_key", None)
            if not key: return
            cfg_set(key, text)
            await update.effective_message.reply_text(f"✅ {key} = {text}")

    except Exception as e:
        logger.exception("admin action error")
        await update.effective_message.reply_text(f"⚠️ خطأ: {e}")


# ==========================================================
#               إدارة الأقسام (Inline)
# ==========================================================

def sections_manage_kb() -> InlineKeyboardMarkup:
    sections = DB.execute("SELECT * FROM sections ORDER BY sort_order, id").fetchall()
    kb = []
    for s in sections:
        st = "🟢" if s["active"] else "🔴"
        kb.append([InlineKeyboardButton(
            f"{st} {s['emoji']} {s['name']}", callback_data=f"secm:open:{s['id']}",
        )])
    kb.append([InlineKeyboardButton("➕ إضافة قسم", callback_data="secm:add")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")])
    return InlineKeyboardMarkup(kb)


def section_detail_kb(sec_id: int, active: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة خدمة", callback_data=f"secm:addsvc:{sec_id}"),
         InlineKeyboardButton("✏️ تعديل خدمة", callback_data=f"secm:editsvc:{sec_id}")],
        [InlineKeyboardButton("🗑 حذف خدمة", callback_data=f"secm:delsvc:{sec_id}"),
         InlineKeyboardButton("🔄 تبديل خدمة", callback_data=f"secm:toggsvc:{sec_id}")],
        [InlineKeyboardButton("🔴 تعطيل" if active else "🟢 تفعيل",
                              callback_data=f"secm:toggle:{sec_id}"),
         InlineKeyboardButton("✏️ إعادة تسمية", callback_data=f"secm:rename:{sec_id}")],
        [InlineKeyboardButton("⬆️", callback_data=f"secm:up:{sec_id}"),
         InlineKeyboardButton("⬇️", callback_data=f"secm:down:{sec_id}")],
        [InlineKeyboardButton("❌ حذف القسم", callback_data=f"secm:delsec:{sec_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="secm:list")],
    ])


async def cb_sections_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id): return
    parts = (q.data or "").split(":")
    sub = parts[1] if len(parts) > 1 else ""

    if sub == "list":
        await q.edit_message_text("🗂 <b>إدارة الأقسام</b>",
                                  reply_markup=sections_manage_kb(),
                                  parse_mode=ParseMode.HTML)
        return
    if sub == "add":
        context.user_data["admin_action"] = "secm_add"
        await q.edit_message_text("➕ صيغة: <code>الاسم|الإيموجي</code>",
                                  parse_mode=ParseMode.HTML)
        return
    if sub == "open":
        sec_id = int(parts[2])
        sec = DB.execute("SELECT * FROM sections WHERE id=?", (sec_id,)).fetchone()
        if not sec:
            await q.edit_message_text("⚠️ غير موجود.", reply_markup=sections_manage_kb())
            return
        services = DB.execute(
            "SELECT * FROM section_services WHERE section_id=? ORDER BY id DESC",
            (sec_id,),
        ).fetchall()
        txt = (f"{sec['emoji']} <b>{html.escape(sec['name'])}</b>\n"
               f"🆔 <code>{sec['id']}</code> | "
               f"{'🟢' if sec['active'] else '🔴'}\n"
               f"عدد الخدمات: <b>{len(services)}</b>\n\n")
        if services:
            txt += "📋 الخدمات:\n"
            for s in services:
                act = "🟢" if s["active"] else "🔴"
                txt += f"• <code>{s['id']}</code> {act} {html.escape(s['title'])} — {s['cost']}\n"
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML,
                                  reply_markup=section_detail_kb(sec_id, sec["active"]))
        return
    if sub == "toggle":
        sec_id = int(parts[2])
        DB.execute("UPDATE sections SET active=1-active WHERE id=?", (sec_id,)); DB.commit()
        q.data = f"secm:open:{sec_id}"; await cb_sections_manage(update, context); return
    if sub == "delsec":
        sec_id = int(parts[2])
        DB.execute("DELETE FROM section_services WHERE section_id=?", (sec_id,))
        DB.execute("DELETE FROM sections WHERE id=?", (sec_id,)); DB.commit()
        await q.edit_message_text("🗑 حُذف.", reply_markup=sections_manage_kb()); return
    if sub == "rename":
        sec_id = int(parts[2])
        context.user_data["admin_action"] = "secm_rename"
        context.user_data["secm_target"] = sec_id
        await q.edit_message_text("✏️ <code>الاسم|الإيموجي</code>", parse_mode=ParseMode.HTML)
        return
    if sub == "addsvc":
        sec_id = int(parts[2])
        context.user_data["admin_action"] = "secm_addsvc"
        context.user_data["secm_target"] = sec_id
        await q.edit_message_text("➕ <code>العنوان|التكلفة</code>", parse_mode=ParseMode.HTML)
        return
    if sub == "delsvc":
        context.user_data["admin_action"] = "secm_delsvc"
        await q.edit_message_text("🗑 أرسل ID الخدمة:")
        return
    if sub == "toggsvc":
        context.user_data["admin_action"] = "secm_toggsvc"
        await q.edit_message_text("🔄 أرسل ID الخدمة لتبديل تفعيلها:")
        # نعالجها هنا مباشرة
        return
    if sub == "editsvc":
        # نطلب ID ثم البيانات
        sec_id = int(parts[2])
        context.user_data["secm_editsvc_sec"] = sec_id
        context.user_data["admin_action"] = "secm_pickedit"
        await q.edit_message_text("✏️ أرسل: ID|العنوان_الجديد|التكلفة")
        return
    if sub in ("up", "down"):
        sec_id = int(parts[2])
        sec = DB.execute("SELECT * FROM sections WHERE id=?", (sec_id,)).fetchone()
        if sec:
            order = sec["sort_order"]
            other = DB.execute(
                "SELECT * FROM sections WHERE sort_order " +
                ("< ? ORDER BY sort_order DESC" if sub == "up" else "> ? ORDER BY sort_order ASC"),
                (order,),
            ).fetchone()
            if other:
                DB.execute("UPDATE sections SET sort_order=? WHERE id=?", (other["sort_order"], sec_id))
                DB.execute("UPDATE sections SET sort_order=? WHERE id=?", (order, other["id"]))
                DB.commit()
        q.data = f"secm:open:{sec_id}"; await cb_sections_manage(update, context); return


# توسعة handle_admin_flow لمعالجة secm_pickedit / secm_toggsvc
_old_handle_admin_flow = handle_admin_flow

async def handle_admin_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    action = context.user_data.get("admin_action")
    if action == "secm_pickedit":
        context.user_data.pop("admin_action", None)
        try:
            sid, title, cost = update.message.text.strip().split("|", 2)
            DB.execute("UPDATE section_services SET title=?, cost=? WHERE id=?",
                       (title.strip(), int(cost), int(sid))); DB.commit()
            await update.effective_message.reply_text("✅ تم.")
        except Exception as e:
            await update.effective_message.reply_text(f"⚠️ {e}")
        return
    if action == "secm_toggsvc":
        context.user_data.pop("admin_action", None)
        try:
            DB.execute("UPDATE section_services SET active=1-active WHERE id=?",
                       (int(update.message.text.strip()),)); DB.commit()
            await update.effective_message.reply_text("🔄 تم.")
        except Exception as e:
            await update.effective_message.reply_text(f"⚠️ {e}")
        return
    await _old_handle_admin_flow(update, context)


# ==========================================================
#                إدارة الأزرار الرئيسية
# ==========================================================

def menu_manage_kb() -> InlineKeyboardMarkup:
    btns = DB.execute("SELECT * FROM menu_buttons ORDER BY row_pos, sort_order, id").fetchall()
    kb = []
    for b in btns:
        st = "🟢" if b["active"] else "🔴"
        kb.append([InlineKeyboardButton(
            f"{st} {b['label']} [{b['action']}]",
            callback_data=f"menm:open:{b['id']}",
        )])
    kb.append([InlineKeyboardButton("➕ إضافة زر", callback_data="menm:add")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")])
    return InlineKeyboardMarkup(kb)


async def cb_menu_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    parts = q.data.split(":"); sub = parts[1]

    if sub == "list":
        actions_help = (
            "📲 <b>إدارة أزرار القائمة الرئيسية</b>\n\n"
            "Actions المتاحة:\n"
            "<code>services, charge, invite, settings, updates, terms, infinite, "
            "funding, daily, profile, shop, lottery, leaderboard, myorders, "
            "achievements, coupon, custom</code>"
        )
        await q.edit_message_text(actions_help, reply_markup=menu_manage_kb(),
                                  parse_mode=ParseMode.HTML)
        return
    if sub == "add":
        context.user_data["admin_action"] = "menm_add"
        await q.edit_message_text(
            "➕ صيغة: <code>التسمية|الأكشن|النص_للعرض(اختياري)</code>\n\n"
            "مثال: <code>📢 قناتنا|custom|انضم: @mychannel</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    if sub == "open":
        bid = int(parts[2])
        b = DB.execute("SELECT * FROM menu_buttons WHERE id=?", (bid,)).fetchone()
        if not b:
            await q.edit_message_text("⚠️ غير موجود.", reply_markup=menu_manage_kb()); return
        txt = (f"📲 <b>{html.escape(b['label'])}</b>\n"
               f"🆔 <code>{b['id']}</code>\n"
               f"⚙️ Action: <code>{b['action']}</code>\n"
               f"💬 Payload: <code>{html.escape((b['payload'] or '—')[:200])}</code>\n"
               f"الحالة: {'🟢' if b['active'] else '🔴'}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ تعديل", callback_data=f"menm:edit:{bid}"),
             InlineKeyboardButton("🔄 تبديل", callback_data=f"menm:toggle:{bid}")],
            [InlineKeyboardButton("⬆️", callback_data=f"menm:up:{bid}"),
             InlineKeyboardButton("⬇️", callback_data=f"menm:down:{bid}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"menm:del:{bid}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="menm:list")],
        ])
        await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML); return
    if sub == "toggle":
        bid = int(parts[2])
        DB.execute("UPDATE menu_buttons SET active=1-active WHERE id=?", (bid,)); DB.commit()
        q.data = f"menm:open:{bid}"; await cb_menu_manage(update, context); return
    if sub == "del":
        bid = int(parts[2])
        DB.execute("DELETE FROM menu_buttons WHERE id=?", (bid,)); DB.commit()
        await q.edit_message_text("🗑 حُذف.", reply_markup=menu_manage_kb()); return
    if sub == "edit":
        bid = int(parts[2])
        context.user_data["admin_action"] = "menm_edit"
        context.user_data["menm_target"] = bid
        await q.edit_message_text(
            "✏️ <code>التسمية|الأكشن|payload</code>", parse_mode=ParseMode.HTML
        ); return
    if sub in ("up", "down"):
        bid = int(parts[2])
        b = DB.execute("SELECT * FROM menu_buttons WHERE id=?", (bid,)).fetchone()
        if b:
            new_row = max(0, b["row_pos"] - 1) if sub == "up" else b["row_pos"] + 1
            DB.execute("UPDATE menu_buttons SET row_pos=? WHERE id=?", (new_row, bid))
            DB.commit()
        q.data = f"menm:open:{bid}"; await cb_menu_manage(update, context); return


# ==========================================================
#                إدارة القنوات
# ==========================================================

def channels_manage_kb() -> InlineKeyboardMarkup:
    chans = DB.execute("SELECT * FROM mandatory_channels").fetchall()
    kb = []
    for c in chans:
        st = "🟢" if c["active"] else "🔴"
        rq = "📢" if c["required"] else "🎁"
        kb.append([InlineKeyboardButton(
            f"{st}{rq} {c['title'] or c['channel']} (+{c['reward']})",
            callback_data=f"chm:open:{c['id']}",
        )])
    kb.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="chm:add")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")])
    return InlineKeyboardMarkup(kb)


async def cb_channels_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    parts = q.data.split(":"); sub = parts[1]
    if sub == "list":
        await q.edit_message_text(
            "📢 <b>إدارة القنوات</b>\n📢=إجباري | 🎁=مكافأة",
            reply_markup=channels_manage_kb(), parse_mode=ParseMode.HTML,
        ); return
    if sub == "add":
        context.user_data["admin_action"] = "chm_add"
        await q.edit_message_text(
            "➕ <code>@قناة|العنوان|المكافأة|إجباري(0/1)</code>",
            parse_mode=ParseMode.HTML,
        ); return
    if sub == "open":
        cid = int(parts[2])
        c = DB.execute("SELECT * FROM mandatory_channels WHERE id=?", (cid,)).fetchone()
        if not c:
            await q.edit_message_text("⚠️ غير موجود.", reply_markup=channels_manage_kb()); return
        txt = (f"📢 <b>{html.escape(c['title'] or c['channel'])}</b>\n"
               f"🆔 <code>{c['id']}</code>\n"
               f"📡 {c['channel']}\n"
               f"🎁 {c['reward']} نقطة\n"
               f"الحالة: {'🟢' if c['active'] else '🔴'} | "
               f"إجباري: {'✅' if c['required'] else '❌'}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تفعيل/تعطيل", callback_data=f"chm:toggle:{cid}"),
             InlineKeyboardButton("🔁 تبديل إجباري", callback_data=f"chm:togreq:{cid}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"chm:del:{cid}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="chm:list")],
        ])
        await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.HTML); return
    if sub == "toggle":
        DB.execute("UPDATE mandatory_channels SET active=1-active WHERE id=?",
                   (int(parts[2]),)); DB.commit()
        q.data = f"chm:open:{parts[2]}"; await cb_channels_manage(update, context); return
    if sub == "togreq":
        DB.execute("UPDATE mandatory_channels SET required=1-required WHERE id=?",
                   (int(parts[2]),)); DB.commit()
        q.data = f"chm:open:{parts[2]}"; await cb_channels_manage(update, context); return
    if sub == "del":
        DB.execute("DELETE FROM mandatory_channels WHERE id=?", (int(parts[2]),)); DB.commit()
        await q.edit_message_text("🗑 حُذف.", reply_markup=channels_manage_kb()); return


# ==========================================================
#                إدارة باقات النجوم
# ==========================================================

def packages_manage_kb() -> InlineKeyboardMarkup:
    pkgs = DB.execute("SELECT * FROM stars_packages ORDER BY sort_order, id").fetchall()
    kb = []
    for p in pkgs:
        st = "🟢" if p["active"] else "🔴"
        kb.append([InlineKeyboardButton(
            f"{st} #{p['id']} {p['points']} pt — ⭐{p['stars']}",
            callback_data=f"pkm:toggle:{p['id']}",
        )])
    kb.append([InlineKeyboardButton("➕ إضافة باقة", callback_data="pkm:add"),
               InlineKeyboardButton("🗑 حذف", callback_data="pkm:del")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")])
    return InlineKeyboardMarkup(kb)


async def cb_packages_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    parts = q.data.split(":"); sub = parts[1]
    if sub == "list":
        await q.edit_message_text("⭐ <b>باقات النجوم</b>",
                                  reply_markup=packages_manage_kb(),
                                  parse_mode=ParseMode.HTML); return
    if sub == "add":
        context.user_data["admin_action"] = "pkm_add"
        await q.edit_message_text("➕ <code>النقاط|النجوم</code>",
                                  parse_mode=ParseMode.HTML); return
    if sub == "del":
        context.user_data["admin_action"] = "pkm_del"
        await q.edit_message_text("🗑 أرسل ID الباقة:"); return
    if sub == "toggle":
        DB.execute("UPDATE stars_packages SET active=1-active WHERE id=?",
                   (int(parts[2]),)); DB.commit()
        q.data = "pkm:list"; await cb_packages_manage(update, context); return


# ==========================================================
#                  إدارة الكوبونات
# ==========================================================

def coupons_manage_kb() -> InlineKeyboardMarkup:
    cs = DB.execute("SELECT * FROM coupons ORDER BY created_at DESC LIMIT 30").fetchall()
    kb = []
    for c in cs:
        st = "🟢" if c["active"] else "🔴"
        kb.append([InlineKeyboardButton(
            f"{st} {c['code']} +{c['reward']} ({c['used_count']}/{c['max_uses']})",
            callback_data=f"cpm:toggle:{c['code']}",
        )])
    kb.append([InlineKeyboardButton("➕ إضافة", callback_data="cpm:add"),
               InlineKeyboardButton("🗑 حذف", callback_data="cpm:del")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")])
    return InlineKeyboardMarkup(kb)


async def cb_coupons_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    parts = q.data.split(":"); sub = parts[1]
    if sub == "list":
        await q.edit_message_text("🎟 <b>الكوبونات</b>",
                                  reply_markup=coupons_manage_kb(),
                                  parse_mode=ParseMode.HTML); return
    if sub == "add":
        context.user_data["admin_action"] = "cpm_add"
        await q.edit_message_text(
            "➕ <code>CODE|REWARD|MAX_USES</code>\nمثال: <code>WELCOME|100|50</code>",
            parse_mode=ParseMode.HTML,
        ); return
    if sub == "del":
        context.user_data["admin_action"] = "cpm_del"
        await q.edit_message_text("🗑 أرسل الكود:"); return
    if sub == "toggle":
        code = parts[2]
        DB.execute("UPDATE coupons SET active=1-active WHERE code=?", (code,)); DB.commit()
        q.data = "cpm:list"; await cb_coupons_manage(update, context); return


# ==========================================================
#               الإعدادات الحية
# ==========================================================

CFG_KEYS_DESC = {
    "invite_reward":        "نقاط مكافأة الدعوة",
    "transfer_fee_percent": "نسبة عمولة التحويل %",
    "daily_gift_points":    "نقاط الهدية اليومية",
    "daily_gift_bonus":     "بونص ستريك يومي",
    "daily_gift_max_streak":"الحد الأقصى للستريك",
    "rate_limit_seconds":   "حد السبام (ثانية)",
    "vip_price_stars":      "سعر VIP أسبوع (نجوم)",
    "verify_price_points":  "سعر التوثيق (نقاط)",
    "lottery_ticket_cost":  "سعر تذكرة اليانصيب",
    "lottery_jackpot_pct":  "نسبة جائزة اليانصيب %",
    "shop_gem_to_points":   "1💎 = كم نقطة؟",
    "welcome_bonus":        "نقاط ترحيب لأول مرة",
    "likes_min_qty":        "حد أدنى للايكات",
    "likes_max_qty":        "حد أعلى للايكات",
}


def cfg_manage_kb() -> InlineKeyboardMarkup:
    kb = []
    for key, desc in CFG_KEYS_DESC.items():
        kb.append([InlineKeyboardButton(
            f"{desc} = {cfg(key, '-')}",
            callback_data=f"cfg:edit:{key}",
        )])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="adm:menu")])
    return InlineKeyboardMarkup(kb)


async def cb_cfg_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    if not is_admin(q.from_user.id): return
    parts = q.data.split(":"); sub = parts[1]
    if sub == "list":
        await q.edit_message_text("⚙️ <b>الإعدادات الحية</b>\nاضغط لتعديل القيمة:",
                                  reply_markup=cfg_manage_kb(),
                                  parse_mode=ParseMode.HTML); return
    if sub == "edit":
        key = parts[2]
        context.user_data["admin_action"] = "cfg_set"
        context.user_data["cfg_key"] = key
        await q.edit_message_text(
            f"✏️ القيمة الحالية لـ <b>{key}</b>: <code>{cfg(key)}</code>\n\n"
            "أرسل القيمة الجديدة:",
            parse_mode=ParseMode.HTML,
        )
        return


# ==========================================================
#                     معالج الأخطاء
# ==========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    logger.error("Exception:", exc_info=err)
    if isinstance(err, (NetworkError, TimedOut)):
        return
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ حدث خطأ مؤقت، الرجاء المحاولة أو /start."
            )
    except Exception: pass
    try:
        tb = "".join(traceback.format_exception(None, err, err.__traceback__))[-3000:]
        upd = ""
        if isinstance(update, Update):
            try:
                upd = json.dumps(update.to_dict(), ensure_ascii=False, indent=2)[:1500]
            except Exception:
                upd = str(update)[:1500]
        msg = (
            "🛑 <b>Bot Exception</b>\n"
            f"<b>Type:</b> <code>{html.escape(type(err).__name__)}</code>\n"
            f"<b>Error:</b> <code>{html.escape(str(err))[:300]}</code>\n\n"
            f"<b>Update:</b>\n<pre>{html.escape(upd)}</pre>\n"
            f"<b>Traceback:</b>\n<pre>{html.escape(tb)}</pre>"
        )
        for aid in all_admins():
            try:
                await context.bot.send_message(aid, msg, parse_mode=ParseMode.HTML)
            except Exception: pass
    except Exception:
        logger.exception("error_handler failed")


# ==========================================================
#                   أوامر مساعدة
# ==========================================================

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cleared = False
    for k in ("pending_order","transfer_step","transfer_target","admin_action",
              "coupon_step","secm_target","menm_target","cfg_key"):
        if context.user_data.pop(k, None) is not None:
            cleared = True
    await update.effective_message.reply_text(
        "✅ تم الإلغاء." if cleared else "ℹ️ لا عملية جارية.",
        reply_markup=main_menu_kb(update.effective_user.id),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "🆘 <b>الأوامر:</b>\n\n"
        "/start - القائمة الرئيسية\n"
        "/profile - ملفي الشخصي\n"
        "/daily - الهدية اليومية\n"
        "/myorders - طلباتي\n"
        "/shop - المتجر\n"
        "/lottery - اليانصيب\n"
        "/leaderboard - لوحة الشرف\n"
        "/coupon - استخدام كوبون\n"
        "/cancel - إلغاء عملية\n"
        "/admin - لوحة الأدمن\n"
        "/help - هذه الرسالة\n\n"
        f"📞 الدعم: @{SUPPORT_USERNAME}"
    )
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML)


# ==========================================================
#                    نقطة التشغيل
# ==========================================================

def build_app() -> Application:
    db_init()
    request = HTTPXRequest(
        connection_pool_size=20,
        read_timeout=30, write_timeout=30,
        connect_timeout=20, pool_timeout=20,
    )
    app = (ApplicationBuilder()
           .token(BOT_TOKEN).request(request)
           .concurrent_updates(True).build())

    # أوامر
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("profile",     profile_cmd))
    app.add_handler(CommandHandler("daily",       section_daily_gift))
    app.add_handler(CommandHandler("myorders",    section_myorders))
    app.add_handler(CommandHandler("shop",        section_shop))
    app.add_handler(CommandHandler("lottery",     section_lottery))
    app.add_handler(CommandHandler("leaderboard", section_leaderboard))
    app.add_handler(CommandHandler("coupon",      section_coupon))
    app.add_handler(CommandHandler("help",        help_cmd))
    app.add_handler(CommandHandler("cancel",      cancel_cmd))
    app.add_handler(CommandHandler("admin",       admin_cmd))

    # كولباكات
    app.add_handler(CallbackQueryHandler(cb_main_menu,       pattern=r"^mn:"))
    app.add_handler(CallbackQueryHandler(cb_section_open,    pattern=r"^sec:"))
    app.add_handler(CallbackQueryHandler(cb_services_back,   pattern=r"^services_back$"))
    app.add_handler(CallbackQueryHandler(cb_buy_dyn,         pattern=r"^buy_dyn:"))
    app.add_handler(CallbackQueryHandler(cb_pay,             pattern=r"^pay:"))
    app.add_handler(CallbackQueryHandler(cb_stars,           pattern=r"^stars:"))
    app.add_handler(CallbackQueryHandler(cb_check_subs,      pattern=r"^check_subs$"))
    app.add_handler(CallbackQueryHandler(cb_force_join,      pattern=r"^force_join_check$"))
    app.add_handler(CallbackQueryHandler(cb_shop,            pattern=r"^shop:"))
    app.add_handler(CallbackQueryHandler(cb_lottery,         pattern=r"^lot:"))
    app.add_handler(CallbackQueryHandler(cb_order_action,    pattern=r"^ord:"))
    app.add_handler(CallbackQueryHandler(cb_admin,           pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(cb_sections_manage, pattern=r"^secm:"))
    app.add_handler(CallbackQueryHandler(cb_menu_manage,     pattern=r"^menm:"))
    app.add_handler(CallbackQueryHandler(cb_channels_manage, pattern=r"^chm:"))
    app.add_handler(CallbackQueryHandler(cb_packages_manage, pattern=r"^pkm:"))
    app.add_handler(CallbackQueryHandler(cb_coupons_manage,  pattern=r"^cpm:"))
    app.add_handler(CallbackQueryHandler(cb_cfg_manage,      pattern=r"^cfg:"))

    # دفع
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_router))

    # نص
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    app.add_error_handler(error_handler)
    return app


def main() -> None:
    app = build_app()
    logger.info("Bot started ✅")
    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )
            break
        except (NetworkError, TimedOut) as e:
            logger.warning(f"Net err: {e}. retry 5s...")
            time.sleep(5)
        except Exception:
            logger.exception("Fatal. retry 10s...")
            time.sleep(10)


# --- إضافة نظام الويب لضمان الاستضافة 24/7 ---
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

class _KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write("🚀 Bot is Online 24/7!".encode('utf-8'))
    def log_message(self, format, *args):
        return

def run_server():
    # المنفذ يؤخذ من متغير البيئة PORT (مطلوب على Render وغيرها)
    port = int(os.environ.get("PORT", "8080"))
    HTTPServer(('0.0.0.0', port), _KeepAliveHandler).serve_forever()

def keep_alive():
    t = Thread(target=run_server)
    t.start()
# ------------------------------------------

def main() -> None:
    app = build_app()
    logger.info("Bot started ✅")
    
    # تشغيل نظام الويب قبل بدء البوت
    keep_alive()
    print("✅ Web Server started. Monitoring is ready.")

    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )
            break
        except (NetworkError, TimedOut) as e:
            logger.warning(f"Net err: {e}. retry 5s...")
            time.sleep(5)
        except Exception:
            logger.exception("Fatal. retry 10s...")
            time.sleep(10)

if __name__ == "__main__":
    main()
