import asyncio
import logging
import os
import sys
import time
import urllib.request
import json

# --- FIX NOTIMPLEMENTEDERROR FOR SUBPROCESSES ON UNIX ---
if sys.platform != "win32":
    try:
        watcher = asyncio.ThreadedChildWatcher()
        asyncio.get_event_loop_policy().set_child_watcher(watcher)
        print("Successfully set asyncio ThreadedChildWatcher for Unix.")
    except Exception as e:
        print(f"Warning: Failed to set ThreadedChildWatcher: {e}")
# --------------------------------------------------------


# --- FIX WORKING DIRECTORY AND TIME SYNC ---
# 1. Fix cwd so Pyrogram can find plugins in bot.handlers when run from parent dir
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

# 2. Telegram strictly requires the client time to be accurate.
# Since the system clock is in 2026, we monkey-patch time.time()
# using google.com's Date header which is robust against blocking.
import email.utils
try:
    req = urllib.request.Request('https://google.com', headers={'User-Agent': 'Mozilla/5.0'}, method='HEAD')
    with urllib.request.urlopen(req, timeout=5) as response:
        date_str = response.headers.get('Date')
        real_time = email.utils.parsedate_to_datetime(date_str).timestamp()
        time_offset = real_time - time.time()
        _original_time = time.time
        time.time = lambda: _original_time() + time_offset
        print(f"Monkey-patched time.time() with offset: {time_offset} seconds to fix Telegram MTProto sync.")
except Exception as e:
    print(f"Failed to fetch real time for monkey-patch: {e}")
# ------------------------------

# Force UTF-8 encoding for stdout to prevent cp1252 charmap errors with emojis
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
try:
    import uvloop
    has_uvloop = True
except ImportError:
    has_uvloop = False
from pyrogram import Client, idle
from pyrogram.raw.core import Message
from pyrogram.raw.core.tl_object import TLObject
from pyrogram.raw.core.primitives.int import Int, Long
from io import BytesIO

@staticmethod
def patched_message_read(data: BytesIO, *args) -> "Message":
    msg_id = Long.read(data)
    seq_no = Int.read(data)
    length = Int.read(data)
    body = data.read(length)
    try:
        parsed_body = TLObject.read(BytesIO(body), *args)
        return Message(parsed_body, msg_id, seq_no, length)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to parse message body (likely unknown constructor), using dummy: {e}")
        class DummyBody(TLObject):
            QUALNAME = "types.UpdateShort"
            __slots__ = []
        return Message(DummyBody(), msg_id, seq_no, length)

Message.read = patched_message_read

from pyrogram.types import Message as PyMessage, CallbackQuery as PyCallbackQuery

# --- MOCKED MESSAGE CLASS FOR ROBUST COMPATIBILITY ---
class MockedMessage:
    def __init__(self, client, chat_id, message_id):
        self._client = client
        self.chat = type('MockChat', (), {'id': chat_id})()
        self.id = message_id

    async def edit_text(self, text, reply_markup=None, **kwargs):
        client = self._client
        if client is None:
            try:
                from pyrogram import Client
                if Client._instances:
                    client = Client._instances[0]
            except Exception:
                pass
        
        if client:
            return await client.edit_message_text(
                chat_id=self.chat.id,
                message_id=self.id,
                text=text,
                reply_markup=reply_markup,
                **kwargs
            )
        else:
            import aiohttp
            from bot.config.settings import settings
            payload = {
                "chat_id": self.chat.id,
                "message_id": self.id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
            }
            if reply_markup is not None:
                if hasattr(reply_markup, "to_dict"):
                    payload["reply_markup"] = reply_markup.to_dict()
                elif isinstance(reply_markup, dict):
                    payload["reply_markup"] = reply_markup
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/editMessageText", json=payload) as resp:
                        if resp.status == 200:
                            return self
            except Exception as e:
                logging.getLogger(__name__).error(f"MockedMessage fallback edit_text failed: {e}")
            return self

    async def delete(self, *args, **kwargs):
        client = self._client
        if client is None:
            try:
                from pyrogram import Client
                if Client._instances:
                    client = Client._instances[0]
            except Exception:
                pass
        if client:
            return await client.delete_messages(
                chat_id=self.chat.id,
                message_ids=self.id
            )
        else:
            import aiohttp
            from bot.config.settings import settings
            payload = {
                "chat_id": self.chat.id,
                "message_id": self.id
            }
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/deleteMessage", json=payload)
            except Exception as e:
                logging.getLogger(__name__).error(f"MockedMessage fallback delete failed: {e}")
            return True


# --- PATCH MESSAGE & CALLBACK REPLY/EDIT FOR FALLBACK AND DEFAULT BUTTONS ---

_original_send_message = Client.send_message

async def _patched_send_message(self, chat_id, text, *args, **kwargs):
    try:
        chat_id = int(chat_id)
    except Exception:
        pass

    no_buttons = kwargs.pop("no_buttons", False)
    reply_markup = kwargs.get("reply_markup")

    if not no_buttons and reply_markup is None and isinstance(chat_id, int) and chat_id > 0:
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏡 Main Menu", callback_data="main_menu")]])
        kwargs["reply_markup"] = reply_markup

    if reply_markup is not None and hasattr(reply_markup, "to_dict") and "telegram" in type(reply_markup).__module__:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup.to_dict(),
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        return MockedMessage(self, chat_id, msg_id)
                    else:
                        err_text = await resp.text()
                        logging.getLogger(__name__).error(f"Fallback send_message failed: {resp.status} - {err_text}")
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback send_message failed with exception: {api_err}")

    try:
        return await _original_send_message(self, chat_id, text, *args, **kwargs)
    except Exception as e:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        if reply_markup is not None:
            if hasattr(reply_markup, "to_dict"):
                payload["reply_markup"] = reply_markup.to_dict()
            elif isinstance(reply_markup, dict):
                payload["reply_markup"] = reply_markup
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        return MockedMessage(self, chat_id, msg_id)
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback send_message after failure failed: {api_err}")
        raise e

Client.send_message = _patched_send_message

_original_reply_text = PyMessage.reply_text

async def _patched_reply_text(self, text, reply_markup=None, **kwargs):
    no_buttons = kwargs.pop("no_buttons", False)
    
    if not no_buttons and reply_markup is None and self.chat.id > 0:
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏡 Main Menu", callback_data="main_menu")]])

    if reply_markup is not None and hasattr(reply_markup, "to_dict") and "telegram" in type(reply_markup).__module__:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": self.chat.id,
            "text": text,
            "reply_markup": reply_markup.to_dict(),
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        client = getattr(self, "_client", None)
                        return MockedMessage(client, self.chat.id, msg_id)
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback reply_text failed: {api_err}")

    try:
        return await _original_reply_text(self, text, reply_markup=reply_markup, **kwargs)
    except Exception as e:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": self.chat.id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        if reply_markup is not None:
            if hasattr(reply_markup, "to_dict"):
                payload["reply_markup"] = reply_markup.to_dict()
            elif isinstance(reply_markup, dict):
                payload["reply_markup"] = reply_markup
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        client = getattr(self, "_client", None)
                        return MockedMessage(client, self.chat.id, msg_id)
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback reply_text after failure failed: {api_err}")
        raise e

PyMessage.reply_text = _patched_reply_text

_original_edit_text = PyMessage.edit_text

async def _patched_edit_text(self, text, reply_markup=None, **kwargs):
    no_buttons = kwargs.pop("no_buttons", False)

    if not no_buttons and reply_markup is None and self.chat.id > 0:
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏡 Main Menu", callback_data="main_menu")]])

    if reply_markup is not None and hasattr(reply_markup, "to_dict") and "telegram" in type(reply_markup).__module__:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": self.chat.id,
            "message_id": self.id,
            "text": text,
            "reply_markup": reply_markup.to_dict(),
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/editMessageText", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        client = getattr(self, "_client", None)
                        return MockedMessage(client, self.chat.id, msg_id)
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback edit_text failed: {api_err}")

    try:
        return await _original_edit_text(self, text, reply_markup=reply_markup, **kwargs)
    except Exception as e:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": self.chat.id,
            "message_id": self.id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        if reply_markup is not None:
            if hasattr(reply_markup, "to_dict"):
                payload["reply_markup"] = reply_markup.to_dict()
            elif isinstance(reply_markup, dict):
                payload["reply_markup"] = reply_markup
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/editMessageText", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id")
                        client = getattr(self, "_client", None)
                        return MockedMessage(client, self.chat.id, msg_id)
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback edit_text after failure failed: {api_err}")
        raise e

PyMessage.edit_text = _patched_edit_text

_original_edit_message_text = PyCallbackQuery.edit_message_text

async def _patched_edit_message_text(self, text, reply_markup=None, **kwargs):
    no_buttons = kwargs.pop("no_buttons", False)

    chat_id = self.message.chat.id if self.message else 0
    if not no_buttons and reply_markup is None and chat_id > 0:
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏡 Main Menu", callback_data="main_menu")]])

    if reply_markup is not None and hasattr(reply_markup, "to_dict") and "telegram" in type(reply_markup).__module__:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": self.message.chat.id,
            "message_id": self.message.id,
            "text": text,
            "reply_markup": reply_markup.to_dict(),
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/editMessageText", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id") if isinstance(data.get("result"), dict) else self.message.id
                        client = getattr(self, "_client", None)
                        return MockedMessage(client, self.message.chat.id, msg_id)
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback edit_message_text failed: {api_err}")

    try:
        return await _original_edit_message_text(self, text, reply_markup=reply_markup, **kwargs)
    except Exception as e:
        import aiohttp
        from bot.config.settings import settings
        payload = {
            "chat_id": self.message.chat.id,
            "message_id": self.message.id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": kwargs.get("disable_web_page_preview", False)
        }
        if reply_markup is not None:
            if hasattr(reply_markup, "to_dict"):
                payload["reply_markup"] = reply_markup.to_dict()
            elif isinstance(reply_markup, dict):
                payload["reply_markup"] = reply_markup
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/editMessageText", json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data.get("result", {}).get("message_id") if isinstance(data.get("result"), dict) else self.message.id
                        client = getattr(self, "_client", None)
                        return MockedMessage(client, self.message.chat.id, msg_id)
        except Exception as api_err:
            logging.getLogger(__name__).error(f"Fallback edit_message_text after failure failed: {api_err}")
        raise e

PyCallbackQuery.edit_message_text = _patched_edit_message_text


# ===== IMPORT ALL HANDLERS =====
# This ensures all handlers are registered
from bot.handlers import start, admin, deployment, variables, callback, payment, admin_points

from bot.config.settings import settings
from bot.database.db import database
from bot.workers.deployment_worker import deployment_worker
from bot.services.log_service import owner_log
from bot.services.cleanup_service import cleanup_service
from bot.services.telegram_log_handler import telegram_log_handler
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("motor").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def start_bot():
    logger.info("Starting Python Bot Cloud...")
    logger.info(f"DEBUG: API_ID={settings.API_ID}, API_HASH='{settings.API_HASH}', BOT_TOKEN='{settings.BOT_TOKEN[:10]}...'")

    await database.connect()
    logger.info("Database connected")

    app = Client(
        "python_bot_cloud",
        api_id=settings.API_ID,
        api_hash=settings.API_HASH,
        bot_token=settings.BOT_TOKEN,
        plugins={"root": "bot"},
    )

    await owner_log.set_client(app)
    telegram_log_handler.set_client(app)
    logging.getLogger().addHandler(telegram_log_handler)
    await deployment_worker.start()
    logger.info("Deployment worker started")
    await cleanup_service.start(interval=1800)
    logger.info("Cleanup service started (interval=30min)")

    await app.start()
    logger.info(f"Bot started as @{settings.BOT_USERNAME}")

    if settings.LOG_GROUP_ID:
        try:
            await app.send_message(
                settings.LOG_GROUP_ID,
                f"<b>🚀 Bot Started</b>\n\n<b>Version:</b> {settings.BOT_VERSION}\n<b>Status:</b> ✅ Running",
            )
        except Exception as e:
            logger.error(f"Failed to send startup log: {e}")

    api_task = asyncio.create_task(start_api())
    logger.info("API server task created")

    await idle()

    api_task.cancel()
    try:
        await api_task
    except asyncio.CancelledError:
        pass
    await cleanup_service.stop()
    await deployment_worker.stop()
    await app.stop()
    await database.close()
    logger.info("Bot stopped")


async def start_api():
    config = uvicorn.Config(
        "api.server:app",
        host="0.0.0.0",
        port=settings.PORT,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    if has_uvloop:
        uvloop.install()
    try:
        await start_bot()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class Colors:
    GREEN = "🟢"
    RED = "🔴"
    BLUE = "🔵"
    YELLOW = "🟡"
    PURPLE = "🟣"
    ORANGE = "🟠"
    WHITE = "⚪"
    BLACK = "⚫"


def btn(text: str, callback: str = None, url: str = None, color: str = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text, url=url)
    return InlineKeyboardButton(text, callback_data=callback)


def build_menu(buttons: list, row_width: int = 2) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(buttons), row_width):
        rows.append(buttons[i:i + row_width])
    return InlineKeyboardMarkup(rows)


# ========== START KEYBOARD ==========
def start_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [btn("🚀 Deploy Bot", "deploy_menu"), btn("🤖 My Bot", "my_bot")],
        [btn("💎 Hosting Plans", "plans"), btn("👤 Profile", "profile")],
        [btn("📊 Analytics", "analytics"), btn("🏆 Referrals", "referral")],
        [btn("📚 Help", "help"), btn("📢 Updates", "updates")],
        [btn("💳 Buy Points", "buy_points")],
    ]
    if is_admin:
        buttons.append([btn("⚙ Admin Panel", "admin_panel")])
    return InlineKeyboardMarkup(buttons)


# ========== DEPLOY KEYBOARD ==========
def deploy_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [btn("🐙 Deploy via GitHub", "deploy_github")],
        [btn("◀ Back", "main_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


# ========== MY BOT KEYBOARD ==========
def my_bot_keyboard(has_deployment: bool = False, deployment_id: str = None) -> InlineKeyboardMarkup:
    if not has_deployment:
        buttons = [
            [btn("🚀 Create Deployment", "deploy_menu")],
            [btn("◀ Back", "main_menu")],
        ]
        return InlineKeyboardMarkup(buttons)
    suffix = f"_{deployment_id}" if deployment_id else ""
    buttons = [
        [btn("🛠 Build Logs", f"live_terminal{suffix}"), btn("🚀 Deploy Logs", f"runtime_logs{suffix}")],
        [btn("📊 Runtime Stats", f"runtime_stats{suffix}"), btn("🔧 Setup Variables", f"edit_vars{suffix}")],
        [btn("🌐 Change Region", f"change_region{suffix}"), btn("🌍 Domain Manager", f"domain_manager{suffix}")],
        [btn("🟡 🔄 Restart Bot", f"restart_bot{suffix}"), btn("🟠 ⏹ Stop Bot", f"stop_bot{suffix}")],
        [btn("🔴 🗑 Delete Bot", f"delete_bot{suffix}"), btn("🔵 🌍 View URL", f"view_url{suffix}")],
        [btn("📥 Download Logs", f"download_logs{suffix}"), btn("🔄 Check Repo Update", f"redeploy{suffix}")],
        [btn("🔁 Redeploy with Vars", f"redeploy_vars{suffix}")],
        [btn("✏ Rename Dashboard", f"rename_bot{suffix}")],
        [btn("⭐ My Points", "my_points")],
        [btn("◀ Back to Bots List", "my_bot")],
    ]
    return InlineKeyboardMarkup(buttons)


# ========== VARIABLE KEYBOARD ==========
def variable_keyboard(deployment_id: str = None) -> InlineKeyboardMarkup:
    suffix = f"_{deployment_id}" if deployment_id else ""
    buttons = [
        [btn("➕ Add Variable", f"var_add{suffix}"), btn("✏ Edit Variable", f"var_edit{suffix}")],
        [btn("🗑 Delete Variable", f"var_delete{suffix}"), btn("👁 View Variables", f"var_view{suffix}")],
        [btn("📥 Import Variables", f"var_import{suffix}"), btn("📤 Export Variables", f"var_export{suffix}")],
        [btn("📄 Upload ENV File", f"var_upload_env{suffix}"), btn("📋 Paste Variables", f"var_paste{suffix}")],
        [btn("💾 Backup Variables", f"var_backup{suffix}"), btn("🔄 Restore Backup", f"var_restore{suffix}")],
        [btn("🔒 Encrypt Variables", f"var_encrypt{suffix}"), btn("🔄 Reset Variables", f"var_reset{suffix}")],
        [btn("◀ Back", f"my_bot{suffix}")],
    ]
    return InlineKeyboardMarkup(buttons)


# ========== ADMIN KEYBOARD ==========
def admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [btn("🚂 Add Railway Token", "admin_add_token"), btn("🗑 Remove Token", "admin_remove_token")],
        [btn("🎫 View Tokens & Stats", "admin_token_stats"), btn("🚫 Restrict Token", "admin_restrict_token")],
        [btn("👥 User Stats", "admin_user_stats"), btn("📢 Broadcast", "admin_broadcast")],
        [btn("🔨 Ban User", "admin_ban"), btn("🔓 Unban User", "admin_unban")],
        [btn("💳 Payment Requests", "admin_payments"), btn("➕ Add Plan", "admin_add_plan")],
        [btn("⚡ Force Redeploy", "admin_force_redeploy"), btn("📋 System Logs", "admin_system_logs")],
        [btn("💾 Database Status", "admin_db_status"), btn("🔧 Maintenance", "admin_maintenance")],
        [btn("🩺 API Health Check", "admin_api_health"), btn("🧹 Cleanup Workshops", "admin_cleanup_workshops")],
        [btn("🔍 Validate Tokens", "admin_validate_tokens")],
        [btn("⭐ Edit User Points", "admin_edit_points")],
        [btn("⏳ Pending Payments", "admin_pending_payments")],
        [btn("◀ Back", "main_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


# ========== FORCE SUB KEYBOARD ==========
def force_sub_keyboard(channels: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in channels:
        buttons.append([btn(f"📢 Join {ch.get('name', 'Channel')}", url=ch.get("invite_link", ""))])
    buttons.append([btn("✅ Check Join", "check_join")])
    buttons.append([btn("🔄 Refresh", "refresh"), btn("📞 Contact Support", "support")])
    return InlineKeyboardMarkup(buttons)


# ========== TOKEN STATS KEYBOARD ==========
def token_stats_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [btn("🔄 Refresh", "admin_token_stats")],
        [btn("◀ Back", "admin_panel")],
    ]
    return InlineKeyboardMarkup(buttons)


# ========== CONFIRMATION KEYBOARD ==========
def confirmation_keyboard(action: str) -> InlineKeyboardMarkup:
    if action.startswith("deploy_"):
        confirm_btn = btn("🟢 🚀 Deploy", f"confirm_{action}")
        cancel_btn = btn("🔴 ❌ Cancel", f"cancel_{action}")
        buttons = [
            [confirm_btn, cancel_btn],
        ]
        deploy_id = action[7:]
        buttons.append([
            btn("🌐 Select Region", f"selectregion_{deploy_id}"),
            btn("⚙ Add Variables", f"addvars_{action}")
        ])
    elif action in ("delete", "var_reset"):
        confirm_btn = btn("🔴 🗑 Delete", f"confirm_{action}")
        cancel_btn = btn("🟢 ❌ Cancel", f"cancel_{action}")
        buttons = [[confirm_btn, cancel_btn]]
    elif action == "stop":
        confirm_btn = btn("🟠 ⏹ Stop", f"confirm_{action}")
        cancel_btn = btn("🟢 ❌ Cancel", f"cancel_{action}")
        buttons = [[confirm_btn, cancel_btn]]
    elif action == "restart":
        confirm_btn = btn("🟡 🔄 Restart", f"confirm_{action}")
        cancel_btn = btn("🟢 ❌ Cancel", f"cancel_{action}")
        buttons = [[confirm_btn, cancel_btn]]
    else:
        confirm_btn = btn("🟢 ✅ Confirm", f"confirm_{action}")
        cancel_btn = btn("🔴 ❌ Cancel", f"cancel_{action}")
        buttons = [[confirm_btn, cancel_btn]]
    return InlineKeyboardMarkup(buttons)


# ========== REGION SELECTION KEYBOARD ==========
def region_selection_keyboard(deploy_id: str, is_active_bot: bool = False) -> InlineKeyboardMarkup:
    regions = [
        ("🇺🇸 US West", "us-west1"),
        ("🇺🇸 US East", "us-east-1"),
        ("🇸🇬 Singapore", "asia-southeast1"),
        ("🇳🇱 Netherlands", "europe-west4")
    ]
    buttons = []
    for label, code in regions:
        cb = f"setregion_{deploy_id}_{code}" if not is_active_bot else f"setregionactive_{code}"
        buttons.append([btn(label, cb)])
    back_cb = f"cancel_deploy_{deploy_id}" if not is_active_bot else "my_bot"
    buttons.append([btn("◀ Back", back_cb)])
    return InlineKeyboardMarkup(buttons)


# ========== DOMAIN MANAGER KEYBOARD ==========
def domain_manager_keyboard(deployment_id: str = None) -> InlineKeyboardMarkup:
    suffix = f"_{deployment_id}" if deployment_id else ""
    buttons = [
        [btn("➕ Add Railway Domain", f"dom_create_railway{suffix}"), btn("➕ Add Custom Domain", f"dom_create_custom{suffix}")],
        [btn("🗑 Delete Domain", f"dom_delete_menu{suffix}"), btn("🔄 Refresh Domains", f"domain_manager{suffix}")],
        [btn("◀ Back", f"my_bot{suffix}")]
    ]
    return InlineKeyboardMarkup(buttons)


# ========== DOMAIN DELETE KEYBOARD ==========
def domain_delete_keyboard(domains: list, deployment_id: str = None) -> InlineKeyboardMarkup:
    suffix = f"_{deployment_id}" if deployment_id else ""
    buttons = []
    for dom in domains:
        buttons.append([btn(f"🔴 🗑 {dom['domain']}", f"confirm_delete_dom_{dom['id']}{suffix}")])
    buttons.append([btn("◀ Back", f"domain_manager{suffix}")])
    return InlineKeyboardMarkup(buttons)


# ========== PAGINATION KEYBOARD ==========
def pagination_keyboard(base_callback: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    if page > 0:
        row.append(btn("◀", f"{base_callback}:{page - 1}"))
    row.append(btn(f"{page + 1}/{total_pages}", f"{base_callback}:{page}"))
    if page < total_pages - 1:
        row.append(btn("▶", f"{base_callback}:{page + 1}"))
    buttons.append(row)
    return InlineKeyboardMarkup(buttons)


# ========== SUPPORT KEYBOARD ==========
def support_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [btn("📞 Contact Support", "support_contact"), btn("❓ FAQ", "faq")],
        [btn("📢 Updates", "updates"), btn("👨‍💻 Developer", "developer")],
        [btn("◀ Back", "main_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


if __name__ == "__main__":
    asyncio.run(main())
