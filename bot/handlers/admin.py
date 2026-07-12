import datetime
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.config.settings import settings
from bot.database.db import database
from bot.keyboards.main import admin_keyboard, confirmation_keyboard
from bot.utils.security import validate_railway_token
from railway.token_manager import token_manager
from bot.deployment.engine import deployment_engine

logger = logging.getLogger(__name__)


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


@Client.on_message(filters.command("addtoken") & filters.private & filters.user(settings.OWNER_IDS))
async def add_token_handler(client: Client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("<b>Usage:</b> <code>/addtoken RAILWAY_TOKEN</code>")
        return
    token = parts[1].strip()
    if not validate_railway_token(token):
        await message.reply_text("<b>❌ Invalid Railway token format</b>")
        return
    try:
        doc = await token_manager.add_token(token, message.from_user.id)
        await message.reply_text(f"<b>✅ Token added successfully</b>\n\n<b>Token:</b> <code>{token[:8]}...</code>")
    except ValueError as e:
        await message.reply_text(f"<b>❌ {str(e)}</b>")


@Client.on_message(filters.command("removetoken") & filters.private & filters.user(settings.OWNER_IDS))
async def remove_token_handler(client: Client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("<b>Usage:</b> <code>/removetoken TOKEN</code>")
        return
    token = parts[1].strip()
    await token_manager.remove_token(token)
    await message.reply_text("<b>✅ Token removed</b>")


@Client.on_message(filters.command("addchannel") & filters.private & filters.user(settings.OWNER_IDS))
async def add_channel_handler(client: Client, message: Message):
    parts = message.text.split(maxsplit=3)
    if len(parts) < 3:
        await message.reply_text("<b>Usage:</b> <code>/addchannel CHANNEL_ID INVITE_LINK [NAME]</code>")
        return
    try:
        channel_id = int(parts[1])
        invite_link = parts[2]
        name = parts[3] if len(parts) > 3 else ""
        await database.add_channel(channel_id, invite_link, name)
        await message.reply_text(f"<b>✅ Channel added:</b> {name or channel_id}")
    except ValueError:
        await message.reply_text("<b>❌ Invalid channel ID</b>")


@Client.on_message(filters.command("removechannel") & filters.private & filters.user(settings.OWNER_IDS))
async def remove_channel_handler(client: Client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("<b>Usage:</b> <code>/removechannel CHANNEL_ID</code>")
        return
    try:
        channel_id = int(parts[1])
        await database.remove_channel(channel_id)
        await message.reply_text("<b>✅ Channel removed</b>")
    except ValueError:
        await message.reply_text("<b>❌ Invalid channel ID</b>")


@Client.on_message(filters.command("channels") & filters.private & filters.user(settings.OWNER_IDS))
async def list_channels_handler(client: Client, message: Message):
    channels = await database.get_all_channels()
    if not channels:
        await message.reply_text("<b>No channels configured</b>")
        return
    text = "<blockquote><b>📢 ᴄᴏɴғɪɢᴜʀᴇᴅ ᴄʜᴀɴɴᴇʟs</b></blockquote>\n\n"
    for ch in channels:
        text += f"<b>📌 {ch.get('name', 'Unnamed')}</b>\n"
        text += f"<b>  ID:</b> <code>{ch['channel_id']}</code>\n"
        text += f"<b>  Link:</b> {ch.get('invite_link', 'N/A')}\n\n"
    await message.reply_text(text)


@Client.on_message(filters.command("broadcast") & filters.private & filters.user(settings.OWNER_IDS))
async def broadcast_handler(client: Client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("<b>Reply to a message to broadcast it to all users</b>")
        return
    users = await database.get_all_users()
    success = 0
    failed = 0
    status_msg = await message.reply_text("<b>📢 Broadcasting...</b>")
    for user in users:
        try:
            await message.reply_to_message.copy(user["user_id"])
            success += 1
        except Exception:
            failed += 1
    await status_msg.edit_text(
        f"<b>📢 Broadcast Complete</b>\n\n"
        f"<b>✅ Sent:</b> {success}\n"
        f"<b>❌ Failed:</b> {failed}"
    )


@Client.on_message(filters.command("ban") & filters.private & filters.user(settings.OWNER_IDS))
async def ban_handler(client: Client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("<b>Usage:</b> <code>/ban USER_ID [REASON]</code>")
        return
    try:
        user_id = int(parts[1])
        reason = " ".join(parts[2:]) if len(parts) > 2 else "No reason"
        await database.update_user(user_id, {"is_banned": True, "ban_reason": reason})
        await message.reply_text(f"<b>✅ User {user_id} banned</b>\n<b>Reason:</b> {reason}")
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID</b>")


@Client.on_message(filters.command("unban") & filters.private & filters.user(settings.OWNER_IDS))
async def unban_handler(client: Client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("<b>Usage:</b> <code>/unban USER_ID</code>")
        return
    try:
        user_id = int(parts[1])
        await database.update_user(user_id, {"is_banned": False, "ban_reason": ""})
        await message.reply_text(f"<b>✅ User {user_id} unbanned</b>")
    except ValueError:
        await message.reply_text("<b>❌ Invalid user ID</b>")


# ==================== POINTS ADMIN COMMANDS ====================

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
    
    for i, user in enumerate(sorted_users[:50]):
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
        
        settings.DAILY_POINT_COST = amount
        
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


@Client.on_message(filters.command("points") & filters.private)
async def points_handler(client: Client, message: Message):
    """Check your points balance and recent transactions."""
    user_id = message.from_user.id
    points = await database.get_points_balance(user_id)
    transactions = await database.get_point_transactions(user_id, limit=10)
    
    text = f"<b>⭐ Your Points Balance:</b> {points}\n\n"
    
    if transactions:
        text += "<b>Recent Transactions:</b>\n"
        for tx in transactions:
            amount = tx.get("amount", 0)
            type_emoji = "➕" if tx.get("type") == "credit" else "➖"
            reason = tx.get("reason", "Unknown")
            created = tx.get("created_at")
            if created:
                created_str = created.strftime("%Y-%m-%d %H:%M")
            else:
                created_str = "Unknown"
            text += f"{type_emoji} {amount} pts - {reason} ({created_str})\n"
    else:
        text += "No transactions yet."
    
    text += f"\n\n<b>📌 Daily Cost per Bot:</b> {settings.DAILY_POINT_COST} pts"
    text += f"\n<b>📌 Min Points for Deployment:</b> {settings.MINIMUM_POINTS_FOR_DEPLOYMENT} pts"
    
    await message.reply_text(text)
