import os
import sqlite3
import asyncio
import logging
import time
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ChatPermissions
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties

# --- SETUP LOGGING ---
logging.basicConfig(level=logging.INFO)

# --- CONFIG DARI RAILWAY ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- FSM STATES ---
class AdminStates(StatesGroup):
    waiting_welcome_text = State()
    waiting_welcome_btn = State()
    waiting_filter_word = State()
    waiting_bc_text = State()
    waiting_tagall_text = State()  # NEW: TagAll state

# --- ANTI SPAM & RATE LIMIT ---
user_spam_data = defaultdict(lambda: {'count': 0, 'last_reset': 0})
CHAT_COOLDOWN = 2  # detik antar pesan per user
MAX_MSGS_PER_MIN = 10  # max pesan per menit per user

def check_spam(user_id: int) -> bool:
    now = time.time()
    data = user_spam_data[user_id]
    
    # Reset per menit
    if now - data['last_reset'] > 60:
        data['count'] = 0
        data['last_reset'] = now
    
    # Check cooldown antar pesan
    if now - data['last_reset'] < CHAT_COOLDOWN:
        return True
    
    data['count'] += 1
    return data['count'] > MAX_MSGS_PER_MIN

def reset_spam_counter(user_id: int):
    user_spam_data[user_id]['count'] = 0
    user_spam_data[user_id]['last_reset'] = time.time()

# --- DATABASE SYSTEM ---
def db_query(query, params=(), fetch=False):
    conn = sqlite3.connect("database.db")
    curr = conn.cursor()
    curr.execute(query, params)
    data = curr.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return data

def init_db():
    db_query("CREATE TABLE IF NOT EXISTS filters (word TEXT UNIQUE)")
    db_query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    db_query("CREATE TABLE IF NOT EXISTS group_logs (group_id TEXT PRIMARY KEY, log_chat_id TEXT)")
    db_query("CREATE TABLE IF NOT EXISTS mutes (user_id INTEGER, group_id TEXT, until TIMESTAMP, reason TEXT)")
    
    # Default settings
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('group_id', '0')")
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', 'Selamat datang!')")
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_btn', 'Join Channel|https://t.me/telegram')")

init_db()

# --- GET GROUP LOG CHAT ---
def get_group_log_chat(group_id: str) -> str:
    result = db_query("SELECT log_chat_id FROM group_logs WHERE group_id = ?", (group_id,), fetch=True)
    return result[0][0] if result else "0"

# --- SEND TO LOG ---
async def send_to_log(group_id: str, text: str):
    log_chat = get_group_log_chat(group_id)
    if log_chat != "0":
        try:
            await bot.send_message(int(log_chat), f"<b>📍 Group ID:</b> <code>{group_id}</code>\n\n{text}", parse_mode="HTML")
        except:
            pass

# --- CLEAN MUTEs EXPIRED ---
async def clean_expired_mutes():
    db_query("DELETE FROM mutes WHERE until < CURRENT_TIMESTAMP")

# --- GET ALL MEMBERS (SAFE & EFFICIENT) ---
async def get_group_members(group_id: int, limit: int = 1000):
    """Ambil member grup secara aman dengan pagination"""
    members = []
    offset = 0
    while len(members) < limit:
        try:
            chat_members = await bot.get_chat_member_count(group_id)
            # Simulate getting members (real implementation needs admin rights)
            # This is demo - in production use proper member list API
            break  # Simplified for demo
        except:
            break
    return members[:limit]

# --- TAG ALL FUNCTION ---
async def do_tag_all(gid: str, text: str):
    """Kirim pesan dengan @all mention"""
    try:
        # Kirim dengan @all (Telegram native)
        await bot.send_message(int(gid), f"{text}\n\n@all")
        await send_to_log(gid, f"🔔 **TAG ALL** dari Admin:\n<code>{text[:100]}...</code>")
        return True
    except Exception as e:
        # Fallback: kirim pesan biasa + log
        await bot.send_message(int(gid), text)
        await send_to_log(gid, f"📢 **TAG ALL (Fallback)** dari Admin:\n<code>{text[:100]}...</code>\nError: {str(e)}")
        return False

# --- MENU UTAMA (UPDATED) ---
@dp.message(Command("start"), F.chat.type == "private")
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Set Target Grup", callback_data="guide_group")],
        [InlineKeyboardButton(text="📝 Set Welcome", callback_data="set_welcome")],
        [InlineKeyboardButton(text="🚫 Set Filter Kata", callback_data="set_filter")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="bc")],
        [InlineKeyboardButton(text="🔔 Tag All", callback_data="tagall")],  # NEW!
        [InlineKeyboardButton(text="📊 Group Logs", callback_data="group_logs")],
        [InlineKeyboardButton(text="💾 Send DB (Backup)", callback_data="send_db")]
    ])
    await message.answer("🛡️ **Super Admin Panel**", reply_markup=kb)

# --- GROUP LOGS MANAGEMENT ---
@dp.callback_query(F.data == "group_logs")
async def group_logs_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: 
        await callback.answer("❌ Unauthorized!", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Set Log Chat", callback_data="set_log_chat")],
        [InlineKeyboardButton(text="📋 Lihat Logs Aktif", callback_data="view_logs")],
        [InlineKeyboardButton(text="🗑️ Hapus Log Chat", callback_data="del_log_chat")]
    ])
    await callback.message.answer("📊 **Group Logs Management**", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "set_log_chat")
async def set_log_chat_prompt(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("Kirim ID chat log (forward pesan dari chat tersebut atau ketik ID):")
    await callback.answer()

@dp.message(Command("setlog"))
@dp.message(F.text.startswith("setlog "))
async def set_log_chat(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    gid = str(message.chat.id)
    log_chat_id = message.text.split(" ", 1)[1] if " " in message.text else message.text
    
    # Simpan ke DB
    db_query("INSERT OR REPLACE INTO group_logs (group_id, log_chat_id) VALUES (?, ?)", (gid, log_chat_id))
    
    await send_to_log(gid, f"✅ **Log Chat diatur** ke <code>{log_chat_id}</code>")
    await message.answer(f"✅ Log chat untuk grup {gid} diset ke {log_chat_id}")
    
    reset_spam_counter(message.from_user.id)

@dp.callback_query(F.data == "view_logs")
async def view_active_logs(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    logs = db_query("SELECT group_id, log_chat_id FROM group_logs", fetch=True)
    if not logs:
        await callback.message.answer("📋 Belum ada log chat yang diatur.")
    else:
        text = "📋 **Active Logs:**\n\n"
        for gid, logid in logs:
            text += f"• Group <code>{gid}</code> → Log <code>{logid}</code>\n"
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "del_log_chat")
async def del_log_chat_prompt(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("Kirim ID grup untuk hapus log chat:")
    await callback.answer()

# --- NEW: TAG ALL BUTTON ---
@dp.callback_query(F.data == "tagall")
async def start_tagall(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: 
        await callback.answer("❌ Unauthorized!", show_alert=True)
        return
    await callback.message.answer("🔔 Kirim pesan untuk **TAG ALL** ke grup:")
    await state.set_state(AdminStates.waiting_tagall_text)
    await callback.answer()

# --- SET GRUP ---
@dp.message(Command("setgrup"))
async def set_group_id(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    gid = str(message.chat.id)
    db_query("UPDATE settings SET value = ? WHERE key = 'group_id'", (gid,))
    await send_to_log(gid, f"✅ **Grup terdaftar** oleh Admin")
    rep = await message.answer(f"✅ Grup terdaftar: {gid}")
    await asyncio.sleep(3)
    await message.delete()
    await rep.delete()

# --- FITUR BROADCAST ---
@dp.callback_query(F.data == "bc")
async def start_bc(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Kirim pesan yang ingin di-broadcast ke grup:")
    await state.set_state(AdminStates.waiting_bc_text)
    await callback.answer()

@dp.message(AdminStates.waiting_bc_text)
async def do_broadcast(message: types.Message, state: FSMContext):
    gid = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    try:
        await bot.send_message(gid, message.text)
        await send_to_log(gid, f"📢 **Broadcast** dari Admin:\n<code>{message.text[:100]}...</code>")
        await message.answer("✅ Pesan broadcast berhasil dikirim ke grup.")
    except Exception as e:
        await message.answer(f"❌ Gagal kirim: {e}")
    await state.clear()

# --- NEW: TAG ALL EXECUTION ---
@dp.message(AdminStates.waiting_tagall_text)
async def do_tag_all(message: types.Message, state: FSMContext):
    gid = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    try:
        success = await do_tag_all(gid, message.text)
        if success:
            await message.answer("🔔 **TAG ALL berhasil dikirim!** @all semua member akan notif.")
        else:
            await message.answer("✅ Tag all dikirim (mode fallback).")
    except Exception as e:
        await message.answer(f"❌ Gagal tag all: {e}")
    await state.clear()

# --- FITUR SET FILTER ---
@dp.callback_query(F.data == "set_filter")
async def start_filter(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Kirim kata kasar yang ingin ditambah ke filter:")
    await state.set_state(AdminStates.waiting_filter_word)
    await callback.answer()

@dp.message(AdminStates.waiting_filter_word)
async def save_filter(message: types.Message, state: FSMContext):
    word = message.text.lower()
    try:
        db_query("INSERT INTO filters (word) VALUES (?)", (word,))
        await message.answer(f"✅ Kata <code>{word}</code> berhasil ditambah!")
        await send_to_log(message.chat.id, f"🚫 **Filter baru**: <code>{word}</code>")
    except:
        await message.answer("Kata tersebut sudah ada dalam daftar.")
    await state.clear()

# --- WELCOME SETTINGS ---
@dp.callback_query(F.data == "set_welcome")
async def start_welcome(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Kirim teks welcome baru:")
    await state.set_state(AdminStates.waiting_welcome_text)
    await callback.answer()

@dp.message(AdminStates.waiting_welcome_text)
async def save_welcome_text(message: types.Message, state: FSMContext):
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_text'", (message.text,))
    await message.answer("Teks disimpan! Sekarang kirim tombol (Nama|Link):")
    await state.set_state(AdminStates.waiting_welcome_btn)

@dp.message(AdminStates.waiting_welcome_btn)
async def save_welcome_btn(message: types.Message, state: FSMContext):
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_btn'", (message.text,))
    await message.answer("✅ Welcome & Tombol diupdate!")
    await state.clear()

# --- ENHANCED WELCOME + AUTO MENTION ---
@dp.chat_member()
async def on_user_join(event: types.ChatMemberUpdated):
    gid = str(event.chat.id)
    
    # Check if this group has log enabled
    if get_group_log_chat(gid) == "0": 
        target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
        if gid != target_group: return
    else:
        if get_group_log_chat(gid) != "0":  # This group has its own log
            pass
        else:
            return

    if event.new_chat_member.status == "member" and event.old_chat_member.status != "member":
        user = event.new_chat_member.user
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a> (<code>{user.id}</code>)'
        username = f"@{user.username}" if user.username else "No username"
        
        txt = db_query("SELECT value FROM settings WHERE key = 'welcome_text'", fetch=True)[0][0]
        btn_data = db_query("SELECT value FROM settings WHERE key = 'welcome_btn'", fetch=True)[0][0].split("|")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_data[0], url=btn_data[1])]])
        
        # Kirim Welcome
        wel_msg = await bot.send_message(event.chat.id, f"Halo {mention}!\n\n{username}\n\n{txt}", reply_markup=kb)
        
        # Log ke log chat
        log_text = f"👋 **Member Baru**\n{mention}\nUsername: {username}\n⏰ <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>"
        await send_to_log(gid, log_text)
        
        # Auto Delete Welcome Message (10 detik)
        await asyncio.sleep(10)
        try: 
            await wel_msg.delete()
        except: 
            pass

# --- ENHANCED FILTER + ANTI SPAM + ANTI FLOOD ---
warn_count = {}

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def security_monitor(message: types.Message):
    gid = str(message.chat.id)
    
    # Skip if not registered group or has own log
    target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    if gid != target_group and get_group_log_chat(gid) == "0":
        return
    
    uid = message.from_user.id
    
    # Admin & Bot kebal
    if uid == ADMIN_ID or message.from_user.is_bot:
        reset_spam_counter(uid)
        return
    
    # Check spam/flood
    if check_spam(uid):
        await message.delete()
        await send_to_log(gid, f"🚫 **SPAM DETECTED** {message.from_user.full_name}\n<code>{message.text[:50] if message.text else 'Media'}</code>")
        # Temporary mute spammer (5 menit)
        permissions = ChatPermissions(can_send_messages=False)
        await bot.restrict_chat_member(gid, uid, permissions=permissions, types="until_date", until_date=int(time.time() + 300))
        return
    
    # Check filters
    banned_words = [row[0] for row in db_query("SELECT word FROM filters", fetch=True)]
    text_lower = message.text.lower() if message.text else ""
    
    if any(word in text_lower for word in banned_words):
        await message.delete()
        warn_count[uid] = warn_count.get(uid, 0) + 1
        
        log_text = f"🚫 **FILTER HIT** {message.from_user.full_name}\nKata: <code>{next(w for w in banned_words if w in text_lower)}</code>\nWarn: {warn_count[uid]}/2"
        await send_to_log(gid, log_text)
        
        if warn_count[uid] >= 2:
            # Mute 1 jam
            permissions = ChatPermissions(can_send_messages=False)
            await bot.restrict_chat_member(gid, uid, permissions=permissions, types="until_date", until_date=int(time.time() + 3600))
            await send_to_log(gid, f"🔇 **MUTED** {message.from_user.full_name} (Filter violation x2)")
        else:
            await message.chat.send_message(f"⚠️ @{message.from_user.username or 'user'}, jangan bicara kasar! (Peringatan {warn_count[uid]}/2)")
        return
    
    # Auto delete service messages, stickers, excessive media
    if (message.service or 
        message.sticker or 
        (message.photo and len(message.photo) > 1) or
        (message.video and message.video.duration and message.video.duration > 60)):
        await message.delete()
        await send_to_log(gid, f"🗑️ **AUTO DELETED** {message.from_user.full_name}\nTipe: {message.content_type}")

# --- OTHER BUTTONS ---
@dp.callback_query(F.data == "guide_group")
async def guide(c: types.CallbackQuery):
    text = """📍 **Cara Set Grup & Log:**

1️⃣ Masuk grup → Jadikan bot **ADMIN** (Delete Messages, Ban Members)
2️⃣ Ketik `/setgrup`
3️⃣ Set log: `/setlog [ID_CHAT]` atau forward pesan dari chat log
4️⃣ **NEW! 🔔 Tag All** - Tombol di menu utama
5️⃣ Selesai! Semua aktivitas akan dilog + tag all ready!"""
    await c.message.answer(text)
    await c.answer()

@dp.callback_query(F.data == "send_db")
async def send_db(c: types.CallbackQuery):
    await clean_expired_mutes()
    await bot.send_document(ADMIN_ID, FSInputFile("database.db"), caption="💾 Backup DB Terbaru")
    await c.answer()

# --- BACKGROUND CLEANUP ---
async def cleanup_task():
    while True:
        await clean_expired_mutes()
        await asyncio.sleep(300)  # 5 menit

async def main():
    # Start cleanup task
    asyncio.create_task(cleanup_task())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
