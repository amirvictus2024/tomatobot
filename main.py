import os
import logging
import random
import json
import requests
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

# --- وضعیت سیستم ---
LOCATIONS_ENABLED = True  # وضعیت فعال/غیرفعال بودن لوکیشن‌ها
import threading

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
BOT_TOKEN = os.getenv("BOT_TOKEN",
                      "8093306771:AAHIt63O2nHmEfFCx1u3w4kegqxuyRY2Xv4")

# Conversation states
ENTER_ACTIVATION, ENTER_NEW_CODE, ENTER_NEW_IPV4, ENTER_COUNTRY_NAME, ENTER_COUNTRY_FLAG, CHOOSE_CODE_TYPE, ENTER_TOKEN_COUNT, ENTER_IP_FOR_VALIDATION, ENTER_BROADCAST_MESSAGE, ENTER_CHANNEL_LINK = range(
    10)

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
    """Updated main menu with subscription status display and activation button."""
    subscription_status = get_subscription_status(user_id)
    buttons = [[
        InlineKeyboardButton(f"🔐 {subscription_status}", callback_data='noop')
    ]]

    if not db.is_user_active(user_id) and not db.is_user_subscribed(user_id):
        buttons.append([
            InlineKeyboardButton("🔑 فعال‌سازی اشتراک",
                                 callback_data='activate')
        ])

    # بررسی وضعیت دکمه‌ها و ساخت دکمه‌های منو
    ipv6_button = InlineKeyboardButton("🌐 تولید IPv6",
                                       callback_data='generate_ipv6')
    ipv4_button = InlineKeyboardButton("📋 لیست IPv4", callback_data='get_ipv4')

    validate_button = InlineKeyboardButton("🔍 اعتبارسنجی IPv4",
                                           callback_data='validate_ipv4')
    wireguard_button = InlineKeyboardButton("🔒 وایرگارد اختصاصی",
                                            callback_data='wireguard')

    account_button = InlineKeyboardButton("👤 حساب کاربری",
                                          callback_data='user_account')
    support_button = InlineKeyboardButton("❓ پشتیبانی",
                                          callback_data='support')

    # اگر دکمه غیرفعال بود، به جای آن دکمه‌ی وضعیت نگهداری نمایش داده شود
    if DISABLED_BUTTONS.get('generate_ipv6', False):
        ipv6_button = InlineKeyboardButton("🚧 تولید IPv6 (در حال بروزرسانی)",
                                           callback_data='disabled_button')

    if DISABLED_BUTTONS.get('get_ipv4', False):
        ipv4_button = InlineKeyboardButton("🚧 لیست IPv4 (در حال بروزرسانی)",
                                           callback_data='disabled_button')

    if DISABLED_BUTTONS.get('validate_ipv4', False):
        validate_button = InlineKeyboardButton(
            "🚧 اعتبارسنجی IPv4 (در حال بروزرسانی)",
            callback_data='disabled_button')

    if DISABLED_BUTTONS.get('wireguard', False):
        wireguard_button = InlineKeyboardButton(
            "🚧 وایرگارد (در حال بروزرسانی)", callback_data='disabled_button')

    if DISABLED_BUTTONS.get('user_account', False):
        account_button = InlineKeyboardButton(
            "🚧 حساب کاربری (در حال بروزرسانی)",
            callback_data='disabled_button')

    if DISABLED_BUTTONS.get('support', False):
        support_button = InlineKeyboardButton("🚧 پشتیبانی (در حال بروزرسانی)",
                                              callback_data='disabled_button')

    buttons.extend([[ipv6_button, ipv4_button],
                    [validate_button, wireguard_button],
                    [account_button, support_button]])

    if user_id == ADMIN_ID:
        buttons.append([
            InlineKeyboardButton("🛠️ پنل ادمین", callback_data='admin_panel')
        ])

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
            send_reply(update, welcome_text, reply_markup=create_join_channel_button())
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
    else:
        # چینش کشورها در سه ستون
        buttons = []
        row = []
        count = 0
        countries_with_ips = False

        for country_code, (country, flag, ips) in country_ips.items():
            # فقط کشورهایی که حداقل یک آی‌پی دارند و غیرفعال نیستند را نمایش بده
            if len(ips) > 0 and not db.is_location_disabled(
                    country_code, "ipv4"):
                countries_with_ips = True
                row.append(
                    InlineKeyboardButton(
                        f"{flag} {country} ({len(ips)})",
                        callback_data=f"country_{country_code}"))
                count += 1
                if count % 3 == 0:  # هر سه آیتم یک ردیف جدید
                    buttons.append(row)
                    row = []

        # اضافه کردن آیتم‌های باقی‌مانده
        if row:
            buttons.append(row)

        # اضافه کردن دکمه بازگشت
        buttons.append(
            [InlineKeyboardButton("↩️ بازگشت", callback_data='back')])

        if not countries_with_ips:
            send_reply(update,
                       "ℹ️ هیچ کشوری با آدرس IP فعال وجود ندارد.",
                       reply_markup=InlineKeyboardMarkup([[
                           InlineKeyboardButton("↩️ بازگشت",
                                                callback_data='back')
                       ]]))
        else:
            send_reply(update,
                       "🌍 انتخاب کشور:",
                       reply_markup=InlineKeyboardMarkup(buttons))


def cb_country_ips(update: Update, context: CallbackContext) -> None:
    try:
        country_code = update.callback_query.data.split('_')[1]
        ips = db.get_ips_by_country(country_code)

        # نمایش اطلاعات کشور از پایگاه داده
        country_data = db.get_ipv4_countries().get(country_code)
        if not country_data:
            update.callback_query.answer("اطلاعات کشور یافت نشد.")
            cb_get_ipv4(update, context)
            return

        country_name = country_data[0] if country_data else country_code
        flag = country_data[1] if country_data else "🏳️"

        if ips:
            text = f"📡 آدرس‌های {flag} {country_name}:\n" + "\n".join(
                f"• `{ip}`" for ip in ips)
            # افزودن دکمه بازگشت
            buttons = [[
                InlineKeyboardButton("↩️ بازگشت به لیست کشورها",
                                     callback_data='get_ipv4')
            ]]
            send_reply(update,
                       text,
                       parse_mode=ParseMode.MARKDOWN,
                       reply_markup=InlineKeyboardMarkup(buttons))
        else:
            # اگر آدرسی یافت نشد، به منوی اصلی برگرد
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
    buttons = [
        [
            InlineKeyboardButton("➕ اضافه کردن IPv4",
                                 callback_data='admin_add_ipv4'),
            InlineKeyboardButton("➕ اضافه کردن کد فعالسازی",
                                 callback_data='admin_add_code')
        ],
        [
            InlineKeyboardButton("🔍 پردازش و افزودن IP",
                                 callback_data='admin_process_ip')
        ],
        [
            InlineKeyboardButton("❌ حذف IPv4",
                                 callback_data='admin_remove_ipv4'),
            InlineKeyboardButton("🌐 مدیریت لوکیشن‌ها",
                                 callback_data='admin_manage_locations')
        ],
        [
            InlineKeyboardButton("📊 آمار", callback_data='admin_stats'),
            InlineKeyboardButton("👥 مدیریت کاربران",
                                 callback_data='admin_manage_users')
        ],
        [
            InlineKeyboardButton("🚫 مدیریت دکمه‌ها",
                                 callback_data='admin_manage_buttons')
        ],
        [
            InlineKeyboardButton("📢 ارسال پیام همگانی", 
                                 callback_data='admin_broadcast')
        ],
        [
            InlineKeyboardButton("🔔 تنظیم کانال اجباری", 
                                 callback_data='admin_set_channel')
        ],
        [
            InlineKeyboardButton("↩️ بازگشت", callback_data='back'),
            InlineKeyboardButton("🔒 خاموش کردن ربات",
                                 callback_data='admin_shutdown'),
            InlineKeyboardButton("🟢 روشن کردن ربات",
                                 callback_data='admin_startup')
        ],
    ]
    send_reply(update,
               "🛠️ پنل ادمین:",
               reply_markup=InlineKeyboardMarkup(buttons))


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
        text = update.message.text.strip()
        # Extract IP and country details
        if '->' in text:
            ip_part, country_part = text.split('->')
            ip_address = ip_part.split()[-1]
            flag, country_name = country_part.split(maxsplit=1)
            # Add the IP to the database
            db.add_ipv4_address(country_name.strip(), flag.strip(),
                                ip_address.strip())
            send_reply(update, "✅ آدرس IPv4 پردازش شد و افزوده گردید.")
        else:
            send_reply(update,
                       "❌ فرمت وارد شده نادرست است. لطفاً مجدد تلاش کنید.")
    except Exception as e:
        send_reply(update, f"❌ مشکلی در پردازش وجود دارد: {e}")
    return ConversationHandler.END


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
    """مدیریت دکمه‌های ربات"""
    buttons = []

    # ایجاد دکمه‌ها برای هر قابلیت
    for button_name, is_disabled in DISABLED_BUTTONS.items():
        status = "🚫 غیرفعال است" if is_disabled else "✅ فعال است"
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

        buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f'admin_{action}_button_{button_name}')
        ])

    buttons.append([
        InlineKeyboardButton("↩️ بازگشت به پنل ادمین",
                             callback_data='admin_panel')
    ])
    send_reply(update,
               "🚫 مدیریت دکمه‌های ربات:",
               reply_markup=InlineKeyboardMarkup(buttons))


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
    """تولید پیکربندی وایرگارد اختصاصی."""
    user_id = update.callback_query.from_user.id

    # بررسی نوع اشتراک و کم کردن توکن در صورت نیاز
    user_data = db.active_users.get(user_id, {})
    if user_data.get('type') == 'token':
        # کسر توکن برای هر بار استفاده (وایرگارد ۲ توکن نیاز دارد)
        current_tokens = user_data.get('tokens', 0)
        if current_tokens < 2:
            send_reply(
                update,
                "❌ وایرگارد اختصاصی نیاز به حداقل ۲ توکن دارد. توکن کافی ندارید.",
                reply_markup=main_menu_keyboard(user_id))
            return

        # کم کردن ۲ توکن و به‌روزرسانی پایگاه داده
        db.active_users[user_id]['tokens'] = current_tokens - 2
        db.save_database()

    # استفاده از کلاس WireguardConfig برای تولید پیکربندی
    wg_config = WireguardConfig()
    config = wg_config.generate_config()

    # نمایش پیکربندی به کاربر
    message = "🔒 پیکربندی وایرگارد اختصاصی شما:\n\n"
    message += f"```\n{config}\n```"

    # نمایش تعداد توکن‌های باقی‌مانده برای کاربران توکنی
    if user_data.get('type') == 'token':
        remaining_tokens = db.active_users[user_id].get('tokens', 0)
        message += f"\n\n🔄 توکن‌های باقی‌مانده: {remaining_tokens}"

    buttons = [[
        InlineKeyboardButton("↩️ بازگشت به منوی اصلی", callback_data='back')
    ]]
    send_reply(update,
               message,
               parse_mode=ParseMode.MARKDOWN,
               reply_markup=InlineKeyboardMarkup(buttons))


def main() -> None:
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
            CallbackQueryHandler(cb_admin_broadcast, pattern='^admin_broadcast$')
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
            CallbackQueryHandler(cb_admin_set_channel, pattern='^admin_set_channel$')
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
    
    # هندلرهای جدید برای درخواست و تایید/رد IP
    dp.add_handler(
        CallbackQueryHandler(cb_request_add_ip,
                             pattern='^request_add_ip_'))
    dp.add_handler(
        CallbackQueryHandler(cb_approve_ip,
                             pattern='^approve_ip_'))
    dp.add_handler(
        CallbackQueryHandler(cb_reject_ip,
                             pattern='^reject_ip_'))

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
    updater.start_polling()
    updater.idle()


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
            update.callback_query.answer("خطا در فرمت داده‌ها. لطفاً دوباره تلاش کنید.")
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
        update.callback_query.answer("درخواست شما به ادمین ارسال شد و در انتظار تایید است.")
        send_reply(update, "✅ درخواست افزودن IP به لیست ارسال شد و در انتظار تایید ادمین است.")

        # اطلاع به ادمین
        admin_buttons = [
            [
                InlineKeyboardButton("✅ تایید", 
                                    callback_data=f'approve_ip_{request_id}'),
                InlineKeyboardButton("❌ رد", 
                                    callback_data=f'reject_ip_{request_id}')
            ]
        ]
        
        # ارسال پیام به ادمین با اطلاعات کامل
        context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 درخواست جدید برای افزودن IP:\n\n"
                 f"👤 کاربر: {username}\n"
                 f"🌐 آدرس IP: {ip_address}\n"
                 f"🌍 کشور: {flag} {country_name}\n"
                 f"🔑 شناسه درخواست: {request_id}\n\n"
                 f"لطفاً این درخواست را تایید یا رد کنید:",
            reply_markup=InlineKeyboardMarkup(admin_buttons)
        )
        
        # لاگ کردن درخواست برای بررسی
        logger.info(f"درخواست جدید IP با شناسه {request_id} ایجاد شد. IP: {ip_address}, کاربر: {user_id}")
        
    except Exception as e:
        update.callback_query.answer(f"خطایی رخ داد: {str(e)[:50]}")
        logger.error(f"خطا در درخواست افزودن IP: {e}")
        send_reply(update, f"❌ خطا در ارسال درخواست: {str(e)[:100]}")

def cb_approve_ip(update: Update, context: CallbackContext) -> None:
    """تایید درخواست افزودن IP توسط ادمین."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer("فقط ادمین می‌تواند این عملیات را انجام دهد.")
        return
    
    try:
        request_id = update.callback_query.data.split('_')[2]
        if request_id not in PENDING_IPS:
            update.callback_query.answer("درخواست یافت نشد یا قبلاً پردازش شده است.")
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
            f"✅ IP {ip_address} با موفقیت تایید و به لیست اضافه شد."
        )
        
        # اطلاع به کاربر
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"✅ درخواست شما برای افزودن IP {ip_address} برای کشور {flag} {country_name} توسط ادمین تایید شد و به لیست اضافه شد."
            )
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر: {e}")
    except Exception as e:
        logger.error(f"خطا در تایید IP: {e}")
        update.callback_query.answer(f"خطایی رخ داد: {str(e)[:50]}")
        update.callback_query.message.reply_text("خطایی در پردازش درخواست رخ داد.")

def cb_admin_broadcast(update: Update, context: CallbackContext) -> int:
    """آغاز فرآیند ارسال پیام همگانی."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer("فقط ادمین می‌تواند پیام همگانی ارسال کند.")
        return ConversationHandler.END
    
    send_reply(update, "📢 لطفاً متن پیام همگانی را وارد کنید:")
    return ENTER_BROADCAST_MESSAGE

def enter_broadcast_message(update: Update, context: CallbackContext) -> int:
    """دریافت متن پیام همگانی و ارسال به همه کاربران."""
    message_text = update.message.text.strip()
    user_id = update.message.from_user.id
    
    if user_id != ADMIN_ID:
        update.message.reply_text("⛔ فقط ادمین می‌تواند پیام همگانی ارسال کند.")
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
                parse_mode=ParseMode.MARKDOWN
            )
            success_count += 1
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر {user_id}: {e}")
            fail_count += 1
    
    # به‌روزرسانی پیام وضعیت
    status_message.edit_text(
        f"✅ پیام همگانی ارسال شد.\n\n"
        f"📊 آمار ارسال:\n"
        f"✅ موفق: {success_count}\n"
        f"❌ ناموفق: {fail_count}\n"
        f"📋 کل: {success_count + fail_count}"
    )
    
    return ConversationHandler.END

def cb_admin_set_channel(update: Update, context: CallbackContext) -> int:
    """آغاز فرآیند تنظیم کانال اجباری."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer("فقط ادمین می‌تواند کانال اجباری را تنظیم کند.")
        return ConversationHandler.END
    
    send_reply(update, 
               "📢 لطفاً لینک کانال اجباری را وارد کنید (مثال: @channel_name):\n\n"
               "برای غیرفعال کردن عضویت اجباری، عبارت 'disable' را ارسال کنید.")
    return ENTER_CHANNEL_LINK

def enter_channel_link(update: Update, context: CallbackContext) -> int:
    """دریافت لینک کانال اجباری و ذخیره آن."""
    channel_link = update.message.text.strip()
    user_id = update.message.from_user.id
    
    if user_id != ADMIN_ID:
        update.message.reply_text("⛔ فقط ادمین می‌تواند کانال اجباری را تنظیم کند.")
        return ConversationHandler.END
    
    global REQUIRED_CHANNEL
    
    if channel_link.lower() == 'disable':
        REQUIRED_CHANNEL = ""
        update.message.reply_text("✅ عضویت اجباری در کانال غیرفعال شد.")
    else:
        if not channel_link.startswith('@'):
            channel_link = '@' + channel_link
        
        REQUIRED_CHANNEL = channel_link
        update.message.reply_text(f"✅ کانال اجباری به {channel_link} تغییر یافت.")
    
    return ConversationHandler.END

def check_channel_membership(user_id, context) -> bool:
    """بررسی عضویت کاربر در کانال اجباری."""
    if not REQUIRED_CHANNEL:
        return True  # اگر کانال اجباری تنظیم نشده باشد، همه مجازند
    
    try:
        user_status = context.bot.get_chat_member(
            chat_id=REQUIRED_CHANNEL, 
            user_id=user_id
        )
        # اگر کاربر عضو کانال باشد (هر نوع عضویتی به جز left یا kicked)
        if user_status.status not in ['left', 'kicked']:
            return True
    except Exception as e:
        logger.error(f"خطا در بررسی عضویت کانال: {e}")
    
    return False

def create_join_channel_button() -> InlineKeyboardMarkup:
    """ایجاد دکمه عضویت در کانال."""
    buttons = [[InlineKeyboardButton("🔔 عضویت در کانال", url=f"https://t.me/{REQUIRED_CHANNEL[1:]}")]]
    return InlineKeyboardMarkup(buttons)

    # حذف درخواست از لیست انتظار
    del PENDING_IPS[request_id]

def cb_reject_ip(update: Update, context: CallbackContext) -> None:
    """رد درخواست افزودن IP توسط ادمین."""
    if update.callback_query.from_user.id != ADMIN_ID:
        update.callback_query.answer("فقط ادمین می‌تواند این عملیات را انجام دهد.")
        return
    
    try:
        request_id = update.callback_query.data.split('_')[2]
        if request_id not in PENDING_IPS:
            update.callback_query.answer("درخواست یافت نشد یا قبلاً پردازش شده است.")
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
            f"❌ درخواست افزودن IP {ip_address} رد شد."
        )
        
        # اطلاع به کاربر
        try:
            context.bot.send_message(
                chat_id=user_id,
                text=f"❌ درخواست شما برای افزودن IP {ip_address} توسط ادمین رد شد."
            )
        except Exception as e:
            logger.error(f"خطا در ارسال پیام به کاربر: {e}")
    except Exception as e:
        logger.error(f"خطا در رد IP: {e}")
        update.callback_query.answer(f"خطایی رخ داد: {str(e)[:50]}")
        update.callback_query.message.reply_text("خطایی در پردازش درخواست رخ داد.")



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
        message.edit_text("❌ آدرس IP وارد شده معتبر نیست. لطفاً یک آدرس IPv4 معتبر وارد کنید.")
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
        country_response = requests.get(f"https://api.iplocation.net/?cmd=ip-country&ip={ip_address}")

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
                    logger.info(f"کد کشور از API ثانویه: {data['country_code']}")

            # نمایش نتیجه
            country = data.get('country_name', 'نامشخص')
            country_code = data.get('country_code', '').upper()
            isp = data.get('isp', 'نامشخص')
            
            # لاگ کردن اطلاعات برای بررسی
            logger.info(f"IP: {ip_address}, Country: {country}, Code: {country_code}")

            # دریافت پرچم کشور
            flag = "🏳️"
            if country_code and len(country_code) == 2:
                # تنظیم دستی کد کشور برای کشورهای خاص که ممکن است از API به درستی دریافت نشوند
                special_country_codes = {
                    "Qatar": "QA",
                    "UAE": "AE",
                    "United Arab Emirates": "AE",
                    "Saudi Arabia": "SA",
                    "Iran": "IR",
                    "Iraq": "IQ",
                    "Kuwait": "KW",
                    "Bahrain": "BH"
                }
                
                if country in special_country_codes:
                    country_code = special_country_codes[country]
                    
                # ساخت ایموجی پرچم از کد کشور
                try:
                    # تبدیل کدهای ISO دو حرفی به ایموجی پرچم
                    flag_chars = []
                    for c in country_code.upper():
                        if 'A' <= c <= 'Z':
                            flag_chars.append(chr(ord(c) + 127397))
                    if len(flag_chars) == 2:
                        flag = "".join(flag_chars)
                        logger.info(f"تولید پرچم برای {country}: {flag} از کد {country_code}")
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
                            f'request_add_ip_{country_code}_{ip_address}_{country}_{flag}')
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
            if country_code and len(country_code) == 2:
                country_code = country_code.upper()
                try:
                    flag_chars = []
                    for c in country_code:
                        if 'A' <= c <= 'Z':
                            flag_chars.append(chr(ord(c) + 127397))
                    if len(flag_chars) == 2:
                        flag = "".join(flag_chars)
                        logger.info(f"تولید پرچم برای کشور: {flag} از کد {country_code}")
                except Exception as e:
                    logger.error(f"خطا در تولید پرچم: {e}")
                    
                # پشتیبانی از کشورهای خاص
                if not flag or flag == "🏳️":
special_flags = {
    "QA": "🇶🇦",  # قطر
    "AE": "🇦🇪",  # امارات
    "SA": "🇸🇦",  # عربستان
    "IR": "🇮🇷",  # ایران
    "IQ": "🇮🇶",  # عراق
    "KW": "🇰🇼",  # کویت
    "BH": "🇧🇭",  # بحرین
    "AF": "🇦🇫",  # افغانستان
    "AL": "🇦🇱",  # آلبانی
    "DZ": "🇩🇿",  # الجزایر
    "AD": "🇦🇩",  # آندورا
    "AO": "🇦🇴",  # آنگولا
    "AR": "🇦🇷",  # آرژانتین
    "AM": "🇦🇲",  # ارمنستان
    "AU": "🇦🇺",  # استرالیا
    "AT": "🇦🇹",  # اتریش
    "AZ": "🇦🇿",  # آذربایجان
    "BS": "🇧🇸",  # باهاما
    "BH": "🇧🇭",  # بحرین
    "BD": "🇧🇩",  # بنگلادش
    "BB": "🇧🇧",  # باربادوس
    "BY": "🇧🇾",  # بلاروس
    "BE": "🇧🇪",  # بلژیک
    "BZ": "🇧🇿",  # بلیز
    "BJ": "🇧🇯",  # بنین
    "BT": "🇧🇹",  # بوتان
    "BO": "🇧🇴",  # بولیوی
    "BA": "🇧🇦",  # بوسنی و هرزگوین
    "BW": "🇧🇼",  # بوتسوانا
    "BR": "🇧🇷",  # برزیل
    "BN": "🇧🇳",  # برونئی
    "BG": "🇧🇬",  # بلغارستان
    "BF": "🇧🇫",  # بورکینافاسو
    "BI": "🇧🇮",  # بوروندی
    "KH": "🇰🇭",  # کامبوج
    "CM": "🇨🇲",  # کامرون
    "CA": "🇨🇦",  # کانادا
    "CV": "🇨🇻",  # کیپ ورد
    "KY": "🇰🇾",  # جزایر کیمن
    "CF": "🇨🇫",  # جمهوری آفریقای مرکزی
    "TD": "🇹🇩",  # چاد
    "CL": "🇨🇱",  # شیلی
    "CN": "🇨🇳",  # چین
    "CO": "🇨🇴",  # کلمبیا
    "KM": "🇰🇲",  # کومور
    "CG": "🇨🇬",  # جمهوری کنگو
    "CD": "🇨🇩",  # جمهوری دموکراتیک کنگو
    "CR": "🇨🇷",  # کاستاریکا
    "CU": "🇨🇺",  # کوبا
    "CY": "🇨🇾",  # قبرس
    "CZ": "🇨🇿",  # چک
    "DK": "🇩🇰",  # دانمارک
    "DJ": "🇩🇯",  # جیبوتی
    "DM": "🇩🇲",  # دومینیکا
    "DO": "🇩🇴",  # جمهوری دومینیکن
    "EC": "🇪🇨",  # اکوادور
    "EG": "🇪🇬",  # مصر
    "SV": "🇸🇻",  # السالوادور
    "GQ": "🇬🇶",  # گینه استوایی
    "ER": "🇪🇷",  # اریتره
    "EE": "🇪🇪",  # استونی
    "SZ": "🇸🇿",  # اسواتینی
    "ET": "🇪🇹",  # اتیوپی
    "FI": "🇫🇮",  # فنلاند
    "FJ": "🇫🇯",  # فیجی
    "FM": "🇫🇲",  # میکرونزی
    "FR": "🇫🇷",  # فرانسه
    "GA": "🇬🇦",  # گابن
    "GB": "🇬🇧",  # بریتانیا
    "GD": "🇬🇩",  # گرنادا
    "GE": "🇬🇪",  # گرجستان
    "GH": "🇬🇭",  # غنا
    "GR": "🇬🇷",  # یونان
    "GT": "🇬🇹",  # گواتمالا
    "GN": "🇬🇳",  # گینه
    "GW": "🇬🇼",  # گینه بیسائو
    "GY": "🇬🇾",  # گویانا
    "HT": "🇭🇹",  # هائیتی
    "HN": "🇭🇳",  # هندوراس
    "HK": "🇭🇰",  # هنگ کنگ
    "HU": "🇭🇺",  # مجارستان
    "IS": "🇮🇸",  # ایسلند
    "IN": "🇮🇳",  # هند
    "ID": "🇮🇩",  # اندونزی
    "IR": "🇮🇷",  # ایران
    "IQ": "🇮🇶",  # عراق
    "IE": "🇮🇪",  # ایرلند
    "IL": "🇮🇱",  # اسرائیل
    "IT": "🇮🇹",  # ایتالیا
    "JM": "🇯🇲",  # جامائیکا
    "JP": "🇯🇵",  # ژاپن
    "JO": "🇯🇴",  # اردن
    "KZ": "🇰🇿",  # قزاقستان
    "KE": "🇰🇪",  # کنیا
    "KI": "🇰🇮",  # کیریباتی
    "KP": "🇰🇵",  # کره شمالی
    "KR": "🇰🇷",  # کره جنوبی
    "KW": "🇰🇼",  # کویت
    "KG": "🇰🇬",  # قرقیزستان
    "LA": "🇱🇦",  # لائوس
    "LV": "🇱🇻",  # لتونی
    "LB": "🇱🇧",  # لبنان
    "LS": "🇱🇸",  # لسوتو
    "LR": "🇱🇷",  # لیبریا
    "LY": "🇱🇾",  # لیبی
    "LT": "🇱🇹",  # لیتوانی
    "LU": "🇱🇺",  # لوکزامبورگ
    "MO": "🇲🇴",  # ماکائو
    "MK": "🇲🇰",  # مقدونیه شمالی
    "MG": "🇲🇬",  # ماداگاسکار
    "MW": "🇲🇼",  # مالاوی
    "MY": "🇲🇾",  # مالزی
    "MV": "🇲🇻",  # مالدیو
    "ML": "🇲🇱",  # مالی
    "MT": "🇲🇹",  # مالت
    "MH": "🇲🇭",  # جزایر مارشال
    "MQ": "🇲🇶",  # ماریتینی
    "MR": "🇲🇷",  # موریتانی
    "MU": "🇲🇺",  # موریس
    "MX": "🇲🇽",  # مکزیک
    "FM": "🇫🇲",  # میکرونزی
    "MD": "🇲🇩",  # مولداوی
    "MC": "🇲🇨",  # موناکو
    "MN": "🇲🇳",  # مغولستان
    "ME": "🇲🇪",  # مونته‌نگرو
    "MS": "🇲🇸",  # مونتسرات
    "MA": "🇲🇦",  # مراکش
    "MZ": "🇲🇿",  # موزامبیک
    "MM": "🇲🇲",  # میانمار
    "NA": "🇳🇦",  # نامیبیا
    "NR": "🇳🇷",  # نائورو
    "NP": "🇳🇵",  # نپال
    "NI": "🇳🇮",  # نیکاراگوئه
    "NE": "🇳🇪",  # نیجر
    "NG": "🇳🇬",  # نیجریه
    "NO": "🇳🇴",  # نروژ
    "NP": "🇳🇵",  # نپال
    "NC": "🇳🇨",  # کالدونیای جدید
    "NZ": "🇳🇿",  # نیوزیلند
    "OM": "🇴🇲",  # عمان
    "PK": "🇵🇰",  # پاکستان
    "PA": "🇵🇦",  # پاناما
    "PG": "🇵🇬",  # پاپوآ گینه نو
    "PY": "🇵🇾",  # پاراگوئه
    "PE": "🇵🇪",  # پرو
    "PH": "🇵🇭",  # فیلیپین
    "PL": "🇵🇱",  # لهستان
    "PT": "🇵🇹",  # پرتغال
    "PR": "🇵🇷",  # پورتو ریکو
    "QA": "🇶🇦",  # قطر
    "RO": "🇷🇴",  # رومانی
    "RU": "🇷🇺",  # روسیه
    "RW": "🇷🇼",  # رواندا
    "KN": "🇰🇳",  # سنت کیتس و نویس
    "LC": "🇱🇨",  # سنت لوسیا
    "VC": "🇻🇨",  # سنت وینسنت و گرنادین‌ها
    "WS": "🇼🇸",  # ساموآ
    "SM": "🇸🇲",  # سن مارینو
    "ST": "🇸🇹",  # سائو تومه و پرنسیپ
    "SA": "🇸🇦",  # عربستان سعودی
    "SN": "🇸🇳",  # سنگال
    "RS": "🇷🇸",  # صربستان
    "SC": "🇸🇨",  # سیشل
    "SL": "🇸🇱",  # سیرا لئون
    "SG": "🇸🇬",  # سنگاپور
    "SK": "🇸🇰",  # اسلواکی
    "SI": "🇸🇮",  # اسلوونی
    "SB": "🇸🇧",  # جزایر سلیمان
    "SO": "🇸🇴",  # سومالی
    "ZA": "🇿🇦",  # آفریقای جنوبی
    "SS": "🇸🇸",  # سودان جنوبی
    "ES": "🇪🇸",  # اسپانیا
    "LK": "🇱🇰",  # سریلانکا
    "SD": "🇸🇩",  # سودان
    "SR": "🇸🇷",  # سورینام
    "SE": "🇸🇪",  # سوئد
    "CH": "🇨🇭",  # سوئیس
    "SY": "🇸🇾",  # سوریه
    "TJ": "🇹🇯",  # تاجیکستان
    "TH": "🇹🇭",  # تایلند
    "TG": "🇹🇬",  # توگو
    "TK": "🇹🇰",  # توکلائو
    "TL": "🇹🇱",  # تیمور شرقی
    "TM": "🇹🇲",  # ترکمنستان
    "TN": "🇹🇳",  # تونس
    "TR": "🇹🇷",  # ترکیه
    "TT": "🇹🇹",  # ترینیداد و توباگو
    "TV": "🇹🇻",  # تووالو
    "TZ": "🇹🇿",  # تانزانیا
    "UA": "🇺🇦",  # اوکراین
    "UG": "🇺🇬",  # اوگاندا
    "UY": "🇺🇾",  # اروگوئه
    "US": "🇺🇸",  # ایالات متحده
    "UZ": "🇺🇿",  # ازبکستان
    "VU": "🇻🇺",  # وانواتو
    "VE": "🇻🇪",  # ونزوئلا
    "VN": "🇻🇳",  # ویتنام
    "YE": "🇾🇪",  # یمن
    "ZM": "🇿🇲",  # زامبیا
    "ZW": "🇿🇼",  # زیمبابوه
}

                    flag = special_flags.get(country_code, flag)

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


if __name__ == '__main__':
    main()
