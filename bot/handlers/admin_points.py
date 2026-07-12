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


@Client.on_message(filters.command("view_user") & filters.private & filters.user(settings.OWNER_IDS))
async def view_user_handler(client: Client, message: Message):
    """View user details including points"""
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("<b>Usage:</b> <code>/view_user USER_ID</code>")
        return
    
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID</b>")
        return
    
    user = await database.get_user(user_id)
    if not user:
        await message.reply_text(f"<b>❌ User <code>{user_id}</code> not found</b>")
        return
    
    payments = await database.get_user_payments(user_id, limit=5)
    point_logs = await database.get_point_logs(user_id, limit=5)
    
    text = (
        f"<blockquote><b>👤 ᴜsᴇʀ ᴅᴇᴛᴀɪʟs</b></blockquote>\n\n"
        f"<b>🆔 ID:</b> <code>{user_id}</code>\n"
        f"<b>👤 Name:</b> {user.get('full_name', 'Unknown')}\n"
        f"<b>👤 Username:</b> @{user.get('username', 'Unknown')}\n"
        f"<b>⭐ Points:</b> <code>{user.get('points', 0)}</code>\n"
        f"<b>💎 Plan:</b> {user.get('plan', 'free').title()}\n"
        f"<b>🚫 Banned:</b> {'✅' if user.get('is_banned', False) else '❌'}\n"
        f"<b>📦 Total Deployments:</b> {user.get('total_deployments', 0)}\n\n"
    )
    
    if payments:
        text += "<b>💳 Recent Payments:</b>\n"
        for p in payments[:3]:
            status_emoji = "✅" if p["status"] == "approved" else "⏳" if p["status"] == "pending" else "❌"
            text += f"  {status_emoji} ₹{p['amount']:.2f} → {p.get('points', 0)} pts ({p['status']})\n"
    
    if point_logs:
        text += f"\n<b>📊 Recent Point Changes:</b>\n"
        for log in point_logs[:3]:
            if 'points_deducted' in log:
                text += f"  ➖ {log.get('points_deducted')} pts ({log.get('reason', 'Unknown')})\n"
            else:
                text += f"  ⭐ {log.get('new_points')} pts ({log.get('reason', 'Admin')})\n"
    
    text += f"\n<b>💳 Edit Points:</b>\n<code>/edit_points {user_id} NEW_POINTS</code>"
    
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 ◀ Back", "admin_panel")]
        ])
    )


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
            f"<b>⏰ Time:</b> {time.ctime(p['created_at'])}\n"
            f"─────────────────\n"
        )
    
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔵 ◀ Back", "admin_panel")]
        ])
    )
