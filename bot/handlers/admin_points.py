import time
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config.settings import settings
from bot.database.db import database
from bot.keyboards.main import admin_keyboard


@Client.on_message(filters.command("edit_points") & filters.private & filters.user(settings.OWNER_IDS))
async def edit_points_handler(client: Client, message: Message):
    """Edit points of any user"""
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text(
            "<b>📝 Edit User Points</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/edit_points USER_ID NEW_POINTS</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/edit_points 123456789 100</code>\n\n"
            "This will set the user's points to exactly 100."
        )
        return
    
    try:
        user_id = int(parts[1])
        new_points = int(parts[2])
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID or points value. Must be numbers.</b>")
        return
    
    if new_points < 0:
        await message.reply_text("<b>❌ Points cannot be negative</b>")
        return
    
    user = await database.get_user(user_id)
    if not user:
        await message.reply_text(f"<b>❌ User <code>{user_id}</code> not found in database.</b>")
        return
    
    success = await database.update_user_points(user_id, new_points, f"Admin edit by {message.from_user.first_name}")
    
    if success:
        await message.reply_text(
            f"<blockquote><b>✅ ᴘᴏɪɴᴛs ᴜᴘᴅᴀᴛᴇᴅ</b></blockquote>\n\n"
            f"<b>👤 User ID:</b> <code>{user_id}</code>\n"
            f"<b>👤 Name:</b> {user.get('full_name', 'Unknown')}\n"
            f"<b>⭐ New Points:</b> <code>{new_points}</code>\n"
            f"<b>📝 Updated by:</b> {message.from_user.first_name}"
        )
        
        try:
            await client.send_message(
                user_id,
                f"<blockquote><b>⭐ ᴘᴏɪɴᴛs ᴜᴘᴅᴀᴛᴇᴅ</b></blockquote>\n\n"
                f"<b>Your points have been updated by admin.</b>\n"
                f"<b>⭐ New Points:</b> <code>{new_points}</code>"
            )
        except Exception:
            pass
    else:
        await message.reply_text("<b>❌ Failed to update points</b>")


@Client.on_message(filters.command("add_points") & filters.private & filters.user(settings.OWNER_IDS))
async def add_points_handler(client: Client, message: Message):
    """Add points to a user"""
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text(
            "<b>📝 Add Points to User</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/add_points USER_ID AMOUNT</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/add_points 123456789 50</code>"
        )
        return
    
    try:
        user_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID or amount. Must be numbers.</b>")
        return
    
    if amount <= 0:
        await message.reply_text("<b>❌ Amount must be positive</b>")
        return
    
    user = await database.get_user(user_id)
    if not user:
        await message.reply_text(f"<b>❌ User <code>{user_id}</code> not found in database.</b>")
        return
    
    current_points = user.get("points", 0)
    new_points = current_points + amount
    
    success = await database.update_user_points(user_id, new_points, f"Admin added {amount} points")
    
    if success:
        await message.reply_text(
            f"<blockquote><b>✅ ᴘᴏɪɴᴛs ᴀᴅᴅᴇᴅ</b></blockquote>\n\n"
            f"<b>👤 User:</b> <code>{user_id}</code>\n"
            f"<b>➕ Added:</b> <code>{amount}</code> points\n"
            f"<b>⭐ New Total:</b> <code>{new_points}</code>"
        )
        
        try:
            await client.send_message(
                user_id,
                f"<blockquote><b>⭐ ᴘᴏɪɴᴛs ᴀᴅᴅᴇᴅ</b></blockquote>\n\n"
                f"<b>➕ {amount} points have been added to your account by admin.</b>\n"
                f"<b>⭐ New Balance:</b> <code>{new_points}</code>"
            )
        except Exception:
            pass
    else:
        await message.reply_text("<b>❌ Failed to add points</b>")


@Client.on_message(filters.command("pending_payments") & filters.private & filters.user(settings.OWNER_IDS))
async def pending_payments_handler(client: Client, message: Message):
    """List all pending payments"""
    payments = await database.get_pending_payments(limit=50)
    
    if not payments:
        await message.reply_text("<b>✅ No pending payments</b>")
        return
    
    text = f"<blockquote><b>⏳ ᴘᴇɴᴅɪɴɢ ᴘᴀʏᴍᴇɴᴛs ({len(payments)})</b></blockquote>\n\n"
    
    for p in payments[:20]:
        user = await database.get_user(p["user_id"])
        name = user.get("full_name", "Unknown") if user else "Unknown"
        text += (
            f"<b>🆔 ID:</b> <code>{p['payment_id'][:8]}</code>\n"
            f"<b>👤 User:</b> {name} (<code>{p['user_id']}</code>)\n"
            f"<b>💰 Amount:</b> ₹{p['amount']:.2f}\n"
            f"<b>⭐ Points:</b> {p.get('points', 0)}\n"
            f"<b>📝 TXN:</b> <code>{p['transaction_id']}</code>\n"
            f"─────────────────\n"
        )
    
    await message.reply_text(text, reply_markup=admin_keyboard())