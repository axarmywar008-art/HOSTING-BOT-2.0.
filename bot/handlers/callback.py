import datetime
import time
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup
from bot.config.settings import settings
from bot.config.constants import START_CAPTION, HELP_TEXT, PLANS_TEXT, ANALYTICS_TEMPLATE
from bot.database.db import database
from bot.keyboards.main import (
    start_keyboard, deploy_keyboard, my_bot_keyboard, variable_keyboard,
    admin_keyboard, confirmation_keyboard, force_sub_keyboard,
    support_keyboard, token_stats_keyboard, region_selection_keyboard,
    domain_manager_keyboard, domain_delete_keyboard, btn
)
from bot.deployment.engine import deployment_engine
from bot.utils.formatters import format_uptime, format_variables_for_display
from railway.token_manager import token_manager
from railway.client import RailwayClient
from github.client import github_client
from bot.workers.point_deduction_worker import point_deduction_worker

logger = logging.getLogger(__name__)


@Client.on_callback_query()
async def points_callback_handler(client: Client, query: CallbackQuery):
    """Handle points-related callback queries."""
    user_id = query.from_user.id
    data = query.data
    
    if data == "points":
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
        
        await query.message.edit_text(text, reply_markup=start_keyboard(user_id in settings.OWNER_IDS))
        await query.answer()
    
    elif data == "admin_add_points":
        if user_id not in settings.OWNER_IDS:
            await query.answer("Unauthorized", show_alert=True)
            return
        await query.message.edit_text(
            "<b>⭐ Add Points</b>\n\n"
            "<b>Usage:</b> <code>/addpoints USER_ID AMOUNT [REASON]</code>\n\n"
            "<b>Example:</b> <code>/addpoints 123456789 100 Welcome bonus</code>",
            reply_markup=admin_keyboard()
        )
        await query.answer()
    
    elif data == "admin_deduct_points":
        if user_id not in settings.OWNER_IDS:
            await query.answer("Unauthorized", show_alert=True)
            return
        await query.message.edit_text(
            "<b>⭐ Deduct Points</b>\n\n"
            "<b>Usage:</b> <code>/deductpoints USER_ID AMOUNT [REASON]</code>\n\n"
            "<b>Example:</b> <code>/deductpoints 123456789 10 Penalty</code>",
            reply_markup=admin_keyboard()
        )
        await query.answer()
    
    elif data == "admin_points_users":
        if user_id not in settings.OWNER_IDS:
            await query.answer("Unauthorized", show_alert=True)
            return
        users = await database.get_all_users_with_points()
        if not users:
            await query.message.edit_text("<b>No users found</b>", reply_markup=admin_keyboard())
            await query.answer()
            return
        
        text = "<blockquote><b>⭐ ᴜsᴇʀs ᴘᴏɪɴᴛs ʙᴀʟᴀɴᴄᴇ</b></blockquote>\n\n"
        sorted_users = sorted(users, key=lambda x: x.get("points", 0), reverse=True)
        
        for i, user in enumerate(sorted_users[:50]):
            uid = user.get("user_id")
            username = user.get("username", "Unknown")
            points = user.get("points", 0)
            text += f"<b>{i+1}.</b> <code>{uid}</code> ({username}) — <b>{points}</b> pts\n"
        
        if len(sorted_users) > 50:
            text += f"\n...and {len(sorted_users) - 50} more users"
        
        await query.message.edit_text(text, reply_markup=admin_keyboard())
        await query.answer()
    
    elif data == "admin_set_points":
        if user_id not in settings.OWNER_IDS:
            await query.answer("Unauthorized", show_alert=True)
            return
        await query.message.edit_text(
            "<b>⭐ Set Points</b>\n\n"
            "<b>Usage:</b> <code>/setpoints USER_ID AMOUNT</code>\n\n"
            f"<b>Example:</b> <code>/setpoints 123456789 100</code>",
            reply_markup=admin_keyboard()
        )
        await query.answer()
    
    elif data == "admin_set_daily_cost":
        if user_id not in settings.OWNER_IDS:
            await query.answer("Unauthorized", show_alert=True)
            return
        await query.message.edit_text(
            f"<b>📉 Set Daily Point Cost</b>\n\n"
            f"<b>Current daily cost:</b> {settings.DAILY_POINT_COST} pts/day\n\n"
            "<b>Usage:</b> <code>/setdailycost AMOUNT</code>\n\n"
            "<b>Example:</b> <code>/setdailycost 3</code>",
            reply_markup=admin_keyboard()
        )
        await query.answer()
    
    elif data == "admin_set_min_points":
        if user_id not in settings.OWNER_IDS:
            await query.answer("Unauthorized", show_alert=True)
            return
        await query.message.edit_text(
            f"<b>📌 Set Minimum Points for Deployment</b>\n\n"
            f"<b>Current minimum:</b> {settings.MINIMUM_POINTS_FOR_DEPLOYMENT} pts\n\n"
            "<b>Usage:</b> <code>/setminpoints AMOUNT</code>\n\n"
            "<b>Example:</b> <code>/setminpoints 80</code>",
            reply_markup=admin_keyboard()
        )
        await query.answer()