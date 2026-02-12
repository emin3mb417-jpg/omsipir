import os
import sqlite3
import asyncio
import logging
import time
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ChatPermissions
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties

# --- CONFIG ---
logging.basicConfig(level=logging.INFO)
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
    waiting_tagall_text = State()

# --- GLOBAL VARS & CACHE ---
FILTER_CACHE = set()
SETTINGS_CACHE = {}
user_violations = defaultdict(int)
user_spam_data = defaultdict(lambda: {'count': 0, 'last_reset': 0})

# --- DATABASE ENGINE ---
def _execute_query(query, params=(), fetch=False):
    conn = sqlite3.connect("database.db")
    curr = conn.cursor()
    try:
        curr.execute(query, params)
        data = curr.fetchall() if fetch else None
        conn.commit()
        return data
    finally:
        conn.close()

async def db_query(query, params=(), fetch=False):
    return await asyncio.to_thread(_execute_query, query, params, fetch)

async def refresh_cache():
    global FILTER_CACHE, SETTINGS_CACHE
    f = await db_query("SELECT word FROM filters", fetch=True)
    FILTER_CACHE = {r[0] for r in f} if f else set()
    s = await db_query("SELECT key, value FROM settings", fetch=True)
    SETTINGS_CACHE = {r[0]: r[1] for r in s} if s else {}

async def init_db():
    await db_query("CREATE TABLE IF NOT EXISTS filters (word TEXT UNIQUE)")
    await db_query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    await db_query("CREATE TABLE IF NOT EXISTS group_logs (group_id TEXT PRIMARY KEY, log_chat_id TEXT)")
    await db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('group_id', '0')")
    await db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', 'Selamat datang!')")
    await db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_btn', '0')")
    await refresh_cache()

# --- HELPERS ---
async def send_to_log(group_id, text):
    res = await db_query("SELECT log_chat_id FROM group_logs WHERE group_id = ?", (str(group_id),), fetch=True)
    if res and res[0][0] != "0":
        try: await bot.send_message(int(res[0][0]), f"<b>🛡 LOG:</b> {text}")
        except: pass

# --- ADMIN PANEL ---
@dp.message(Command("start"), F.chat.type == "private")
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Set Grup (Info)", callback_data="guide_group")],
        [InlineKeyboardButton(text="📝 Set Welcome", callback_data="set_welcome"), InlineKeyboardButton(text="🚫 Set Filter", callback_data="set_filter")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="bc"), InlineKeyboardButton(text="🔔 Tag All (Pin)", callback_data="tagall")],
        [InlineKeyboardButton(text="📊 Group Logs", callback_data="group_logs"), InlineKeyboardButton(text="💾 Send DB", callback_data="send_db")]
    ])
    await message.answer("🛡 <b>ADMIN PANEL</b>\nKelola grup Anda melalui tombol di bawah:", reply_markup=kb)

# --- BROADCAST & TAGALL LOGIC ---
@dp.callback_query(F.data == "bc")
async def bc_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 <b>BROADCAST</b>\nKirim pesan yang ingin dikirim ke grup:")
    await state.set_state(AdminStates.waiting_bc_text)
    await callback.answer()

@dp.message(AdminStates.waiting_bc_text)
async def bc_exec(message: types.Message, state: FSMContext):
    gid = SETTINGS_CACHE.get('group_id', '0')
    if gid == '0': return await message.answer("❌ Grup belum diset. Gunakan /setgrup di grup target.")
    try:
        await bot.send_message(int(gid), message.text)
        await message.answer("✅ Broadcast terkirim sebagai chat biasa.")
    except Exception as e: await message.answer(f"❌ Gagal: {e}")
    await state.clear()

@dp.callback_query(F.data == "tagall")
async def tagall_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔔 <b>TAG ALL</b>\nKirim pesan yang akan dikirim & di-PIN (Notif ke semua):")
    await state.set_state(AdminStates.waiting_tagall_text)
    await callback.answer()

@dp.message(AdminStates.waiting_tagall_text)
async def tagall_exec(message: types.Message, state: FSMContext):
    gid = SETTINGS_CACHE.get('group_id', '0')
    try:
        msg = await bot.send_message(int(gid), f"🔔 <b>PENGUMUMAN</b>\n\n{message.text}")
        await bot.pin_chat_message(int(gid), msg.message_id)
        await message.answer("✅ TagAll berhasil (Pesan dikirim & di-Pin).")
    except Exception as e: await message.answer(f"❌ Gagal: {e}")
    await state.clear()

# --- SETTINGS (GROUPS, WELCOME, LOGS) ---
@dp.message(Command("setgrup"))
async def set_group(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    gid = str(message.chat.id)
    await db_query("UPDATE settings SET value = ? WHERE key = 'group_id'", (gid,))
    await refresh_cache()
    await message.answer(f"✅ <b>Grup Target Diset:</b> <code>{gid}</code>")

@dp.message(Command("setlog"))
async def set_log_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2: return await message.answer("Format: <code>/setlog ID_LOG</code>")
    await db_query("INSERT OR REPLACE INTO group_logs VALUES (?, ?)", (str(message.chat.id), args[1]))
    await message.answer(f"✅ <b>Log Target Diset:</b> <code>{args[1]}</code>")

@dp.callback_query(F.data == "set_welcome")
async def welcome_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Kirim teks welcome baru:")
    await state.set_state(AdminStates.waiting_welcome_text)
    await callback.answer()

@dp.message(AdminStates.waiting_welcome_text)
async def welcome_save(message: types.Message, state: FSMContext):
    await db_query("UPDATE settings SET value = ? WHERE key = 'welcome_text'", (message.text,))
    await refresh_cache()
    await message.answer("✅ Welcome text disimpan!")
    await state.clear()

@dp.callback_query(F.data == "group_logs")
async def show_logs(callback: types.CallbackQuery):
    logs = await db_query("SELECT * FROM group_logs", fetch=True)
    txt = "📊 <b>DAFTAR LOG:</b>\n\n"
    for g, l in logs: txt += f"Grup: <code>{g}</code> → Log: <code>{l}</code>\n"
    await callback.message.answer(txt or "Kosong.")
    await callback.answer()

@dp.callback_query(F.data == "send_db")
async def send_db_file(callback: types.CallbackQuery):
    if os.path.exists("database.db"):
        await callback.message.answer_document(FSInputFile("database.db"), caption="💾 Backup Database")
    else: await callback.message.answer("❌ File DB tidak ditemukan.")
    await callback.answer()

@dp.callback_query(F.data == "guide_group")
async def guide_group(callback: types.CallbackQuery):
    await callback.message.answer("💡 <b>CARA SET GRUP:</b>\n1. Masukkan bot ke grup.\n2. Jadikan Admin.\n3. Ketik <code>/setgrup</code> di grup tersebut.")
    await callback.answer()

@dp.callback_query(F.data == "set_filter")
async def filter_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🚫 Kirim kata kasar yang ingin dilarang:")
    await state.set_state(AdminStates.waiting_filter_word)
    await callback.answer()

@dp.message(AdminStates.waiting_filter_word)
async def filter_save(message: types.Message, state: FSMContext):
    await db_query("INSERT OR IGNORE INTO filters (word) VALUES (?)", (message.text.lower().strip(),))
    await refresh_cache()
    await message.answer(f"✅ Filter <code>{message.text}</code> ditambahkan.")
    await state.clear()

# --- SECURITY & AUTO MUTE ---
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def security_handler(message: types.Message):
    gid = str(message.chat.id)
    if gid != SETTINGS_CACHE.get('group_id'): return
    if message.from_user.id == ADMIN_ID or message.from_user.is_bot: return

    text = (message.text or message.caption or "").lower()
    for word in FILTER_CACHE:
        if word in text:
            await message.delete()
            user_violations[message.from_user.id] += 1
            count = user_violations[message.from_user.id]
            
            if count >= 2:
                try:
                    await bot.restrict_chat_member(message.chat.id, message.from_user.id, permissions=ChatPermissions(can_send_messages=False))
                    await message.answer(f"🚫 {message.from_user.mention_html()} <b>DI-MUTE</b> (Pelanggaran 2x)")
                    await send_to_log(gid, f"User {message.from_user.id} di-mute karena filter.")
                except: pass
            else:
                await message.answer(f"⚠️ {message.from_user.mention_html()}, jangan bicara kasar! (Peringatan 1/2)")
            return

@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def welcome_handler(event: types.ChatMemberUpdated):
    if str(event.chat.id) != SETTINGS_CACHE.get('group_id'): return
    mention = event.new_chat_member.user.mention_html()
    txt = SETTINGS_CACHE.get('welcome_text', 'Selamat datang!').replace("{mention}", mention)
    await bot.send_message(event.chat.id, txt)

# --- START ---
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
