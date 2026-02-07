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

# --- SETUP LOGGING (Supaya kelihatan di Railway kalau ada error) ---
logging.basicConfig(level=logging.INFO)

# --- CONFIG DARI RAILWAY ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN atau ADMIN_ID belum diisi di Environment Variables Railway!")

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
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', 'Selamat datang di grup!')")
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_btn', 'Join Channel|https://t.me/telegram')")

init_db()

# --- MENU UTAMA (HANYA ADMIN) ---
@dp.message(Command("start"), F.chat.type == "private")
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Set Target Grup", callback_data="guide_group")],
        [InlineKeyboardButton(text="📝 Set Welcome", callback_data="set_welcome")],
        [InlineKeyboardButton(text="🚫 Set Filter Kata", callback_data="set_filter")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="bc")],
        [InlineKeyboardButton(text="💾 Send DB (Backup)", callback_data="send_db")]
    ])
    await message.answer("🛡️ **Super Admin Panel**\nKlik tombol di bawah untuk mengatur grup.", reply_markup=kb)

# --- SET GRUP + AUTO DELETE ---
@dp.message(Command("setgrup"))
async def set_group_id(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    gid = str(message.chat.id)
    db_query("UPDATE settings SET value = ? WHERE key = 'group_id'", (gid,))
    
    rep = await message.answer(f"✅ **Grup Terdaftar!**\nID: <code>{gid}</code>\n<i>Pesan ini akan dihapus otomatis...</i>")
    await asyncio.sleep(3)
    try:
        await message.delete()
        await rep.delete()
    except: pass

# --- HANDLER WELCOME (PROSES INPUT) ---
@dp.callback_query(F.data == "set_welcome")
async def start_set_welcome(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Kirim teks welcome baru:")
    await state.set_state(AdminStates.waiting_welcome_text)
    await callback.answer()

@dp.message(AdminStates.waiting_welcome_text)
async def save_welcome_text(message: types.Message, state: FSMContext):
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_text'", (message.text,))
    await message.answer("Teks disimpan! Sekarang kirim format tombol (Contoh: `Nama|https://link.com`):")
    await state.set_state(AdminStates.waiting_welcome_btn)

@dp.message(AdminStates.waiting_welcome_btn)
async def save_welcome_btn(message: types.Message, state: FSMContext):
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_btn'", (message.text,))
    await message.answer("✅ Welcome & Tombol berhasil diupdate!")
    await state.clear()

# --- MATA ELANG (LOG JOIN/OUT/GANTI NAMA) ---
@dp.chat_member()
async def mata_elang_handler(event: types.ChatMemberUpdated):
    target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    if str(event.chat.id) != target_group: return

    # Hidden Mention untuk User yang Join
    hidden_mention = f'<a href="tg://user?id={event.new_chat_member.user.id}">\u200b</a>'
    
    if event.new_chat_member.status == "member" and event.old_chat_member.status != "member":
        # Kirim Welcome ke Grup
        welcome_txt = db_query("SELECT value FROM settings WHERE key = 'welcome_text'", fetch=True)[0][0]
        btn_raw = db_query("SELECT value FROM settings WHERE key = 'welcome_btn'", fetch=True)[0][0].split("|")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn_raw[0], url=btn_raw[1])]])
        await bot.send_message(event.chat.id, f"{hidden_mention}{welcome_txt}", reply_markup=kb)
        
        # Kirim Log ke Admin
        await bot.send_message(ADMIN_ID, f"📥 **Join:** {event.new_chat_member.user.full_name} (@{event.new_chat_member.user.username})")

    elif event.new_chat_member.status == "left":
        await bot.send_message(ADMIN_ID, f"📤 **Out:** {event.old_chat_member.user.full_name}")

# --- MONITORING PESAN (FILTER KATA) ---
warn_dict = {}

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def watch_messages(message: types.Message):
    target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    if str(message.chat.id) != target_group: return
    if message.from_user.id == ADMIN_ID: return # Admin Kebal

    banned_words = [row[0] for row in db_query("SELECT word FROM filters", fetch=True)]
    if any(word in (message.text or "").lower() for word in banned_words):
        uid = message.from_user.id
        warn_dict[uid] = warn_dict.get(uid, 0) + 1
        
        await message.delete()
        if warn_dict[uid] >= 2:
            await bot.restrict_chat_member(message.chat.id, uid, permissions=types.ChatPermissions(can_send_messages=False))
            await message.answer(f"🔇 {message.from_user.full_name} di-mute karena melanggar filter 2x.")
        else:
            await message.answer(f"⚠️ {message.from_user.full_name}, jangan bicara kasar! (1/2)")

# --- BROADCAST & LAINNYA ---
@dp.callback_query(F.data == "guide_group")
async def guide(c: types.CallbackQuery):
    await c.message.answer("1. Masukkan bot ke grup.\n2. Jadikan Admin.\n3. Ketik /setgrup di grup tersebut.")
    await c.answer()

@dp.callback_query(F.data == "send_db")
async def send_db(c: types.CallbackQuery):
    await bot.send_document(ADMIN_ID, FSInputFile("database.db"), caption="Backup DB")
    await c.answer()

# --- JALANKAN BOT ---
async def main():
    print("Bot sedang berjalan...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot Berhenti")
