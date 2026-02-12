# ... (keep semua import & setup sama) ...

# --- WELCOME SETTINGS (FIXED) ---
@dp.callback_query(F.data == "set_welcome")
async def start_welcome(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Kirim teks welcome baru:\n\n<u>Contoh:</u> Selamat datang di grup kami!")
    await state.set_state(AdminStates.waiting_welcome_text)
    await callback.answer()

@dp.message(AdminStates.waiting_welcome_text)
async def save_welcome_text(message: types.Message, state: FSMContext):
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_text'", (message.text,))
    await message.answer("✅ Teks disimpan!\n\nSekarang kirim tombol:\n<u>Format:</u> Nama Tombol|https://t.me/channel\n\n<u>Contoh:</u>\nJoin Channel|https://t.me/telegram")
    await state.set_state(AdminStates.waiting_welcome_btn)

@dp.message(AdminStates.waiting_welcome_btn)
async def save_welcome_btn(message: types.Message, state: FSMContext):
    # VALIDASI URL (FIX CRITICAL BUG)
    btn_data = message.text.strip().split("|")
    if len(btn_data) != 2:
        await message.answer("❌ Format salah! Gunakan: <code>Nama|URL</code>")
        return
    
    name, url = btn_data[0].strip(), btn_data[1].strip()
    if not url.startswith("http"):
        await message.answer("❌ URL harus mulai dengan http:// atau https://")
        return
    
    db_query("UPDATE settings SET value = ? WHERE key = 'welcome_btn'", (f"{name}|{url}",))
    await message.answer(f"✅ Welcome & Tombol diupdate!\n\n📋 <b>Preview:</b>\n\nSelamat datang!\n[{name}]({url})", parse_mode="Markdown")
    await state.clear()

# --- ENHANCED WELCOME (SAFE URL PARSING) ---
@dp.chat_member()
async def on_user_join(event: types.ChatMemberUpdated):
    gid = str(event.chat.id)
    
    # Skip unregistered groups
    if get_group_log_chat(gid) == "0":
        target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
        if gid != target_group: return

    if event.new_chat_member.status == "member" and event.old_chat_member.status != "member":
        user = event.new_chat_member.user
        mention = f'<a href="tg://user?id={user.id}">{user.full_name}</a>'
        username = f"@{user.username}" if user.username else "Tanpa username"
        
        txt = db_query("SELECT value FROM settings WHERE key = 'welcome_text'", fetch=True)[0][0]
        btn_raw = db_query("SELECT value FROM settings WHERE key = 'welcome_btn'", fetch=True)[0][0]
        
        # SAFE URL SPLITTING (FIX BUG)
        btn_parts = btn_raw.split("|")
        kb = None
        if len(btn_parts) == 2:
            name, url = btn_parts[0].strip(), btn_parts[1].strip()
            if url.startswith(("http://", "https://")):
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=name, url=url)]
                ])
        
        try:
            wel_msg = await bot.send_message(
                event.chat.id, 
                f"👋 Halo {mention}!\n\n{username}\n\n{txt}", 
                reply_markup=kb,
                parse_mode="HTML"
            )
            
            # Log
            log_text = f"👋 **Member Baru**\n{mention}\nUsername: {username}\n⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}"
            await send_to_log(gid, log_text)
            
            # Auto delete welcome (SAFE)
            await asyncio.sleep(10)
            try:
                await bot.delete_message(event.chat.id, wel_msg.message_id)
            except:
                pass  # Ignore if can't delete
                
        except Exception as e:
            # Log error tapi jangan crash
            await send_to_log(gid, f"❌ Welcome error: {str(e)}")

# --- SECURITY MONITOR (SAFE DELETE) ---
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def security_monitor(message: types.Message):
    gid = str(message.chat.id)
    
    # Skip unregistered groups
    if get_group_log_chat(gid) == "0":
        target_group = db_query("SELECT value FROM settings WHERE key = 'group_id'", fetch=True)[0][0]
        if gid != target_group: return
    
    uid = message.from_user.id
    
    # Admin & Bot exempt
    if uid == ADMIN_ID or message.from_user.is_bot:
        reset_spam_counter(uid)
        return
    
    # ANTI-SPAM
    if check_spam(uid):
        try:
            await message.delete()
        except:
            pass  # Ignore delete errors
        await send_to_log(gid, f"🚫 **SPAM** {message.from_user.full_name}")
        return
    
    # FILTER CHECK
    banned_words = [row[0] for row in db_query("SELECT word FROM filters", fetch=True)]
    text_lower = (message.text or "").lower()
    
    if any(word in text_lower for word in banned_words):
        try:
            await message.delete()
        except:
            pass
        
        warn_count[uid] = warn_count.get(uid, 0) + 1
        await send_to_log(gid, f"🚫 **FILTER** {message.from_user.full_name} (Warn {warn_count[uid]}/2)")
        
        if warn_count[uid] >= 2:
            try:
                permissions = ChatPermissions(can_send_messages=False)
                await bot.restrict_chat_member(gid, uid, permissions=permissions, until_date=int(time.time() + 3600))
            except:
                pass
        return
    
    # AUTO CLEAN (SAFE)
    should_delete = False
    if (message.service or 
        message.sticker or 
        (message.photo and len(message.photo) >= 3) or  # Multiple photos only
        (hasattr(message, 'video') and message.video and message.video.duration > 60)):
        should_delete = True
    
    if should_delete:
        try:
            await message.delete()
            await send_to_log(gid, f"🗑️ **CLEAN** {message.content_type}")
        except:
            pass  # No spam log for normal cleans

# ... (keep semua function lain SAMA) ...
