import asyncio
import logging
import time
import uuid
from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config.settings import settings
from bot.database.db import database
from bot.deployment.engine import deployment_engine
from bot.keyboards.main import (
    start_keyboard, deploy_keyboard, my_bot_keyboard, variable_keyboard,
    admin_keyboard, confirmation_keyboard, force_sub_keyboard,
    support_keyboard, token_stats_keyboard, region_selection_keyboard,
    domain_manager_keyboard, domain_delete_keyboard,
)
from bot.config.constants import START_CAPTION, HELP_TEXT, PLANS_TEXT, ANALYTICS_TEMPLATE
from bot.utils.formatters import format_uptime, format_variables_for_display
from railway.token_manager import token_manager
from railway.client import RailwayClient
from github.client import github_client

logger = logging.getLogger(__name__)

ACTIVE_REFRESHES = {}


async def get_deployment_from_callback(query, user_id: int):
    data = query.data
    if len(data) >= 36:
        potential_uuid = data[-36:]
        if potential_uuid.count("-") == 4:
            dep = await database.get_deployment(potential_uuid)
            if dep:
                return dep
    return await database.get_user_deployment(user_id)


# ============================================================
# AUTO REFRESH LOGS
# ============================================================
async def start_auto_refresh(client, chat_id, message_id, deployment_id, log_type):
    key = (chat_id, message_id)
    if key in ACTIVE_REFRESHES:
        try:
            ACTIVE_REFRESHES[key].cancel()
        except Exception:
            pass

    async def refresh_loop():
        try:
            for _ in range(15):
                await asyncio.sleep(4)
                try:
                    msg = await client.get_messages(chat_id, message_id)
                    if not msg or not msg.text:
                        break
                    expected_kw = "ʙᴜɪʟᴅ ʟᴏɢs" if log_type == "build" else "ᴅᴇᴘʟᴏʏ ʟᴏɢs"
                    expected_kw_old = "ʟɪᴠᴇ ʙᴜɪʟᴅ ᴛᴇʀᴍɪɴᴀʟ" if log_type == "build" else "ᴀᴘᴘʟɪᴄᴀᴛɪᴏɴ ʀᴜɴᴛɪᴍᴇ ʟᴏɢs"
                    if expected_kw not in msg.text and expected_kw_old not in msg.text:
                        break
                except Exception:
                    break

                if log_type == "build":
                    logs = await deployment_engine.get_build_logs(deployment_id, limit=50)
                    full_text = (
                        f"🛠 <b>ʙᴜɪʟᴅ ʟᴏɢs</b> (ID: <code>{deployment_id[:8]}</code>)\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"<code>{logs}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🔄 <i>Auto-refreshing dynamically...</i>"
                    )
                else:
                    logs = await deployment_engine.get_runtime_logs(deployment_id, limit=50)
                    full_text = (
                        f"🚀 <b>ᴅᴇᴘʟᴏʏ ʟᴏɢs</b> (ID: <code>{deployment_id[:8]}</code>)\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"<code>{logs}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🔄 <i>Auto-refreshing dynamically...</i>"
                    )

                if len(full_text) > 4000:
                    full_text = full_text[-4000:]

                try:
                    await client.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=full_text,
                        reply_markup=my_bot_keyboard(True, deployment_id)
                    )
                except Exception as e:
                    if "MESSAGE_NOT_MODIFIED" in str(e) or "not modified" in str(e).lower():
                        continue
                    break
        except asyncio.CancelledError:
            pass
        finally:
            ACTIVE_REFRESHES.pop(key, None)

    task = asyncio.create_task(refresh_loop())
    ACTIVE_REFRESHES[key] = task


# ============================================================
# EXISTING CALLBACK HANDLERS (KEEP YOUR EXISTING CODE HERE)
# ============================================================
# ... Your existing callback handlers like cb_main_menu, cb_deploy_menu, etc.
# ... Keep all your existing code between here and the new handlers


# ============================================================
# NEW: POINTS SYSTEM CALLBACK HANDLERS
# ============================================================

async def cb_buy_points(client: Client, query: CallbackQuery):
    """Show buy points menu from callback"""
    user_id = query.from_user.id
    user = await database.get_user(user_id)
    if not user:
        await database.create_user(user_id, query.from_user.username or "", query.from_user.first_name or "")
    
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
    
    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 ✅ Support", "support_contact")],
            [InlineKeyboardButton("🔵 🏡 Main Menu", "main_menu")],
        ])
    )
    await query.answer()


async def cb_my_points(client: Client, query: CallbackQuery):
    """Show user's points"""
    user_id = query.from_user.id
    user = await database.get_user(user_id)
    points = user.get("points", 0) if user else 0
    payments = await database.get_user_payments(user_id, limit=5)
    
    text = (
        f"<blockquote><b>⭐ ʏᴏᴜʀ ᴘᴏɪɴᴛs</b></blockquote>\n\n"
        f"<b>⭐ Current Points:</b> <code>{points}</code>\n"
        f"<b>⚡ Points Required:</b> <code>{settings.HOST_COST_POINTS}</code> per deployment\n\n"
    )
    
    if payments:
        text += "<b>💳 Recent Payments:</b>\n"
        for p in payments[:3]:
            status_emoji = "✅" if p["status"] == "approved" else "⏳" if p["status"] == "pending" else "❌"
            text += f"  {status_emoji} ₹{p['amount']:.2f} → {p.get('points', 0)} pts ({p['status']})\n"
    else:
        text += "<b>No payment history.</b>\n"
    
    text += f"\n<b>💳 Buy more points:</b> /buy_points"
    
    # Extract deployment_id from callback data
    parts = query.data.split("_")
    dep_id = parts[1] if len(parts) > 1 else ""
    
    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 💳 Buy Points", "buy_points")],
            [InlineKeyboardButton("🔵 ◀ Back", f"my_bot_{dep_id}" if dep_id else "my_bot")],
        ])
    )
    await query.answer()


async def cb_admin_edit_points(client: Client, query: CallbackQuery):
    """Show edit points instructions"""
    if query.from_user.id not in settings.OWNER_IDS:
        await query.answer("❌ Unauthorized", show_alert=True)
        return
    
    await query.message.edit_text(
        "<blockquote><b>⭐ ᴇᴅɪᴛ ᴜsᴇʀ ᴘᴏɪɴᴛs</b></blockquote>\n\n"
        "<b>Use the command to edit any user's points:</b>\n\n"
        "<code>/edit_points USER_ID NEW_POINTS</code>\n\n"
        "<b>Examples:</b>\n"
        "<code>/edit_points 123456789 100</code> - Set points to 100\n"
        "<code>/edit_points 123456789 0</code> - Reset points to 0\n\n"
        "<b>To view user details:</b>\n"
        "<code>/view_user USER_ID</code>",
        reply_markup=admin_keyboard(),
    )
    await query.answer()


async def cb_admin_pending_payments(client: Client, query: CallbackQuery):
    """Show pending payments"""
    if query.from_user.id not in settings.OWNER_IDS:
        await query.answer("❌ Unauthorized", show_alert=True)
        return
    
    payments = await database.get_pending_payments(limit=20)
    if not payments:
        await query.message.edit_text(
            "<b>✅ No pending payments</b>",
            reply_markup=admin_keyboard(),
        )
        await query.answer()
        return
    
    text = f"<blockquote><b>⏳ ᴘᴇɴᴅɪɴɢ ᴘᴀʏᴍᴇɴᴛs ({len(payments)})</b></blockquote>\n\n"
    for p in payments[:10]:
        user = await database.get_user(p["user_id"])
        name = user.get("full_name", "Unknown") if user else "Unknown"
        text += f"<b>👤 {name}</b> (<code>{p['user_id']}</code>)\n"
        text += f"💰 ₹{p['amount']:.2f} → {p.get('points', 0)} pts\n"
        text += f"🆔 <code>{p['payment_id'][:8]}</code> | 📝 {p['transaction_id']}\n─────────────────\n"
    
    text += f"\n<b>Check the payment group for screenshots.</b>"
    
    await query.message.edit_text(text, reply_markup=admin_keyboard())
    await query.answer()


async def cb_approve_payment_callback(client: Client, query: CallbackQuery):
    """Admin approves a payment"""
    admin_id = query.from_user.id
    if admin_id not in settings.OWNER_IDS:
        await query.answer("❌ Unauthorized", show_alert=True)
        return
    
    payment_id = query.data[16:]  # remove "approve_payment_"
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


async def cb_reject_payment_callback(client: Client, query: CallbackQuery):
    """Admin rejects a payment"""
    admin_id = query.from_user.id
    if admin_id not in settings.OWNER_IDS:
        await query.answer("❌ Unauthorized", show_alert=True)
        return
    
    payment_id = query.data[16:]  # remove "reject_payment_"
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


# ============================================================
# REGISTER ALL CALLBACK HANDLERS IN THE DICTIONARY
# ============================================================
# Add these to your existing handlers dictionary in the callback_handler function:

# "buy_points": cb_buy_points,
# "my_points": cb_my_points,
# "admin_edit_points": cb_admin_edit_points,
# "admin_pending_payments": cb_admin_pending_payments,
# "approve_payment_": cb_approve_payment_callback,  # For dynamic callback
# "reject_payment_": cb_reject_payment_callback,    # For dynamic callback
