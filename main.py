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

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

class AdminStates(StatesGroup):
    waiting_welcome_text = State()
    waiting_welcome_btn = State()
    waiting_filter_word = State()
    waiting_bc_text = State()
    waiting_tagall_text = State()

user_spam_data = defaultdict(lambda: {'count': 0, 'last_reset': 0})
warn_count = {}
CHAT_COOLDOWN = 2
MAX_MSGS_PER_MIN = 10

def check_spam(user_id: int) -> bool:
    now = time.time()
    data = user_spam_data[user_id]
    if now - data['last_reset'] > 60:
        data['count'] = 0
        data['last_reset'] = now
    if now - data['last_reset'] < CHAT_COOLDOWN:
        return True
    data['count'] += 1
    return data['count'] > MAX_MSGS_PER_MIN

def reset_spam_counter(user_id: int):
    user_spam_data[user_id]['count'] = 0
    user_spam_data[user_id]['last_reset'] = time.time()

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
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('group_id', '0')")
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', 'Selamat datang!')")
    db_query("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_btn', 'Join|https://t.me/telegram')")

init_db()

def get_group_log_chat(group_id: str) -> str:
    result = db_query("SELECT log_chat_id FROM group_logs WHERE group_id = ?", (group_id,), fetch=True)
    return result[0][0] if result else "0"

async def send_to_log(group_id: str, text: str):
    log_chat = get_group_log_chat(group_id)
    if log_chat != "0":
        try:
            await bot.send_message(int(log_chat), f"<b>📍 Group ID:</b> <code>{group_id}</code>\n\n{text}", parse_mode="HTML")
        except:
            pass

async def do_tag_all(gid: str, text: str):
    try:
        await bot.send_message(int(gid), f"{text}\n\n🔔 <b>@all</b>", parse_mode="HTML")
        await send_to_log(gid, f"🔔 **TAG ALL** dari Admin:\n<code>{text[:100]}...</code>")
        return True
    except:
        await bot.send_message(int(gid), text)
        await send_to_log(gid, f"📢 **TAG ALL**:\n<code>{text[:100]}...</code>")
        return False

@dp.message(Command("start"), F.chat.type == "private")
async def admin_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Set Target Grup", callback_data="guide_group")],
        [InlineKeyboardButton(text="📝 Set Welcome", callback_data="set_welcome")],
        [InlineKeyboardButton(text="🚫 Set Filter Kata", callback_data="set_filter")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="bc")],
        [InlineKeyboardButton(text="🔔 Tag All", callback_data="tagall")],
        [InlineKeyboardButton(text="📊 Group Logs", callback_data="group_logs")],
        [InlineKeyboardButton(text="💾 Send DB", callback_data="send_db")]
    ])
    await message.answer("🛡️ **ADMIN PANEL**", reply_markup=kb)

@dp.callback_query(F.data == "tagall")
async def tagall_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("🔔 Kirim pesan TAG ALL:")
    await state.set_state(AdminStates.waiting_tagall_text)
    await callback.answer()

@dp.message(AdminStates.waiting_tagall_text)
async def tagall_exec(message: types.Message, state: FSMContext):
    gid = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    await do_tag_all(gid, message.text)
    await message.answer("✅ **TAG ALL** berhasil!")
    await state.clear()

@dp.callback_query(F.data == "bc")
async def bc_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📢 Kirim pesan broadcast:")
    await state.set_state(AdminStates.waiting_bc_text)
    await callback.answer()

@dp.message(AdminStates.waiting_bc_text)
async def bc_exec(message: types.Message, state: FSMContext):
    gid = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    try:
        await bot.send_message(gid, message.text)
        await send_to_log(gid, f"📢 **BROADCAST**:\n<code>{message.text[:100]}...</code>")
        await message.answer("✅ Broadcast OK!")
    except Exception as e:
        await message.answer(f"❌ {e}")
    await state.clear()

@dp.message(Command("setgrup"))
async def set_group(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    gid = str(message.chat.id)
    db_query("UPDATE settings SET value = ? WHERE key = 'group_id'", (gid,))
    await send_to_log(gid, "✅ **Grup registered**")
    await message.answer(f"✅ Grup ID: <code>{gid}</code>", parse_mode="HTML")

@dp.callback_query(F.data == "set_welcome")
async def welcome_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("📝 Kirim teks welcome baru:")
    await state.set_state(AdminStates.waiting_welcome_text)
    await callback.answer()

@dp.message(AdminStates.waiting_welcome_text)
async def welcome_text_save(message: types.Message, state: FSMContext):
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_text'", (message.text,))
    await message.answer("✅ Teks saved!\n\nKirim tombol: <code>Nama|https://link</code>")
    await state.set_state(AdminStates.waiting_welcome_btn)

@dp.message(AdminStates.waiting_welcome_btn)
async def welcome_btn_save(message: types.Message, state: FSMContext):
    parts = message.text.split("|")
    if len(parts) != 2:
        await message.answer("❌ Format: Nama|https://link")
        return
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_btn'", (message.text,))
    await message.answer("✅ Welcome updated!")
    await state.clear()

@dp.callback_query(F.data == "set_filter")
async def filter_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("🚫 Kirim kata filter:")
    await state.set_state(AdminStates.waiting_filter_word)
    await callback.answer()

@dp.message(AdminStates.waiting_filter_word)
async def filter_save(message: types.Message, state: FSMContext):
    word = message.text.lower()
    try:
        db_query("INSERT INTO filters (word) VALUES (?)", (word,))
        await message.answer(f"✅ Filter: <code>{word}</code>")
    except:
        await message.answer("❌ Sudah ada!")
    await state.clear()

@dp.callback_query(F.data == "group_logs")
async def logs_menu(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    logs = db_query("SELECT * FROM group_logs", fetch=True)
    text = "📊 **Logs:**\n\n"
    for g, l in logs:
        text += f"• {g} → <code>{l}</code>\n"
    if not logs:
        text += "Belum ada log"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "send_db")
async def send_db(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await bot.send_document(ADMIN_ID, FSInputFile("database.db"), caption="💾 DB Backup")
    await callback.answer()

@dp.callback_query(F.data == "guide_group")
async def guide(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    text = """📋 **Setup Guide:**

1. Bot → ADMIN di grup
2. `/setgrup` di grup
3. `/setlog [ID]` untuk log
4. ✅ Selesai!"""
    await callback.message.answer(text)
    await callback.answer()

@dp.message(Command("setlog"))
async def set_log_cmd(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    gid = str(message.chat.id)
    logid = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else "0"
    db_query("INSERT OR REPLACE INTO group_logs VALUES (?, ?)", (gid, logid))
    await message.answer(f"✅ Log set: <code>{logid}</code>")

@dp.chat_member()
async def welcome_new_member(event: types.ChatMemberUpdated):
    gid = str(event.chat.id)
    target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    if gid != target_group: return
    
    if event.new_chat_member.status == "member" and event.old_chat_member.status != "member":
        user = event.new_chat_member.user
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        
        txt = db_query("SELECT value FROM settings WHERE key = 'welcome_text'", fetch=True)[0][0]
        btn_raw = db_query("SELECT value FROM settings WHERE key = 'welcome_btn'", fetch=True)[0][0]
        
        kb = None
        if "|" in btn_raw:
            name, url = btn_raw.split("|")
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=name.strip(), url=url.strip())]])
        
        try:
            msg = await bot.send_message(event.chat.id, f"👋 {mention}!\n\n{txt}", reply_markup=kb, parse_mode="HTML")
            await asyncio.sleep(10)
            await bot.delete_message(event.chat.id, msg.message_id)
        except:
            pass

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def security_filter(message: types.Message):
    gid = str(message.chat.id)
    target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
    if gid != target_group: return
    
    uid = message.from_user.id
    if uid == ADMIN_ID or message.from_user.is_bot: return
    
    if check_spam(uid):
        try:
            await message.delete()
        except:
            pass
        return
    
    text = (message.text or "").lower()
    filters = [w[0] for w in db_query("SELECT word FROM filters", fetch=True)]
    if any(f in text for f in filters):
        try:
            await message.delete()
        except:
            pass
        return
    
    if message.sticker or message.service:
        try:
            await message.delete()
        except:
            pass

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
