from pyrogram import Client, filters
from pyrogram.types import Message
import datetime
from bot.config.settings import settings
from bot.database.db import database
from bot.keyboards.main import admin_keyboard, confirmation_keyboard
from bot.utils.security import validate_railway_token
from railway.token_manager import token_manager
from bot.deployment.engine import deployment_engine
from bot.workers.point_deduction_worker import point_deduction_worker


@Client.on_message(filters.command("admin") & filters.private & filters.user(settings.OWNER_IDS))
async def admin_panel_handler(client: Client, message: Message):
    # Get stats
    total_users = await database.count_users()
    active_deployments = await database.count_active_deployments()
    total_points_distributed = 0
    users = await database.get_all_users()
    for u in users:
        total_points_distributed += u.get("points", 0)
    
    await message.reply_text(
        f"<blockquote><b>⚙ ᴀᴅᴍɪɴ ᴄᴏɴᴛʀᴏʟ ᴘᴀɴᴇʟ</b></blockquote>\n\n"
        f"<b>👥 Users:</b> {total_users}\n"
        f"<b>🤖 Active Deployments:</b> {active_deployments}\n"
        f"<b>⭐ Total Points in System:</b> {total_points_distributed}\n"
        f"<b>📉 Daily Cost per Bot:</b> {settings.DAILY_POINT_COST} pts\n"
        f"<b>📌 Min Points for Deployment:</b> {settings.MINIMUM_POINTS_FOR_DEPLOYMENT} pts\n\n"
        "<b>ᴜsᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴍᴀɴᴀɢᴇ ᴛʜᴇ sʏsᴛᴇᴍ.</b>",
        reply_markup=admin_keyboard(),
    )


@Client.on_message(filters.command("addpoints") & filters.private & filters.user(settings.OWNER_IDS))
async def add_points_handler(client: Client, message: Message):
    """Add points to a user."""
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text(
            "<b>Usage:</b> <code>/addpoints USER_ID AMOUNT [REASON]</code>\n\n"
            "<b>Example:</b> <code>/addpoints 123456789 100 Welcome bonus</code>"
        )
        return
    
    try:
        user_id = int(parts[1])
        amount = int(parts[2])
        reason = " ".join(parts[3:]) if len(parts) > 3 else "admin_added"
        
        if amount <= 0:
            await message.reply_text("<b>❌ Amount must be positive</b>")
            return
        
        user = await database.get_user(user_id)
        if not user:
            await message.reply_text(f"<b>❌ User {user_id} not found</b>")
            return
        
        success = await database.add_points(user_id, amount, reason)
        if success:
            new_balance = await database.get_points_balance(user_id)
            await message.reply_text(
                f"<b>✅ Added {amount} points to user {user_id}</b>\n\n"
                f"<b>New Balance:</b> {new_balance}\n"
                f"<b>Reason:</b> {reason}"
            )
            # Notify user
            from bot.services.log_service import owner_log
            await owner_log.send_user_notification(
                user_id,
                f"<b>⭐ Points Added!</b>\n\n"
                f"<b>Amount:</b> +{amount} points\n"
                f"<b>Reason:</b> {reason}\n"
                f"<b>New Balance:</b> {new_balance}"
            )
        else:
            await message.reply_text("<b>❌ Failed to add points</b>")
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID or amount</b>")


@Client.on_message(filters.command("deductpoints") & filters.private & filters.user(settings.OWNER_IDS))
async def deduct_points_handler(client: Client, message: Message):
    """Deduct points from a user."""
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text(
            "<b>Usage:</b> <code>/deductpoints USER_ID AMOUNT [REASON]</code>\n\n"
            "<b>Example:</b> <code>/deductpoints 123456789 10 Penalty</code>"
        )
        return
    
    try:
        user_id = int(parts[1])
        amount = int(parts[2])
        reason = " ".join(parts[3:]) if len(parts) > 3 else "admin_deducted"
        
        if amount <= 0:
            await message.reply_text("<b>❌ Amount must be positive</b>")
            return
        
        user = await database.get_user(user_id)
        if not user:
            await message.reply_text(f"<b>❌ User {user_id} not found</b>")
            return
        
        current = await database.get_points_balance(user_id)
        if current < amount:
            await message.reply_text(
                f"<b>❌ Insufficient points</b>\n\n"
                f"Current balance: {current}\n"
                f"Requested deduction: {amount}"
            )
            return
        
        success = await database.deduct_points(user_id, amount, reason)
        if success:
            new_balance = await database.get_points_balance(user_id)
            await message.reply_text(
                f"<b>✅ Deducted {amount} points from user {user_id}</b>\n\n"
                f"<b>New Balance:</b> {new_balance}\n"
                f"<b>Reason:</b> {reason}"
            )
            # Notify user
            from bot.services.log_service import owner_log
            await owner_log.send_user_notification(
                user_id,
                f"<b>⭐ Points Deducted!</b>\n\n"
                f"<b>Amount:</b> -{amount} points\n"
                f"<b>Reason:</b> {reason}\n"
                f"<b>New Balance:</b> {new_balance}"
            )
        else:
            await message.reply_text("<b>❌ Failed to deduct points</b>")
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID or amount</b>")


@Client.on_message(filters.command("pointsusers") & filters.private & filters.user(settings.OWNER_IDS))
async def list_users_points_handler(client: Client, message: Message):
    """List all users with their points balance."""
    users = await database.get_all_users_with_points()
    if not users:
        await message.reply_text("<b>No users found</b>")
        return
    
    text = "<blockquote><b>⭐ ᴜsᴇʀs ᴘᴏɪɴᴛs ʙᴀʟᴀɴᴄᴇ</b></blockquote>\n\n"
    sorted_users = sorted(users, key=lambda x: x.get("points", 0), reverse=True)
    
    for i, user in enumerate(sorted_users[:50]):  # Show top 50
        user_id = user.get("user_id")
        username = user.get("username", "Unknown")
        points = user.get("points", 0)
        text += f"<b>{i+1}.</b> <code>{user_id}</code> ({username}) — <b>{points}</b> pts\n"
    
    if len(sorted_users) > 50:
        text += f"\n...and {len(sorted_users) - 50} more users"
    
    await message.reply_text(text)


@Client.on_message(filters.command("setpoints") & filters.private & filters.user(settings.OWNER_IDS))
async def set_points_handler(client: Client, message: Message):
    """Set a user's points to a specific value."""
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text(
            "<b>Usage:</b> <code>/setpoints USER_ID AMOUNT</code>\n\n"
            "<b>Example:</b> <code>/setpoints 123456789 100</code>"
        )
        return
    
    try:
        user_id = int(parts[1])
        amount = int(parts[2])
        
        if amount < 0:
            await message.reply_text("<b>❌ Amount cannot be negative</b>")
            return
        
        user = await database.get_user(user_id)
        if not user:
            await message.reply_text(f"<b>❌ User {user_id} not found</b>")
            return
        
        old_balance = user.get("points", 0)
        await database.update_user(user_id, {"points": amount})
        
        # Log transaction
        await database.db.point_transactions.insert_one({
            "user_id": user_id,
            "amount": amount - old_balance,
            "type": "credit" if amount > old_balance else "debit",
            "reason": "admin_set",
            "balance_after": amount,
            "created_at": datetime.datetime.utcnow()
        })
        
        await message.reply_text(
            f"<b>✅ Points set for user {user_id}</b>\n\n"
            f"<b>Old Balance:</b> {old_balance}\n"
            f"<b>New Balance:</b> {amount}"
        )
        
        # Notify user
        from bot.services.log_service import owner_log
        await owner_log.send_user_notification(
            user_id,
            f"<b>⭐ Points Updated!</b>\n\n"
            f"<b>Old Balance:</b> {old_balance}\n"
            f"<b>New Balance:</b> {amount}\n"
            f"<b>Reason:</b> Admin updated your points balance."
        )
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID or amount</b>")


@Client.on_message(filters.command("setdailycost") & filters.private & filters.user(settings.OWNER_IDS))
async def set_daily_cost_handler(client: Client, message: Message):
    """Set the daily point cost for deployments."""
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text(
            "<b>Usage:</b> <code>/setdailycost AMOUNT</code>\n\n"
            f"<b>Current daily cost:</b> {settings.DAILY_POINT_COST} pts/day\n"
            f"<b>Example:</b> <code>/setdailycost 3</code>"
        )
        return
    
    try:
        amount = int(parts[1])
        if amount <= 0:
            await message.reply_text("<b>❌ Amount must be greater than 0</b>")
            return
        
        # Update settings
        settings.DAILY_POINT_COST = amount
        # Also update the worker
        point_deduction_worker.DAILY_COST = amount
        
        await message.reply_text(
            f"<b>✅ Daily point cost updated to {amount} points/day</b>\n\n"
            f"<b>Note:</b> This will affect all future deductions."
        )
    except ValueError:
        await message.reply_text("<b>❌ Invalid amount</b>")


@Client.on_message(filters.command("setminpoints") & filters.private & filters.user(settings.OWNER_IDS))
async def set_min_points_handler(client: Client, message: Message):
    """Set the minimum points required for deployment."""
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text(
            "<b>Usage:</b> <code>/setminpoints AMOUNT</code>\n\n"
            f"<b>Current minimum:</b> {settings.MINIMUM_POINTS_FOR_DEPLOYMENT} pts\n"
            f"<b>Example:</b> <code>/setminpoints 80</code>"
        )
        return
    
    try:
        amount = int(parts[1])
        if amount <= 0:
            await message.reply_text("<b>❌ Amount must be greater than 0</b>")
            return
        
        settings.MINIMUM_POINTS_FOR_DEPLOYMENT = amount
        
        await message.reply_text(
            f"<b>✅ Minimum points for deployment updated to {amount} points</b>\n\n"
            f"<b>Note:</b> This will affect all future deployments."
        )
    except ValueError:
        await message.reply_text("<b>❌ Invalid amount</b>")


# Keep all existing admin commands (addtoken, removetoken, addchannel, etc.)
# ... rest of the admin commands remain unchanged