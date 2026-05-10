import os
import asyncio
import aiosqlite
from datetime import date, datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from telegram.constants import ParseMode

# ══════════════════════════════════════════════════
#   CONFIG
# ══════════════════════════════════════════════════
TOKEN        = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "TiTiMinerBot")
ADMIN_ID     = int(os.environ.get("ADMIN_ID", "5517506058"))
CHANNEL_LINK = "https://t.me/TiTiappdownload"
CHANNEL_ID   = "@TiTiappdownload"
DB_PATH      = "titi.db"

# ══════════════════════════════════════════════════
#   VISUALS — Emoji-based animated messages
# ══════════════════════════════════════════════════
LOGO = """
╔══════════════════════════╗
║  🌟  T i T i  C O I N  🌟  ║
║   Mine · Earn · Win      ║
╚══════════════════════════╝"""

COIN_ANIM = ["🪙", "✨🪙", "💫🪙✨", "🌟💰🌟", "💎🪙💎"]

LEVEL_BADGES = {
    0:     ("🥉", "Newcomer",    0),
    5000:  ("🥈", "Miner",       5000),
    25000: ("🥇", "Pro Miner",   25000),
    100000:("💎", "Diamond",     100000),
    500000:("👑", "King Miner",  500000),
}

def get_level(credits):
    badge, title, threshold = "🥉", "Newcomer", 0
    for req, (b, t, th) in LEVEL_BADGES.items():
        if credits >= req:
            badge, title, threshold = b, t, th
    return badge, title

def progress_bar(credits):
    thresholds = [0, 5000, 25000, 100000, 500000, 1000000]
    for i, th in enumerate(thresholds[:-1]):
        if credits < thresholds[i+1]:
            pct = (credits - th) / (thresholds[i+1] - th)
            filled = int(pct * 10)
            bar = "█" * filled + "░" * (10 - filled)
            return f"[{bar}] {int(pct*100)}%\n➡️ Next: {thresholds[i+1]:,} credits"
    return "[██████████] MAX LEVEL 👑"

# ══════════════════════════════════════════════════
#   DATABASE
# ══════════════════════════════════════════════════
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id      INTEGER PRIMARY KEY,
                username     TEXT,
                full_name    TEXT,
                credits      INTEGER DEFAULT 0,
                referred_by  INTEGER DEFAULT NULL,
                tap_streak   INTEGER DEFAULT 0,
                last_tap     TEXT DEFAULT NULL,
                total_taps   INTEGER DEFAULT 0,
                joined_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                channel_joined INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT,
                description TEXT,
                reward      INTEGER,
                link        TEXT,
                emoji       TEXT DEFAULT '🎯'
            );
            CREATE TABLE IF NOT EXISTS completed_tasks (
                user_id INTEGER,
                task_id INTEGER,
                PRIMARY KEY (user_id, task_id)
            );
            CREATE TABLE IF NOT EXISTS tap_log (
                user_id   INTEGER,
                tapped_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.executemany(
            "INSERT OR IGNORE INTO tasks (id,title,description,reward,link,emoji) VALUES (?,?,?,?,?,?)",
            [
                (1, "Join TiTi Channel",    "Official channel join karo",          500,  CHANNEL_LINK,                    "📢"),
                (2, "Share Bot with 5 friends", "5 doston ko bot link bhejo",       300,  None,                            "📤"),
                (3, "Tap 10 times total",   "Total 10 taps pore karo",             200,  None,                            "👆"),
                (4, "Reach 5,000 credits",  "5,000 credits earn karo",             500,  None,                            "💰"),
                (5, "7-day streak",         "7 din lagaataar tap karo",           1000,  None,                            "🔥"),
            ]
        )
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as c:
            return await c.fetchone()

async def ensure_user(user_id, username, full_name, referred_by=None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)) as c:
            existing = await c.fetchone()
        if not existing:
            await db.execute(
                "INSERT INTO users (user_id,username,full_name,referred_by) VALUES (?,?,?,?)",
                (user_id, username or "anon", full_name, referred_by)
            )
            if referred_by:
                await db.execute(
                    "UPDATE users SET credits=credits+500 WHERE user_id=?", (referred_by,)
                )
            await db.commit()
            return True
        return False

async def add_credits(user_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET credits=credits+? WHERE user_id=?", (amount, user_id)
        )
        await db.commit()

# ══════════════════════════════════════════════════
#   KEYBOARDS
# ══════════════════════════════════════════════════
def main_kb(user_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👆 TAP & MINE",    callback_data="tap"),
            InlineKeyboardButton("💰 MY WALLET",     callback_data="wallet"),
        ],
        [
            InlineKeyboardButton("🎯 MISSIONS",      callback_data="tasks"),
            InlineKeyboardButton("👥 INVITE & EARN", callback_data="referral"),
        ],
        [
            InlineKeyboardButton("🏆 LEADERBOARD",   callback_data="leaderboard"),
            InlineKeyboardButton("ℹ️ HOW IT WORKS",  callback_data="howto"),
        ],
        [
            InlineKeyboardButton("📢 Official Channel", url=CHANNEL_LINK),
        ],
    ])

def back_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu")
    ]])

def back_tasks_kb():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Refresh Tasks", callback_data="tasks"),
        InlineKeyboardButton("⬅️ Menu",          callback_data="menu"),
    ]])

# ══════════════════════════════════════════════════
#   /start
# ══════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args
    ref = int(args[0]) if args and args[0].isdigit() and int(args[0]) != user.id else None

    is_new = await ensure_user(user.id, user.username, user.full_name, ref)
    row = await get_user(user.id)
    credits = row[3]
    badge, level = get_level(credits)

    bonus_line = ""
    if is_new and ref:
        bonus_line = "\n🎁 *+500 bonus credits* referral ke liye mil gaye!\n"

    text = (
        f"{LOGO}\n\n"
        f"👋 Salam, *{user.first_name}*!\n"
        f"{bonus_line}\n"
        f"🪙 *TiTi Coin* — Pakistan ka pehla tap-to-earn platform!\n\n"
        f"✅ Roz tap karo\n"
        f"✅ Doston ko invite karo (+500 each)\n"
        f"✅ Missions complete karo\n"
        f"✅ Launch par *real TiTi Coin* pao!\n\n"
        f"{badge} Level: *{level}*\n"
        f"💰 Balance: *{credits:,} credits*\n\n"
        f"_Abhi shuru karo_ 👇"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb(user.id))

# ══════════════════════════════════════════════════
#   CALLBACK ROUTER
# ══════════════════════════════════════════════════
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    data = q.data

    await ensure_user(user.id, user.username, user.full_name)
    row = await get_user(user.id)
    uid, uname, fname, credits, ref_by, streak, last_tap, total_taps, joined, ch_joined = row

    # ── MENU ──────────────────────────────────────
    if data == "menu":
        badge, level = get_level(credits)
        text = (
            f"{LOGO}\n\n"
            f"{badge} *{fname}* — {level}\n"
            f"💰 *{credits:,} credits*\n\n"
            f"_Choose an option below_ 👇"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_kb(user.id))

    # ── TAP ───────────────────────────────────────
    elif data == "tap":
        today = str(date.today())
        yesterday = str(date.fromordinal(date.today().toordinal() - 1))

        if last_tap == today:
            # already tapped — show timer feel
            text = (
                "⏰ *Aaj ka tap ho gaya!*\n\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔥 Streak: *{streak} din*\n"
                f"💰 Balance: *{credits:,} credits*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🕐 Kal midnight ke baad dobara aao!\n"
                "_Streak mat todna — bonus milta hai!_ 🎯"
            )
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb())
            return

        # calculate streak & earnings
        new_streak = (streak + 1) if last_tap == yesterday else 1
        base = 100
        streak_bonus = 0
        milestone_msg = ""

        if new_streak == 7:
            streak_bonus = 500
            milestone_msg = "\n🎉 *7-day streak bonus! +500 credits!*"
        elif new_streak == 3:
            streak_bonus = 100
            milestone_msg = "\n⚡ *3-day streak! +100 bonus!*"
        elif new_streak % 30 == 0:
            streak_bonus = 2000
            milestone_msg = f"\n👑 *{new_streak}-day LEGEND bonus! +2000 credits!*"

        earned = base + streak_bonus
        new_credits = credits + earned
        new_taps = total_taps + 1

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET credits=?, tap_streak=?, last_tap=?, total_taps=? WHERE user_id=?",
                (new_credits, new_streak, today, new_taps, uid)
            )
            await db.execute("INSERT INTO tap_log (user_id) VALUES (?)", (uid,))
            await db.commit()

        badge, level = get_level(new_credits)
        pbar = progress_bar(new_credits)

        # auto-complete tap tasks
        await check_auto_tasks(uid, new_credits, new_streak, new_taps)

        text = (
            f"💥 *TAP SUCCESSFUL!*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 Earned: *+{earned} credits*\n"
            f"🔥 Streak: *{new_streak} din*"
            f"{milestone_msg}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{badge} Level: *{level}*\n"
            f"💰 Total: *{new_credits:,} credits*\n\n"
            f"{pbar}\n\n"
            f"_Kal dobara ao — streak mat todna!_ 🎯"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Friends Invite karo (+500)", callback_data="referral")],
            [InlineKeyboardButton("🎯 Missions dekho",             callback_data="tasks")],
            [InlineKeyboardButton("⬅️ Menu",                       callback_data="menu")],
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

    # ── WALLET ────────────────────────────────────
    elif data == "wallet":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)
            ) as c:
                ref_count = (await c.fetchone())[0]

        badge, level = get_level(credits)
        pbar = progress_bar(credits)
        coin_val = credits / 1000

        text = (
            f"💼 *MY WALLET*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{badge} Level: *{level}*\n"
            f"💰 Credits: *{credits:,}*\n"
            f"🪙 TiTi Coin (launch par): *~{coin_val:.1f} TiTi*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *Stats*\n"
            f"👆 Total taps: *{total_taps:,}*\n"
            f"🔥 Current streak: *{streak} din*\n"
            f"👥 Friends invited: *{ref_count}*\n"
            f"💵 From referrals: *{ref_count * 500:,} credits*\n\n"
            f"📈 *Progress to next level:*\n"
            f"{pbar}\n\n"
            f"📅 Member since: _{joined[:10]}_\n\n"
            f"_1,000 credits = 1 TiTi Coin at launch_ 🚀"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb())

    # ── REFERRAL ──────────────────────────────────
    elif data == "referral":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT full_name FROM users WHERE referred_by=? ORDER BY joined_at DESC LIMIT 5",
                (uid,)
            ) as c:
                refs = await c.fetchall()
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)
            ) as c:
                ref_count = (await c.fetchone())[0]

        ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        recent = "\n".join([f"  ✅ {r[0]}" for r in refs]) if refs else "  _Abhi koi nahi_"

        text = (
            f"👥 *INVITE & EARN*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Har dost ke liye:\n"
            f"  👤 Aapko: *+500 credits*\n"
            f"  🎁 Unhe: *+500 credits (welcome bonus)*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *Aapke referrals: {ref_count}*\n"
            f"💰 Total earned: *{ref_count * 500:,} credits*\n\n"
            f"🕐 *Recent invites:*\n{recent}\n\n"
            f"🔗 *Aapka invite link:*\n"
            f"`{ref_link}`\n\n"
            f"_Upar se copy karo aur share karo!_ 📤"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Link", switch_inline_query=f"TiTi Coin — Pakistan ka pehla tap-to-earn! Mere se join karo, +500 bonus: {ref_link}")],
            [InlineKeyboardButton("⬅️ Menu", callback_data="menu")],
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

    # ── TASKS ─────────────────────────────────────
    elif data == "tasks":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM tasks") as c:
                all_tasks = await c.fetchall()
            async with db.execute(
                "SELECT task_id FROM completed_tasks WHERE user_id=?", (uid,)
            ) as c:
                done = {r[0] for r in await c.fetchall()}

        total_reward = sum(t[3] for t in all_tasks)
        earned_reward = sum(t[3] for t in all_tasks if t[0] in done)

        text = (
            f"🎯 *MISSIONS*\n\n"
            f"Earned: *{earned_reward:,}* / {total_reward:,} credits\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        buttons = []
        for t in all_tasks:
            tid, title, desc, reward, link, emoji = t
            if tid in done:
                text += f"✅ ~~{title}~~ (+{reward:,})\n"
            else:
                text += f"{emoji} *{title}*\n_{desc}_ → *+{reward:,} credits*\n\n"
                row_btns = []
                if link:
                    row_btns.append(InlineKeyboardButton(f"🔗 Go", url=link))
                row_btns.append(InlineKeyboardButton(f"✅ Claim +{reward:,}", callback_data=f"claim_{tid}"))
                buttons.append(row_btns)

        buttons.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="tasks"),
            InlineKeyboardButton("⬅️ Menu",    callback_data="menu"),
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

    # ── CLAIM TASK ────────────────────────────────
    elif data.startswith("claim_"):
        task_id = int(data.split("_")[1])
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT * FROM completed_tasks WHERE user_id=? AND task_id=?", (uid, task_id)
            ) as c:
                done = await c.fetchone()
            if done:
                await q.answer("✅ Yeh task pehle complete ho gaya!", show_alert=True)
                return
            async with db.execute("SELECT title,reward FROM tasks WHERE id=?", (task_id,)) as c:
                task = await c.fetchone()
            if not task:
                await q.answer("Task nahi mila!", show_alert=True)
                return

            # verify channel join for task 1
            if task_id == 1:
                try:
                    member = await ctx.bot.get_chat_member(CHANNEL_ID, uid)
                    if member.status in ("left", "kicked", "banned", "restricted"):
                        await q.answer("⚠️ Pehle channel join karo, phir claim karo!", show_alert=True)
                        return
                except Exception:
                    await q.answer("⚠️ Channel join verify nahi ho saka. Pehle join karo!", show_alert=True)
                    return

            await db.execute("INSERT INTO completed_tasks VALUES (?,?)", (uid, task_id))
            await db.execute("UPDATE users SET credits=credits+? WHERE user_id=?", (task[1], uid))
            await db.commit()

        await q.answer(f"🎉 +{task[1]:,} credits mile! Mission complete!", show_alert=True)
        # refresh tasks screen
        ctx.user_data["after_claim"] = True
        q.data = "tasks"
        await button(update, ctx)

    # ── LEADERBOARD ───────────────────────────────
    elif data == "leaderboard":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT full_name, credits, tap_streak FROM users ORDER BY credits DESC LIMIT 10"
            ) as c:
                top = await c.fetchall()
            async with db.execute(
                "SELECT COUNT(*) FROM users"
            ) as c:
                total_users = (await c.fetchone())[0]
            async with db.execute(
                "SELECT credits FROM users ORDER BY credits DESC"
            ) as c:
                all_credits = [r[0] for r in await c.fetchall()]

        user_rank = next((i+1 for i, c in enumerate(all_credits) if c <= credits), len(all_credits))

        medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        board = ""
        for i, (name, cred, st) in enumerate(top):
            b, _ = get_level(cred)
            board += f"{medals[i]} {b} *{name[:15]}*\n    💰 {cred:,}  🔥{st}d\n"

        text = (
            f"🏆 *TOP MINERS*\n\n"
            f"👥 Total community: *{total_users:,}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{board}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 Aapki rank: *#{user_rank}* of {total_users}\n"
            f"💰 Aapke credits: *{credits:,}*"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb())

    # ── HOW IT WORKS ──────────────────────────────
    elif data == "howto":
        text = (
            f"ℹ️ *HOW TiTi COIN WORKS*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"*Phase 1 — Mining (Abhi)*\n"
            f"👆 Roz tap karo → credits kamao\n"
            f"👥 Dosto ko invite karo → +500 each\n"
            f"🎯 Missions complete karo → bonus credits\n"
            f"🔥 Streak banao → extra bonuses\n\n"
            f"*Phase 2 — Launch*\n"
            f"🪙 Credits → real TiTi Coin convert honge\n"
            f"📊 Exchange par list hoga\n"
            f"💸 Sell/trade kar sako ge\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"*💡 Conversion Rate:*\n"
            f"1,000 credits = 1 TiTi Coin\n\n"
            f"*🏆 Level System:*\n"
            f"🥉 Newcomer     → 0+\n"
            f"🥈 Miner        → 5,000+\n"
            f"🥇 Pro Miner    → 25,000+\n"
            f"💎 Diamond      → 100,000+\n"
            f"👑 King Miner   → 500,000+\n\n"
            f"*📢 Official Channel:*\n"
            f"[t.me/TiTiappdownload]({CHANNEL_LINK})\n\n"
            f"_Jitna pehle joinoge, utna zyada kamao ge!_ 🚀"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
                [InlineKeyboardButton("⬅️ Menu", callback_data="menu")],
            ]))

# ══════════════════════════════════════════════════
#   AUTO TASK CHECKER
# ══════════════════════════════════════════════════
async def check_auto_tasks(uid, credits, streak, taps):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT task_id FROM completed_tasks WHERE user_id=?", (uid,)
        ) as c:
            done = {r[0] for r in await c.fetchall()}

        to_complete = []
        if 3 not in done and taps >= 10:
            to_complete.append((3, 200))
        if 4 not in done and credits >= 5000:
            to_complete.append((4, 500))
        if 5 not in done and streak >= 7:
            to_complete.append((5, 1000))

        for task_id, reward in to_complete:
            await db.execute("INSERT OR IGNORE INTO completed_tasks VALUES (?,?)", (uid, task_id))
            await db.execute("UPDATE users SET credits=credits+? WHERE user_id=?", (reward, uid))
        if to_complete:
            await db.commit()

# ══════════════════════════════════════════════════
#   ADMIN COMMANDS
# ══════════════════════════════════════════════════
async def admin_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE last_tap=?", (str(date.today()),)
        ) as c:
            active = (await c.fetchone())[0]
        async with db.execute("SELECT SUM(credits) FROM users") as c:
            total_credits = (await c.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL") as c:
            via_ref = (await c.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at >= datetime('now','-1 day')"
        ) as c:
            new_today = (await c.fetchone())[0]

    await update.message.reply_text(
        f"📊 *TiTi Bot Stats*\n\n"
        f"👥 Total users: *{total:,}*\n"
        f"🆕 New today: *{new_today:,}*\n"
        f"🟢 Active today: *{active:,}*\n"
        f"🔗 Via referral: *{via_ref:,}*\n"
        f"🪙 Total credits: *{total_credits:,}*\n"
        f"🪙 Est. coins at launch: *{total_credits//1000:,}*",
        parse_mode=ParseMode.MARKDOWN
    )

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(ctx.args)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as c:
            users = await c.fetchall()
    sent = failed = 0
    for (uid_,) in users:
        try:
            await ctx.bot.send_message(
                uid_, f"📢 *TiTi Announcement*\n\n{msg}",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await update.message.reply_text(f"✅ Sent: {sent} | ❌ Failed: {failed}")

async def add_credits_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>")
        return
    try:
        target_id = int(ctx.args[0])
        amount = int(ctx.args[1])
        await add_credits(target_id, amount)
        await update.message.reply_text(f"✅ +{amount:,} credits added to {target_id}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# ══════════════════════════════════════════════════
#   MAIN
# ══════════════════════════════════════════════════
def main():
    import asyncio
    asyncio.run(init_db())

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("stats",       admin_stats))
    app.add_handler(CommandHandler("broadcast",   broadcast))
    app.add_handler(CommandHandler("addcredits",  add_credits_cmd))
    app.add_handler(CallbackQueryHandler(button))

    print("🚀 TiTi Bot live hai!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
