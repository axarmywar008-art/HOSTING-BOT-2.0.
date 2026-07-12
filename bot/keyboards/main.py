from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class Styles:
    PRIMARY = "primary"
    SUCCESS = "success"
    DANGER = "danger"
    WARNING = "warning"
    SECONDARY = "secondary"


def btn(text: str, callback: str = None, url: str = None, style: str = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text, url=url)
    return InlineKeyboardButton(text, callback_data=callback)


def build_menu(buttons: list, row_width: int = 2) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(buttons), row_width):
        rows.append(buttons[i:i + row_width])
    return InlineKeyboardMarkup(rows)


def start_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [btn("🚀 Deploy Bot", "deploy_menu"), btn("🤖 My Bot", "my_bot")],
        [btn("💎 Hosting Plans", "plans"), btn("👤 Profile", "profile")],
        [btn("📊 Analytics", "analytics"), btn("🏆 Referrals", "referral")],
        [btn("📚 Help", "help"), btn("📢 Updates", "updates")],
        [btn("⭐ Points Balance", "points")],
    ]
    if is_admin:
        buttons.append([btn("⚙ Admin Panel", "admin_panel")])
    return InlineKeyboardMarkup(buttons)


# ... (rest of the existing keyboard functions remain unchanged)


def admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [btn("🚂 Add Railway Token", "admin_add_token"), btn("🗑 Remove Token", "admin_remove_token")],
        [btn("🎫 View Tokens & Stats", "admin_token_stats"), btn("🚫 Restrict Token", "admin_restrict_token")],
        [btn("⭐ Add Points", "admin_add_points"), btn("⭐ Deduct Points", "admin_deduct_points")],
        [btn("📊 Points Users", "admin_points_users"), btn("⭐ Set Points", "admin_set_points")],
        [btn("📉 Set Daily Cost", "admin_set_daily_cost"), btn("📌 Set Min Points", "admin_set_min_points")],
        [btn("👥 User Stats", "admin_user_stats"), btn("📢 Broadcast", "admin_broadcast")],
        [btn("🔨 Ban User", "admin_ban"), btn("🔓 Unban User", "admin_unban")],
        [btn("💳 Payment Requests", "admin_payments"), btn("➕ Add Plan", "admin_add_plan")],
        [btn("⚡ Force Redeploy", "admin_force_redeploy"), btn("📋 System Logs", "admin_system_logs")],
        [btn("💾 Database Status", "admin_db_status"), btn("🔧 Maintenance", "admin_maintenance")],
        [btn("🩺 API Health Check", "admin_api_health"), btn("🧹 Cleanup Workshops", "admin_cleanup_workshops")],
        [btn("🔍 Validate Tokens", "admin_validate_tokens")],
        [btn("◀ Back", "main_menu")],
    ]
    return InlineKeyboardMarkup(buttons)