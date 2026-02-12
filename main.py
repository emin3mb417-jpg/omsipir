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

# Konfigurasi Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- CACHE & DATA STORAGE ---
FILTER_CACHE = set()
SETTINGS_CACHE = {}
user_violations = defaultdict(int) # Mencatat jumlah pelanggaran filter
user_spam_data = defaultdict(lambda: {'count': 0, 'last_reset': 0, 'last_msg': 0})

class AdminStates(StatesGroup):
    waiting_welcome_text = State()
    waiting_welcome_btn = State()
    waiting_filter_word = State()
    waiting_bc_text = State()
    waiting_tagall_text = State()

# --- DATABASE ENGINE ---
def _execute_query(query, params=(), fetch=False):
    conn = sqlite3.connect("database.db")
    curr = conn.cursor()
    try:
        curr.execute(query, params)
        data = curr.fetchall() if fetch else None
        conn.commit()
        return data
    except Exception as e:
        logging.error(f"DB Error: {e}")
        return None
    finally:
        conn.close()

async def db_query(query, params=(), fetch=False):
    return await asyncio.to_thread(_execute_query, query, params, fetch)

async def refresh_cache():
    global FILTER_CACHE, SETTINGS_CACHE
    filters = await db_query("SELECT word FROM filters", fetch=True)
    FILTER_CACHE = {row[0] for row in filters} if filters else set()
    settings = await db_query("SELECT key, value FROM settings", fetch=True)
    SETTINGS_CACHE = {row[0]: row[1] for row in settings} if settings else {}

async def init_db():
    await db_query("CREATE TABLE IF NOT EXISTS filters (word TEXT UNIQUE)")
    await db_query("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    await db_query("CREATE TABLE IF NOT EXISTS group_logs (group_id TEXT PRIMARY KEY, log_chat_id TEXT)")
    await db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('group_id', '0')")
    await db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', 'Selamat datang {mention}!')")
    await db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_btn', '0')")
    await refresh_cache()

# --- UTILS ---
async def delete_later(chat_id, message_id, delay=10):
    await asyncio.sleep(delay)
    try: await bot.delete_message(chat_id, message_id)
    except: pass

async def send_to_log(group_id, text):
    res = await db_query("SELECT log_chat_id FROM group_logs WHERE group_id = ?", (str(group_id),), fetch=True)
    if res and res[0][0] != "0":
        try: await bot.send_message(int(res[0][0]), f"<b>LOG:</b> {text}")
        except: pass

def check_spam(user_id):
    now = time.time()
    data = user_spam_data[user_id]
    if now - data['last_reset'] > 60:
        data['count'] = 0
        data['last_reset'] = now
    if now - data['last_msg'] < 1.5: return True # Terlalu cepat
    data['last_msg'] = now
    data['count'] += 1
    return data['count'] > 15

# --- ADMIN COMMANDS ---
@dp.message(Command("start"), F.chat.type == "private")
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Set Grup", callback_data="guide_group"), InlineKeyboardButton(text="🚫 Set Filter", callback_data="set_filter")],
        [InlineKeyboardButton(text="📝 Set Welcome", callback_data="set_welcome"), InlineKeyboardButton(text="📢 Broadcast", callback_data="bc")],
        [InlineKeyboardButton(text="🔔 Tag All (Pin)", callback_data="tagall"), InlineKeyboardButton(text="📊 Logs", callback_data="group_logs")],
        [InlineKeyboardButton(text="💾 Backup DB", callback_data="send_db")]
    ])
    await message.answer("🛡️ <b>ADMIN CONTROL PANEL</b>", reply_markup=kb)

@dp.message(Command("setgrup"))
async def set_group(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    gid = str(message.chat.id)
    await db_query("UPDATE settings SET value = ? WHERE key = 'group_id'", (gid,))
    await refresh_cache()
    await message.answer(f"✅ Grup berhasil didaftarkan: <code>{gid}</code>")

@dp.message(Command("setlog"))
async def set_log_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    args = message.text.split()
    if len(args) < 2: return await message.answer("Gunakan: /setlog ID_LOG")
    await db_query("INSERT OR REPLACE INTO group_logs VALUES (?, ?)", (str(message.chat.id), args[1]))
    await message.answer(f"✅ Log diset ke: <code>{args[1]}</code>")

# --- CALLBACK HANDLERS ---
@dp.callback_query(F.data == "tagall")
async def tagall_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔔 Masukkan pesan yang ingin di-TAG (Pesan akan di-PIN otomatis):")
    await state.set_state(AdminStates.waiting_tagall_text)
    await callback.answer()

@dp.message(AdminStates.waiting_tagall_text)
async def tagall_exec(message: types.Message, state: FSMContext):
    gid = SETTINGS_CACHE.get('group_id')
    try:
        msg = await bot.send_message(int(gid), f"🔔 <b>PENGUMUMAN</b>\n\n{message.text}")
        await bot.pin_chat_message(int(gid), msg.message_id, disable_notification=False)
        await message.answer("✅ Berhasil Tag All & Pin!")
    except Exception as e:
        await message.answer(f"❌ Gagal: {e}")
    await state.clear()

@dp.callback_query(F.data == "set_filter")
async def filter_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🚫 Kirim kata kasar yang ingin dilarang:")
    await state.set_state(AdminStates.waiting_filter_word)
    await callback.answer()

@dp.message(AdminStates.waiting_filter_word)
async def filter_save(message: types.Message, state: FSMContext):
    await db_query("INSERT OR IGNORE INTO filters (word) VALUES (?)", (message.text.lower().strip(),))
    await refresh_cache()
    await message.answer(f"✅ Kata <code>{message.text}</code> berhasil diblokir.")
    await state.clear()

# (Sisa callback Broadcast, Welcome, dll tetap sama dengan pola di atas)

# --- SECURITY LOGIC (FILTER & MUTE) ---
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def security_filter(message: types.Message):
    gid = str(message.chat.id)
    if gid != SETTINGS_CACHE.get('group_id'): return
    if message.from_user.id == ADMIN_ID or message.from_user.is_bot: return

    # 1. Anti Spam
    if check_spam(message.from_user.id):
        return await message.delete()

    # 2. Filter Kata & Auto Mute
    text = (message.text or message.caption or "").lower()
    for bad_word in FILTER_CACHE:
        if bad_word in text:
            await message.delete()
            user_violations[message.from_user.id] += 1
            v_count = user_violations[message.from_user.id]

            if v_count >= 2:
                # AKSI MUTE (Mencabut izin kirim pesan)
                try:
                    await bot.restrict_chat_member(
                        chat_id=message.chat.id,
                        user_id=message.from_user.id,
                        permissions=ChatPermissions(can_send_messages=False)
                    )
                    warn = await message.answer(f"🚫 {message.from_user.mention_html()} <b>DI-MUTE permanen</b> karena melanggar filter 2x.")
                    await send_to_log(gid, f"🔇 <b>MUTE:</b> {message.from_user.full_name} (Pelanggaran ke-{v_count})")
                except Exception as e:
                    logging.error(f"Gagal mute: {e}")
            else:
                warn = await message.answer(f"⚠️ {message.from_user.mention_html()}, jangan gunakan kata terlarang! (Peringatan {v_count}/2)")
            
            asyncio.create_task(delete_later(message.chat.id, warn.message_id, 5))
            return

# --- WELCOME SYSTEM ---
@dp.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def welcome_new_member(event: types.ChatMemberUpdated):
    if str(event.chat.id) != SETTINGS_CACHE.get('group_id'): return
    user = event.new_chat_member.user
    mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
    
    txt = SETTINGS_CACHE.get('welcome_text', 'Welcome').replace("{mention}", mention)
    msg = await bot.send_message(event.chat.id, txt)
    asyncio.create_task(delete_later(event.chat.id, msg.message_id, 20))

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
