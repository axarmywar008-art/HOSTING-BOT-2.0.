import asyncio
import logging
import time
import uuid
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config.settings import settings
from bot.database.db import database

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("buy_points") & filters.private)
async def buy_points_handler(client: Client, message: Message):
    """Show payment options to buy points"""
    user_id = message.from_user.id
    user = await database.get_user(user_id)
    if not user:
        await database.create_user(user_id, message.from_user.username or "", message.from_user.first_name or "")
    
    current_points = user.get("points", 0) if user else 0
    
    text = (
        f"<blockquote><b>💳 ᴘᴜʀᴄʜᴀsᴇ ᴘᴏɪɴᴛs</b></blockquote>\n\n"
        f"<b>⭐ Your Points:</b> <code>{current_points}</code>\n\n"
        f"<b>📊 Points Packages:</b>\n"
        f"┌─────────────────────┐\n"
        f"│ 💰 ₹10  →  100 points │\n"
        f"│ 💰 ₹25  →  250 points │\n"
        f"│ 💰 ₹50  →  500 points │\n"
        f"│ 💰 ₹100 → 1000 points │\n"
        f"│ 💰 ₹250 → 2500 points │\n"
        f"│ 💰 ₹500 → 5000 points │\n"
        f"└─────────────────────┘\n\n"
        f"<b>💳 UPI ID:</b> <code>{settings.UPI_ID}</code>\n\n"
        f"<b>📝 How to pay:</b>\n"
        f"1️⃣ Send payment via UPI to above ID\n"
        f"2️⃣ Take a screenshot of the payment\n"
        f"3️⃣ Use the <b>/pay</b> command with the amount"
    )
    
    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 ✅ Support", "support_contact")],
            [InlineKeyboardButton("🔵 🏡 Main Menu", "main_menu")],
        ])
    )


@Client.on_message(filters.command("pay") & filters.private)
async def pay_handler(client: Client, message: Message):
    """Handle payment submission with screenshot"""
    user_id = message.from_user.id
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text(
            "<b>❌ Usage:</b>\n"
            "<code>/pay 50</code>\n\n"
            "<b>Where 50 = amount in rupees</b>\n"
            "After sending the command, upload a screenshot of the payment."
        )
        return
    
    try:
        amount = float(parts[1])
    except ValueError:
        await message.reply_text("<b>❌ Invalid amount. Please use numbers only.</b>")
        return
    
    if amount < 10:
        await message.reply_text("<b>❌ Minimum amount is ₹10</b>")
        return
    
    await database.update_user(user_id, {
        "payment_state": {
            "amount": amount,
            "waiting_for_screenshot": True,
            "timestamp": time.time(),
        }
    })
    
    await message.reply_text(
        f"<b>📤 Payment Submission</b>\n\n"
        f"<b>Amount:</b> ₹{amount:.2f}\n"
        f"<b>Points:</b> <code>{int(amount * settings.POINTS_PER_RUPEE)}</code>\n\n"
        f"<b>Please send a screenshot of the payment confirmation.</b>\n"
        f"<b>💳 UPI ID:</b> <code>{settings.UPI_ID}</code>\n\n"
        f"Send the screenshot as a photo or document."
    )


@Client.on_message(filters.photo & filters.private)
async def handle_payment_screenshot(client: Client, message: Message):
    """Handle payment screenshot upload"""
    user_id = message.from_user.id
    user = await database.get_user(user_id)
    
    if not user or not user.get("payment_state", {}).get("waiting_for_screenshot", False):
        return
    
    payment_state = user.get("payment_state", {})
    amount = payment_state.get("amount", 0)
    
    if amount <= 0:
        await message.reply_text("<b>❌ Invalid payment session. Please use /pay again.</b>")
        await database.update_user(user_id, {"payment_state": None})
        return
    
    status_msg = await message.reply_text("<b>📤 Processing your payment request...</b>")
    
    try:
        if message.photo:
            file_id = message.photo.file_id
        elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
            file_id = message.document.file_id
        else:
            await status_msg.edit_text("<b>❌ Please send a screenshot as a photo or image document.</b>")
            return
        
        transaction_id = f"TXN-{uuid.uuid4().hex[:8].upper()}"
        
        payment = await database.create_payment_request(
            user_id=user_id,
            amount=amount,
            upi_id=settings.UPI_ID,
            transaction_id=transaction_id,
            screenshot_file_id=file_id,
        )
        
        await database.update_user(user_id, {"payment_state": None})
        
        if settings.PAYMENT_GROUP_ID:
            try:
                admin_text = (
                    f"<blockquote><b>💳 ɴᴇᴡ ᴘᴀʏᴍᴇɴᴛ ʀᴇǫᴜᴇsᴛ</b></blockquote>\n\n"
                    f"<b>🆔 Payment ID:</b> <code>{payment['payment_id'][:8]}</code>\n"
                    f"<b>👤 User:</b> {message.from_user.first_name}\n"
                    f"<b>🆔 User ID:</b> <code>{user_id}</code>\n"
                    f"<b>💰 Amount:</b> ₹{amount:.2f}\n"
                    f"<b>⭐ Points:</b> <code>{int(amount * settings.POINTS_PER_RUPEE)}</code>\n"
                    f"<b>📝 Transaction ID:</b> <code>{transaction_id}</code>\n\n"
                    f"<b>📸 Screenshot attached below.</b>"
                )
                
                await client.send_photo(
                    chat_id=settings.PAYMENT_GROUP_ID,
                    photo=file_id,
                    caption=admin_text,
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🟢 ✅ Approve", f"approve_payment_{payment['payment_id']}"),
                            InlineKeyboardButton("🔴 ❌ Reject", f"reject_payment_{payment['payment_id']}"),
                        ],
                        [InlineKeyboardButton("🔵 🔍 View User", f"view_user_{user_id}")],
                    ])
                )
            except Exception as e:
                logger.error(f"Failed to send payment notification: {e}")
        
        await status_msg.edit_text(
            f"<blockquote><b>✅ ᴘᴀʏᴍᴇɴᴛ sᴜʙᴍɪᴛᴛᴇᴅ</b></blockquote>\n\n"
            f"<b>💰 Amount:</b> ₹{amount:.2f}\n"
            f"<b>⭐ Points:</b> <code>{int(amount * settings.POINTS_PER_RUPEE)}</code>\n"
            f"<b>📝 Transaction ID:</b> <code>{transaction_id}</code>\n\n"
            f"<b>⏳ Your payment is pending admin approval.</b>\n"
            f"You will receive a notification once approved."
        )
        
    except Exception as e:
        logger.error(f"Payment processing error: {e}")
        await status_msg.edit_text(f"<b>❌ Error processing payment: {str(e)}</b>")