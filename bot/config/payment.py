import asyncio
import logging
import time
import uuid
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
    
    current_points = user.get("points", 0)
    
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
            [InlineKeyboardButton("🟢 ✅ Approve", "support_contact")],
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


@Client.on_callback_query(filters.regex(r"^approve_payment_"))
async def approve_payment_callback(client: Client, query: CallbackQuery):
    """Admin approves a payment"""
    admin_id = query.from_user.id
    if admin_id not in settings.OWNER_IDS:
        await query.answer("❌ Unauthorized", show_alert=True)
        return
    
    payment_id = query.data[16:]
    payment = await database.get_payment_request(payment_id)
    if not payment:
        await query.answer("❌ Payment not found", show_alert=True)
        return
    
    if payment.get("status") != "pending":
        await query.answer(f"❌ Payment already {payment.get('status')}", show_alert=True)
        return
    
    success = await database.approve_payment(payment_id, admin_id)
    
    if success:
        user_id = payment["user_id"]
        points = payment.get("points", 0)
        
        try:
            await client.send_message(
                user_id,
                f"<blockquote><b>✅ ᴘᴀʏᴍᴇɴᴛ ᴀᴘᴘʀᴏᴠᴇᴅ</b></blockquote>\n\n"
                f"<b>💰 Amount:</b> ₹{payment['amount']:.2f}\n"
                f"<b>⭐ Points Added:</b> <code>{points}</code>\n"
                f"<b>📝 Transaction ID:</b> <code>{payment['transaction_id']}</code>\n\n"
                f"<b>You can now use your points to host your bot!</b>"
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await query.answer("✅ Payment approved! Points added.", show_alert=True)
        
        try:
            await query.message.edit_caption(
                query.message.caption + f"\n\n<b>✅ Approved by:</b> {query.from_user.first_name}\n<b>Status:</b> ✅ APPROVED",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🟢 ✅ Approved", "approved_final")]
                ])
            )
        except Exception:
            pass
    else:
        await query.answer("❌ Failed to approve", show_alert=True)


@Client.on_callback_query(filters.regex(r"^reject_payment_"))
async def reject_payment_callback(client: Client, query: CallbackQuery):
    """Admin rejects a payment"""
    admin_id = query.from_user.id
    if admin_id not in settings.OWNER_IDS:
        await query.answer("❌ Unauthorized", show_alert=True)
        return
    
    payment_id = query.data[16:]
    payment = await database.get_payment_request(payment_id)
    if not payment:
        await query.answer("❌ Payment not found", show_alert=True)
        return
    
    if payment.get("status") != "pending":
        await query.answer(f"❌ Payment already {payment.get('status')}", show_alert=True)
        return
    
    await query.message.reply_text(
        f"<b>❌ Reject Payment</b>\n\n"
        f"<b>Payment ID:</b> <code>{payment_id[:8]}</code>\n\n"
        f"Please send the reason for rejection.\n"
        f"Usage: <code>/reject_reason {payment_id[:8]} REASON</code>"
    )
    await query.answer("📝 Please provide rejection reason", show_alert=True)


@Client.on_message(filters.command("reject_reason") & filters.private & filters.user(settings.OWNER_IDS))
async def reject_reason_handler(client: Client, message: Message):
    """Handle rejection with reason"""
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.reply_text("<b>Usage:</b> <code>/reject_reason PAYMENT_ID REASON</code>")
        return
    
    payment_id_prefix = parts[1]
    reason = parts[2]
    
    payments = await database.get_pending_payments(limit=100)
    payment = None
    for p in payments:
        if p["payment_id"].startswith(payment_id_prefix):
            payment = p
            break
    
    if not payment:
        await message.reply_text("<b>❌ Payment not found</b>")
        return
    
    success = await database.reject_payment(payment["payment_id"], message.from_user.id, reason)
    
    if success:
        user_id = payment["user_id"]
        
        try:
            await client.send_message(
                user_id,
                f"<blockquote><b>❌ ᴘᴀʏᴍᴇɴᴛ ʀᴇᴊᴇᴄᴛᴇᴅ</b></blockquote>\n\n"
                f"<b>💰 Amount:</b> ₹{payment['amount']:.2f}\n"
                f"<b>📝 Transaction ID:</b> <code>{payment['transaction_id']}</code>\n\n"
                f"<b>Reason:</b> {reason}\n\n"
                f"<b>Please try again with the correct payment details.</b>"
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        
        await message.reply_text(f"<b>✅ Payment rejected</b>\n\n<b>User notified.</b>")
    else:
        await message.reply_text("<b>❌ Failed to reject payment</b>")