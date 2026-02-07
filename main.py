import os
import sqlite3
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
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
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('group_id', '0')")
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', 'Selamat datang!')")
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_btn', 'Join Channel|https://t.me/telegram')")

init_db()

# --- MENU UTAMA ---
@dp.message(Command("start"), F.chat.type == "private")
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Set Target Grup", callback_data="guide_group")],
        [InlineKeyboardButton(text="📝 Set Welcome", callback_data="set_welcome")],
        [InlineKeyboardButton(text="🚫 Set Filter Kata", callback_data="set_filter")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="bc")],
        [InlineKeyboardButton(text="💾 Send DB (Backup)", callback_data="send_db")]
    ])
    await message.answer("🛡️ **Super Admin Panel**", reply_markup=kb)

# --- SET GRUP ---
@dp.message(Command("setgrup"))
async def set_group_id(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    gid = str(message.chat.id)
    db_query("UPDATE settings SET value = ? WHERE key = 'group_id'", (gid,))
    rep = await message.answer(f"✅ Grup terdaftar: {gid}")
    await asyncio.sleep(3)
    await message.delete()
    await rep.delete()

# --- FITUR BROADCAST (FIXED) ---
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
        await message.answer("✅ Pesan broadcast berhasil dikirim ke grup.")
    except Exception as e:
        await message.answer(f"❌ Gagal kirim: {e}")
    await state.clear()

# --- FITUR SET FILTER (FIXED) ---
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
    except:
        await message.answer("Kata tersebut sudah ada dalam daftar.")
    await state.clear()

# --- WELCOME + AUTO MENTION + AUTO DELETE ---
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

@dp.chat_member()
async def on_user_join(event: types.ChatMemberUpdated):
    target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    if str(event.chat.id) != target_group: return

    if event.new_chat_member.status == "member" and event.old_chat_member.status != "member":
        user = event.new_chat_member.user
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a> (<code>{user.id}</code>) @{user.username}'
        
        txt = db_query("SELECT value FROM settings WHERE key = 'welcome_text'", fetch=True)[0][0]
        btn_data = db_query("SELECT value FROM settings WHERE key = 'welcome_btn'", fetch=True)[0][0].split("|")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_data[0], url=btn_data[1])]])
        
        # Kirim Welcome
        wel_msg = await bot.send_message(event.chat.id, f"Halo {mention}!\n\n{txt}", reply_markup=kb)
        
        # Log Mata Elang ke Admin
        await bot.send_message(ADMIN_ID, f"👁️ **Mata Elang:** {mention} baru saja bergabung.")
        
        # Auto Delete Welcome Message (10 detik)
        await asyncio.sleep(10)
        try: await wel_msg.delete()
        except: pass

# --- FILTER CHAT + AUTO MUTE ---
warn_count = {}

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def filter_monitor(message: types.Message):
    target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    if str(message.chat.id) != target_group: return
    if message.from_user.id == ADMIN_ID: return # Admin kebal

    banned_words = [row[0] for row in db_query("SELECT word FROM filters", fetch=True)]
    if message.text and any(w in message.text.lower() for w in banned_words):
        uid = message.from_user.id
        warn_count[uid] = warn_count.get(uid, 0) + 1
        
        await message.delete() # Langsung hapus chat kasar

        if warn_count[uid] >= 2:
            # Mute permanen
            await bot.restrict_chat_member(message.chat.id, uid, permissions=types.ChatPermissions(can_send_messages=False))
            await message.answer(f"🔇 {message.from_user.full_name} di-mute karena melanggar filter 2x.")
        else:
            await message.answer(f"⚠️ {message.from_user.full_name}, jangan bicara kasar! (Peringatan 1/2)")

# --- OTHER BUTTONS ---
@dp.callback_query(F.data == "guide_group")
async def guide(c: types.CallbackQuery):
    await c.message.answer("Masuk ke grup, jadikan bot admin, lalu ketik `/setgrup`")
    await c.answer()

@dp.callback_query(F.data == "send_db")
async def send_db(c: types.CallbackQuery):
    await bot.send_document(ADMIN_ID, FSInputFile("database.db"), caption="Backup DB")
    await c.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
