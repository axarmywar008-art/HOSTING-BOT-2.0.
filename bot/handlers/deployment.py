import os
import uuid
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.config.settings import settings
from bot.database.db import database
from bot.keyboards.main import deploy_keyboard, my_bot_keyboard, variable_keyboard, confirmation_keyboard
from bot.deployment.engine import deployment_engine, DEPLOY_CACHE
from bot.utils.formatters import parse_env_content, format_variables_for_display, format_uptime
from bot.utils.security import scan_zip_for_threats
from github.client import github_client

# REMOVED: from bot.workers.point_deduction_worker import point_deduction_worker


@Client.on_message(filters.command("deploy") & filters.private)
async def deploy_handler(client: Client, message: Message):
    user_id = message.from_user.id
    user = await database.get_user(user_id)
    if not user:
        await database.create_user(user_id, message.from_user.username or "", message.from_user.first_name or "")

    # Check points
    points = await database.get_points_balance(user_id)
    min_points = settings.MINIMUM_POINTS_FOR_DEPLOYMENT
    
    if points < min_points:
        await message.reply_text(
            f"<b>❌ Insufficient Points!</b>\n\n"
            f"You need <b>{min_points}</b> points to deploy a bot.\n"
            f"Your current balance: <b>{points}</b> points.\n\n"
            f"Each bot costs <b>{settings.DAILY_POINT_COST}</b> points per day to maintain.\n"
            f"Please contact an admin to add more points to your account."
        )
        return

    existing = await database.get_user_deployment(user_id)
    if existing:
        await message.reply_text(
            "<b>⚠ You already have an active deployment!</b>\n\n"
            "<b>You can only have one deployment at a time.</b>\n"
            "<b>Please stop or delete your current bot first.</b>",
            reply_markup=my_bot_keyboard(True),
        )
        return

    await message.reply_text(
        "<blockquote><b>🚀 ᴅᴇᴘʟᴏʏ ᴍᴇɴᴜ</b></blockquote>\n\n"
        f"<b>⭐ Points Required:</b> {min_points} (You have {points})\n"
        f"<b>📉 Daily Cost:</b> {settings.DAILY_POINT_COST} points/day\n\n"
        "<b>ᴄʜᴏᴏsᴇ ʏᴏᴜʀ ᴅᴇᴘʟᴏʏᴍᴇɴᴛ ᴍᴇᴛʜᴏᴅ:</b>\n\n"
        "<b>🐙 ɢɪᴛʜᴜʙ</b> — ᴅᴇᴘʟᴏʏ ғʀᴏᴍ ᴘᴜʙʟɪᴄ ʀᴇᴘᴏsɪᴛᴏʀʏ\n"
        "<b>📦 ᴢɪᴘ</b> — ᴜᴘʟᴏᴀᴅ ᴢɪᴘ ғɪʟᴇ\n\n"
        "<b>ᴏɴʟʏ ᴘʏᴛʜᴏɴ ᴛᴇʟᴇɢʀᴀᴍ ʙᴏᴛs ᴀʀᴇ sᴜᴘᴘᴏʀᴛᴇᴅ.</b>",
        reply_markup=deploy_keyboard(),
    )


@Client.on_message(filters.text & filters.private & filters.regex(r"^https?://(www\.)?github\.com/"))
async def handle_github_url(client: Client, message: Message):
    import asyncio
    user_id = message.from_user.id
    user = await database.get_user(user_id)
    if not user:
        return

    # Check points
    points = await database.get_points_balance(user_id)
    if points < settings.MINIMUM_POINTS_FOR_DEPLOYMENT:
        await message.reply_text(
            f"<b>❌ Insufficient Points!</b>\n\n"
            f"You need <b>{settings.MINIMUM_POINTS_FOR_DEPLOYMENT}</b> points to deploy.\n"
            f"Your current balance: <b>{points}</b> points."
        )
        return

    url = message.text.strip()
    existing_pending = [did for did, d in DEPLOY_CACHE.items() if d.get("user_id") == user_id]
    if existing_pending:
        await message.reply_text(
            "<b>⚠ You already have a pending deployment!</b>\n\n"
            "Please confirm or cancel the existing one before starting a new one.",
            reply_markup=confirmation_keyboard(f"deploy_{existing_pending[0]}")
        )
        return

    status_msg = await message.reply_text("<b>🔍 Scanning repository...</b>")

    parsed = github_client.parse_github_url(url)
    if not parsed:
        await status_msg.edit_text("<b>❌ Invalid GitHub URL</b>")
        return

    try:
        scan = await asyncio.wait_for(
            github_client.scan_repository(parsed["owner"], parsed["repo"], parsed["branch"]),
            timeout=90,
        )
    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "<b>❌ Scanning timed out!</b>\n\n"
            "The repository may be too large or GitHub is slow right now.\n"
            "Please try again in a moment."
        )
        return
    except Exception as e:
        await status_msg.edit_text(f"<b>❌ Scan error: {str(e)}</b>")
        return

    if not scan.get("success"):
        await status_msg.edit_text(f"<b>❌ {scan.get('error', 'Scan failed')}</b>")
        return

    branch_display = parsed['branch'] or scan.get('branch', 'main')
    preview_text = (
        f"<blockquote><b>📦 ʀᴇᴘᴏsɪᴛᴏʀʏ sᴄᴀɴ ʀᴇsᴜʟᴛ</b></blockquote>\n\n"
        f"<b>🐙 Repo:</b> {parsed['owner']}/{parsed['repo']}\n"
        f"<b>🌿 Branch:</b> {branch_display}\n"
        f"<b>⚙ Framework:</b> {scan['framework']}\n"
        f"<b>🚀 Startup:</b> {scan['startup_file']}\n"
        f"<b>📄 requirements.txt:</b> {'✅' if scan['has_requirements'] else '❌'}\n"
        f"<b>🐳 Dockerfile:</b> {'✅' if scan['has_dockerfile'] else '❌'}\n"
        f"<b>⭐ Points Cost:</b> {settings.MINIMUM_POINTS_FOR_DEPLOYMENT} (you have {points})\n\n"
        f"<b>Click below to start deployment. To add Environment Variables, simply send <code>KEY=VALUE</code> in the chat before clicking Deploy.</b>"
    )

    deploy_id = str(uuid.uuid4())[:8]
    DEPLOY_CACHE[deploy_id] = {
        "user_id": message.from_user.id,
        "type": "github",
        "url": url,
        "owner": parsed["owner"],
        "repo": parsed["repo"],
        "branch": parsed["branch"] or scan.get("branch", "main"),
        "scan_result": scan,
        "variables": {}
    }

    await status_msg.edit_text(
        preview_text,
        reply_markup=confirmation_keyboard(f"deploy_{deploy_id}"),
    )


@Client.on_message(filters.document & filters.private)
async def handle_zip_upload(client: Client, message: Message):
    user_id = message.from_user.id
    user = await database.get_user(user_id)
    if not user:
        return

    # Check points
    points = await database.get_points_balance(user_id)
    if points < settings.MINIMUM_POINTS_FOR_DEPLOYMENT:
        await message.reply_text(
            f"<b>❌ Insufficient Points!</b>\n\n"
            f"You need <b>{settings.MINIMUM_POINTS_FOR_DEPLOYMENT}</b> points to deploy.\n"
            f"Your current balance: <b>{points}</b> points."
        )
        return

    existing_pending = [did for did, d in DEPLOY_CACHE.items() if d.get("user_id") == user_id]
    if existing_pending:
        await message.reply_text(
            "<b>⚠ You already have a pending deployment!</b>\n\n"
            "Please confirm or cancel the existing one before uploading a new ZIP.",
            reply_markup=confirmation_keyboard(f"deploy_{existing_pending[0]}")
        )
        return

    doc = message.document
    if not doc.file_name.lower().endswith(".zip"):
        await message.reply_text("<b>❌ Only ZIP files are supported</b>")
        return

    if doc.file_size > settings.MAX_ZIP_SIZE:
        await message.reply_text(f"<b>❌ File too large. Max: {settings.MAX_ZIP_SIZE // 1024 // 1024}MB</b>")
        return

    status_msg = await message.reply_text("<b>📥 Downloading ZIP file...</b>")

    file_path = os.path.join(settings.TEMP_DIR, f"{uuid.uuid4()}.zip")
    try:
        await message.download(file_path)
        with open(file_path, "rb") as f:
            zip_data = f.read()

        threats = scan_zip_for_threats(file_path)
        if threats:
            await status_msg.edit_text(
                f"<b>❌ Security threats detected!</b>\n\n" + "\n".join(f"• {t}" for t in threats[:5])
            )
            return

        import zipfile
        import io

        files = []
        contents = {}
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                files.append(info.filename)
                try:
                    contents[info.filename] = zf.read(info).decode("utf-8", errors="ignore")
                except Exception:
                    contents[info.filename] = ""

        from bot.utils.formatters import is_python_project, detect_framework, detect_startup_file

        if not is_python_project(files):
            await status_msg.edit_text("<b>❌ ZIP must contain a Python Telegram bot project</b>")
            return

        framework = detect_framework(list(contents.values()))
        startup_file = detect_startup_file(files)

        preview_text = (
            f"<blockquote><b>📦 ᴢɪᴘ sᴄᴀɴ ʀᴇsᴜʟᴛ</b></blockquote>\n\n"
            f"<b>📄 File:</b> {doc.file_name}\n"
            f"<b>📏 Size:</b> {doc.file_size / 1024:.1f} KB\n"
            f"<b>⚙ Framework:</b> {framework}\n"
            f"<b>🚀 Startup:</b> {startup_file}\n"
            f"<b>📄 requirements.txt:</b> {'✅' if 'requirements.txt' in files else '❌'}\n"
            f"<b>⭐ Points Cost:</b> {settings.MINIMUM_POINTS_FOR_DEPLOYMENT} (you have {points})\n\n"
            f"<b>Click below to start deployment. To add Environment Variables, simply send <code>KEY=VALUE</code> in the chat before clicking Deploy.</b>"
        )

        deploy_id = str(uuid.uuid4())[:8]
        DEPLOY_CACHE[deploy_id] = {
            "user_id": message.from_user.id,
            "type": "zip",
            "zip_data": zip_data,
            "filename": doc.file_name,
            "variables": {}
        }

        await status_msg.edit_text(
            preview_text,
            reply_markup=confirmation_keyboard(f"deploy_{deploy_id}"),
        )

    except Exception as e:
        await status_msg.edit_text(f"<b>❌ Error: {str(e)}</b>")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


async def rename_state_filter(_, __, message: Message):
    if not message.from_user:
        return False
    user_id = message.from_user.id
    user = await database.get_user(user_id)
    state = user.get("current_state") if user else None
    return bool(state and state.startswith("rename_bot_"))

rename_state_filter = filters.create(rename_state_filter)


@Client.on_message(filters.text & filters.private & rename_state_filter)
async def handle_rename_state(client: Client, message: Message):
    user_id = message.from_user.id
    user = await database.get_user(user_id)
    state = user.get("current_state")
    deployment_id = state[11:]
    new_name = message.text.strip()
    
    if not new_name:
        await message.reply_text("<b>❌ Name cannot be empty. Please send a valid name:</b>")
        return
    if len(new_name) > 30:
        await message.reply_text("<b>❌ Name is too long. Max 30 characters. Please try again:</b>")
        return
        
    dep = await database.get_deployment(deployment_id)
    if not dep:
        await message.reply_text("<b>❌ Bot deployment not found.</b>")
        await database.update_user(user_id, {"current_state": None})
        return
        
    await database.update_deployment(deployment_id, {"dashboard_name": new_name})
    await database.update_user(user_id, {"current_state": None})
    
    await message.reply_text(
        f"<b>✅ Dashboard name updated to:</b> <code>{new_name}</code>",
        reply_markup=my_bot_keyboard(True, deployment_id)
    )
