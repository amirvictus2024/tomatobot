import os
import logging
import random
import json
import requests
import warnings
from collections import deque

# سرکوب هشدار مربوط به CallbackQueryHandler
warnings.filterwarnings("ignore", message="If 'per_message=False', 'CallbackQueryHandler' will not be tracked for every message.")
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    Filters,
    CallbackContext,
)
from db_manager import DBManager
from wg import WireguardConfig
from backup_manager import BackupManager
from ip_processor import IPProcessor

# --- وضعیت سیستم ---
LOCATIONS_ENABLED = True  # وضعیت فعال/غیرفعال بودن لوکیشن‌ها
import threading

# اضافه کردن قابلیت بکاپ‌گیری خودکار
backup_mgr = BackupManager(backup_interval=3600*6, max_backups=10)  # هر 6 ساعت با نگهداری 10 بکاپ
ip_processor = IPProcessor()  # پردازش کننده آی‌پی‌ها

# دکمه‌های غیرفعال
DISABLED_BUTTONS = {
    'generate_ipv6': False,  # دکمه‌ی تولید IPv6
    'get_ipv4': False,  # دکمه‌ی لیست IPv4
    'validate_ipv4': False,  # دکمه‌ی اعتبارسنجی IPv4
    'wireguard': False,  # دکمه‌ی وایرگارد اختصاصی
    'support': False,  # دکمه‌ی پشتیبانی
    'user_account': False,  # دکمه‌ی حساب کاربری
}

# مسیر فایل تنظیمات دکمه‌های غیرفعال
DISABLED_BUTTONS_FILE = "disabled_buttons.json"


# بارگذاری تنظیمات دکمه‌های غیرفعال از فایل
def load_disabled_buttons():
    global DISABLED_BUTTONS
    try:
        if os.path.exists(DISABLED_BUTTONS_FILE):
            with open(DISABLED_BUTTONS_FILE, 'r') as f:
                DISABLED_BUTTONS = json.load(f)
    except Exception as e:
        logging.error(f"خطا در بارگذاری تنظیمات دکمه‌های غیرفعال: {e}")


# ذخیره تنظیمات دکمه‌های غیرفعال در فایل
def save_disabled_buttons():
    try:
        with open(DISABLED_BUTTONS_FILE, 'w') as f:
            json.dump(DISABLED_BUTTONS, f)
    except Exception as e:
        logging.error(f"خطا در ذخیره تنظیمات دکمه‌های غیرفعال: {e}")


# بارگذاری تنظیمات در شروع برنامه
load_disabled_buttons()

# --- CONFIGURATION ---
ADMIN_ID = int(os.getenv("ADMIN_ID", "7240662021"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "8093306771:AAFc2Cp6MrHxPvgj8GPuJcikC0Sqh6LOG9s")

# Conversation states
ENTER_ACTIVATION, ENTER_NEW_CODE, ENTER_NEW_IPV4, ENTER_COUNTRY_NAME, ENTER_COUNTRY_FLAG, CHOOSE_CODE_TYPE, ENTER_TOKEN_COUNT, ENTER_IP_FOR_VALIDATION, ENTER_BROADCAST_MESSAGE, ENTER_CHANNEL_LINK, ENTER_BATCH_IPS, ENTER_BATCH_ENDPOINTS = range(
    12)

# متغیرهای مورد نیاز برای قابلیت‌های جدید
PENDING_IPS = {}  # ذخیره‌سازی درخواست‌های IP منتظر تایید ادمین
REQUIRED_CHANNEL = ""  # لینک کانال اجباری برای عضویت

# API URL for IP validation
IP_VALIDATION_API = "https://api.iplocation.net/?ip="

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

db = DBManager()


def send_reply(update: Update, text: str, **kwargs):
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.message.reply_text(text, **kwargs)
    elif update.message:
        update.message.reply_text(text, **kwargs)


def cb_user_account(update: Update, context: CallbackContext) -> None:
    """Handle user account button callback."""
    user_id = update.effective_user.id
    membership_date = db.active_users[user_id].get('joined_date', 'نامشخص')
    ips_received = len(db.get_ips_by_country(user_id))
    buttons = [[
        InlineKeyboardButton(f"🆔 آیدی: {user_id} 📋",
                             callback_data=f'copy_{user_id}')
    ],
               [
                   InlineKeyboardButton(f"📅 تاریخ عضویت: {membership_date}",
                                        callback_data='noop')
               ],
               [
                   InlineKeyboardButton(f"📨 تعداد آدرس‌ها: {ips_received}",
                                        callback_data='noop')
               ],
               [
                   InlineKeyboardButton(
                       f"🔑 {get_subscription_status(user_id)}",
                       callback_data='noop')
               ], [InlineKeyboardButton("⬅️ بازگشت", callback_data='back')]]
    send_reply(update,
               "👤 حساب کاربری شما:",
               reply_markup=InlineKeyboardMarkup(buttons))


def get_subscription_status(user_id: int) -> str:
    """Returns detailed subscription status."""
    if db.is_user_active(user_id):
        if db.is_user_subscribed(user_id):
            return "وضعیت اشتراک: فعال دائمی"
        else:
            tokens = db.get_tokens(user_id)
            return f"وضعیت اشتراک: فعال توکنی (توکن‌ها باقی مانده: {tokens})"
    return "وضعیت اشتراک: غیر فعال"


def user_account_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Updated user account keyboard with subscription details."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ بازگشت", callback_data='back')]])


def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    subscription_status = get_subscription_status(user_id)
    buttons = [[InlineKeyboardButton(f"🔐 {subscription_status}", callback_data='noop')]]
    if not db.is_user_active(user_id) and not db.is_user_subscribed(user_id):
        buttons.append([InlineKeyboardButton("🔑 فعال‌سازی اشتراک", callback_data='activate')])
    ipv6_button = InlineKeyboardButton("🌐 تولید IPv6", callback_data='generate_ipv6')
    ipv4_button = InlineKeyboardButton("📋 لیست IPv4", callback_data='ipv4_menu')
    validate_button = InlineKeyboardButton("🔍 اعتبارسنجی IPv4", callback_data='validate_ipv4')
    wireguard_button = InlineKeyboardButton("🔒 وایرگارد اختصاصی", callback_data='wireguard')
    account_button = InlineKeyboardButton("👤 حساب کاربری", callback_data='user_account')
    support_button = InlineKeyboardButton("❓ پشتیبانی", callback_data='support')
    # دکمه‌های غیرفعال
    if DISABLED_BUTTONS.get('generate_ipv6', False):
        ipv6_button = InlineKeyboardButton("🚧 تولید IPv6 (در حال بروزرسانی)", callback_data='disabled_button')
    if DISABLED_BUTTONS.get('get_ipv4', False):
        ipv4_button = InlineKeyboardButton("🚧 لیست IPv4 (در حال بروزرسانی)", callback_data='disabled_button')
    if DISABLED_BUTTONS.get('validate_ipv4', False):
        validate_button = InlineKeyboardButton("🚧 اعتبارسنجی IPv4 (در حال بروزرسانی)", callback_data='disabled_button')
    if DISABLED_BUTTONS.get('wireguard', False):
        wireguard_button = InlineKeyboardButton("🚧 وایرگارد (در حال بروزرسانی)", callback_data='disabled_button')
    if DISABLED_BUTTONS.get('user_account', False):
        account_button = InlineKeyboardButton("🚧 حساب کاربری (در حال بروزرسانی)", callback_data='disabled_button')
    if DISABLED_BUTTONS.get('support', False):
        support_button = InlineKeyboardButton("🚧 پشتیبانی (در حال بروزرسانی)", callback_data='disabled_button')
    buttons.extend([[ipv6_button, ipv4_button], [validate_button, wireguard_button], [account_button, support_button]])
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("🛠️ پنل ادمین", callback_data='admin_panel')])
    return InlineKeyboardMarkup(buttons)


def cb_subscription_status(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    status = get_subscription_status(user_id)
    send_reply(update, status, reply_markup=main_menu_keyboard(user_id))


def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id

    # بررسی عضویت در کانال اجباری (اگر تنظیم شده باشد)
    if REQUIRED_CHANNEL and user_id != ADMIN_ID:
        if not check_channel_membership(user_id, context):
            welcome_text = f"👋 سلام! برای استفاده از ربات، ابتدا باید در کانال {REQUIRED_CHANNEL} عضو شوید."
            send_reply(update,
                       welcome_text,
                       reply_markup=create_join_channel_button())
            return

    welcome_text = "👋 سلام! به ربات خوش آمدید.\nبرای پشتیبانی از دکمه زیر می‌توانید استفاده کنید یا از دستور /help برای راهنمایی.\nدر هر زمان با دستور /stop می‌توانید عملیات فعلی را متوقف کنید."
    send_reply(update, welcome_text, reply_markup=main_menu_keyboard(user_id))


def stop_command(update: Update, context: CallbackContext) -> int:
    """متوقف کردن مکالمه فعلی و برگشت به منوی اصلی."""
    user_id = update.effective_user.id

    # حذف داده‌های موقتی کاربر
    if hasattr(context, 'user_data') and user_id in context.user_data:
        context.user_data.clear()

    send_reply(update,
               "✅ عملیات فعلی متوقف شد. به منوی اصلی برگشتید.",
               reply_markup=main_menu_keyboard(user_id))
    return ConversationHandler.END


def support_command(update: Update,
                    context: CallbackContext) -> None:  #New Support Command
    user_id = update.effective_user.id
    support_text = "برای پشتیبانی مستقیم با من در تماس باشید:"
    buttons = [[
        InlineKeyboardButton("پیام مستقیم به من 📩",
                             url="https://t.me/Minimalcraft")
    ]]
    send_reply(update,
               support_text,
               reply_markup=InlineKeyboardMarkup(buttons))


def require_subscription(func):

    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
        if not db.is_user_active(user_id):
            send_reply(update,
                       "❌ اشتراک فعال ندارید. لطفاً ابتدا فعال‌سازی کنید.",
                       reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END
        return func(update, context, *args, **kwargs)

    return wrapper


def generate_ipv6(option: int) -> list:
    blocks = lambda n: ":".join(f"{random.randint(0, 65535):04x}"
                                for _ in range(n))
    if option == 1:
        ipv6_1 = f"{blocks(1)}:{random.randint(0, 255):02x}::" + f"{random.randint(0, 65535):04x}"
        ipv6_2 = f"{blocks(1)}:{random.randint(0, 255):02x}::" + f"{random.randint(0, 65535):04x}"
        return [ipv6_1, ipv6_2]
    if option == 2:
        ipv6_1 = f"{blocks(2)}::" + f"{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
        ipv6_2 = f"{blocks(2)}::" + f"{random.randint(0, 255):02x}:{random.randint(0, 255):02x}"
        return [ipv6_1, ipv6_2]
    if option == 3:
        ipv6_1 = f"{blocks(1)}:{random.randint(0, 255):02x}:{blocks(1)}::1"
        ipv6_2 = f"{blocks(1)}:{random.randint(0, 255):02x}:{blocks(1)}::1"
        return [ipv6_1, ipv6_2]
    if option == 4:
        ipv6_1 = f"{blocks(2)}::{blocks(1)}"
        ipv6_2 = f"{blocks(2)}::{blocks(1)}"
        return [ipv6_1, ipv6_2]
    if option == 5:
        ipv6_1 = f"{blocks(1)}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}::1"
        ipv6_2 = f"{blocks(1)}:{random.randint(0, 255):02x}:{random.randint(0, 255):02x}::1"
        return [ipv6_1, ipv6_2]
    raise ValueError("گزینه نامعتبر برای تولید IPv6")


def cb_activate(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if db.is_user_active(user_id):
        send_reply(update,
                   "✅ شما قبلاً فعال‌سازی شده‌اید.",
                   reply_markup=main_menu_keyboard(user_id))
        return ConversationHandler.END
    send_reply(update, "🔑 لطفاً کد فعال‌سازی را وارد کنید:")
    return ENTER_ACTIVATION


def enter_activation(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    code = update.message.text.strip()
    is_valid, code_data = db.check_activation_code(code)
    if is_valid:
        db.activate_user(user_id, code_data)
        if code_data["type"] == "token":
            send_reply(
                update,
                f"✅ فعال‌سازی موفق! اشتراک توکنی شما با {code_data['tokens']} توکن فعال شد.",
                reply_markup=main_menu_keyboard(user_id))
        else:
            send_reply(update,
                       "✅ فعال‌سازی موفق! اشتراک دائمی شما فعال شد.",
                       reply_markup=main_menu_keyboard(user_id))
    else:
        send_reply(update,
                   "❌ کد فعال‌سازی نامعتبر است.",
                   reply_markup=main_menu_keyboard(user_id))
    return ConversationHandler.END


def cb_generate(update: Update, context: CallbackContext) -> None:
    user_id = update.callback_query.from_user.id
    if not db.is_user_active(user_id):
        send_reply(update,
                   "❌ اشتراک فعال ندارید. لطفاً ابتدا فعال‌سازی کنید.",
                   reply_markup=main_menu_keyboard(user_id))
        return

    # بررسی گزینه‌های غیرفعال IPv6
    buttons = []
    row1 = []
    row2 = []

    # گزینه 1
    if db.disabled_locations.get("ipv6_option_1", False):
        row1.append(
            InlineKeyboardButton("🚫 گزینه 1 (غیرفعال)",
                                 callback_data='disabled_button'))
    else:
        row1.append(InlineKeyboardButton("گزینه 1", callback_data='gen_1'))

    # گزینه 2
    if db.disabled_locations.get("ipv6_option_2", False):
        row1.append(
            InlineKeyboardButton("🚫 گزینه 2 (غیرفعال)",
                                 callback_data='disabled_button'))
    else:
        row1.append(InlineKeyboardButton("گزینه 2", callback_data='gen_2'))

    # گزینه 3
    if db.disabled_locations.get("ipv6_option_3", False):
        row2.append(
            InlineKeyboardButton("🚫 گزینه 3 (غیرفعال)",
                                 callback_data='disabled_button'))
    else:
        row2.append(InlineKeyboardButton("گزینه 3", callback_data='gen_3'))

    # گزینه 4
    if db.disabled_locations.get("ipv6_option_4", False):
        row2.append(
            InlineKeyboardButton("🚫 گزینه 4 (غیرفعال)",
                                 callback_data='disabled_button'))
    else:
        row2.append(InlineKeyboardButton("گزینه 4", callback_data='gen_4'))

    buttons.append(row1)
    buttons.append(row2)

    # گزینه 5
    if db.disabled_locations.get("ipv6_option_5", False):
        buttons.append([
            InlineKeyboardButton("🚫 گزینه 5 (غیرفعال)",
                                 callback_data='disabled_button')
        ])
    else:
        buttons.append(
            [InlineKeyboardButton("گزینه 5", callback_data='gen_5')])

    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='back')])

    send_reply(update,
               "لطفاً یک گزینه برای تولید IPv6 انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))


@require_subscription
def cb_generate_option(update: Update, context: CallbackContext) -> None:
    user_id = update.callback_query.from_user.id
    option = int(update.callback_query.data.split('_')[1])

    # بررسی نوع اشتراک و کم کردن توکن در صورت نیاز
    user_data = db.active_users.get(user_id, {})
    if user_data.get('type') == 'token':
        # کسر توکن برای هر بار استفاده
        current_tokens = user_data.get('tokens', 0)
        if current_tokens <= 0:
            send_reply(
                update,
                "❌ توکن شما تمام شده است. لطفاً اشتراک خود را تمدید کنید.",
                reply_markup=main_menu_keyboard(user_id))
            return

        # کم کردن یک توکن و به‌روزرسانی پایگاه داده
        db.active_users[user_id]['tokens'] = current_tokens - 1
        db.save_database()

    ipv6_list = generate_ipv6(option)
    formatted_ipv6 = "\n".join(f"`{address}`" for address in ipv6_list)

    # نمایش تعداد توکن‌های باقی‌مانده برای کاربران توکنی
    token_message = ""
    if user_data.get('type') == 'token':
        remaining_tokens = db.active_users[user_id].get('tokens', 0)
        token_message = f"\n\n🔄 توکن‌های باقی‌مانده: {remaining_tokens}"

    send_reply(update,
               f"✨ آدرس IPv6 شما:\n{formatted_ipv6}{token_message}",
               parse_mode=ParseMode.MARKDOWN)


@require_subscription
def cb_get_ipv4(update: Update, context: CallbackContext) -> None:
    country_ips = db.get_ipv4_countries()
    if not country_ips:
        text = "ℹ️ هیچ IPv4 ذخیره‌شده‌ای یافت نشد."
        send_reply(update, text)
        return

    # نقشه پرچم‌های خاص برای کشورهای مشکل‌دار
    special_flags = {
        "SA": "🇸🇦", "KSA": "🇸🇦", "SAUDI": "🇸🇦", "SAUDI ARABIA": "🇸🇦",
        "IR": "🇮🇷", "AE": "🇦🇪", 
        "QA": "🇶🇦", "PK": "🇵🇰", "TR": "🇹🇷", "IQ": "🇮🇶", 
        "OM": "🇴🇲", "KW": "🇰🇼", "BH": "🇧🇭", "EG": "🇪🇬", 
        "RU": "🇷🇺", "US": "🇺🇸", "DE": "🇩🇪", "GB": "🇬🇧", 
        "FR": "🇫🇷", "CN": "🇨🇳", "IN": "🇮🇳", "JP": "🇯🇵", 
        "CA": "🇨🇦", "GE": "🇬🇪"
    }

    def get_flag(country_code, flag):
        code = country_code.upper()
        if code in special_flags:
            return special_flags[code]
        if len(code) == 2 and code.isalpha():
            # ساخت ایموجی پرچم از کد کشور
            return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)
        return flag or "🏳️"

    buttons = []
    row = []
    count = 0
    countries_with_ips = False

    for country_code, (country, flag, ips) in country_ips.items():
        if len(ips) > 0 and not db.is_location_disabled(country_code, "ipv4"):
            countries_with_ips = True
            display_flag = get_flag(country_code, flag)
            row.append(InlineKeyboardButton(f"{display_flag} {country} ({len(ips)})", callback_data=f"country_{country_code}"))
            count += 1
            if count % 3 == 0:
                buttons.append(row)
                row = []

    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='back')])

    if not countries_with_ips:
        send_reply(update, "ℹ️ هیچ کشوری با آدرس IP فعال وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ بازگشت", callback_data='back')]]))
    else:
        send_reply(update, "🌍 انتخاب کشور:", reply_markup=InlineKeyboardMarkup(buttons))


def cb_country_ips(update: Update, context: CallbackContext) -> None:
    try:
        if '_page_' in update.callback_query.data:
            # مدیریت صفحه‌بندی
            parts = update.callback_query.data.split('_page_')
            country_code = parts[0].split('_')[-1]  # آخرین بخش قبل از _page_
            try:
                page = int(parts[1])
            except ValueError:
                # اگر نتوانستیم page را به عدد تبدیل کنیم، صفحه 0 را انتخاب می کنیم
                page = 0
        else:
            # درخواست اولیه
            country_code = update.callback_query.data.split('_')[1]
            page = 0  # صفحه اول
        
        # استاندارد‌سازی کد عربستان - اضافه کردن حالت‌های بیشتر
        if country_code.upper() in ["KSA", "SAUDI", "SAUDI ARABIA", "SAUDI_ARABIA", "KINGDOMOFSAUDIARABIA"]:
            country_code = "SA"
            logger.info(f"Saudi Arabia country code standardized: {country_code}")
            
        ips = db.get_ips_by_country(country_code)
        country_data = db.get_ipv4_countries().get(country_code)
        if not country_data:
            update.callback_query.answer("اطلاعات کشور یافت نشد.")
            cb_get_ipv4(update, context)
            return
        
        # بررسی ساختار country_data برای مطمئن شدن از وجود همه مقادیر مورد نیاز
        if isinstance(country_data, tuple) and len(country_data) >= 2:
            country_name = country_data[0]
            flag = country_data[1]
        else:
            # در صورت نامعتبر بودن ساختار، مقادیر پیش‌فرض تعیین کنیم
            country_name = country_code
            flag = "🏳️"
        
        # همان منطق پرچم را اینجا هم اعمال کن
        special_flags = {
            "SA": "🇸🇦", "KSA": "🇸🇦", "IR": "🇮🇷", "AE": "🇦🇪", "QA": "🇶🇦", "PK": "🇵🇰", 
            "TR": "🇹🇷", "IQ": "🇮🇶", "OM": "🇴🇲", "KW": "🇰🇼", "BH": "🇧🇭", "EG": "🇪🇬", 
            "RU": "🇷🇺", "US": "🇺🇸", "DE": "🇩🇪", "GB": "🇬🇧", "FR": "🇫🇷", "CN": "🇨🇳", 
            "IN": "🇮🇳", "JP": "🇯🇵", "CA": "🇨🇦", "GE": "🇬🇪"
        }
        
        code = country_code.upper() if isinstance(country_code, str) and len(country_code) <= 2 else country_code
        if code in special_flags:
            display_flag = special_flags[code]
        elif isinstance(code, str) and len(code) == 2 and code.isalpha():
            display_flag = chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)
        else:
            display_flag = flag or "🏳️"
            
        if ips:
            total_ips = len(ips)
            
            # نمایش یک آدرس در هر صفحه
            if page >= total_ips:
                page = 0  # بازگشت به صفحه اول اگر خارج از محدوده باشد
            elif page < 0:
                page = total_ips - 1  # رفتن به آخرین صفحه
                
            current_ip = ips[page]
            
            # ساخت دکمه‌های صفحه‌بندی
            pagination_buttons = []
            
            if total_ips > 1:
                prev_page = page - 1 if page > 0 else total_ips - 1
                next_page = page + 1 if page < total_ips - 1 else 0
                
                pagination_buttons = [
                    InlineKeyboardButton("◀️ قبلی", callback_data=f"country_{country_code}_page_{prev_page}"),
                    InlineKeyboardButton(f"{page + 1}/{total_ips}", callback_data="noop"),
                    InlineKeyboardButton("بعدی ▶️", callback_data=f"country_{country_code}_page_{next_page}")
                ]
            
            # تهیه متن پیام با شماره صفحه
            text = f"📡 آدرس {page + 1} از {total_ips} برای {display_flag} {country_name}:\n\n`{current_ip}`"
            
            buttons = []
            if total_ips > 1:
                buttons.append(pagination_buttons)
            buttons.append([InlineKeyboardButton("↩️ بازگشت به لیست کشورها", callback_data='get_ipv4')])
            
            # اگر پیام قبلاً وجود دارد، آن را ویرایش کنیم، در غیر این صورت پیام جدید بفرستیم
            if update.callback_query.message and '_page_' in update.callback_query.data:
                update.callback_query.edit_message_text(
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
            else:
                send_reply(update, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
        else:
            update.callback_query.answer("هیچ آدرسی برای این کشور یافت نشد.")
            cb_get_ipv4(update, context)
    except Exception as e:
        logger.error(f"خطا در نمایش آدرس‌های کشور: {e}")
        update.callback_query.answer("خطایی رخ داد. دوباره تلاش کنید.")
        cb_get_ipv4(update, context)


def cb_disabled_button(update: Update, context: CallbackContext) -> None:
    """هندلر برای دکمه‌های غیرفعال"""
    update.callback_query.answer(
        "این قابلیت در حال بروزرسانی است. لطفا بعدا تلاش کنید.")


def cb_admin_panel(update: Update, context: CallbackContext) -> None:
    # بررسی منوی فعلی
    current_menu = context.user_data.get('admin_menu', 'main')
    
    if current_menu == 'main':
        # منوی اصلی ادمین
        buttons = [
            # دسته‌بندی‌های اصلی
            [InlineKeyboardButton("📡 مدیریت IP ها", callback_data='admin_menu_ip')],
            [InlineKeyboardButton("🔑 مدیریت اشتراک‌ها", callback_data='admin_menu_subscription')],
            [InlineKeyboardButton("👥 مدیریت کاربران", callback_data='admin_menu_users')],
            [InlineKeyboardButton("🔒 مدیریت وایرگارد", callback_data='admin_menu_wireguard')],
            [InlineKeyboardButton("⚙️ تنظیمات عمومی", callback_data='admin_menu_settings')],
            
            # آمار و بازگشت
            [InlineKeyboardButton("📊 آمار", callback_data='admin_stats')],
            [InlineKeyboardButton("↩️ بازگشت به منوی اصلی", callback_data='back')]
        ]
        send_reply(update, "🛠️ پنل مدیریت ربات:", reply_markup=InlineKeyboardMarkup(buttons))
    
    elif current_menu == 'ip':
        # منوی مدیریت IP
        buttons = [
            [InlineKeyboardButton("➕ اضافه کردن IPv4", callback_data='admin_add_ipv4'), 
             InlineKeyboardButton("🔍 پردازش و افزودن IP", callback_data='admin_process_ip')],
            [InlineKeyboardButton("📥 پردازش گروهی IP", callback_data='admin_batch_process_ip'), 
             InlineKeyboardButton("❌ حذف IPv4", callback_data='admin_remove_ipv4')],
            [InlineKeyboardButton("🌐 مدیریت لوکیشن‌ها", callback_data='admin_manage_locations'), 
             InlineKeyboardButton("📤 خروجی CSV لیست IP", callback_data='export_ips')],
            [InlineKeyboardButton("↩️ بازگشت به منوی اصلی ادمین", callback_data='admin_menu_main')]
        ]
        send_reply(update, "📡 مدیریت IP ها:", reply_markup=InlineKeyboardMarkup(buttons))
    
    elif current_menu == 'subscription':
        # منوی مدیریت اشتراک‌ها
        buttons = [
            [InlineKeyboardButton("➕ اضافه کردن کد فعالسازی", callback_data='admin_add_code')],
            [InlineKeyboardButton("📋 مشاهده کدها", callback_data='admin_view_codes')],
            [InlineKeyboardButton("🔍 جستجوی کد فعالسازی", callback_data='admin_search_code')],
            [InlineKeyboardButton("📊 آمار استفاده از کدها", callback_data='admin_code_stats')],
            [InlineKeyboardButton("↩️ بازگشت به منوی اصلی ادمین", callback_data='admin_menu_main')]
        ]
        send_reply(update, "🔑 مدیریت اشتراک‌ها:", reply_markup=InlineKeyboardMarkup(buttons))
    
    elif current_menu == 'users':
        # منوی مدیریت کاربران
        buttons = [
            [InlineKeyboardButton("➕ افزودن توکن به کاربر", callback_data='admin_grant_tokens'),
             InlineKeyboardButton("🚫 غیرفعال کردن کاربر", callback_data='admin_disable_user')],
            [InlineKeyboardButton("✅ فعال کردن کاربر", callback_data='admin_enable_user'),
             InlineKeyboardButton("🔍 جستجوی کاربر", callback_data='admin_search_user')],
            [InlineKeyboardButton("📋 لیست کاربران فعال", callback_data='admin_list_active_users'),
             InlineKeyboardButton("📋 لیست کاربران غیرفعال", callback_data='admin_list_disabled_users')],
            [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data='admin_broadcast')],
            [InlineKeyboardButton("↩️ بازگشت به منوی اصلی ادمین", callback_data='admin_menu_main')]
        ]
        send_reply(update, "👥 مدیریت کاربران:", reply_markup=InlineKeyboardMarkup(buttons))
    
    elif current_menu == 'wireguard':
        # منوی مدیریت وایرگارد
        buttons = [
            [InlineKeyboardButton("🌐 مدیریت Endpoint ها", callback_data='admin_manage_wg_endpoints')],
            [InlineKeyboardButton("➕ افزودن Endpoint", callback_data='add_wg_endpoint')],
            [InlineKeyboardButton("📥 افزودن گروهی Endpoint", callback_data='admin_batch_add_endpoints')],
            [InlineKeyboardButton("⚙️ تنظیمات وایرگارد", callback_data='admin_wg_settings')],
            [InlineKeyboardButton("📊 آمار استفاده از وایرگارد", callback_data='admin_wg_stats')],
            [InlineKeyboardButton("↩️ بازگشت به منوی اصلی ادمین", callback_data='admin_menu_main')]
        ]
        send_reply(update, "🔒 مدیریت وایرگارد:", reply_markup=InlineKeyboardMarkup(buttons))
    
    elif current_menu == 'settings':
        # منوی تنظیمات عمومی
        buttons = [
            [InlineKeyboardButton("🚫 مدیریت دکمه‌ها", callback_data='admin_manage_buttons'),
             InlineKeyboardButton("🔔 تنظیم کانال اجباری", callback_data='admin_set_channel')],
            [InlineKeyboardButton("💾 مدیریت بکاپ‌ها", callback_data='admin_manage_backups')],
            [InlineKeyboardButton("🔒 خاموش کردن ربات", callback_data='admin_shutdown'),
             InlineKeyboardButton("🟢 روشن کردن ربات", callback_data='admin_startup')],
            [InlineKeyboardButton("↩️ بازگشت به منوی اصلی ادمین", callback_data='admin_menu_main')]
        ]
        send_reply(update, "⚙️ تنظیمات عمومی:", reply_markup=InlineKeyboardMarkup(buttons))

def cb_admin_menu_main(update: Update, context: CallbackContext) -> None:
    """بازگشت به منوی اصلی ادمین"""
    context.user_data['admin_menu'] = 'main'
    cb_admin_panel(update, context)

def cb_admin_menu_ip(update: Update, context: CallbackContext) -> None:
    """رفتن به منوی مدیریت IP"""
    context.user_data['admin_menu'] = 'ip'
    cb_admin_panel(update, context)

def cb_admin_menu_subscription(update: Update, context: CallbackContext) -> None:
    """رفتن به منوی مدیریت اشتراک‌ها"""
    context.user_data['admin_menu'] = 'subscription'
    cb_admin_panel(update, context)

def cb_admin_menu_users(update: Update, context: CallbackContext) -> None:
    """رفتن به منوی مدیریت کاربران"""
    context.user_data['admin_menu'] = 'users'
    cb_admin_panel(update, context)

def cb_admin_menu_wireguard(update: Update, context: CallbackContext) -> None:
    """رفتن به منوی مدیریت وایرگارد"""
    context.user_data['admin_menu'] = 'wireguard'
    cb_admin_panel(update, context)

def cb_admin_menu_settings(update: Update, context: CallbackContext) -> None:
    """رفتن به منوی تنظیمات عمومی"""
    context.user_data['admin_menu'] = 'settings'
    cb_admin_panel(update, context)


def cb_admin_add_code(update: Update, context: CallbackContext) -> int:
    buttons = [[
        InlineKeyboardButton("دائمی", callback_data='code_type_unlimited')
    ], [InlineKeyboardButton("توکنی", callback_data='code_type_token')]]
    send_reply(update,
               "🔑 نوع کد فعال‌سازی را انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSE_CODE_TYPE


def cb_code_type_selected(update: Update, context: CallbackContext) -> int:
    code_type = update.callback_query.data.split('_')[2]
    context.user_data['code_type'] = code_type

    if code_type == 'token':
        send_reply(update, "🔢 لطفاً تعداد توکن را وارد کنید:")
        return ENTER_TOKEN_COUNT
    else:
        send_reply(update, "🔑 لطفاً کد فعال‌سازی را وارد کنید:")
        return ENTER_NEW_CODE


def enter_token_count(update: Update, context: CallbackContext) -> int:
    try:
        tokens = int(update.message.text.strip())
        if tokens <= 0:
            send_reply(
                update,
                "❌ تعداد توکن باید بیشتر از صفر باشد. لطفاً دوباره وارد کنید:")
            return ENTER_TOKEN_COUNT
        context.user_data['tokens'] = tokens
        send_reply(update, "🔑 لطفاً کد فعال‌سازی را وارد کنید:")
        return ENTER_NEW_CODE
    except ValueError:
        send_reply(update, "❌ لطفاً یک عدد معتبر وارد کنید:")
        return ENTER_TOKEN_COUNT


def enter_new_code(update: Update, context: CallbackContext) -> int:
    code = update.message.text.strip()
    code_type = context.user_data.get('code_type')
    tokens = context.user_data.get('tokens', 0)

    db.add_active_code(code, code_type, tokens)
    if code_type == 'token':
        send_reply(update, f"✅ کد فعال‌سازی توکنی با {tokens} توکن افزوده شد.")
    else:
        send_reply(update, "✅ کد فعال‌سازی دائمی افزوده شد.")
    return ConversationHandler.END


def cb_admin_add_ipv4(update: Update, context: CallbackContext) -> int:
    send_reply(update, "🌍 لطفاً اسم کشور را وارد کنید:")
    context.user_data['ipv4_data'] = {}
    return ENTER_COUNTRY_NAME


def enter_country_name(update: Update, context: CallbackContext) -> int:
    context.user_data['ipv4_data']['country_name'] = update.message.text.strip(
    )
    send_reply(update, "🏳️ لطفاً ایموجی پرچم کشور را وارد کنید:")
    return ENTER_COUNTRY_FLAG


def enter_country_flag(update: Update, context: CallbackContext) -> int:
    context.user_data['ipv4_data']['flag'] = update.message.text.strip()
    send_reply(update, "🌐 لطفاً آدرس آی‌پی IPv4 جدید را وارد کنید:")
    return ENTER_NEW_IPV4


def enter_new_ipv4(update: Update, context: CallbackContext) -> int:
    ipv4_data = context.user_data['ipv4_data']
    ipv4_data['ipv4'] = update.message.text.strip()
    db.add_ipv4_address(ipv4_data['country_name'], ipv4_data['flag'],
                        ipv4_data['ipv4'])
    send_reply(update, "✅ آدرس IPv4 جدید افزوده شد.")
    return ConversationHandler.END


def cb_admin_stats(update: Update, context: CallbackContext) -> None:
    stats = db.get_stats()
    text = "📊 *آمار بات:*\n" + "\n".join(f"• {k}: {v}"
                                         for k, v in stats.items())
    send_reply(update, text, parse_mode=ParseMode.MARKDOWN)


def cb_back(update: Update, context: CallbackContext) -> None:
    start(update, context)


def cb_ipv4_menu(update: Update, context: CallbackContext) -> None:
    """زیر منوی مدیریت IPv4"""
    buttons = [
        [InlineKeyboardButton("📋 مشاهده لیست کشورها", callback_data='get_ipv4')],
        [InlineKeyboardButton("🔍 جستجوی سریع کشور/IP", callback_data='quick_search_ipv4')],
        [InlineKeyboardButton("🌎 دسته‌بندی بر اساس قاره", callback_data='continent_list_ipv4')],
        [InlineKeyboardButton("🆕 آخرین IPهای افزوده شده", callback_data='latest_ips_ipv4')],
        [InlineKeyboardButton("↩️ بازگشت", callback_data='back')]
    ]
    send_reply(update, "لطفاً یک گزینه انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))


def cb_quick_search_ipv4(update: Update, context: CallbackContext) -> None:
    """جستجوی سریع IPv4"""
    send_reply(update, "🔍 لطفاً نام کشور یا بخشی از IP را وارد کنید:")
    context.user_data['search_mode_ipv4'] = True
    return ConversationHandler.END


def handle_search_input_ipv4(update: Update, context: CallbackContext) -> None:
    """پردازش متن جستجو شده توسط کاربر"""
    if context.user_data.get('search_mode_ipv4'):
        query = update.message.text.strip().lower()
        results = []
        
        # نقشه کشورهای فارسی به انگلیسی برای جستجوی فارسی
        persian_to_english = {
            "ایران": "iran", 
            "عربستان": "saudi arabia", "عربستان سعودی": "saudi arabia", "سعودی": "saudi arabia",
            "آمریکا": "united states", "امریکا": "united states", 
            "انگلیس": "united kingdom", "انگلستان": "united kingdom", "آلمان": "germany", "روسیه": "russia",
            "فرانسه": "france", "چین": "china", "هند": "india", "ژاپن": "japan", "کانادا": "canada",
            "پاکستان": "pakistan", "قطر": "qatar", "امارات": "uae", "عراق": "iraq", "کویت": "kuwait",
            "بحرین": "bahrain", "عمان": "oman", "مصر": "egypt", "ترکیه": "turkey", "گرجستان": "georgia"
        }
        
        # کد کشورهای مرتبط با عربستان
        saudi_codes = ["sa", "ksa", "saudi", "saudi arabia", "saudi_arabia"]
        
        # تبدیل جستجوی فارسی به انگلیسی
        english_query = persian_to_english.get(query, query)
        
        # لاگ کردن کوئری برای اشکال‌زدایی
        logger.info(f"جستجوی کاربر: {query} -> {english_query}")
        
        for country_code, (country, flag, ips) in db.get_ipv4_countries().items():
            # برای عربستان، کدهای مختلف را بررسی کنیم
            if (country_code.lower() in saudi_codes or 
                "saudi" in country.lower() or 
                english_query in saudi_codes):
                
                # اگر جستجو مرتبط با عربستان است
                if ("saudi" in english_query or 
                    query == "عربستان" or 
                    query == "عربستان سعودی" or 
                    query == "سعودی"):
                    results.append(f"{flag} {country}: {len(ips)} IP (کد کشور: {country_code})")
                    logger.info(f"Saudi Arabia found: {country_code}, {country}")
            
            # جستجوی استاندارد در نام و کد کشور
            elif (english_query in country.lower() or 
                  english_query in country_code.lower() or 
                  query in country.lower()):
                results.append(f"{flag} {country}: {len(ips)} IP")
            else:
                # جستجو در آدرس‌های IP
                for ip in ips:
                    if query in ip:
                        results.append(f"{flag} {country}: {ip}")
        
        if results:
            # اگر تعداد نتایج زیاد است، آنها را به چند پیام تقسیم می‌کنیم
            if len(results) > 30:
                send_reply(update, f"🔍 {len(results)} نتیجه برای جستجوی '{query}' یافت شد.")
                
                for i in range(0, len(results), 30):
                    chunk = results[i:i+30]
                    message = f"نتایج {i+1} تا {min(i+30, len(results))}:\n" + "\n".join(chunk)
                    update.message.reply_text(message)
            else:
                send_reply(update, f"🔍 نتایج جستجو برای '{query}':\n" + "\n".join(results))
        else:
            send_reply(update, f"❌ نتیجه‌ای برای جستجوی '{query}' یافت نشد.")
            
        context.user_data['search_mode_ipv4'] = False
        
        # بازگشت به منوی اصلی
        buttons = [[InlineKeyboardButton("↩️ بازگشت", callback_data='ipv4_menu')]]
        update.message.reply_text("عملیات جستجو به پایان رسید.", reply_markup=InlineKeyboardMarkup(buttons))


def cb_latest_ips_ipv4(update: Update, context: CallbackContext) -> None:
    """نمایش آخرین IPهای اضافه شده"""
    if not hasattr(db, 'last_added_ips'):
        db.last_added_ips = deque(maxlen=20)  # ایجاد لیست برای نگهداری آخرین IPها
        
    if not db.last_added_ips:
        send_reply(update, "هیچ IP جدیدی ثبت نشده است.")
    else:
        text = "🆕 آخرین IPهای افزوده شده:\n" + "\n".join(db.last_added_ips)
        send_reply(update, text)
    
    # بازگشت به منوی IPv4
    buttons = [[InlineKeyboardButton("↩️ بازگشت", callback_data='ipv4_menu')]]
    update.callback_query.message.reply_text("", reply_markup=InlineKeyboardMarkup(buttons))


# Define global continent mapping at the module level
CONTINENT_MAP = {
    'AS': 'آسیا 🌏', 'EU': 'اروپا 🇪🇺', 'AF': 'آفریقا 🌍', 
    'NA': 'آمریکای شمالی 🌎', 'SA': 'آمریکای جنوبی 🌎', 
    'OC': 'اقیانوسیه 🏝️', 'AN': 'جنوبگان 🏔️'
}

# Global country to continent mapping
COUNTRY_TO_CONTINENT = {
    # آسیا - Asia
    'IR': 'AS', 'SA': 'AS', 'AE': 'AS', 'QA': 'AS', 'TR': 'AS', 'IQ': 'AS',
    'KW': 'AS', 'OM': 'AS', 'BH': 'AS', 'CN': 'AS', 'JP': 'AS', 'ID': 'AS',
    'IN': 'AS', 'KR': 'AS', 'SG': 'AS', 'PK': 'AS', 'MY': 'AS', 'TH': 'AS',
    'KSA': 'AS', 'SAUDI': 'AS', 'SAUDI ARABIA': 'AS', 'SAUDI_ARABIA': 'AS',
    'GE': 'AS', 'IL': 'AS', 'JO': 'AS', 'LB': 'AS', 'SY': 'AS',
    'AF': 'AS', 'BD': 'AS', 'LK': 'AS', 'NP': 'AS', 'VN': 'AS', 'HK': 'AS',
    'YE': 'AS', 'UZ': 'AS', 'TW': 'AS', 'TJ': 'AS', 'TM': 'AS', 'KZ': 'AS',
    'KG': 'AS', 'MO': 'AS', 'LA': 'AS', 'KH': 'AS', 'MM': 'AS', 'MN': 'AS',
    'MV': 'AS', 'BT': 'AS', 'BN': 'AS', 'TL': 'AS', 'PS': 'AS', 'PH': 'AS',
    
    # اروپا - Europe
    'DE': 'EU', 'GB': 'EU', 'FR': 'EU', 'IT': 'EU', 'ES': 'EU', 'RU': 'EU',
    'NL': 'EU', 'CH': 'EU', 'SE': 'EU', 'PL': 'EU', 'BE': 'EU', 'AT': 'EU',
    'NO': 'EU', 'DK': 'EU', 'FI': 'EU', 'PT': 'EU', 'IE': 'EU', 'GR': 'EU',
    'UA': 'EU', 'CZ': 'EU', 'RO': 'EU', 'BG': 'EU', 'HU': 'EU', 'HR': 'EU',
    'RS': 'EU', 'SK': 'EU', 'SI': 'EU', 'EE': 'EU', 'LV': 'EU', 'LT': 'EU',
    'IS': 'EU', 'LU': 'EU', 'MT': 'EU', 'CY': 'EU', 'ME': 'EU', 'MK': 'EU',
    'AL': 'EU', 'BA': 'EU', 'MD': 'EU', 'MC': 'EU', 'LI': 'EU', 'SM': 'EU',
    'VA': 'EU', 'BY': 'EU', 'GI': 'EU', 'JE': 'EU', 'IM': 'EU', 'FO': 'EU',
    
    # آفریقا - Africa
    'EG': 'AF', 'ZA': 'AF', 'NG': 'AF', 'MA': 'AF', 'KE': 'AF', 'TN': 'AF',
    'DZ': 'AF', 'GH': 'AF', 'CM': 'AF', 'CI': 'AF', 'LY': 'AF', 'SD': 'AF',
    'ET': 'AF', 'AO': 'AF', 'TZ': 'AF', 'UG': 'AF', 'ZM': 'AF', 'ZW': 'AF',
    'SN': 'AF', 'ML': 'AF', 'MR': 'AF', 'NE': 'AF', 'TD': 'AF', 'SO': 'AF',
    'MG': 'AF', 'RW': 'AF', 'BF': 'AF', 'GA': 'AF', 'BJ': 'AF', 'BI': 'AF',
    'DJ': 'AF', 'ER': 'AF', 'GM': 'AF', 'GN': 'AF', 'GQ': 'AF', 'GW': 'AF',
    'LR': 'AF', 'LS': 'AF', 'MW': 'AF', 'MU': 'AF', 'MZ': 'AF', 'NA': 'AF',
    'SC': 'AF', 'SL': 'AF', 'SS': 'AF', 'ST': 'AF', 'SZ': 'AF', 'TG': 'AF',
    
    # آمریکای شمالی - North America
    'US': 'NA', 'CA': 'NA', 'MX': 'NA', 'PA': 'NA', 'CR': 'NA', 'CU': 'NA',
    'DO': 'NA', 'GT': 'NA', 'HN': 'NA', 'SV': 'NA', 'NI': 'NA', 'JM': 'NA',
    'HT': 'NA', 'BS': 'NA', 'TT': 'NA', 'BB': 'NA', 'BZ': 'NA', 'PR': 'NA',
    'DM': 'NA', 'LC': 'NA', 'VC': 'NA', 'AG': 'NA', 'KN': 'NA', 'GD': 'NA',
    
    # آمریکای جنوبی - South America
    'BR': 'SA', 'AR': 'SA', 'CL': 'SA', 'CO': 'SA', 'PE': 'SA', 'VE': 'SA',
    'EC': 'SA', 'BO': 'SA', 'PY': 'SA', 'UY': 'SA', 'GY': 'SA', 'SR': 'SA',
    'FK': 'SA', 'GF': 'SA',
    
    # اقیانوسیه - Oceania
    'AU': 'OC', 'NZ': 'OC', 'FJ': 'OC', 'PG': 'OC', 'SB': 'OC', 'VU': 'OC',
    'KI': 'OC', 'MH': 'OC', 'WS': 'OC', 'TO': 'OC', 'TV': 'OC', 'NR': 'OC',
    'PW': 'OC', 'FM': 'OC', 'PF': 'OC', 'NC': 'OC', 'AS': 'OC', 'CK': 'OC',
    'GU': 'OC', 'MP': 'OC', 'NU': 'OC', 'NF': 'OC', 'TK': 'OC', 'WF': 'OC',
    
    # جنوبگان - Antarctica
    'AQ': 'AN', 'BV': 'AN', 'GS': 'AN', 'HM': 'AN', 'TF': 'AN'
}

def cb_continent_list_ipv4(update: Update, context: CallbackContext) -> None:
    """نمایش لیست قاره‌ها برای انتخاب با چیدمان دو به دو"""
    
    # Log available countries for debugging
    logger.info("Available countries in database for continent grouping:")
    all_countries = db.get_ipv4_countries()
    logger.info(f"Total countries: {len(all_countries)}")
    for code, data in all_countries.items():
        if len(data) >= 3 and len(data[2]) > 0:
            logger.info(f"Country: {code}, Name: {data[0]}, IPs: {len(data[2])}")
    
    # چیدمان دو به دو دکمه‌ها با ترتیب خاص
    buttons = [
        [
            InlineKeyboardButton(CONTINENT_MAP['AS'], callback_data='continent_ipv4_AS'),
            InlineKeyboardButton(CONTINENT_MAP['EU'], callback_data='continent_ipv4_EU')
        ],
        [
            InlineKeyboardButton(CONTINENT_MAP['AF'], callback_data='continent_ipv4_AF'),
            InlineKeyboardButton(CONTINENT_MAP['NA'], callback_data='continent_ipv4_NA')
        ],
        [
            InlineKeyboardButton(CONTINENT_MAP['SA'], callback_data='continent_ipv4_SA'),
            InlineKeyboardButton(CONTINENT_MAP['OC'], callback_data='continent_ipv4_OC')
        ],
        [
            InlineKeyboardButton(CONTINENT_MAP['AN'], callback_data='continent_ipv4_AN')
        ],
        [
            InlineKeyboardButton("↩️ بازگشت", callback_data='ipv4_menu')
        ]
    ]
    
    # Use global COUNTRY_TO_CONTINENT mapping that's already defined 
    # at the module level
    
    send_reply(update, "🌎 یک قاره را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))


def cb_show_countries_by_continent_ipv4(update: Update, context: CallbackContext) -> None:
    """نمایش کشورهای یک قاره خاص با چیدمان دو به دو"""
    code = update.callback_query.data.split('_')[2]
    
    # Using the global COUNTRY_TO_CONTINENT mapping
    # that's now defined at the module level
    
    # نام قاره‌ها برای نمایش
    continent_names = {
        'AS': 'آسیا 🌏', 'EU': 'اروپا 🇪🇺', 'AF': 'آفریقا 🌍', 
        'NA': 'آمریکای شمالی 🌎', 'SA': 'آمریکای جنوبی 🌎', 
        'OC': 'اقیانوسیه 🏝️', 'AN': 'جنوبگان 🏔️'
    }
    
    logger.info(f"Finding countries for continent: {code}")
    
    # کشورهای این قاره را پیدا کن
    countries = [k for k, v in COUNTRY_TO_CONTINENT.items() if v == code]
    
    if not countries:
        send_reply(update, f"کشوری برای قاره {continent_names.get(code, code)} ثبت نشده است.")
        return
    
    # تهیه لیست کشورهایی که IP دارند
    countries_with_ips = []
    all_ipv4_countries = db.get_ipv4_countries()
    
    logger.info(f"Available country codes in DB: {list(all_ipv4_countries.keys())}")
    logger.info(f"Countries in this continent: {countries}")
    
    # Special handling for problematic country codes (to prevent duplicates)
    handled_countries = set()
    
    # First handle Saudi Arabia specially if in Asia continent
    if code == 'AS':
        saudi_variants = ['SA', 'KSA', 'SAUDI', 'SAUDI ARABIA', 'SAUDI_ARABIA']
        for variant in saudi_variants:
            if variant in all_ipv4_countries:
                saudi_data = all_ipv4_countries[variant]
                if saudi_data and len(saudi_data) >= 3 and len(saudi_data[2]) > 0:
                    countries_with_ips.append((variant, saudi_data[0], saudi_data[1], len(saudi_data[2])))
                    logger.info(f"Added Saudi Arabia variant: {variant}, {saudi_data[0]}, {len(saudi_data[2])} IPs")
                    # Mark all Saudi variants as handled
                    for sv in saudi_variants:
                        handled_countries.add(sv.upper())
                    break
    
    # Process all other countries
    for country_code in countries:
        # Skip if already handled as a special case
        if country_code.upper() in handled_countries:
            continue
            
        # Try variants of the country code (uppercase, lowercase)
        for code_variant in [country_code, country_code.upper(), country_code.lower()]:
            if code_variant in all_ipv4_countries:
                country_data = all_ipv4_countries[code_variant]
                if country_data and len(country_data) >= 3:
                    country_name, flag, ips = country_data[0], country_data[1], country_data[2]
                    if len(ips) > 0:  # فقط کشورهایی که IP دارند را اضافه کن
                        countries_with_ips.append((code_variant, country_name, flag, len(ips)))
                        logger.info(f"Found country with IPs: {code_variant}, {country_name}, {len(ips)} IPs")
                        handled_countries.add(country_code.upper())
                        break
    
    if not countries_with_ips:
        send_reply(update, f"هیچ کشوری با IP در قاره {continent_names.get(code, code)} یافت نشد.")
        return
    
    # مرتب‌سازی کشورها بر اساس تعداد IP (نزولی)
    countries_with_ips.sort(key=lambda x: x[3], reverse=True)
    
    # ایجاد دکمه‌ها با چیدمان دو به دو
    buttons = []
    row = []
    for i, (country_code, country_name, flag, ip_count) in enumerate(countries_with_ips):
        row.append(InlineKeyboardButton(
            f"{flag} {country_name} ({ip_count})", 
            callback_data=f"country_{country_code}")
        )
        
        # هر دو کشور، یک ردیف جدید
        if i % 2 == 1 or i == len(countries_with_ips) - 1:
            buttons.append(row)
            row = []
    
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='continent_list_ipv4')])
    
    send_reply(update, 
               f"🌍 کشورهای قاره {continent_names.get(code, code)} با IP:\n"
               f"لطفاً یک کشور را انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))


def error_handler(update: object, context: CallbackContext) -> None:
    logger.error("❗Unhandled exception: %s", context.error)
    if isinstance(update, Update) and update.effective_user:
        context.bot.send_message(
            chat_id=update.effective_user.id,
            text="⚠️ متأسفم، خطایی رخ داد. لطفاً دوباره امتحان کنید.")


def cb_admin_manage_users(update: Update, context: CallbackContext) -> None:
    """Show user management panel."""
    buttons = [
        [
            InlineKeyboardButton("➕ افزودن توکن به کاربر",
                                 callback_data='admin_grant_tokens')
        ],
        [
            InlineKeyboardButton("🚫 غیرفعال کردن کاربر",
                                 callback_data='admin_disable_user')
        ],
        [
            InlineKeyboardButton("✅ فعال کردن کاربر",
                                 callback_data='admin_enable_user')
        ],
        [
            InlineKeyboardButton("↩️ بازگشت به پنل ادمین",
                                 callback_data='admin_panel')
        ],
    ]
    send_reply(update,
               "👥 مدیریت کاربران:",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_admin_grant_tokens(update: Update, context: CallbackContext) -> int:
    """Initialize process to add tokens to a user."""
    send_reply(
        update,
        "لطفاً آیدی عددی کاربر و تعداد توکن را وارد کنید (مثال: 1234567 50).")
    return ENTER_NEW_CODE


def enter_grant_tokens(update: Update, context: CallbackContext) -> int:
    try:
        user_id, tokens = map(int, update.message.text.strip().split())
        db.grant_tokens(user_id, tokens)
        send_reply(update,
                   f"✅ {tokens} توکن به کاربر با آیدی {user_id} افزوده شد.")
    except (ValueError, TypeError):
        send_reply(update,
                   "❌ لطفاً یک آیدی عددی معتبر و تعداد توکن صحیح وارد کنید.")
    return ConversationHandler.END


def cb_admin_process_ip(update: Update, context: CallbackContext) -> int:
    send_reply(
        update,
        "لطفاً یک آدرس IPv4 و کشور مربوطه را وارد کنید (مثال: [PING OK] 39.62.163.207 -> 🇵🇰 Pakistan)."
    )
    return ENTER_NEW_IPV4


def process_ipv4_entry(update: Update, context: CallbackContext) -> int:
    try:
        import re
        text = update.message.text.strip()
        ip_address = None
        country_name = None
        flag = None
        
        # الگوی استخراج آدرس IP
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        ip_match = re.search(ip_pattern, text)
        
        if not ip_match:
            send_reply(update, "❌ هیچ آدرس IP معتبری در متن یافت نشد.")
            return ConversationHandler.END
            
        ip_address = ip_match.group(0)
        
        # حالت اول: [PING OK] 39.62.163.207 -> 🇵🇰 Pakistan
        if '->' in text:
            try:
                ip_part, country_part = text.split('->')
                flag, country_name = country_part.strip().split(maxsplit=1)
            except ValueError:
                # اگر فرمت دقیقاً مطابق نبود، سعی می‌کنیم کشور را از API بگیریم
                country_result = get_country_info(ip_address)
                if country_result:
                    country_name, flag = country_result
                else:
                    send_reply(update, "❌ نمی‌توان اطلاعات کشور را تشخیص داد.")
                    return ConversationHandler.END
                    
        # حالت دوم: New IP Found! IP: 188.210.21.97 Country: Germany
        elif 'Country:' in text or 'country:' in text:
            try:
                # استخراج نام کشور از متن
                country_pattern = r'[Cc]ountry:?\s*([A-Za-z\s]+)'
                country_match = re.search(country_pattern, text)
                
                if country_match:
                    country_name = country_match.group(1).strip()
                    
                    # تلاش برای یافتن پرچم کشور
                    country_result = get_country_info(ip_address)
                    if country_result:
                        _, flag = country_result
                    else:
                        flag = "🏳️"  # پرچم پیش‌فرض
                else:
                    # اگر کشور در متن نبود، از API استفاده می‌کنیم
                    country_result = get_country_info(ip_address)
                    if country_result:
                        country_name, flag = country_result
                    else:
                        send_reply(update, "❌ نمی‌توان اطلاعات کشور را تشخیص داد.")
                        return ConversationHandler.END
            except Exception as e:
                send_reply(update, f"❌ خطا در استخراج اطلاعات کشور: {e}")
                return ConversationHandler.END
        
        # حالت سوم: فقط آدرس IP بدون اطلاعات اضافی
        else:
            # دریافت اطلاعات کشور از API
            country_result = get_country_info(ip_address)
            if country_result:
                country_name, flag = country_result
            else:
                send_reply(update, "❌ نمی‌توان اطلاعات کشور را تشخیص داد.")
                return ConversationHandler.END
        
        # افزودن IP به پایگاه داده
        if ip_address and country_name and flag:
            db.add_ipv4_address(country_name.strip(), flag.strip(), ip_address.strip())
            send_reply(update, f"✅ آدرس IPv4 {ip_address} برای کشور {flag} {country_name} افزوده شد.")
        else:
            send_reply(update, "❌ اطلاعات ناقص است. نمی‌توان IP را اضافه کرد.")
            
    except Exception as e:
        send_reply(update, f"❌ مشکلی در پردازش وجود دارد: {e}")
    
    return ConversationHandler.END

def get_country_info(ip_address):
    """دریافت اطلاعات کشور برای یک آدرس IP با استفاده از API"""
    try:
        response = requests.get(f"https://api.iplocation.net/?ip={ip_address}")
        if response.status_code == 200:
            data = response.json()
            country_name = data.get('country_name', 'نامشخص')
            country_code = data.get('country_code', '').upper()
            
            # نگاشت کشورهای خاص
            special_country_codes = {
                "Qatar": "QA", "UAE": "AE", "United Arab Emirates": "AE",
                "Saudi Arabia": "SA", "Iran": "IR", "Iraq": "IQ",
                "Kuwait": "KW", "Bahrain": "BH", "Oman": "OM",
                "Egypt": "EG", "Turkey": "TR", "Russia": "RU",
                "United States": "US", "USA": "US", "Germany": "DE",
                "United Kingdom": "GB", "UK": "GB", "France": "FR",
                "China": "CN", "India": "IN", "Japan": "JP",
                "Canada": "CA", "Pakistan": "PK"
            }
            
            if country_name in special_country_codes:
                country_code = special_country_codes[country_name]
                
            # نگاشت پرچم‌های خاص
            special_flags = {
                "QA": "🇶🇦", "AE": "🇦🇪", "SA": "🇸🇦", "IR": "🇮🇷",
                "IQ": "🇮🇶", "KW": "🇰🇼", "BH": "🇧🇭", "OM": "🇴🇲",
                "EG": "🇪🇬", "TR": "🇹🇷", "RU": "🇷🇺", "US": "🇺🇸",
                "DE": "🇩🇪", "GB": "🇬🇧", "FR": "🇫🇷", "CN": "🇨🇳",
                "IN": "🇮🇳", "JP": "🇯🇵", "CA": "🇨🇦", "PK": "🇵🇰"
            }
            
            flag = "🏳️"  # پرچم پیش‌فرض
            
            if country_code in special_flags:
                flag = special_flags[country_code]
            elif country_code and len(country_code) == 2:
                try:
                    # تبدیل کد کشور به پرچم
                    flag_chars = []
                    for c in country_code:
                        if 'A' <= c <= 'Z':
                            flag_chars.append(chr(ord(c) + 127397))
                    if len(flag_chars) == 2:
                        flag = "".join(flag_chars)
                except Exception:
                    pass
                    
            return country_name, flag
    except Exception:
        pass
    
    return None


def generate_wireguard_config() -> str:
    """تولید پیکربندی وایرگارد."""
    # تولید کلیدهای خصوصی و عمومی
    private_key = ''.join(random.choices('abcdef0123456789', k=44))
    public_key = ''.join(random.choices('abcdef0123456789', k=44))

    # انتخاب تصادفی آدرس سرور و پورت
    server_ip = f"162.159.{random.randint(1, 255)}.{random.randint(1, 255)}"
    port = random.randint(10000, 60000)

    # تولید پیکربندی وایرگارد
    config = f"""[Interface]
PrivateKey = {private_key}
Address = 10.66.66.2/32
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {public_key}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {server_ip}:{port}
PersistentKeepalive = 25
"""
    return config


@require_subscription
def cb_admin_manage_buttons(update: Update, context: CallbackContext) -> None:
    """مدیریت دکمه‌های ربات با امکان مخفی‌سازی یک به یک"""
    # دکمه‌های منوی اصلی
    main_menu_buttons = []
    for button_name, is_disabled in DISABLED_BUTTONS.items():
        status = "🔴 غیرفعال" if is_disabled else "🟢 فعال"
        action = "enable" if is_disabled else "disable"
        button_text = ""

        if button_name == 'generate_ipv6':
            button_text = f"🌐 تولید IPv6: {status}"
        elif button_name == 'get_ipv4':
            button_text = f"📋 لیست IPv4: {status}"
        elif button_name == 'validate_ipv4':
            button_text = f"🔍 اعتبارسنجی IPv4: {status}"
        elif button_name == 'wireguard':
            button_text = f"🔒 وایرگارد: {status}"
        elif button_name == 'user_account':
            button_text = f"👤 حساب کاربری: {status}"
        elif button_name == 'support':
            button_text = f"❓ پشتیبانی: {status}"

        main_menu_buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f'admin_{action}_button_{button_name}')
        ])
    
    # دکمه‌های زیرمنوی IPv4
    sub_ipv4_buttons = []
    # اگر کلیدهای زیرمنو در DISABLED_BUTTONS وجود ندارد، آنها را اضافه کنیم
    if 'ipv4_country_list' not in DISABLED_BUTTONS:
        DISABLED_BUTTONS['ipv4_country_list'] = False
    if 'ipv4_quick_search' not in DISABLED_BUTTONS:
        DISABLED_BUTTONS['ipv4_quick_search'] = False
    if 'ipv4_continent' not in DISABLED_BUTTONS:
        DISABLED_BUTTONS['ipv4_continent'] = False
    if 'ipv4_latest' not in DISABLED_BUTTONS:
        DISABLED_BUTTONS['ipv4_latest'] = False
    
    # ایجاد دکمه‌های زیرمنوی IPv4
    sub_menu_items = [
        ('ipv4_country_list', "📋 مشاهده لیست کشورها"),
        ('ipv4_quick_search', "🔍 جستجوی سریع کشور/IP"),
        ('ipv4_continent', "🌎 دسته‌بندی بر اساس قاره"),
        ('ipv4_latest', "🆕 آخرین IPهای افزوده شده")
    ]
    
    for key, label in sub_menu_items:
        status = "🔴 غیرفعال" if DISABLED_BUTTONS.get(key, False) else "🟢 فعال"
        action = "enable" if DISABLED_BUTTONS.get(key, False) else "disable"
        sub_ipv4_buttons.append([
            InlineKeyboardButton(
                f"{label}: {status}",
                callback_data=f'admin_{action}_button_{key}')
        ])
    
    # تنظیم دکمه‌های نمایش داده شده بر اساس حالت جاری
    current_mode = context.user_data.get('button_management_mode', 'main')
    
    buttons = []
    if current_mode == 'main':
        buttons = main_menu_buttons
        buttons.append([InlineKeyboardButton("📋 مدیریت زیرمنوی IPv4", callback_data='admin_manage_sub_ipv4')])
    elif current_mode == 'sub_ipv4':
        buttons = sub_ipv4_buttons
        buttons.append([InlineKeyboardButton("↩️ بازگشت به مدیریت دکمه‌های اصلی", callback_data='admin_manage_main_buttons')])
    
    buttons.append([InlineKeyboardButton("↩️ بازگشت به پنل ادمین", callback_data='admin_panel')])
    
    title = "🚫 مدیریت دکمه‌های اصلی ربات:" if current_mode == 'main' else "🚫 مدیریت دکمه‌های زیرمنوی IPv4:"
    send_reply(update, title, reply_markup=InlineKeyboardMarkup(buttons))

def cb_admin_manage_sub_ipv4(update: Update, context: CallbackContext) -> None:
    """مدیریت دکمه‌های زیرمنوی IPv4"""
    context.user_data['button_management_mode'] = 'sub_ipv4'
    cb_admin_manage_buttons(update, context)

def cb_admin_manage_main_buttons(update: Update, context: CallbackContext) -> None:
    """بازگشت به مدیریت دکمه‌های اصلی"""
    context.user_data['button_management_mode'] = 'main'
    cb_admin_manage_buttons(update, context)


def cb_admin_toggle_button(update: Update, context: CallbackContext) -> None:
    """فعال/غیرفعال کردن یک دکمه"""
    callback_data = update.callback_query.data
    action, button_name = callback_data.split('_button_')[0].replace(
        'admin_', ''), callback_data.split('_button_')[1]

    if action == 'disable':
        DISABLED_BUTTONS[button_name] = True
        message = f"🚫 دکمه {button_name} غیرفعال شد."
    elif action == 'enable':
        DISABLED_BUTTONS[button_name] = False
        message = f"✅ دکمه {button_name} فعال شد."

    # ذخیره تنظیمات
    save_disabled_buttons()

    # نمایش پیام موفقیت و بازگشت به منوی مدیریت دکمه‌ها
    update.callback_query.answer(message)
    cb_admin_manage_buttons(update, context)


def cb_wireguard(update: Update, context: CallbackContext) -> None:
    """تولید پیکربندی وایرگارد اختصاصی با گزینه‌های متنوع."""
    user_id = update.callback_query.from_user.id

    # بررسی نوع اشتراک و کم کردن توکن در صورت نیاز
    user_data = db.active_users.get(user_id, {})
    if not db.is_user_active(user_id):
        send_reply(update,
                   "❌ اشتراک فعال ندارید. لطفاً ابتدا فعال‌سازی کنید.",
                   reply_markup=main_menu_keyboard(user_id))
        return

    if user_data.get('type') == 'token':
        # کسر توکن برای هر بار استفاده (وایرگارد ۲ توکن نیاز دارد)
        current_tokens = user_data.get('tokens', 0)
        if current_tokens < 2:
            send_reply(
                update,
                "❌ وایرگارد اختصاصی نیاز به حداقل ۲ توکن دارد. توکن کافی ندارید.",
                reply_markup=main_menu_keyboard(user_id))
            return

    # نمایش منوی انتخاب آدرس
    addresses = [
        ("10.10.0.2/32", "محدوده 10.10.x.x"),
        ("10.66.66.2/32", "محدوده 10.66.x.x"),
        ("192.168.100.2/32", "محدوده 192.168.x.x"),
        ("172.16.0.2/32", "محدوده 172.16.x.x")
    ]
    
    buttons = []
    for addr, desc in addresses:
        buttons.append([InlineKeyboardButton(f"{addr} ({desc})", callback_data=f'wg_addr_{addr}')])
    
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='back')])
    
    send_reply(update, 
               "🔒 ساخت کانفیگ وایرگارد اختصاصی\n\n"
               "لطفاً آدرس IP مورد نظر را انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))

def cb_wg_select_address(update: Update, context: CallbackContext) -> None:
    """انتخاب آدرس IP برای کانفیگ وایرگارد"""
    user_id = update.callback_query.from_user.id
    addr = update.callback_query.data.replace('wg_addr_', '')
    
    # ذخیره آدرس انتخاب شده
    context.user_data['wg_address'] = addr
    
    # نمایش منوی انتخاب پورت
    ports = [
        (53, "DNS"),
        (80, "HTTP"),
        (443, "HTTPS"),
        (8080, "Proxy"),
        (51820, "WireGuard Default"),
        (1194, "OpenVPN Default")
    ]
    
    buttons = []
    row = []
    for i, (port, desc) in enumerate(ports):
        row.append(InlineKeyboardButton(f"{port} ({desc})", callback_data=f'wg_port_{port}'))
        if i % 2 == 1:
            buttons.append(row)
            row = []
    
    if row:  # اضافه کردن آخرین ردیف اگر ناقص باشد
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='wireguard')])
    
    send_reply(update, 
               "🔒 ساخت کانفیگ وایرگارد اختصاصی\n\n"
               f"✅ آدرس انتخاب شده: `{addr}`\n\n"
               "لطفاً پورت مورد نظر را انتخاب کنید:",
               parse_mode=ParseMode.MARKDOWN,
               reply_markup=InlineKeyboardMarkup(buttons))

def cb_wg_select_port(update: Update, context: CallbackContext) -> None:
    """انتخاب پورت برای کانفیگ وایرگارد"""
    user_id = update.callback_query.from_user.id
    port = int(update.callback_query.data.replace('wg_port_', ''))
    
    # ذخیره پورت انتخاب شده
    context.user_data['wg_port'] = port
    
    # انتخاب DNS
    dns_options = [
        ("1.1.1.1,8.8.8.8", "Cloudflare + Google"),
        ("8.8.8.8,8.8.4.4", "Google"),
        ("9.9.9.9,149.112.112.112", "Quad9"),
        ("208.67.222.222,208.67.220.220", "OpenDNS")
    ]
    
    buttons = []
    for dns, desc in dns_options:
        buttons.append([InlineKeyboardButton(f"{desc}", callback_data=f'wg_dns_{dns}')])
    
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data=f'wg_addr_{context.user_data["wg_address"]}')])
    
    send_reply(update, 
               "🔒 ساخت کانفیگ وایرگارد اختصاصی\n\n"
               f"✅ آدرس انتخاب شده: `{context.user_data['wg_address']}`\n"
               f"✅ پورت انتخاب شده: `{port}`\n\n"
               "لطفاً DNS مورد نظر را انتخاب کنید:",
               parse_mode=ParseMode.MARKDOWN,
               reply_markup=InlineKeyboardMarkup(buttons))

def cb_wg_select_dns(update: Update, context: CallbackContext) -> None:
    """انتخاب DNS برای کانفیگ وایرگارد و تولید نهایی کانفیگ"""
    user_id = update.callback_query.from_user.id
    dns = update.callback_query.data.replace('wg_dns_', '')
    
    # ذخیره DNS انتخاب شده
    context.user_data['wg_dns'] = dns
    
    # کسر توکن‌ها (اگر حساب توکنی باشد)
    user_data = db.active_users.get(user_id, {})
    if user_data.get('type') == 'token':
        # کم کردن ۲ توکن و به‌روزرسانی پایگاه داده
        db.active_users[user_id]['tokens'] = user_data.get('tokens', 0) - 2
        db.save_database()
    
    # انتخاب endpoint مناسب
    endpoints = db.get_endpoints()
    if not endpoints:
        # اگر endpoint تعریف نشده باشد، یک نمونه پیش‌فرض استفاده کنیم
        endpoint = "162.159.192.1"
    else:
        import random
        endpoint = random.choice(endpoints)
    
    # تولید کانفیگ وایرگارد با تنظیمات انتخاب شده
    from wg import WireguardConfig
    wg = WireguardConfig()
    
    private_key = wg.generate_private_key()
    public_key = wg.generate_public_key()
    
    # انتخاب MTU تصادفی از بین مقادیر معمول
    mtu = random.choice([1280, 1380, 1420, 1480])
    
    # تنظیم PersistentKeepalive
    keepalive = random.choice([15, 25, 30, 40])
    
    # ساخت کانفیگ با تنظیمات سفارشی
    config = f"""[Interface]
PrivateKey = {private_key}
Address = {context.user_data['wg_address']}
DNS = {context.user_data['wg_dns']}
MTU = {mtu}

[Peer]
PublicKey = {public_key}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = {endpoint}:{context.user_data['wg_port']}
PersistentKeepalive = {keepalive}
"""
    
    # تلاش برای دریافت اطلاعات کشور endpoint
    try:
        import requests
        response = requests.get(f"https://api.iplocation.net/?ip={endpoint}")
        if response.status_code == 200:
            country_data = response.json()
            country = country_data.get('country_name', 'نامشخص')
        else:
            country = 'نامشخص'
    except Exception:
        country = 'نامشخص'
    
    # نمایش کانفیگ به کاربر
    message = f"✅ کانفیگ وایرگارد با موفقیت ایجاد شد!\n\n"
    message += f"📋 اطلاعات کانفیگ:\n"
    message += f"• 🌐 آدرس IP: `{context.user_data['wg_address']}`\n"
    message += f"• 🔌 پورت: `{context.user_data['wg_port']}`\n"
    message += f"• 🔍 DNS: `{context.user_data['wg_dns']}`\n"
    message += f"• 📏 MTU: `{mtu}`\n"
    message += f"• 💓 KeepAlive: `{keepalive}`\n"
    message += f"• 🌍 کشور سرور: `{country}`\n"
    message += f"• 🖥️ Endpoint: `{endpoint}:{context.user_data['wg_port']}`\n\n"
    
    # نمایش کانفیگ با فرمت مناسب برای کپی کردن
    message += "```\n" + config + "\n```"
    
    # نمایش تعداد توکن‌های باقی‌مانده برای کاربران توکنی
    if user_data.get('type') == 'token':
        remaining_tokens = db.active_users[user_id].get('tokens', 0)
        message += f"\n\n🔄 توکن‌های باقی‌مانده: {remaining_tokens}"
    
    buttons = [
        [InlineKeyboardButton("🔄 ساخت کانفیگ جدید", callback_data='wireguard')],
        [InlineKeyboardButton("↩️ بازگشت به منوی اصلی", callback_data='back')]
    ]
    
    send_reply(update,
               message,
               parse_mode=ParseMode.MARKDOWN,
               reply_markup=InlineKeyboardMarkup(buttons))


def main() -> None:
    # مکانیزم قفل برای جلوگیری از اجرای چندگانه ربات
    import os
    import sys
    import socket
    import fcntl
    import struct
    
    # ایجاد سوکت برای قفل کردن
    lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    
    try:
        # تلاش برای قفل کردن فرآیند
        lock_socket.bind('\0telegram_bot_lock')
        # قفل فایل توصیف‌کننده برای اطمینان از انحصار
        fcntl.lockf(lock_socket.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (socket.error, IOError):
        logger.error("یک نمونه دیگر از ربات در حال اجراست. خروج...")
        sys.exit(1)
    
    # عادی‌سازی کلیدهای کشورها برای حل مشکل عربستان و سایر کشورها
    normalized_keys = {}
    # ادغام کلیدهای تکراری کشورها با نام‌های مشابه
    for country_code in list(db.ipv4_data.keys()):
        normalized_key = country_code.lower().replace(' ', '_')
        if normalized_key in normalized_keys:
            # این کشور قبلاً با کلید مشابهی اضافه شده است
            primary_key = normalized_keys[normalized_key]
            if country_code != primary_key:
                # ادغام داده‌ها
                old_name, old_flag, old_ips = db.ipv4_data[primary_key]
                _, _, new_ips = db.ipv4_data[country_code]

                # ادغام لیست آی‌پی‌ها و حذف موارد تکراری
                merged_ips = old_ips.copy()
                for ip in new_ips:
                    if ip not in merged_ips:
                        merged_ips.append(ip)

                # به‌روزرسانی داده‌ها
                db.ipv4_data[primary_key] = (old_name, old_flag, merged_ips)
                del db.ipv4_data[country_code]
                logger.info(f"کشور {country_code} با {primary_key} ادغام شد")
        else:
            normalized_keys[normalized_key] = country_code

    # ذخیره تغییرات
    db.save_database()

    # شروع بکاپ‌گیری خودکار
    backup_mgr.start_backup_thread()

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler(
        'help', support_command))  # Changed help command handler
    dp.add_handler(CommandHandler('stop',
                                  stop_command))  # اضافه کردن دستور توقف
    dp.add_handler(CallbackQueryHandler(
        support_command, pattern='^support$'))  #Added support callback handler
    dp.add_handler(CallbackQueryHandler(
        cb_wireguard, pattern='^wireguard$'))  #اضافه کردن هندلر وایرگارد

    # کانورسیشن هندلرها
    activate_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_activate, pattern='^activate$')],
        states={
            ENTER_ACTIVATION: [
                MessageHandler(Filters.text & ~Filters.command,
                               enter_activation)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    addcode_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_add_code, pattern='^admin_add_code$')
        ],
        states={
            CHOOSE_CODE_TYPE: [
                CallbackQueryHandler(cb_code_type_selected,
                                     pattern='^code_type_')
            ],
            ENTER_TOKEN_COUNT: [
                MessageHandler(Filters.text & ~Filters.command,
                               enter_token_count)
            ],
            ENTER_NEW_CODE:
            [MessageHandler(Filters.text & ~Filters.command, enter_new_code)]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    addipv4_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_add_ipv4, pattern='^admin_add_ipv4$')
        ],
        states={
            ENTER_COUNTRY_NAME: [
                MessageHandler(Filters.text & ~Filters.command,
                               enter_country_name)
            ],
            ENTER_COUNTRY_FLAG: [
                MessageHandler(Filters.text & ~Filters.command,
                               enter_country_flag)
            ],
            ENTER_NEW_IPV4:
            [MessageHandler(Filters.text & ~Filters.command, enter_new_ipv4)],
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # Add grant tokens conversation handler
    grant_tokens_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_grant_tokens,
                                 pattern='^admin_grant_tokens$')
        ],
        states={
            ENTER_NEW_CODE: [
                MessageHandler(Filters.text & ~Filters.command,
                               enter_grant_tokens)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # Add process IP conversation handler
    process_ip_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_process_ip,
                                 pattern='^admin_process_ip$')
        ],
        states={
            ENTER_NEW_IPV4: [
                MessageHandler(Filters.text & ~Filters.command,
                               process_ipv4_entry)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # کانورسیشن هندلر برای غیرفعال کردن کاربر
    disable_user_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_disable_user,
                                 pattern='^admin_disable_user$')
        ],
        states={
            ENTER_NEW_CODE:
            [MessageHandler(Filters.text & ~Filters.command, disable_user)]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # کانورسیشن هندلر برای فعال کردن کاربر
    enable_user_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_enable_user,
                                 pattern='^admin_enable_user$')
        ],
        states={
            ENTER_NEW_CODE:
            [MessageHandler(Filters.text & ~Filters.command, enable_user)]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # کانورسیشن هندلر برای اعتبارسنجی IPv4
    validate_ipv4_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_validate_ipv4, pattern='^validate_ipv4$')
        ],
        states={
            ENTER_IP_FOR_VALIDATION: [
                MessageHandler(Filters.text & ~Filters.command,
                               validate_ipv4_address)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # کانورسیشن هندلر برای پیام همگانی
    broadcast_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_broadcast,
                                 pattern='^admin_broadcast$')
        ],
        states={
            ENTER_BROADCAST_MESSAGE: [
                MessageHandler(Filters.text & ~Filters.command,
                               enter_broadcast_message)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # کانورسیشن هندلر برای تنظیم کانال اجباری
    set_channel_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_set_channel,
                                 pattern='^admin_set_channel$')
        ],
        states={
            ENTER_CHANNEL_LINK: [
                MessageHandler(Filters.text & ~Filters.command,
                               enter_channel_link)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # کانورسیشن هندلر برای پردازش گروهی IP
    batch_process_ip_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_batch_process_ip,
                                 pattern='^admin_batch_process_ip$')
        ],
        states={
            ENTER_BATCH_IPS: [
                MessageHandler(Filters.text & ~Filters.command,
                               process_batch_ips)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )

    # استفاده از حالت تعریف شده برای افزودن گروهی Endpoint ها
    
    # ثبت همه کانورسیشن هندلرها
    dp.add_handler(activate_conv)
    dp.add_handler(addcode_conv)
    dp.add_handler(addipv4_conv)
    dp.add_handler(grant_tokens_conv)
    dp.add_handler(process_ip_conv)
    dp.add_handler(disable_user_conv)
    dp.add_handler(enable_user_conv)
    dp.add_handler(validate_ipv4_conv)
    dp.add_handler(broadcast_conv)
    dp.add_handler(set_channel_conv)
    dp.add_handler(batch_process_ip_conv)
    
    # اضافه کردن کانورسیشن هندلر برای افزودن گروهی Endpoint ها
    batch_endpoints_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cb_admin_batch_add_endpoints,
                                pattern='^admin_batch_add_endpoints$')
        ],
        states={
            ENTER_BATCH_ENDPOINTS: [
                MessageHandler(Filters.text & ~Filters.command,
                            handle_batch_endpoints)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cb_back, pattern='^back$'),
            CommandHandler('stop', stop_command)
        ],
    )
    dp.add_handler(batch_endpoints_conv)
    
    # هندلرهای جدید سیستم کانال اجباری
    dp.add_handler(CallbackQueryHandler(cb_check_membership, pattern='^check_membership$'))
    dp.add_handler(CallbackQueryHandler(cb_channel_help, pattern='^channel_help$'))
    
    # هندلرهای منوی ادمین بهبود یافته
    dp.add_handler(CallbackQueryHandler(cb_admin_menu_main, pattern='^admin_menu_main$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_menu_ip, pattern='^admin_menu_ip$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_menu_subscription, pattern='^admin_menu_subscription$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_menu_users, pattern='^admin_menu_users$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_menu_wireguard, pattern='^admin_menu_wireguard$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_menu_settings, pattern='^admin_menu_settings$'))
    
    # هندلرهای سیستم مدیریت دکمه‌های بهبود یافته
    dp.add_handler(CallbackQueryHandler(cb_admin_manage_sub_ipv4, pattern='^admin_manage_sub_ipv4$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_manage_main_buttons, pattern='^admin_manage_main_buttons$'))
    
    # هندلرهای تأیید افزودن IP گروهی
    dp.add_handler(CallbackQueryHandler(cb_confirm_add_batch_ips, pattern='^confirm_add_batch_ips$'))
    dp.add_handler(CallbackQueryHandler(cb_confirm_add_batch_ips_notify, pattern='^confirm_add_batch_ips_notify$'))
    dp.add_handler(CallbackQueryHandler(cb_cancel_add_batch_ips, pattern='^cancel_add_batch_ips$'))
    
    # هندلرهای وایرگارد بهبود یافته
    dp.add_handler(CallbackQueryHandler(cb_wg_select_address, pattern='^wg_addr_'))
    dp.add_handler(CallbackQueryHandler(cb_wg_select_port, pattern='^wg_port_'))
    dp.add_handler(CallbackQueryHandler(cb_wg_select_dns, pattern='^wg_dns_'))
    
    # هندلر برای صفحه‌بندی آدرس‌های IP
    dp.add_handler(CallbackQueryHandler(cb_country_ips, pattern='^country_page_'))

    # سایر هندلرها
    dp.add_handler(
        CallbackQueryHandler(cb_admin_panel, pattern='^admin_panel$'))
    dp.add_handler(CallbackQueryHandler(cb_generate,
                                        pattern='^generate_ipv6$'))
    dp.add_handler(CallbackQueryHandler(cb_generate_option, pattern='^gen_'))
    dp.add_handler(CallbackQueryHandler(cb_get_ipv4, pattern='^get_ipv4$'))
    dp.add_handler(CallbackQueryHandler(cb_country_ips, pattern='^country_'))
    dp.add_handler(
        CallbackQueryHandler(cb_admin_stats, pattern='^admin_stats$'))
    dp.add_handler(CallbackQueryHandler(cb_back, pattern='^back$'))
    dp.add_handler(
        CallbackQueryHandler(cb_admin_shutdown, pattern='^admin_shutdown$'))
    dp.add_handler(CallbackQueryHandler(lambda u, c: None, pattern='^noop$'))
    dp.add_handler(
        CallbackQueryHandler(cb_user_account, pattern='^user_account$'))
    dp.add_handler(
        CallbackQueryHandler(cb_subscription_status,
                             pattern='^subscription_status$'))
    dp.add_handler(
        CallbackQueryHandler(cb_admin_startup, pattern='^admin_startup$'))
    dp.add_handler(
        CallbackQueryHandler(cb_add_validated_ip,
                             pattern='^add_validated_ip_'))
                             
    # هندلرهای جدید برای منوی IPv4
    dp.add_handler(CallbackQueryHandler(cb_ipv4_menu, pattern='^ipv4_menu$'))
    dp.add_handler(CallbackQueryHandler(cb_quick_search_ipv4, pattern='^quick_search_ipv4$'))
    dp.add_handler(CallbackQueryHandler(cb_latest_ips_ipv4, pattern='^latest_ips_ipv4$'))
    dp.add_handler(CallbackQueryHandler(cb_continent_list_ipv4, pattern='^continent_list_ipv4$'))
    dp.add_handler(CallbackQueryHandler(cb_show_countries_by_continent_ipv4, pattern='^continent_ipv4_'))
    
    # هندلر برای جستجوی متنی
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command & ~Filters.update.edited_message, 
                                  handle_search_input_ipv4, 
                                  pass_user_data=True))

    # هندلرهای جدید برای درخواست و تایید/رد IP
    dp.add_handler(
        CallbackQueryHandler(cb_request_add_ip, pattern='^request_add_ip_'))
    dp.add_handler(CallbackQueryHandler(cb_approve_ip, pattern='^approve_ip_'))
    dp.add_handler(CallbackQueryHandler(cb_reject_ip, pattern='^reject_ip_'))

    # هندلرهای مدیریت کاربران
    dp.add_handler(
        CallbackQueryHandler(cb_admin_manage_users,
                             pattern='^admin_manage_users$'))

    # هندلرهای مدیریت لوکیشن‌ها
    dp.add_handler(
        CallbackQueryHandler(cb_admin_manage_locations,
                             pattern='^admin_manage_locations$'))

    # هندلرهای مدیریت IPv4
    dp.add_handler(
        CallbackQueryHandler(cb_manage_ipv4, pattern='^manage_ipv4$'))
    dp.add_handler(
        CallbackQueryHandler(cb_disable_ipv4_menu,
                             pattern='^disable_ipv4_menu$'))
    dp.add_handler(
        CallbackQueryHandler(cb_enable_ipv4_menu,
                             pattern='^enable_ipv4_menu$'))
    dp.add_handler(
        CallbackQueryHandler(cb_disable_ipv4, pattern='^disable_ipv4_'))
    dp.add_handler(
        CallbackQueryHandler(cb_enable_ipv4, pattern='^enable_ipv4_'))
    dp.add_handler(
        CallbackQueryHandler(cb_manage_ipv4_buttons,
                             pattern='^manage_ipv4_buttons$'))
    dp.add_handler(
        CallbackQueryHandler(cb_toggle_ipv4, pattern='^toggle_ipv4_'))
        
    # هندلر برای مشاهده کدهای فعال‌سازی
    dp.add_handler(
        CallbackQueryHandler(cb_admin_view_codes, pattern='^admin_view_codes$'))

    # هندلرهای مدیریت IPv6
    dp.add_handler(
        CallbackQueryHandler(cb_manage_ipv6, pattern='^manage_ipv6$'))
    dp.add_handler(
        CallbackQueryHandler(cb_disable_ipv6_menu,
                             pattern='^disable_ipv6_menu$'))
    dp.add_handler(
        CallbackQueryHandler(cb_enable_ipv6_menu,
                             pattern='^enable_ipv6_menu$'))
    dp.add_handler(
        CallbackQueryHandler(cb_disable_ipv6, pattern='^disable_ipv6_'))
    dp.add_handler(
        CallbackQueryHandler(cb_enable_ipv6, pattern='^enable_ipv6_'))
    dp.add_handler(
        CallbackQueryHandler(cb_manage_ipv6_buttons,
                             pattern='^manage_ipv6_buttons$'))
    dp.add_handler(
        CallbackQueryHandler(cb_toggle_ipv6, pattern='^toggle_ipv6_'))

    # هندلرهای حذف آدرس IP
    dp.add_handler(
        CallbackQueryHandler(cb_admin_remove_ipv4,
                             pattern='^admin_remove_ipv4$'))
    dp.add_handler(
        CallbackQueryHandler(cb_remove_country_ips,
                             pattern='^remove_country_'))
    dp.add_handler(CallbackQueryHandler(cb_remove_ip, pattern='^remove_ip_'))

    # هندلرهای مدیریت بکاپ
    dp.add_handler(
        CallbackQueryHandler(cb_admin_manage_backups,
                             pattern='^admin_manage_backups$'))
    dp.add_handler(
        CallbackQueryHandler(cb_create_backup,
                             pattern='^create_backup$'))
    dp.add_handler(
        CallbackQueryHandler(cb_restore_last_backup,
                             pattern='^restore_last_backup$'))
    dp.add_handler(
        CallbackQueryHandler(cb_toggle_auto_backup,
                             pattern='^(enable|disable)_auto_backup$'))
    dp.add_handler(
        CallbackQueryHandler(cb_send_latest_backup,
                             pattern='^send_latest_backup$'))

    # هندلر دکمه‌های غیرفعال
    dp.add_handler(
        CallbackQueryHandler(cb_disabled_button, pattern='^disabled_button$'))

    # هندلرهای مدیریت دکمه‌ها
    dp.add_handler(
        CallbackQueryHandler(cb_admin_manage_buttons,
                             pattern='^admin_manage_buttons$'))
    dp.add_handler(
        CallbackQueryHandler(cb_admin_toggle_button,
                             pattern='^admin_(enable|disable)_button_'))

    # هندلر خطاها
    dp.add_error_handler(error_handler)

    logger.info("Bot start✅✅✅")
    # اضافه کردن مدیریت خطا و سیگنال
    def cleanup_and_exit(signum=None, frame=None):
        logger.info("در حال خروج و پاکسازی منابع...")
        backup_mgr.stop_backup_thread()
        updater.stop()
        logger.info("ربات با موفقیت متوقف شد")
    
    # ثبت تابع پاکسازی برای سیگنال‌های خروج
    import signal
    signal.signal(signal.SIGINT, cleanup_and_exit)
    signal.signal(signal.SIGTERM, cleanup_and_exit)
    
    try:
        logger.info("Bot started successfully ✅")
        updater.start_polling(clean=True)
        updater.idle()
    except Exception as e:
        logger.error(f"خطای غیرمنتظره: {e}")
        cleanup_and_exit()
    finally:
        # اطمینان از اجرای پاکسازی
        cleanup_and_exit()


def cb_admin_shutdown(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        send_reply(
            update,
            "🤖 ربات در حال بروزرسانی و بهینه شدن میباشد بعدا تلاش کنید.")

        # Shutdown code here, temporarily disable message processing
        def shutdown():
            # context.bot.updater.stop()  Removed this line
            logger.info("Bot has been shutdown by admin.")

        if update.message:
            update.message.reply_text(
                "ربات خاموش شد. برای راه‌اندازی مجدد دوباره /start بزنید.")
        threading.Thread(target=shutdown).start()
    else:
        send_reply(update, "شما اجازه این کار را ندارید.")


def cb_admin_remove_ipv4(update: Update, context: CallbackContext) -> int:
    """شروع فرآیند حذف IPv4."""
    country_ips = db.get_ipv4_countries()
    if not country_ips:
        send_reply(update, "❌ هیچ IPv4 برای حذف وجود ندارد.")
        return ConversationHandler.END

    buttons = []
    has_countries_with_ips = False

    for country_code, (country, flag, ips) in country_ips.items():
        # فقط کشورهایی که دارای آی‌پی هستند را نمایش می‌دهیم
        if len(ips) > 0:
            has_countries_with_ips = True
            buttons.append([
                InlineKeyboardButton(
                    f"{flag} {country} ({len(ips)})",
                    callback_data=f"remove_country_{country_code}")
            ])

    if not has_countries_with_ips:
        send_reply(update, "❌ هیچ کشوری با آدرس IP وجود ندارد.")
        return ConversationHandler.END

    buttons.append(
        [InlineKeyboardButton("↩️ بازگشت", callback_data='admin_panel')])
    send_reply(update,
               "🌍 انتخاب کشور برای حذف آدرس:",
               reply_markup=InlineKeyboardMarkup(buttons))
    return ENTER_NEW_CODE  # استفاده از یک حالت موجود برای ادامه مکالمه


def cb_remove_country_ips(update: Update, context: CallbackContext) -> int:
    """نمایش آدرس‌های IP یک کشور برای حذف."""
    country_code = update.callback_query.data.split('_')[2]
    ips = db.get_ips_by_country(country_code)

    if not ips:
        send_reply(update, "❌ هیچ آدرسی برای این کشور یافت نشد.")
        return ConversationHandler.END

    context.user_data['remove_country'] = country_code

    buttons = []
    for ip in ips:
        buttons.append(
            [InlineKeyboardButton(f"❌ {ip}", callback_data=f"remove_ip_{ip}")])

    buttons.append(
        [InlineKeyboardButton("↩️ بازگشت", callback_data='admin_remove_ipv4')])
    send_reply(update,
               "📡 انتخاب آدرس برای حذف:",
               reply_markup=InlineKeyboardMarkup(buttons))
    return ENTER_NEW_CODE


def cb_remove_ip(update: Update, context: CallbackContext) -> int:
    """حذف یک آدرس IP خاص."""
    ip = update.callback_query.data.split('_')[2]
    country_code = context.user_data.get('remove_country')

    if country_code and ip:
        # حذف IP از پایگاه داده
        if country_code in db.ipv4_data:
            # استفاده از تابع remove_ipv4_address برای حذف صحیح
            result = db.remove_ipv4_address(country_code, ip)
            if result:
                send_reply(update, f"✅ آدرس {ip} با موفقیت حذف شد.")
            else:
                send_reply(update, "❌ آدرس مورد نظر یافت نشد.")
        else:
            send_reply(update, "❌ کشور مورد نظر یافت نشد.")
    else:
        send_reply(update, "❌ خطا در حذف آدرس.")

    # بازگشت به پنل ادمین
    buttons = [[
        InlineKeyboardButton("↩️ بازگشت به پنل ادمین",
                             callback_data='admin_panel')
    ]]
    update.callback_query.message.reply_text(
        "عملیات حذف به پایان رسید.",
        reply_markup=InlineKeyboardMarkup(buttons))

    return ConversationHandler.END


def cb_admin_manage_locations(update: Update,
                              context: CallbackContext) -> None:
    """مدیریت لوکیشن‌ها."""
    locations = db.get_all_locations()

    # نمایش وضعیت فعلی همه لوکیشن‌ها
    location_status = "🌐 وضعیت لوکیشن‌ها:\n\n"

    # بررسی آیا لوکیشنی وجود دارد
    if not locations:
        location_status = "ℹ️ هیچ لوکیشنی موجود نیست. ابتدا با افزودن IP ها از طریق پنل ادمین لوکیشن‌ها را ایجاد کنید."
    else:
        for country_code, info in locations.items():
            ipv4_status = "❌ غیرفعال" if info["ipv4_disabled"] else "✅ فعال"
            ipv6_status = "❌ غیرفعال" if info["ipv6_disabled"] else "✅ فعال"

            location_status += f"{info['flag']} {info['name']}:\n"
            location_status += f"  • IPv4: {ipv4_status} (تعداد: {info['ipv4_count']})\n"
            location_status += f"  • IPv6: {ipv6_status} (تعداد: {info['ipv6_count']})\n"

    buttons = [
        [
            InlineKeyboardButton("📡 مدیریت تک به تک دکمه‌های IPv4",
                                 callback_data='manage_ipv4_buttons')
        ],
        [
            InlineKeyboardButton("🌐 مدیریت تک به تک دکمه‌های IPv6",
                                 callback_data='manage_ipv6_buttons')
        ],
        [
            InlineKeyboardButton("📡 مدیریت گروهی IPv4",
                                 callback_data='manage_ipv4')
        ],
        [
            InlineKeyboardButton("🌐 مدیریت گروهی IPv6",
                                 callback_data='manage_ipv6')
        ],
        [
            InlineKeyboardButton("↩️ بازگشت به پنل ادمین",
                                 callback_data='admin_panel')
        ],
    ]
    send_reply(update,
               location_status,
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_manage_ipv4(update: Update, context: CallbackContext) -> None:
    """نمایش منوی مدیریت IPv4."""
    buttons = [
        [
            InlineKeyboardButton("❌ غیرفعال کردن IPv4",
                                 callback_data='disable_ipv4_menu')
        ],
        [
            InlineKeyboardButton("✅ فعال کردن IPv4",
                                 callback_data='enable_ipv4_menu')
        ],
        [
            InlineKeyboardButton("↩️ بازگشت",
                                 callback_data='admin_manage_locations')
        ],
    ]
    send_reply(update,
               "📡 مدیریت IPv4:",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_manage_ipv6(update: Update, context: CallbackContext) -> None:
    """نمایش منوی مدیریت IPv6."""
    buttons = [
        [
            InlineKeyboardButton("❌ غیرفعال کردن IPv6",
                                 callback_data='disable_ipv6_menu')
        ],
        [
            InlineKeyboardButton("✅ فعال کردن IPv6",
                                 callback_data='enable_ipv6_menu')
        ],
        [
            InlineKeyboardButton("↩️ بازگشت",
                                 callback_data='admin_manage_locations')
        ],
    ]
    send_reply(update,
               "🌐 مدیریت IPv6:",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_disable_ipv4_menu(update: Update, context: CallbackContext) -> None:
    """نمایش منوی غیرفعال کردن IPv4 لوکیشن‌ها."""
    locations = db.get_all_locations()

    # ایجاد دکمه‌های کشورهای با IPv4 فعال
    buttons = []
    for country_code, info in locations.items():
        if not info["ipv4_disabled"] and info["ipv4_count"] > 0:
            buttons.append([
                InlineKeyboardButton(
                    f"{info['flag']} {info['name']} ({info['ipv4_count']} IP)",
                    callback_data=f'disable_ipv4_{country_code}')
            ])

    if not buttons:
        send_reply(update, "❌ هیچ لوکیشن با IPv4 فعالی یافت نشد.")
        return

    buttons.append(
        [InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv4')])
    send_reply(update,
               "🌍 کشور مورد نظر برای غیرفعال کردن IPv4 را انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_enable_ipv4_menu(update: Update, context: CallbackContext) -> None:
    """نمایش منوی فعال کردن IPv4 لوکیشن‌ها."""
    locations = db.get_all_locations()

    # ایجاد دکمه‌های کشورهای با IPv4 غیرفعال
    buttons = []
    for country_code, info in locations.items():
        if info["ipv4_disabled"] and info["ipv4_count"] > 0:
            buttons.append([
                InlineKeyboardButton(
                    f"{info['flag']} {info['name']} ({info['ipv4_count']} IP)",
                    callback_data=f'enable_ipv4_{country_code}')
            ])

    if not buttons:
        send_reply(update, "❌ هیچ لوکیشن با IPv4 غیرفعالی یافت نشد.")
        return

    buttons.append(
        [InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv4')])
    send_reply(update,
               "🌍 کشور مورد نظر برای فعال کردن IPv4 را انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_disable_ipv6_menu(update: Update, context: CallbackContext) -> None:
    """نمایش منوی غیرفعال کردن IPv6 لوکیشن‌ها."""
    locations = db.get_all_locations()

    # ایجاد دکمه‌های کشورهای با IPv6 فعال
    buttons = []
    for country_code, info in locations.items():
        if not info["ipv6_disabled"]:
            buttons.append([
                InlineKeyboardButton(
                    f"{info['flag']} {info['name']} ({info['ipv6_count']} IP)",
                    callback_data=f'disable_ipv6_{country_code}')
            ])

    if not buttons:
        send_reply(update, "❌ هیچ لوکیشن با IPv6 فعالی یافت نشد.")
        return

    buttons.append(
        [InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv6')])
    send_reply(update,
               "🌍 کشور مورد نظر برای غیرفعال کردن IPv6 را انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_enable_ipv6_menu(update: Update, context: CallbackContext) -> None:
    """نمایش منوی فعال کردن IPv6 لوکیشن‌ها."""
    locations = db.get_all_locations()

    # ایجاد دکمه‌های کشورهای با IPv6 غیرفعال
    buttons = []
    for country_code, info in locations.items():
        if info["ipv6_disabled"]:
            buttons.append([
                InlineKeyboardButton(
                    f"{info['flag']} {info['name']} ({info['ipv6_count']} IP)",
                    callback_data=f'enable_ipv6_{country_code}')
            ])

    if not buttons:
        send_reply(update, "❌ هیچ لوکیشن با IPv6 غیرفعالی یافت نشد.")
        return

    buttons.append(
        [InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv6')])
    send_reply(update,
               "🌍 کشور مورد نظر برای فعال کردن IPv6 را انتخاب کنید:",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_disable_ipv4(update: Update, context: CallbackContext) -> None:
    """غیرفعال کردن IPv4 یک لوکیشن خاص."""
    country_code = update.callback_query.data.split('_')[2]
    result = db.disable_location(country_code, "ipv4")

    if result:
        # دریافت اطلاعات کشور برای نمایش نام آن
        country_data = db.get_ipv4_countries().get(country_code)
        country_name = country_data[0] if country_data else country_code
        flag = country_data[1] if country_data else "🏳️"

        send_reply(
            update,
            f"✅ IPv4 لوکیشن {flag} {country_name} با موفقیت غیرفعال شد.")
    else:
        send_reply(update, "❌ خطا در غیرفعال کردن IPv4 لوکیشن.")

    # بازگشت به منوی مدیریت IPv4
    buttons = [[
        InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv4')
    ]]
    update.callback_query.message.reply_text(
        "عملیات انجام شد.", reply_markup=InlineKeyboardMarkup(buttons))


def cb_enable_ipv4(update: Update, context: CallbackContext) -> None:
    """فعال کردن IPv4 یک لوکیشن خاص."""
    country_code = update.callback_query.data.split('_')[2]
    result = db.enable_location(country_code, "ipv4")

    if result:
        # دریافت اطلاعات کشور برای نمایش نام آن
        country_data = db.get_ipv4_countries().get(country_code)
        country_name = country_data[0] if country_data else country_code
        flag = country_data[1] if country_data else "🏳️"

        send_reply(update,
                   f"✅ IPv4 لوکیشن {flag} {country_name} با موفقیت فعال شد.")
    else:
        send_reply(update, "❌ خطا در فعال کردن IPv4 لوکیشن.")

    # بازگشت به منوی مدیریت IPv4
    buttons = [[
        InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv4')
    ]]
    update.callback_query.message.reply_text(
        "عملیات انجام شد.", reply_markup=InlineKeyboardMarkup(buttons))


def cb_disable_ipv6(update: Update, context: CallbackContext) -> None:
    """غیرفعال کردن IPv6 یک لوکیشن خاص."""
    country_code = update.callback_query.data.split('_')[2]
    result = db.disable_location(country_code, "ipv6")

    if result:
        # دریافت اطلاعات کشور برای نمایش نام آن
        country_data = db.get_ipv4_countries().get(country_code)
        country_name = country_data[0] if country_data else country_code
        flag = country_data[1] if country_data else "🏳️"

        send_reply(
            update,
            f"✅ IPv6 لوکیشن {flag} {country_name} با موفقیت غیرفعال شد.")
    else:
        send_reply(update, "❌ خطا در غیرفعال کردن IPv6 لوکیشن.")

    # بازگشت به منوی مدیریت IPv6
    buttons = [[
        InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv6')
    ]]
    update.callback_query.message.reply_text(
        "عملیات انجام شد.", reply_markup=InlineKeyboardMarkup(buttons))


def cb_enable_ipv6(update: Update, context: CallbackContext) -> None:
    """فعال کردن IPv6 یک لوکیشن خاص."""
    country_code = update.callback_query.data.split('_')[2]
    result = db.enable_location(country_code, "ipv6")

    if result:
        # دریافت اطلاعات کشور برای نمایش نام آن
        country_data = db.get_ipv4_countries().get(country_code)
        country_name = country_data[0] if country_data else country_code
        flag = country_data[1] if country_data else "🏳️"

        send_reply(update,
                   f"✅ IPv6 لوکیشن {flag} {country_name} با موفقیت فعال شد.")
    else:
        send_reply(update, "❌ خطا در فعال کردن IPv6 لوکیشن.")

    # بازگشت به منوی مدیریت IPv6
    buttons = [[
        InlineKeyboardButton("↩️ بازگشت", callback_data='manage_ipv6')
    ]]
    update.callback_query.message.reply_text(
        "عملیات انجام شد.", reply_markup=InlineKeyboardMarkup(buttons))


def cb_request_add_ip(update: Update, context: CallbackContext) -> None:
    """ارسال درخواست افزودن IP به ادمین."""
    try:
        callback_data = update.callback_query.data
        data = callback_data.split('_')

        if len(data) < 7:
            update.callback_query.answer(
                "خطا در فرمت داده‌ها. لطفاً دوباره تلاش کنید.")
            return

        country_code = data[3]
        ip_address = data[4]
        country_name = data[5]
        flag = data[6]
        user_id = update.callback_query.from_user.id
        username = update.callback_query.from_user.username or f"کاربر {user_id}"

        # تولید یک شناسه منحصر به فرد با تایم استمپ برای جلوگیری از تداخل
        import time
        timestamp = int(time.time())
        request_id = f"{country_code}_{ip_address}_{user_id}_{timestamp}"

        # ذخیره درخواست در لیست درخواست‌های منتظر تایید
        PENDING_IPS[request_id] = {
            "country_code": country_code,
            "ip_address": ip_address,
            "country_name": country_name,
            "flag": flag,
            "user_id": user_id,
            "username": username,
            "timestamp": timestamp
        }

        # اطلاع به کاربر
        update.callback_query.answer(
            "درخواست شما به ادمین ارسال شد و در انتظار تایید است.")
        send_reply(
            update,
            "✅ درخواست افزودن IP به لیست ارسال شد و در انتظار تایید ادمین است."
        )

        # اطلاع به ادمین
        admin_buttons = [[
            InlineKeyboardButton("✅ تایید",
                                 callback_data=f'approve_ip_{request_id}'),
            InlineKeyboardButton("❌ رد",
                                 callback_data=f'reject_ip_{request_id}')
        ]]

        # ارسال پیام به ادمین با اطلاعات کامل
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 درخواست جدید برای افزودن IP:\n\n"
            f"👤 کاربر: {username}\n"
            f"🌐 آدرس IP: {ip_address}\n"
            f"🌍 کشور: {flag} {country_name}\n"
            f"🔑 شناسه درخواست: {request_id}\n\n"
            f"لطفاً این درخواست را تایید یا رد کنید:",
            reply_markup=InlineKeyboardMarkup(admin_buttons))

        # لاگ کردن درخواست برای بررسی
        logger.info(
            f"درخواست جدید IP با شناسه {request_id} ایجاد شد. IP: {ip_address}, کاربر: {user_id}"
        )

    except Exception as e:
        update.callback_query.answer(f"خطایی رخ داد: {str(e)[:50]}")
        logger.error(f"خطا در درخواست افزودن IP: {e}")
        send_reply(update, f"❌ خطا در ارسال درخواست: {str(e)[:100]}")


def cb_approve_ip(update: Update, context: CallbackContext) -> None:
    """تایید درخواست افزودن IP توسط ادمین."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer(
            "فقط ادمین می‌تواند این عملیات را انجام دهد.")
        return

    try:
        request_id = update.callback_query.data.split('_')[2]
        if request_id not in PENDING_IPS:
            update.callback_query.answer(
                "درخواست یافت نشد یا قبلاً پردازش شده است.")
            return

        # کپی کردن اطلاعات قبل از حذف
        ip_data = PENDING_IPS[request_id].copy()
        user_id = ip_data["user_id"]
        ip_address = ip_data["ip_address"]
        country_name = ip_data["country_name"]
        flag = ip_data["flag"]

        # حذف درخواست از لیست انتظار قبل از پردازش
        del PENDING_IPS[request_id]

        # افزودن IP به پایگاه داده
        db.add_ipv4_address(country_name, flag, ip_address)

        # اطلاع به ادمین
        update.callback_query.answer("IP با موفقیت تایید و اضافه شد.")
        update.callback_query.message.edit_text(
            f"✅ IP {ip_address} با موفقیت تایید و به لیست اضافه شد.")

        # اطلاع به کاربر
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=
                f"✅ درخواست شما برای افزودن IP {ip_address} برای کشور {flag} {country_name} توسط ادمین تایید شد و به لیست اضافه شد."
            )
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر: {e}")
    except Exception as e:
        logger.error(f"خطا در تایید IP: {e}")
        update.callback_query.answer(f"خطایی رخ داد: {str(e)[:50]}")
        update.callback_query.message.reply_text(
            "خطایی در پردازش درخواست رخ داد.")


def cb_admin_broadcast(update: Update, context: CallbackContext) -> int:
    """آغاز فرآیند ارسال پیام همگانی."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer(
            "فقط ادمین می‌تواند پیام همگانی ارسال کند.")
        return ConversationHandler.END

    send_reply(update, "📢 لطفاً متن پیام همگانی را وارد کنید:")
    return ENTER_BROADCAST_MESSAGE


def enter_broadcast_message(update: Update, context: CallbackContext) -> int:
    """دریافت متن پیام همگانی و ارسال به همه کاربران."""
    message_text = update.message.text.strip()
    user_id = update.message.from_user.id

    if user_id != ADMIN_ID:
        update.message.reply_text(
            "⛔ فقط ادمین می‌تواند پیام همگانی ارسال کند.")
        return ConversationHandler.END

    # تایید دریافت پیام
    status_message = update.message.reply_text("🔄 در حال ارسال پیام همگانی...")

    # ارسال پیام به همه کاربران فعال
    success_count = 0
    fail_count = 0

    for user_id in db.active_users:
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"📢 *پیام مهم از مدیریت*\n\n{message_text}",
                parse_mode=ParseMode.MARKDOWN)
            success_count += 1
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر {user_id}: {e}")
            fail_count += 1

    # به‌روزرسانی پیام وضعیت
    status_message.edit_text(f"✅ پیام همگانی ارسال شد.\n\n"
                             f"📊 آمار ارسال:\n"
                             f"✅ موفق: {success_count}\n"
                             f"❌ ناموفق: {fail_count}\n"
                             f"📋 کل: {success_count + fail_count}")

    return ConversationHandler.END


def cb_admin_set_channel(update: Update, context: CallbackContext) -> int:
    """آغاز فرآیند تنظیم کانال اجباری."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer(
            "فقط ادمین می‌تواند کانال اجباری را تنظیم کند.")
        return ConversationHandler.END

    send_reply(
        update,
        "📢 لطفاً لینک کانال اجباری را وارد کنید (مثال: @channel_name):\n\n"
        "برای غیرفعال کردن عضویت اجباری، عبارت 'disable' را ارسال کنید.")
    return ENTER_CHANNEL_LINK


def enter_channel_link(update: Update, context: CallbackContext) -> int:
    """دریافت لینک کانال اجباری و ذخیره آن."""
    channel_link = update.message.text.strip()
    user_id = update.message.from_user.id

    if user_id != ADMIN_ID:
        update.message.reply_text(
            "⛔ فقط ادمین می‌تواند کانال اجباری را تنظیم کند.")
        return ConversationHandler.END

    global REQUIRED_CHANNEL

    if channel_link.lower() == 'disable':
        REQUIRED_CHANNEL = ""
        update.message.reply_text("✅ عضویت اجباری در کانال غیرفعال شد.")
    else:
        if not channel_link.startswith('@'):
            channel_link = '@' + channel_link

        REQUIRED_CHANNEL = channel_link
        update.message.reply_text(
            f"✅ کانال اجباری به {channel_link} تغییر یافت.")

    return ConversationHandler.END


def check_channel_membership(user_id, context) -> bool:
    """بررسی عضویت کاربر در کانال اجباری."""
    if not REQUIRED_CHANNEL:
        return True  # اگر کانال اجباری تنظیم نشده باشد، همه مجازند

    try:
        user_status = context.bot.get_chat_member(chat_id=REQUIRED_CHANNEL,
                                                  user_id=user_id)
        # اگر کاربر عضو کانال باشد (هر نوع عضویتی به جز left یا kicked)
        if user_status.status not in ['left', 'kicked']:
            return True
    except Exception as e:
        logger.error(f"خطا در بررسی عضویت کانال: {e}")

    return False


def create_join_channel_button() -> InlineKeyboardMarkup:
    """ایجاد دکمه عضویت در کانال."""
    buttons = [
        [InlineKeyboardButton("🔔 عضویت در کانال", url=f"https://t.me/{REQUIRED_CHANNEL[1:]}")],
        [InlineKeyboardButton("🔄 بررسی مجدد عضویت", callback_data='check_membership')],
        [InlineKeyboardButton("❓ راهنما", callback_data='channel_help')]
    ]
    return InlineKeyboardMarkup(buttons)

def cb_check_membership(update: Update, context: CallbackContext) -> None:
    """بررسی مجدد عضویت کاربر در کانال"""
    user_id = update.effective_user.id
    
    if check_channel_membership(user_id, context):
        send_reply(update, 
                   "✅ عضویت شما در کانال تأیید شد. اکنون می‌توانید از ربات استفاده کنید.",
                   reply_markup=main_menu_keyboard(user_id))
    else:
        send_reply(update,
                  f"❌ شما هنوز در کانال {REQUIRED_CHANNEL} عضو نشده‌اید. لطفاً ابتدا عضو شوید.",
                  reply_markup=create_join_channel_button())

def cb_channel_help(update: Update, context: CallbackContext) -> None:
    """راهنمای عضویت در کانال"""
    help_text = (
        "🔔 راهنمای عضویت در کانال:\n\n"
        f"1. ابتدا روی دکمه «عضویت در کانال» کلیک کنید تا به کانال {REQUIRED_CHANNEL} هدایت شوید.\n"
        "2. روی دکمه «Join» یا «عضویت» در کانال کلیک کنید.\n"
        "3. پس از عضویت، به ربات برگردید و روی دکمه «بررسی مجدد عضویت» کلیک کنید.\n\n"
        "❗️ در صورت بروز مشکل، با پشتیبانی تماس بگیرید."
    )
    send_reply(update, help_text, reply_markup=create_join_channel_button())

    # حذف درخواست از لیست انتظار
    del PENDING_IPS[request_id]


def cb_reject_ip(update: Update, context: CallbackContext) -> None:
    """رد درخواست افزودن IP توسط ادمین."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer(
            "فقط ادمین می‌تواند این عملیات را انجام دهد.")
        return

    try:
        request_id = update.callback_query.data.split('_')[2]
        if request_id not in PENDING_IPS:
            update.callback_query.answer(
                "درخواست یافت نشد یا قبلاً پردازش شده است.")
            return

        # کپی کردن اطلاعات قبل از حذف
        ip_data = PENDING_IPS[request_id].copy()
        user_id = ip_data["user_id"]
        ip_address = ip_data["ip_address"]

        # حذف درخواست از لیست انتظار قبل از انجام عملیات دیگر
        del PENDING_IPS[request_id]

        # اطلاع به ادمین
        update.callback_query.answer("درخواست رد شد.")
        update.callback_query.message.edit_text(
            f"❌ درخواست افزودن IP {ip_address} رد شد.")

        # اطلاع به کاربر
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=
                f"❌ درخواست شما برای افزودن IP {ip_address} توسط ادمین رد شد.")
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر: {e}")
    except Exception as e:
        logger.error(f"خطا در رد IP: {e}")
        update.callback_query.answer(f"خطایی رخ داد: {str(e)[:50]}")
        update.callback_query.message.reply_text(
            "خطایی در پردازش درخواست رخ داد.")


def cb_admin_batch_process_ip(update: Update, context: CallbackContext) -> int:
    """شروع فرآیند پردازش گروهی آدرس‌های IP."""
    send_reply(update, 
               "📋 لطفاً لیست آدرس‌های IP مورد نظر را وارد کنید.\n\n"
               "می‌توانید هر تعداد IP را در یک یا چند پیام ارسال کنید. "
               "ربات به صورت خودکار آن‌ها را بر اساس کشور دسته‌بندی خواهد کرد.")
    return ENTER_BATCH_IPS


def process_batch_ips(update: Update, context: CallbackContext) -> int:
    """پردازش گروهی آدرس‌های IP دریافتی."""
    import re
    text = update.message.text.strip()

    # نمایش پیام انتظار
    status_message = update.message.reply_text("🔄 در حال پردازش آدرس‌های IP... لطفاً صبر کنید.")

    try:
        # استخراج و پردازش آدرس‌های IP
        ip_groups = ip_processor.process_bulk_ips(text)

        if not ip_groups:
            status_message.edit_text("❌ هیچ آدرس IP معتبری در متن ارسالی یافت نشد.")
            return ENTER_BATCH_IPS

        total_ips = sum(len(ips) for ips in ip_groups.values())

        # ذخیره اطلاعات در user_data برای استفاده بعدی
        context.user_data['ip_groups'] = ip_groups
        context.user_data['total_ips'] = total_ips

        # بروزرسانی پیام با اطلاعات پردازش اولیه و درخواست تأیید
        preview = f"✅ {total_ips} آدرس IP شناسایی شد.\n🌐 در {len(ip_groups)} کشور مختلف.\n\n"
        
        # نمایش پیش‌نمایش کشورها و تعداد IPها
        country_previews = []
        for country_info, ip_list in ip_groups.items():
            country_name = country_info.split(" ", 1)[1] if " " in country_info else country_info
            flag = country_info.split(" ")[0] if " " in country_info else "🏳️"
            country_previews.append(f"• {flag} {country_name}: {len(ip_list)} آدرس")
        
        preview += "📋 پیش‌نمایش:\n" + "\n".join(country_previews[:10])
        
        if len(country_previews) > 10:
            preview += f"\n... و {len(country_previews) - 10} کشور دیگر"
        
        # دکمه‌های تأیید یا لغو عملیات
        buttons = [
            [InlineKeyboardButton("✅ تایید و اضافه کردن", callback_data='confirm_add_batch_ips')],
            [InlineKeyboardButton("✅ تایید و اطلاع‌رسانی به کاربران", callback_data='confirm_add_batch_ips_notify')],
            [InlineKeyboardButton("❌ لغو عملیات", callback_data='cancel_add_batch_ips')]
        ]
        
        status_message.edit_text(preview, reply_markup=InlineKeyboardMarkup(buttons))
        
        return ENTER_BATCH_IPS

    except Exception as e:
        logger.error(f"خطا در پردازش گروهی IP: {e}")
        status_message.edit_text(f"❌ خطایی رخ داد: {str(e)}")
        return ConversationHandler.END

def cb_confirm_add_batch_ips(update: Update, context: CallbackContext) -> int:
    """تأیید و اضافه کردن IPهای پردازش شده"""
    return complete_batch_ip_process(update, context, notify_users=False)

def cb_confirm_add_batch_ips_notify(update: Update, context: CallbackContext) -> int:
    """تأیید و اضافه کردن IPهای پردازش شده با اطلاع‌رسانی"""
    return complete_batch_ip_process(update, context, notify_users=True)

def cb_cancel_add_batch_ips(update: Update, context: CallbackContext) -> int:
    """لغو عملیات اضافه کردن IPهای پردازش شده"""
    update.callback_query.answer("عملیات اضافه کردن IPها لغو شد.")
    update.callback_query.message.edit_text("❌ عملیات اضافه کردن IPها لغو شد.")
    
    # پاکسازی داده‌های موقت
    if 'ip_groups' in context.user_data:
        del context.user_data['ip_groups']
    if 'total_ips' in context.user_data:
        del context.user_data['total_ips']
    
    # برگشت به پنل ادمین
    buttons = [[InlineKeyboardButton("↩️ بازگشت به پنل ادمین", callback_data='admin_panel')]]
    update.callback_query.message.reply_text("عملیات لغو شد.", reply_markup=InlineKeyboardMarkup(buttons))
    
    return ConversationHandler.END

def complete_batch_ip_process(update: Update, context: CallbackContext, notify_users: bool) -> int:
    """تکمیل فرآیند اضافه کردن IPها با یا بدون اطلاع‌رسانی"""
    update.callback_query.answer("در حال اضافه کردن IPها...")
    
    if 'ip_groups' not in context.user_data or 'total_ips' not in context.user_data:
        update.callback_query.message.edit_text("❌ اطلاعات پردازش شده یافت نشد.")
        return ConversationHandler.END
    
    ip_groups = context.user_data['ip_groups']
    total_ips = context.user_data['total_ips']
    
    # اضافه کردن آدرس‌ها به دیتابیس و تولید گزارش
    added_count = 0
    country_reports = []

    for country_info, ip_list in ip_groups.items():
        country_name = country_info.split(" ", 1)[1] if " " in country_info else country_info
        flag = country_info.split(" ")[0] if " " in country_info else "🏳️"

        country_report = f"{flag} {country_name}: "
        country_added = 0

        for ip_data in ip_list:
            db.add_ipv4_address(country_name, flag, ip_data["ip"])
            country_added += 1
            added_count += 1

        country_reports.append(f"{country_report}{country_added} آدرس")
    
    # ارسال گزارش نهایی
    report = f"✅ عملیات اضافه کردن IPها با موفقیت انجام شد.\n\n" \
             f"📊 گزارش:\n" \
             f"• تعداد کل IP‌های شناسایی شده: {total_ips}\n" \
             f"• تعداد IP‌های اضافه شده: {added_count}\n" \
             f"• تعداد کشورها: {len(ip_groups)}\n\n" \
             f"🌐 دسته‌بندی بر اساس کشور:\n"
    
    # نمایش همه کشورها بدون محدودیت
    for i, report_item in enumerate(country_reports):
        report += f"• {report_item}\n"
        # برای جلوگیری از پیام خیلی طولانی، هر 30 کشور یک پیام جدید ارسال می‌کنیم
        if (i + 1) % 30 == 0 and i + 1 < len(country_reports):
            update.callback_query.message.edit_text(report)
            report = "⬇️ ادامه لیست کشورها:\n\n"
    
    update.callback_query.message.edit_text(report)
    
    # اطلاع‌رسانی به کاربران در صورت درخواست
    if notify_users:
        # متن اطلاع‌رسانی
        notification = "🔥 آدرس‌های جدید اضافه شدند! 🔥\n\n"
        notification += "📡 کشورهای جدید:\n"
        
        # تقسیم اطلاع‌رسانی به چند پیام اگر تعداد کشورها زیاد باشد
        for i in range(0, len(country_reports), 20):
            chunk = country_reports[i:i+20]
            chunk_notification = notification + "\n".join(f"• {report}" for report in chunk)
            
            if i + 20 < len(country_reports):
                chunk_notification += f"\n\n(بخش {i//20 + 1}/{(len(country_reports)+19)//20})"
            
            chunk_notification += "\n\nبرای مشاهده لیست کامل به بخش «📋 لیست IPv4» مراجعه کنید."
            
            # ارسال هر بخش به تمام کاربران فعال
            success_count = 0
            fail_count = 0
            for user_id in db.active_users:
                if db.is_user_active(user_id):
                    try:
                        context.bot.send_message(chat_id=user_id, text=chunk_notification)
                        success_count += 1
                    except Exception as e:
                        logger.error(f"خطا در ارسال اطلاع‌رسانی به کاربر {user_id}: {e}")
                        fail_count += 1
            
            # گزارش نتیجه اطلاع‌رسانی برای هر بخش
            if i == 0:  # فقط برای بخش اول گزارش می‌دهیم
                update.callback_query.message.reply_text(
                    f"📢 اطلاع‌رسانی به کاربران:\n"
                    f"✅ موفق: {success_count}\n"
                    f"❌ ناموفق: {fail_count}"
                )
    
    # پاکسازی داده‌های موقت
    del context.user_data['ip_groups']
    del context.user_data['total_ips']
    
    # برگشت به پنل ادمین
    buttons = [[InlineKeyboardButton("↩️ بازگشت به پنل ادمین", callback_data='admin_panel')]]
    update.callback_query.message.reply_text("عملیات با موفقیت انجام شد.", reply_markup=InlineKeyboardMarkup(buttons))
    
    return ConversationHandler.END


def cb_admin_manage_backups(update: Update, context: CallbackContext) -> None:
    """مدیریت بکاپ‌های دیتابیس."""
    import time
    backups = backup_mgr.list_backups()

    if not backups:
        buttons = [
            [InlineKeyboardButton("💾 ایجاد بکاپ جدید", callback_data='create_backup')],
            [InlineKeyboardButton("↩️ بازگشت", callback_data='admin_panel')]
        ]
        send_reply(update, 
                  "💾 مدیریت بکاپ‌ها\n\n"
                  "هیچ بکاپی یافت نشد. می‌توانید اولین بکاپ را ایجاد کنید.",
                  reply_markup=InlineKeyboardMarkup(buttons))
        return

    # تنظیم وضعیت بکاپ خودکار
    auto_backup_status = "✅ فعال" if backup_mgr.running else "❌ غیرفعال"
    auto_backup_action = "disable_auto_backup" if backup_mgr.running else "enable_auto_backup"

    backup_list = "💾 لیست بکاپ‌های موجود:\n\n"

    for i, (timestamp, path) in enumerate(backups[:5], 1):  # نمایش 5 بکاپ آخر
        # تبدیل timestamp به تاریخ خوانا
        date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        backup_name = os.path.basename(path)
        backup_list += f"{i}. {date_str} - {backup_name}\n"

    if len(backups) > 5:
        backup_list += f"\n... و {len(backups) - 5} بکاپ دیگر"

    buttons = [
        [InlineKeyboardButton("💾 ایجاد بکاپ جدید", callback_data='create_backup')],
        [InlineKeyboardButton("📤 ارسال آخرین بکاپ به ادمین", callback_data='send_latest_backup')],
        [InlineKeyboardButton("🔄 بازیابی آخرین بکاپ", callback_data='restore_last_backup')],
        [InlineKeyboardButton(f"⏱️ بکاپ خودکار: {auto_backup_status}", 
                             callback_data=auto_backup_action)],
        [InlineKeyboardButton("↩️ بازگشت", callback_data='admin_panel')]
    ]

    send_reply(update, 
              f"💾 مدیریت بکاپ‌ها\n\n"
              f"تنظیمات فعلی:\n"
              f"• فاصله بکاپ‌گیری: هر {backup_mgr.backup_interval//3600} ساعت\n"
              f"• حداکثر تعداد بکاپ: {backup_mgr.max_backups}\n"
              f"• وضعیت بکاپ خودکار: {auto_backup_status}\n\n"
              f"{backup_list}",
              reply_markup=InlineKeyboardMarkup(buttons))

# --- ارسال آخرین بکاپ به ادمین ---
def cb_send_latest_backup(update: Update, context: CallbackContext) -> None:
    """ارسال آخرین فایل بکاپ به ادمین به صورت فایل."""
    backups = backup_mgr.list_backups()
    if not backups:
        update.callback_query.answer("هیچ بکاپی وجود ندارد.")
        return
    latest_backup_path = backups[0][1]
    try:
        with open(latest_backup_path, 'rb') as f:
            update.callback_query.message.reply_document(
                document=f,
                filename=os.path.basename(latest_backup_path),
                caption="📤 آخرین بکاپ دیتابیس برای شما ارسال شد."
            )
    except Exception as e:
        update.callback_query.message.reply_text(f"❌ خطا در ارسال بکاپ: {str(e)}")

def cb_create_backup(update: Update, context: CallbackContext) -> None:
    """ایجاد بکاپ دستی از دیتابیس."""
    update.callback_query.answer("در حال ایجاد بکاپ...")

    try:
        backup_file = backup_mgr.create_backup()
        if backup_file:
            update.callback_query.message.reply_text(f"✅ بکاپ با موفقیت ایجاد شد: {os.path.basename(backup_file)}")
        else:
            update.callback_query.message.reply_text("❌ خطا در ایجاد بکاپ: فایل دیتابیس یافت نشد.")
    except Exception as e:
        update.callback_query.message.reply_text(f"❌ خطا در ایجاد بکاپ: {str(e)}")

    # بازگشت به صفحه مدیریت بکاپ‌ها
    cb_admin_manage_backups(update, context)


def cb_restore_last_backup(update: Update, context: CallbackContext) -> None:
    """بازیابی آخرین بکاپ دیتابیس."""
    update.callback_query.answer("در حال بازیابی آخرین بکاپ...")

    try:
        result = backup_mgr.restore_backup()
        if result:
            update.callback_query.message.reply_text("✅ دیتابیس با موفقیت از آخرین بکاپ بازیابی شد.")
        else:
            update.callback_query.message.reply_text("❌ خطا در بازیابی: بکاپی یافت نشد.")
    except Exception as e:
        update.callback_query.message.reply_text(f"❌ خطا در بازیابی بکاپ: {str(e)}")

    # بازگشت به صفحه مدیریت بکاپ‌ها
    cb_admin_manage_backups(update, context)


def cb_toggle_auto_backup(update: Update, context: CallbackContext) -> None:
    """فعال/غیرفعال کردن بکاپ خودکار."""
    action = update.callback_query.data

    if action == 'enable_auto_backup':
        backup_mgr.start_backup_thread()
        update.callback_query.answer("بکاپ خودکار فعال شد.")
    else:
        backup_mgr.stop_backup_thread()
        update.callback_query.answer("بکاپ خودکار غیرفعال شد.")

    # بازگشت به صفحه مدیریت بکاپ‌ها
    cb_admin_manage_backups(update, context)


def cb_reject_ip(update: Update, context: CallbackContext) -> None:
    """رد درخواست افزودن IP توسط ادمین."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer(
            "فقط ادمین می‌تواند این عملیات را انجام دهد.")
        return

    try:
        request_id = update.callback_query.data.split('_')[2]
        if request_id not in PENDING_IPS:
            update.callback_query.answer(
                "درخواست یافت نشد یا قبلاً پردازش شده است.")
            return

        # کپی کردن اطلاعات قبل از حذف
        ip_data = PENDING_IPS[request_id].copy()
        user_id = ip_data["user_id"]
        ip_address = ip_data["ip_address"]

        # حذف درخواست از لیست انتظار قبل از انجام عملیات دیگر
        del PENDING_IPS[request_id]

        # اطلاع به ادمین
        update.callback_query.answer("درخواست رد شد.")
        update.callback_query.message.edit_text(
            f"❌ درخواست افزودن IP {ip_address} رد شد.")

        # اطلاع به کاربر
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=
                f"❌ درخواست شما برای افزودن IP {ip_address} توسط ادمین رد شد.")
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر: {e}")
    except Exception as e:
        logger.error(f"خطا در رد IP: {e}")
        update.callback_query.answer(f"خطایی رخ داد: {str(e)[:50]}")
        update.callback_query.message.reply_text(
            "خطایی در پردازش درخواست رخ داد.")


# --- توابع جدید برای مدیریت تک به تک دکمه‌های لوکیشن ---


def cb_manage_ipv4_buttons(update: Update, context: CallbackContext) -> None:
    """مدیریت تک به تک دکمه‌های IPv4."""
    locations = db.get_all_locations()

    if not locations:
        send_reply(
            update,
            "❌ هیچ لوکیشنی یافت نشد. ابتدا از طریق پنل ادمین IPv4 اضافه کنید.")
        return

    buttons = []
    for country_code, info in locations.items():
        if info['ipv4_count'] > 0:
            status = "🔴" if info["ipv4_disabled"] else "🟢"
            action = "enable" if info["ipv4_disabled"] else "disable"
            buttons.append([
                InlineKeyboardButton(
                    f"{status} {info['flag']} {info['name']} ({info['ipv4_count']} IP)",
                    callback_data=f'toggle_ipv4_{action}_{country_code}')
            ])

    if not buttons:
        send_reply(update, "❌ هیچ لوکیشنی با IPv4 یافت نشد.")
        return

    buttons.append([
        InlineKeyboardButton("↩️ بازگشت",
                             callback_data='admin_manage_locations')
    ])
    send_reply(update,
               "🔘 مدیریت تک به تک دکمه‌های IPv4:\n🟢 = فعال | 🔴 = غیرفعال",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_manage_ipv6_buttons(update: Update, context: CallbackContext) -> None:
    """مدیریت تک به تک دکمه‌های IPv6."""
    # استفاده از گزینه‌های تولید IPv6 موجود
    options = [("گزینه ۱", "option_1"), ("گزینه ۲", "option_2"),
               ("گزینه ۳", "option_3"), ("گزینه ۴", "option_4"),
               ("گزینه ۵", "option_5")]

    buttons = []

    # نمایش وضعیت کلی دکمه تولید IPv6
    ipv6_status = "🔴 غیرفعال" if DISABLED_BUTTONS.get("generate_ipv6",
                                                      False) else "🟢 فعال"
    buttons.append([
        InlineKeyboardButton(f"وضعیت دکمه اصلی تولید IPv6: {ipv6_status}",
                             callback_data="noop")
    ])

    # نمایش وضعیت فعال/غیرفعال برای هر گزینه تولید IPv6
    for name, option_id in options:
        # بررسی وضعیت فعال/غیرفعال (پیش‌فرض: فعال)
        disabled = db.disabled_locations.get(f"ipv6_{option_id}", False)
        status = "🔴" if disabled else "🟢"
        action = "enable" if disabled else "disable"
        buttons.append([
            InlineKeyboardButton(
                f"{status} {name}",
                callback_data=f'toggle_ipv6_{action}_{option_id}')
        ])

    buttons.append([
        InlineKeyboardButton("↩️ بازگشت",
                             callback_data='admin_manage_locations')
    ])
    send_reply(update,
               "🔘 مدیریت گزینه‌های تولید IPv6:\n🟢 = فعال | 🔴 = غیرفعال",
               reply_markup=InlineKeyboardMarkup(buttons))


def cb_toggle_ipv4(update: Update, context: CallbackContext) -> None:
    """تغییر وضعیت فعال/غیرفعال IPv4 یک لوکیشن."""
    data = update.callback_query.data.split('_')
    action = data[2]
    country_code = data[3]

    if action == "disable":
        result = db.disable_location(country_code, "ipv4")
        status_text = "غیرفعال"
    else:  # enable
        result = db.enable_location(country_code, "ipv4")
        status_text = "فعال"

    if result:
        # دریافت اطلاعات کشور برای نمایش نام آن
        country_data = db.get_ipv4_countries().get(country_code)
        country_name = country_data[0] if country_data else country_code
        flag = country_data[1] if country_data else "🏳️"

        send_reply(
            update,
            f"✅ IPv4 لوکیشن {flag} {country_name} با موفقیت {status_text} شد.")
    else:
        send_reply(update, f"❌ خطا در تغییر وضعیت IPv4 لوکیشن.")

    # بازگرداندن به منوی مدیریت دکمه‌ها
    cb_manage_ipv4_buttons(update, context)


def cb_toggle_ipv6(update: Update, context: CallbackContext) -> None:
    """تغییر وضعیت فعال/غیرفعال گزینه‌های تولید IPv6."""
    data = update.callback_query.data.split('_')
    action = data[2]
    option_id = data[3]

    option_names = {
        "option_1": "گزینه ۱",
        "option_2": "گزینه ۲",
        "option_3": "گزینه ۳",
        "option_4": "گزینه ۴",
        "option_5": "گزینه ۵"
    }

    option_name = option_names.get(option_id, option_id)

    # تغییر وضعیت فعال/غیرفعال در پایگاه داده و DISABLED_BUTTONS
    key = f"ipv6_{option_id}"

    # ذخیره در پایگاه داده
    if action == "disable":
        db.disabled_locations[key] = True
        status_text = "غیرفعال"
    else:  # enable
        db.disabled_locations[key] = False
        status_text = "فعال"

    # ذخیره تغییرات
    db.save_database()

    # به روز کردن DISABLED_BUTTONS برای گزینه generate_ipv6
    # این بخش جدید است و برای حل مشکل اضافه شده
    if option_id in [
            "option_1", "option_2", "option_3", "option_4", "option_5"
    ]:
        # وقتی یکی از گزینه‌ها غیرفعال است، دکمه اصلی را هم غیرفعال کنیم
        if action == "disable":
            DISABLED_BUTTONS["generate_ipv6"] = True
        else:
            # اگر همه گزینه‌ها فعال شدند، دکمه اصلی را هم فعال کنیم
            all_options_enabled = True
            for i in range(1, 6):
                if db.disabled_locations.get(f"ipv6_option_{i}", False):
                    all_options_enabled = False
                    break

            if all_options_enabled:
                DISABLED_BUTTONS["generate_ipv6"] = False

        # ذخیره تنظیمات دکمه‌های غیرفعال
        save_disabled_buttons()

    send_reply(update, f"✅ گزینه {option_name} با موفقیت {status_text} شد.")

    # بازگرداندن به منوی مدیریت دکمه‌ها
    cb_manage_ipv6_buttons(update, context)


def cb_admin_disable_user(update: Update, context: CallbackContext) -> int:
    """شروع فرآیند غیرفعال کردن کاربر."""
    send_reply(update, "لطفاً آیدی عددی کاربر را وارد کنید:")
    return ENTER_NEW_CODE


def cb_admin_enable_user(update: Update, context: CallbackContext) -> int:
    """شروع فرآیند فعال کردن کاربر."""
    send_reply(update, "لطفاً آیدی عددی کاربر را وارد کنید:")

def cb_admin_view_codes(update: Update, context: CallbackContext) -> None:
    """نمایش کدهای فعال‌سازی موجود در سیستم"""
    codes = db.get_all_codes()
    
    if not codes:
        send_reply(update, "❌ هیچ کد فعال‌سازی یافت نشد.")
        return
    
    # دسته‌بندی کدها
    unlimited_codes = []
    token_codes = []
    
    for code, data in codes.items():
        if data['type'] == 'unlimited':
            unlimited_codes.append(f"🔑 {code}")
        else:
            token_codes.append(f"🪙 {code} ({data['tokens']} توکن)")
    
    # ساخت متن پاسخ
    response = "📋 لیست کدهای فعال‌سازی:\n\n"
    
    if unlimited_codes:
        response += "🔄 کدهای دائمی:\n"
        response += "\n".join(unlimited_codes) + "\n\n"
    
    if token_codes:
        response += "🔢 کدهای توکنی:\n"
        response += "\n".join(token_codes)
    

def cb_admin_batch_add_endpoints(update: Update, context: CallbackContext) -> int:
    """افزودن گروهی Endpoint های وایرگارد"""
    send_reply(update, 
              "📥 لطفاً لیست Endpoint های وایرگارد را وارد کنید.\n\n"
              "هر Endpoint را در یک خط بنویسید. مثال:\n"
              "162.159.192.1\n"
              "162.159.193.10\n"
              "162.159.195.82\n\n"
              "پورت را نیازی نیست وارد کنید، فقط آدرس IP ها را وارد کنید.")
    return ENTER_BATCH_ENDPOINTS

def handle_batch_endpoints(update: Update, context: CallbackContext) -> int:
    """پردازش لیست Endpoint های دریافتی و افزودن آنها"""
    import re
    text = update.message.text.strip()
    lines = text.split('\n')
    
    status_message = update.message.reply_text("🔄 در حال پردازش Endpoint ها...")
    
    # فیلتر کردن خطوط خالی و استخراج آدرس‌های IP
    ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    added_endpoints = 0
    invalid_lines = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        match = re.search(ip_pattern, line)
        if match:
            endpoint = match.group(0)
            if endpoint not in db.wg_endpoints:
                db.add_endpoint(endpoint)
                added_endpoints += 1
        else:
            invalid_lines += 1
    
    # به‌روزرسانی پیام با نتیجه
    status_message.edit_text(
        f"✅ عملیات افزودن Endpoint ها به پایان رسید.\n\n"
        f"• تعداد Endpoint های افزوده شده: {added_endpoints}\n"
        f"• تعداد خطوط نامعتبر: {invalid_lines}"
    )
    
    # بازگشت به پنل مدیریت Endpoint ها
    buttons = [[InlineKeyboardButton("↩️ بازگشت", callback_data='admin_manage_wg_endpoints')]]
    update.message.reply_text("عملیات به پایان رسید.", reply_markup=InlineKeyboardMarkup(buttons))
    
    return ConversationHandler.END

    # افزودن دکمه برگشت
    buttons = [[InlineKeyboardButton("↩️ بازگشت", callback_data='admin_panel')]]
    
    send_reply(update, response, reply_markup=InlineKeyboardMarkup(buttons))

    return ENTER_NEW_CODE


def disable_user(update: Update, context: CallbackContext) -> int:
    try:
        user_id = int(update.message.text.strip())
        db.disable_user(user_id)
        send_reply(update, f"✅ کاربر با آیدی {user_id} غیرفعال شد.")
    except ValueError:
        send_reply(update, "❌ لطفاً یک آیدی عددی معتبر وارد کنید.")
    return ConversationHandler.END


def enable_user(update: Update, context: CallbackContext) -> int:
    try:
        user_id = int(update.message.text.strip())
        db.enable_user(user_id)
        send_reply(update, f"✅ کاربر با آیدی {user_id} فعال شد.")
    except ValueError:
        send_reply(update, "❌ لطفاً یک آیدی عددی معتبر وارد کنید.")
    return ConversationHandler.END


def cb_enable_user(update: Update, context: CallbackContext) -> int:
    try:
        user_id = int(update.message.text.strip())
        db.enable_user(user_id)
        send_reply(update, f"✅ کاربر با آیدی {user_id} فعال شد.")
    except ValueError:
        send_reply(update, "❌ لطفاً یک آیدی عددی معتبر وارد کنید.")
    return ConversationHandler.END


def cb_admin_startup(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        send_reply(update, "🟢 ربات در حال راه‌اندازی است...")
        logger.info("Bot has been started by admin.")
        send_reply(update, "✅ ربات با موفقیت راه‌اندازی شد.")
    else:
        send_reply(update, "شما اجازه این کار را ندارید.")


def cb_validate_ipv4(update: Update, context: CallbackContext) -> int:
    """شروع فرآیند اعتبارسنجی IPv4."""
    user_id = update.callback_query.from_user.id

    # بررسی فعال بودن کاربر
    if not db.is_user_active(user_id):
        send_reply(update,
                   "❌ اشتراک فعال ندارید. لطفاً ابتدا فعال‌سازی کنید.",
                   reply_markup=main_menu_keyboard(user_id))
        return ConversationHandler.END

    send_reply(update,
               "🔍 لطفاً آدرس IPv4 مورد نظر برای اعتبارسنجی را وارد کنید:")
    return ENTER_IP_FOR_VALIDATION


def validate_ipv4_address(update: Update, context: CallbackContext) -> int:
    """بررسی آدرس IPv4 وارد شده."""
    user_id = update.message.from_user.id
    ip_address = update.message.text.strip()

    # اطلاع رسانی شروع فرآیند
    message = update.message.reply_text(
        "🔄 در حال بررسی آدرس IP... لطفاً صبر کنید.")

    # بررسی معتبر بودن IP برای جلوگیری از خطا
    try:
        import ipaddress
        ipaddress.ip_address(ip_address)
    except ValueError:
        message.edit_text(
            "❌ آدرس IP وارد شده معتبر نیست. لطفاً یک آدرس IPv4 معتبر وارد کنید."
        )
        return ConversationHandler.END

    # کم کردن توکن برای کاربران توکنی
    user_data = db.active_users.get(user_id, {})
    if user_data.get('type') == 'token':
        current_tokens = user_data.get('tokens', 0)
        if current_tokens <= 0:
            message.edit_text(
                "❌ توکن شما تمام شده است. لطفاً اشتراک خود را تمدید کنید.")
            return ConversationHandler.END

        # کم کردن یک توکن
        db.use_tokens(user_id, 1)

    try:
        import time

        # نمایش پیام‌های مرحله‌ای
        time.sleep(2)
        message.edit_text("🔄 در حال ارتباط با سرور IP Location...")

        time.sleep(2)
        message.edit_text("🔄 در حال دریافت اطلاعات IP...")

        # ارسال درخواست به API - استفاده از API ویژه برای اطلاعات کامل
        response = requests.get(f"{IP_VALIDATION_API}{ip_address}")
        country_response = requests.get(
            f"https://api.iplocation.net/?cmd=ip-country&ip={ip_address}")

        if response.status_code == 200:
            time.sleep(1)
            message.edit_text("✅ اطلاعات IP دریافت شد. در حال پردازش...")

            # دریافت اطلاعات
            data = response.json()

            # بررسی API ثانویه برای اطلاعات دقیق‌تر کشور
            if country_response.status_code == 200:
                country_data = country_response.json()
                # به‌روزرسانی کد کشور اگر در پاسخ دوم موجود بود
                if country_data.get('country_code'):
                    data['country_code'] = country_data.get('country_code')
                    logger.info(
                        f"کد کشور از API ثانویه: {data['country_code']}")

            # نمایش نتیجه
            country = data.get('country_name', 'نامشخص')
            country_code = data.get('country_code', '').upper()
            isp = data.get('isp', 'نامشخص')

            # لاگ کردن اطلاعات برای بررسی
            logger.info(
                f"IP: {ip_address}, Country: {country}, Code: {country_code}")

            # دریافت پرچم کشور
            flag = "🏳️"

            # تنظیم دستی کد کشور برای کشورهای خاص که ممکن است از API به درستی دریافت نشوند
            special_country_codes = {
                "Qatar": "QA",
                "UAE": "AE",
                "United Arab Emirates": "AE",
                "Saudi Arabia": "SA",
                "Iran": "IR",
                "Iraq": "IQ",
                "Kuwait": "KW",
                "Bahrain": "BH",
                "Oman": "OM",
                "Egypt": "EG",
                "Turkey": "TR",
                "Russia": "RU",
                "United States": "US",
                "USA": "US",
                "Germany": "DE",
                "United Kingdom": "GB",
                "UK": "GB",
                "France": "FR",
                "China": "CN",
                "India": "IN",
                "Japan": "JP",
                "Canada": "CA",
                "Pakistan": "PK"
            }

            if country in special_country_codes:
                country_code = special_country_codes[country]

            # Map پرچم‌های آماده برای کشورهای خاص
            special_flags = {
                "QA": "🇶🇦",  # قطر
                "AE": "🇦🇪",  # امارات
                "SA": "🇸🇦",  # عربستان
                "IR": "🇮🇷",  # ایران
                "IQ": "🇮🇶",  # عراق
                "KW": "🇰🇼",  # کویت
                "BH": "🇧🇭",  # بحرین
                "OM": "🇴🇲",  # عمان
                "EG": "🇪🇬",  # مصر
                "TR": "🇹🇷",  # ترکیه
                "RU": "🇷🇺",  # روسیه
                "US": "🇺🇸",  # آمریکا
                "DE": "🇩🇪",  # آلمان
                "GB": "🇬🇧",  # بریتانیا
                "FR": "🇫🇷",  # فرانسه
                "CN": "🇨🇳",  # چین
                "IN": "🇮🇳",  # هند
                "JP": "🇯🇵",  # ژاپن
                "CA": "🇨🇦",  # کانادا
                "PK": "🇵🇰"  # پاکستان
            }

            # بررسی اگر کشور در لیست پرچم‌های خاص موجود است
            if country_code in special_flags:
                flag = special_flags[country_code]
                logger.info(f"Using prepared flag for {country}: {flag}")
            elif country_code and len(country_code) == 2:
                # ساخت ایموجی پرچم از کد کشور
                try:
                    # تبدیل کدهای ISO دو حرفی به ایموجی پرچم
                    flag_chars = []
                    for c in country_code.upper():
                        if 'A' <= c <= 'Z':
                            flag_chars.append(chr(ord(c) + 127397))
                    if len(flag_chars) == 2:
                        flag = "".join(flag_chars)
                        logger.info(
                            f"Generated flag for {country}: {flag} from code {country_code}"
                        )
                except Exception as e:
                    logger.error(f"خطا در تولید پرچم: {e}")

            # ساخت دکمه‌های نمایش اطلاعات با پرچم بزرگتر و بهتر
            buttons = [
                [
                    InlineKeyboardButton(f"{flag} کشور: {country}",
                                         callback_data='noop')
                ],
                [InlineKeyboardButton(f"🔌 ISP: {isp}", callback_data='noop')],
                [
                    InlineKeyboardButton(f"🌐 آدرس IP: {ip_address}",
                                         callback_data='noop')
                ],
            ]

            # اضافه کردن دکمه درخواست افزودن IP به لیست در صورت معتبر بودن
            if country != 'نامشخص':
                # اگر کاربر ادمین باشد، مستقیما به لیست اضافه کند
                if user_id == ADMIN_ID:
                    buttons.append([
                        InlineKeyboardButton(
                            "➕ افزودن این IP به لیست",
                            callback_data=
                            f'add_validated_ip_{country_code}_{ip_address}')
                    ])
                else:
                    # برای کاربران عادی، ارسال درخواست تایید به ادمین
                    buttons.append([
                        InlineKeyboardButton(
                            "🔔 درخواست افزودن این IP به لیست",
                            callback_data=
                            f'request_add_ip_{country_code}_{ip_address}_{country}_{flag}'
                        )
                    ])

            buttons.append([
                InlineKeyboardButton("↩️ بازگشت به منوی اصلی",
                                     callback_data='back')
            ])

            # نمایش وضعیت توکن برای کاربران توکنی
            token_message = ""
            if user_data.get('type') == 'token':
                remaining_tokens = db.active_users[user_id].get('tokens', 0)
                token_message = f"\n\n🔄 توکن‌های باقی‌مانده: {remaining_tokens}"

            # اضافه کردن پرچم بزرگ به ابتدای پیام
            flag_header = f"{flag} " if flag != "🏳️" else ""
            message.edit_text(
                f"{flag_header}✅ نتیجه اعتبارسنجی آدرس IP:{token_message}",
                reply_markup=InlineKeyboardMarkup(buttons))

        else:
            message.edit_text(
                f"❌ خطا در دریافت اطلاعات IP: {response.status_code}")

    except Exception as e:
        message.edit_text(f"❌ خطایی رخ داد: {str(e)}")

    return ConversationHandler.END


def cb_add_validated_ip(update: Update, context: CallbackContext) -> None:
    """افزودن آدرس IP اعتبارسنجی شده به لیست."""
    data = update.callback_query.data.split('_')
    country_code = data[3]
    ip_address = data[4]

    # دریافت اطلاعات کشور
    import requests
    try:
        # ارسال درخواست برای دریافت نام کامل کشور
        response = requests.get(
            f"https://api.iplocation.net/?cmd=ip-country&ip={ip_address}")
        if response.status_code == 200:
            data = response.json()
            country_name = data.get('country_name', country_code)

            # ساخت ایموجی پرچم از کد کشور
            flag = "🏳️"

            # تنظیم دستی کد کشور برای کشورهای خاص
            special_country_codes = {
                "Qatar": "QA",
                "UAE": "AE",
                "United Arab Emirates": "AE",
                "Saudi Arabia": "SA",
                "Iran": "IR",
                "Iraq": "IQ",
                "Kuwait": "KW",
                "Bahrain": "BH",
                "Oman": "OM",
                "Egypt": "EG",
                "Turkey": "TR",
                "Russia": "RU",
                "United States": "US",
                "USA": "US",
                "Germany": "DE",
                "United Kingdom": "GB",
                "UK": "GB",
                "France": "FR",
                "China": "CN",
                "India": "IN",
                "Japan": "JP",
                "Canada": "CA",
                "Pakistan": "PK"
            }

            if country_name in special_country_codes:
                country_code = special_country_codes[country_name]

            # Map پرچم‌های آماده برای کشورهای خاص
            special_flags = {
                "QA": "🇶🇦",  # قطر
                "AE": "🇦🇪",  # امارات
                "SA": "🇸🇦",  # عربستان
                "IR": "🇮🇷",  # ایران
                "IQ": "🇮🇶",  # عراق
                "KW": "🇰🇼",  # کویت
                "BH": "🇧🇭",  # بحرین
                "OM": "🇴🇲",  # عمان
                "EG": "🇪🇬",  # مصر
                "TR": "🇹🇷",  # ترکیه
                "RU": "🇷🇺",  # روسیه
                "US": "🇺🇸",  # آمریکا
                "DE": "🇩🇪",  # آلمان
                "GB": "🇬🇧",  # بریتانیا
                "FR": "🇫🇷",  # فرانسه
                "CN": "🇨🇳",  # چین
                "IN": "🇮🇳",  # هند
                "JP": "🇯🇵",  # ژاپن
                "CA": "🇨🇦",  # کانادا
                "PK": "🇵🇰"  # پاکستان
            }

            if country_code and country_code.upper() in special_flags:
                flag = special_flags[country_code.upper()]
                logger.info(
                    f"استفاده از پرچم آماده برای {country_name}: {flag}")
            elif country_code and len(country_code) == 2:
                country_code = country_code.upper()
                try:
                    flag_chars = []
                    for c in country_code:
                        if 'A' <= c <= 'Z':
                            flag_chars.append(chr(ord(c) + 127397))
                    if len(flag_chars) == 2:
                        flag = "".join(flag_chars)
                        logger.info(
                            f"تولید پرچم برای کشور: {flag} از کد {country_code}"
                        )
                except Exception as e:
                    logger.error(f"خطا در تولید پرچم: {e}")

            # افزودن IP به پایگاه داده
            db.add_ipv4_address(country_name, flag, ip_address)

            send_reply(
                update,
                f"✅ آدرس {ip_address} برای کشور {flag} {country_name} افزوده شد.",
                reply_markup=main_menu_keyboard(
                    update.callback_query.from_user.id))
        else:
            send_reply(update, "❌ خطا در دریافت اطلاعات کشور.")
    except Exception as e:
        send_reply(update, f"❌ خطایی رخ داد: {str(e)}")


# --- قابلیت‌های جدید ---
# حافظه آخرین IPهای افزوده شده
LAST_ADDED_IPS = deque(maxlen=20)

# --- هندلر جستجوی سریع ---
def cb_quick_search(update: Update, context: CallbackContext) -> None:
    send_reply(update, "🔍 لطفاً نام کشور یا بخشی از IP را وارد کنید:")
    context.user_data['search_mode'] = True

def handle_search_input(update: Update, context: CallbackContext) -> None:
    if context.user_data.get('search_mode'):
        query = update.message.text.strip().lower()
        results = []
        for country_code, (country, flag, ips) in db.get_ipv4_countries().items():
            if query in country.lower() or query in country_code.lower():
                results.append(f"{flag} {country}: {len(ips)} IP")
            else:
                for ip in ips:
                    if query in ip:
                        results.append(f"{flag} {country}: {ip}")
        if results:
            send_reply(update, "نتایج جستجو:\n" + "\n".join(results))
        else:
            send_reply(update, "نتیجه‌ای یافت نشد.")
        context.user_data['search_mode'] = False

# --- هندلر آخرین IPها ---
def cb_latest_ips(update: Update, context: CallbackContext) -> None:
    if not LAST_ADDED_IPS:
        send_reply(update, "هیچ IP جدیدی ثبت نشده است.")
        return
    text = "🆕 آخرین IPهای افزوده شده:\n" + "\n".join(LAST_ADDED_IPS)
    send_reply(update, text)

# --- افزودن به حافظه آخرین IPها هنگام افزودن ---
# در enter_new_ipv4 و process_ipv4_entry و هر جای دیگر که IP اضافه می‌شود:
# LAST_ADDED_IPS.appendleft(f"{flag} {country_name}: {ipv4}")

# --- دسته‌بندی بر اساس قاره ---
def cb_continent_list(update: Update, context: CallbackContext) -> None:
    # نمایش لیست قاره‌ها
    buttons = [[InlineKeyboardButton(name, callback_data=f'continent_{code}')]
               for code, name in CONTINENT_MAP.items()]
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='back')])
    send_reply(update, "🌎 یک قاره را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))

def cb_show_countries_by_continent(update: Update, context: CallbackContext) -> None:
    code = update.callback_query.data.split('_')[1]
    countries = [k for k, v in COUNTRY_TO_CONTINENT.items() if v == code]
    if not countries:
        send_reply(update, "کشوری برای این قاره ثبت نشده است.")
        return
    buttons = []
    for country_code in countries:
        country = db.get_ipv4_countries().get(country_code)
        if country:
            flag, name, ips = country[1], country[0], country[2]
            buttons.append([InlineKeyboardButton(f"{flag} {name} ({len(ips)})", callback_data=f"country_{country_code}")])
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='continent_list')])
    send_reply(update, "🌍 انتخاب کشور:", reply_markup=InlineKeyboardMarkup(buttons))

# --- ادمین: ارسال پیام همگانی ---
def cb_admin_broadcast(update: Update, context: CallbackContext) -> None:
    send_reply(update, "📢 لطفاً پیام خود را وارد کنید:")
    context.user_data['broadcast_mode'] = True

def handle_broadcast_input(update: Update, context: CallbackContext) -> None:
    if context.user_data.get('broadcast_mode'):
        msg = update.message.text.strip()
        count = 0
        for user_id in db.active_users:
            try:
                update.bot.send_message(chat_id=user_id, text=msg)
                count += 1
            except Exception:
                pass
        send_reply(update, f"📢 پیام به {count} کاربر ارسال شد.")
        context.user_data['broadcast_mode'] = False

# --- ادمین: خروجی CSV ---
def cb_export_ips(update: Update, context: CallbackContext) -> None:
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Country", "Flag", "IP"])
    for country_code, (country, flag, ips) in db.get_ipv4_countries().items():
        for ip in ips:
            writer.writerow([country, flag, ip])
    output.seek(0)
    update.effective_message.reply_document(document=io.BytesIO(output.read().encode()), filename="ipv4_list.csv")

# --- ثبت هندلرها در main() ---
# اضافه کردن CallbackQueryHandler(cb_quick_search, pattern='^quick_search$')
# اضافه کردن CallbackQueryHandler(cb_latest_ips, pattern='^latest_ips$')
# اضافه کردن CallbackQueryHandler(cb_continent_list, pattern='^continent_list$')
# اضافه کردن CallbackQueryHandler(cb_show_countries_by_continent, pattern='^continent_')
# اضافه کردن CallbackQueryHandler(cb_admin_broadcast, pattern='^admin_broadcast$')
# اضافه کردن CallbackQueryHandler(cb_export_ips, pattern='^export_ips$')
# اضافه کردن MessageHandler(Filters.text & ~Filters.command, handle_search_input) (در حالت search_mode)
# اضافه کردن MessageHandler(Filters.text & ~Filters.command, handle_broadcast_input) (در حالت broadcast_mode)

# --- Wireguard Endpoints Admin Panel ---
WG_ENDPOINTS_MENU, WG_ADD_ENDPOINT, WG_REMOVE_ENDPOINT = range(20, 23)

def cb_admin_manage_wg_endpoints(update: Update, context: CallbackContext) -> int:
    endpoints = db.get_endpoints()
    text = "🌐 لیست Endpointهای فعلی:\n" + ("\n".join(endpoints) if endpoints else "هیچ موردی ثبت نشده است.")
    buttons = [[InlineKeyboardButton("➕ افزودن Endpoint", callback_data='add_wg_endpoint')]]
    if endpoints:
        for ep in endpoints:
            buttons.append([InlineKeyboardButton(f"❌ حذف {ep}", callback_data=f'remove_wg_endpoint_{ep}')])
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='admin_panel')])
    send_reply(update, text, reply_markup=InlineKeyboardMarkup(buttons))
    return WG_ENDPOINTS_MENU

def cb_add_wg_endpoint(update: Update, context: CallbackContext) -> int:
    send_reply(update, "لطفاً آدرس Endpoint جدید را وارد کنید:")
    return WG_ADD_ENDPOINT

def enter_wg_endpoint(update: Update, context: CallbackContext) -> int:
    endpoint = update.message.text.strip()
    db.add_endpoint(endpoint)
    send_reply(update, f"✅ Endpoint افزوده شد: {endpoint}")
    return cb_admin_manage_wg_endpoints(update, context)

def cb_remove_wg_endpoint(update: Update, context: CallbackContext) -> int:
    endpoint = update.callback_query.data.replace('remove_wg_endpoint_', '')
    db.remove_endpoint(endpoint)
    send_reply(update, f"❌ Endpoint حذف شد: {endpoint}")
    return cb_admin_manage_wg_endpoints(update, context)

# --- Wireguard User Flow ---
from telegram.ext import ConversationHandler
WG_SELECT_ADDRESS, WG_SELECT_PORT, WG_CONFIRM = range(30, 33)

@require_subscription
def cb_wireguard(update: Update, context: CallbackContext) -> int:
    # مرحله انتخاب آدرس
    addresses = ["10.10.0.2/32", "10.66.66.2/32", "192.168.100.2/32"]
    buttons = [[InlineKeyboardButton(addr, callback_data=f'wg_addr_{addr}')]
               for addr in addresses]
    buttons.append([InlineKeyboardButton("لغو", callback_data='back')])
    send_reply(update, "آدرس مورد نظر را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return WG_SELECT_ADDRESS

def cb_wg_select_address(update: Update, context: CallbackContext) -> int:
    addr = update.callback_query.data.replace('wg_addr_', '')
    context.user_data['wg_address'] = addr
    # مرحله انتخاب پورت
    ports = [53, 80, 443, 8080, 51820, 1195]
    buttons = [[InlineKeyboardButton(str(p), callback_data=f'wg_port_{p}') for p in ports[:3]],
               [InlineKeyboardButton(str(p), callback_data=f'wg_port_{p}') for p in ports[3:]]]
    buttons.append([InlineKeyboardButton("لغو", callback_data='back')])
    send_reply(update, "پورت مورد نظر را انتخاب کنید یا عدد دلخواه را ارسال کنید:", reply_markup=InlineKeyboardMarkup(buttons))
    return WG_SELECT_PORT

def cb_wg_select_port(update: Update, context: CallbackContext) -> int:
    port = int(update.callback_query.data.replace('wg_port_', ''))
    context.user_data['wg_port'] = port
    return wg_generate_config(update, context)

def enter_wg_port(update: Update, context: CallbackContext) -> int:
    try:
        port = int(update.message.text.strip())
        context.user_data['wg_port'] = port
        return wg_generate_config(update, context)
    except Exception:
        send_reply(update, "پورت معتبر وارد کنید!")
        return WG_SELECT_PORT

def wg_generate_config(update: Update, context: CallbackContext) -> int:
    # انتخاب endpoint رندوم
    endpoints = db.get_endpoints()
    if not endpoints:
        send_reply(update, "❌ هیچ Endpointی توسط ادمین ثبت نشده است.")
        return ConversationHandler.END
    import random
    endpoint = random.choice(endpoints)
    # تشخیص کشور endpoint
    try:
        import requests
        country = requests.get(f'https://api.iplocation.net/?ip={endpoint.split(":")[0]}').json().get('country_name', 'نامشخص')
    except Exception:
        country = 'نامشخص'
    # انتخاب MTU رندوم
    mtu = random.choice([1360, 1380, 1440])
    # DNS ثابت و یکی از endpointها
    dns1 = "10.202.10.10"
    dns2 = endpoint.split(":")[0]
    # ساخت کانفیگ
    from wg import WireguardConfig
    wg = WireguardConfig()
    private_key = wg.generate_private_key()
    public_key = wg.generate_public_key()
    address = context.user_data['wg_address']
    port = context.user_data['wg_port']
    config = f"""[Interface]\nPrivateKey = {private_key}\nAddress = {address}\nDNS = {dns1}, {dns2}\nMTU = {mtu}\n\n[Peer]\nPublicKey = {public_key}\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = {endpoint}:{port}\nPersistentKeepalive = 25\n"""
    caption = f"✨ کانفیگ وایرگارد اختصاصی شما آماده است!\n\n🌍 کشور سرور: {country}\n🌐 Endpoint: {endpoint}\n🔢 پورت: {port}\n🟢 آدرس: {address}\n🔑 MTU: {mtu}\n🟦 DNS: {dns1}, {dns2}\n\nبرای اتصال کافیست این کانفیگ را در برنامه WireGuard وارد کنید.\nدر صورت مشکل با پشتیبانی تماس بگیرید."
    send_reply(update, f"<b>{caption}</b>\n\n<pre>{config}</pre>", parse_mode='HTML')
    return ConversationHandler.END

# --- ثبت در main() ---
# اضافه کردن CallbackQueryHandler(cb_admin_manage_wg_endpoints, pattern='^admin_manage_wg_endpoints$')
# اضافه کردن CallbackQueryHandler(cb_add_wg_endpoint, pattern='^add_wg_endpoint$')
# اضافه کردن CallbackQueryHandler(cb_remove_wg_endpoint, pattern='^remove_wg_endpoint_')
# اضافه کردن MessageHandler(Filters.text & ~Filters.command, enter_wg_endpoint) (در حالت WG_ADD_ENDPOINT)
# اضافه کردن ConversationHandler برای وایرگارد با مراحل WG_SELECT_ADDRESS, WG_SELECT_PORT, WG_CONFIRM

# --- زیرمنوی لیست IPv4 ---
def cb_ipv4_menu(update: Update, context: CallbackContext) -> None:
    buttons = [
        [InlineKeyboardButton("📋 مشاهده لیست کشورها", callback_data='get_ipv4')],
        [InlineKeyboardButton("🔍 جستجوی سریع کشور/IP", callback_data='quick_search_ipv4')],
        [InlineKeyboardButton("🌎 دسته‌بندی بر اساس قاره", callback_data='continent_list_ipv4')],
        [InlineKeyboardButton("🆕 آخرین IPهای افزوده شده", callback_data='latest_ips_ipv4')],
        [InlineKeyboardButton("↩️ بازگشت", callback_data='back')]
    ]
    send_reply(update, "لطفاً یک گزینه انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))

# --- اصلاح هندلرهای جستجو/قاره/آخرین IP برای زیرمنوی ipv4 ---
def cb_quick_search_ipv4(update: Update, context: CallbackContext) -> None:
    send_reply(update, "🔍 لطفاً نام کشور یا بخشی از IP را وارد کنید:")
    context.user_data['search_mode_ipv4'] = True

def handle_search_input_ipv4(update: Update, context: CallbackContext) -> None:
    if context.user_data.get('search_mode_ipv4'):
        query = update.message.text.strip().lower()
        results = []
        for country_code, (country, flag, ips) in db.get_ipv4_countries().items():
            if query in country.lower() or query in country_code.lower():
                results.append(f"{flag} {country}: {len(ips)} IP")
            else:
                for ip in ips:
                    if query in ip:
                        results.append(f"{flag} {country}: {ip}")
        if results:
            send_reply(update, "نتایج جستجو:\n" + "\n".join(results))
        else:
            send_reply(update, "نتیجه‌ای یافت نشد.")
        context.user_data['search_mode_ipv4'] = False

def cb_latest_ips_ipv4(update: Update, context: CallbackContext) -> None:
    if not LAST_ADDED_IPS:
        send_reply(update, "هیچ IP جدیدی ثبت نشده است.")
        return
    text = "🆕 آخرین IPهای افزوده شده:\n" + "\n".join(LAST_ADDED_IPS)
    send_reply(update, text)

CONTINENT_MAP = {
    'AS': 'آسیا', 'EU': 'اروپا', 'AF': 'آفریقا', 'NA': 'آمریکای شمالی', 'SA': 'آمریکای جنوبی', 'OC': 'اقیانوسیه', 'AN': 'جنوبگان'
}
COUNTRY_TO_CONTINENT = {
    # نمونه: 'IR': 'AS', 'SA': 'AS', ...
}
def cb_continent_list_ipv4(update: Update, context: CallbackContext) -> None:
    buttons = [[InlineKeyboardButton(name, callback_data=f'continent_ipv4_{code}')]
               for code, name in CONTINENT_MAP.items()]
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='ipv4_menu')])
    send_reply(update, "🌎 یک قاره را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))

def cb_show_countries_by_continent_ipv4(update: Update, context: CallbackContext) -> None:
    code = update.callback_query.data.split('_')[2]
    countries = [k for k, v in COUNTRY_TO_CONTINENT.items() if v == code]
    if not countries:
        send_reply(update, "کشوری برای این قاره ثبت نشده است.")
        return
    buttons = []
    for country_code in countries:
        country = db.get_ipv4_countries().get(country_code)
        if country:
            flag, name, ips = country[1], country[0], country[2]
            buttons.append([InlineKeyboardButton(f"{flag} {name} ({len(ips)})", callback_data=f"country_{country_code}")])
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='continent_list_ipv4')])
    send_reply(update, "🌍 انتخاب کشور:", reply_markup=InlineKeyboardMarkup(buttons))


if __name__ == '__main__':
    main()
