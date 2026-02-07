import os
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
# --- TAMBAHKAN IMPORT INI ---
from aiogram.client.default import DefaultBotProperties 

# --- CONFIG DARI RAILWAY ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# --- PERBAIKAN DI BAGIAN INI ---
bot = Bot(
    token=TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# --- SISANYA TETAP SAMA (TIDAK ADA YANG DIUBAH) ---
class AdminStates(StatesGroup):
    waiting_welcome_text = State()
    waiting_welcome_btn = State()
    waiting_filter_word = State()
    waiting_bc_text = State()

# ... (lanjutkan dengan kode database dan handler yang tadi) ...
