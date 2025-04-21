import os
import logging
import random
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

# --- وضعیت سیستم ---
LOCATIONS_ENABLED = True  # وضعیت فعال/غیرفعال بودن لوکیشن‌ها
import threading

# --- CONFIGURATION ---
ADMIN_ID = int(os.getenv("ADMIN_ID", "7240662021"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "8093306771:AAHIt63O2nHmEfFCx1u3w4kegqxuyRY2Xv4")

# Conversation states
ENTER_ACTIVATION, ENTER_NEW_CODE, ENTER_NEW_IPV4, ENTER_COUNTRY_NAME, ENTER_COUNTRY_FLAG, CHOOSE_CODE_TYPE, ENTER_TOKEN_COUNT = range(7)

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
    buttons = [
        [InlineKeyboardButton(f"🆔 آیدی: {user_id} 📋", callback_data=f'copy_{user_id}')],
        [InlineKeyboardButton(f"📅 تاریخ عضویت: {membership_date}", callback_data='noop')],
        [InlineKeyboardButton(f"📨 تعداد آدرس‌ها: {ips_received}", callback_data='noop')],
        [InlineKeyboardButton(f"🔑 {get_subscription_status(user_id)}", callback_data='noop')],
        [InlineKeyboardButton("⬅️ بازگشت", callback_data='back')]
    ]
    send_reply(update, "👤 حساب کاربری شما:", reply_markup=InlineKeyboardMarkup(buttons))



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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ بازگشت", callback_data='back')]
    ])

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Updated main menu with subscription status display and activation button."""
    subscription_status = get_subscription_status(user_id)
    buttons = [
        [
            InlineKeyboardButton(f"🔐 {subscription_status}", callback_data='noop')
        ]
    ]

    if not db.is_user_active(user_id) and not db.is_user_subscribed(user_id):
        buttons.append([InlineKeyboardButton("🔑 فعال‌سازی اشتراک", callback_data='activate')])

    buttons.extend([
        [
            InlineKeyboardButton("🌐 تولید IPv6", callback_data='generate_ipv6'),
            InlineKeyboardButton("📋 لیست iPv4", callback_data='get_ipv4')
        ],
        [
            InlineKeyboardButton("👤 حساب کاربری", callback_data='user_account')
        ],
        [
            InlineKeyboardButton("❓ پشتیبانی", callback_data='support')
        ]
    ])
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton("🛠️ پنل ادمین", callback_data='admin_panel')])
    return InlineKeyboardMarkup(buttons)

def cb_subscription_status(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    status = get_subscription_status(user_id)
    send_reply(update, status, reply_markup=main_menu_keyboard(user_id))

def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    welcome_text = "👋 سلام! به ربات خوش آمدید.\nبرای پشتیبانی از دکمه زیر می‌توانید استفاده کنید یا از دستور /help برای راهنمایی."
    send_reply(update, welcome_text, reply_markup=main_menu_keyboard(user_id))

def support_command(update: Update, context: CallbackContext) -> None: #New Support Command
    user_id = update.effective_user.id
    support_text = "برای پشتیبانی مستقیم با من در تماس باشید:"
    buttons = [
        [InlineKeyboardButton("پیام مستقیم به من 📩", url="https://t.me/Minimalcraft")]
    ]
    send_reply(update, support_text, reply_markup=InlineKeyboardMarkup(buttons))


def require_subscription(func):
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
        if not db.is_user_active(user_id):
            send_reply(update, "❌ اشتراک فعال ندارید. لطفاً ابتدا فعال‌سازی کنید.", reply_markup=main_menu_keyboard(user_id))
            return ConversationHandler.END
        return func(update, context, *args, **kwargs)
    return wrapper

def generate_ipv6(option: int) -> list:
    blocks = lambda n: ":".join(f"{random.randint(0, 65535):04x}" for _ in range(n))
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
        send_reply(update, "✅ شما قبلاً فعال‌سازی شده‌اید.", reply_markup=main_menu_keyboard(user_id))
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
            send_reply(update, f"✅ فعال‌سازی موفق! اشتراک توکنی شما با {code_data['tokens']} توکن فعال شد.", reply_markup=main_menu_keyboard(user_id))
        else:
            send_reply(update, "✅ فعال‌سازی موفق! اشتراک دائمی شما فعال شد.", reply_markup=main_menu_keyboard(user_id))
    else:
        send_reply(update, "❌ کد فعال‌سازی نامعتبر است.", reply_markup=main_menu_keyboard(user_id))
    return ConversationHandler.END

def cb_generate(update: Update, context: CallbackContext) -> None:
    user_id = update.callback_query.from_user.id
    if not db.is_user_active(user_id):
        send_reply(update, "❌ اشتراک فعال ندارید. لطفاً ابتدا فعال‌سازی کنید.", reply_markup=main_menu_keyboard(user_id))
        return
    buttons = [
        [InlineKeyboardButton("گزینه 1", callback_data='gen_1'), InlineKeyboardButton("گزینه 2", callback_data='gen_2')],
        [InlineKeyboardButton("گزینه 3", callback_data='gen_3'), InlineKeyboardButton("گزینه 4", callback_data='gen_4')],
        [InlineKeyboardButton("گزینه 5", callback_data='gen_5')],
        [InlineKeyboardButton("↩️ بازگشت", callback_data='back')]
    ]
    send_reply(update, "لطفاً یک گزینه برای تولید IPv6 انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))

@require_subscription
def cb_generate_option(update: Update, context: CallbackContext) -> None:
    option = int(update.callback_query.data.split('_')[1])
    ipv6_list = generate_ipv6(option)
    formatted_ipv6 = "\n".join(f"`{address}`" for address in ipv6_list)
    send_reply(update, f"✨ آدرس IPv6 شما:\n{formatted_ipv6}", parse_mode=ParseMode.MARKDOWN)

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
            # فقط کشورهایی که حداقل یک آی‌پی دارند را نمایش بده
            if len(ips) > 0:
                countries_with_ips = True
                row.append(InlineKeyboardButton(f"{flag} {country} ({len(ips)})", callback_data=f"country_{country_code}"))
                count += 1
                if count % 3 == 0:  # هر سه آیتم یک ردیف جدید
                    buttons.append(row)
                    row = []

        # اضافه کردن آیتم‌های باقی‌مانده
        if row:
            buttons.append(row)

        # اضافه کردن دکمه بازگشت
        buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='back')])

        if not countries_with_ips:
            send_reply(update, "ℹ️ هیچ کشوری با آدرس IP وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ بازگشت", callback_data='back')]]))
        else:
            send_reply(update, "🌍 انتخاب کشور:", reply_markup=InlineKeyboardMarkup(buttons))

def cb_country_ips(update: Update, context: CallbackContext) -> None:
    country_code = update.callback_query.data.split('_')[1]
    ips = db.get_ips_by_country(country_code)

    # نمایش اطلاعات کشور از پایگاه داده
    country_data = db.get_ipv4_countries().get(country_code)
    country_name = country_data[0] if country_data else country_code
    flag = country_data[1] if country_data else "🏳️"

    if ips:
        text = f"📡 آدرس‌های {flag} {country_name}:\n" + "\n".join(f"• `{ip}`" for ip in ips)
        # افزودن دکمه بازگشت
        buttons = [[InlineKeyboardButton("↩️ بازگشت به لیست کشورها", callback_data='get_ipv4')]]
        send_reply(update, text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))
    else:
        # اگر آدرسی یافت نشد، به منوی اصلی برگرد
        update.callback_query.answer("هیچ آدرسی برای این کشور یافت نشد.")
        cb_get_ipv4(update, context)


def cb_admin_panel(update: Update, context: CallbackContext) -> None:
    buttons = [
        [InlineKeyboardButton("➕ اضافه کردن IPv4", callback_data='admin_add_ipv4'), InlineKeyboardButton("➕ اضافه کردن کد فعالسازی", callback_data='admin_add_code')],
        [InlineKeyboardButton("🔍 پردازش و افزودن IP", callback_data='admin_process_ip')],
        [InlineKeyboardButton("❌ حذف IPv4", callback_data='admin_remove_ipv4'), InlineKeyboardButton("🌐 مدیریت لوکیشن‌ها", callback_data='admin_manage_locations')],
        [InlineKeyboardButton("📊 آمار", callback_data='admin_stats'), InlineKeyboardButton("👥 مدیریت کاربران", callback_data='admin_manage_users')],
        [InlineKeyboardButton("↩️ بازگشت", callback_data='back'), InlineKeyboardButton("🔒 خاموش کردن ربات", callback_data='admin_shutdown'), InlineKeyboardButton("🟢 روشن کردن ربات", callback_data='admin_startup')],
    ]
    send_reply(update, "🛠️ پنل ادمین:", reply_markup=InlineKeyboardMarkup(buttons))

def cb_admin_add_code(update: Update, context: CallbackContext) -> int:
    buttons = [
        [InlineKeyboardButton("دائمی", callback_data='code_type_unlimited')],
        [InlineKeyboardButton("توکنی", callback_data='code_type_token')]
    ]
    send_reply(update, "🔑 نوع کد فعال‌سازی را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(buttons))
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
            send_reply(update, "❌ تعداد توکن باید بیشتر از صفر باشد. لطفاً دوباره وارد کنید:")
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
    context.user_data['ipv4_data']['country_name'] = update.message.text.strip()
    send_reply(update, "🏳️ لطفاً ایموجی پرچم کشور را وارد کنید:")
    return ENTER_COUNTRY_FLAG

def enter_country_flag(update: Update, context: CallbackContext) -> int:
    context.user_data['ipv4_data']['flag'] = update.message.text.strip()
    send_reply(update, "🌐 لطفاً آدرس آی‌پی IPv4 جدید را وارد کنید:")
    return ENTER_NEW_IPV4

def enter_new_ipv4(update: Update, context: CallbackContext) -> int:
    ipv4_data = context.user_data['ipv4_data']
    ipv4_data['ipv4'] = update.message.text.strip()
    db.add_ipv4_address(ipv4_data['country_name'], ipv4_data['flag'], ipv4_data['ipv4'])
    send_reply(update, "✅ آدرس IPv4 جدید افزوده شد.")
    return ConversationHandler.END

def cb_admin_stats(update: Update, context: CallbackContext) -> None:
    stats = db.get_stats()
    text = "📊 *آمار بات:*\n" + "\n".join(f"• {k}: {v}" for k, v in stats.items())
    send_reply(update, text, parse_mode=ParseMode.MARKDOWN)

def cb_back(update: Update, context: CallbackContext) -> None:
    start(update, context)

def error_handler(update: object, context: CallbackContext) -> None:
    logger.error("❗Unhandled exception: %s", context.error)
    if isinstance(update, Update) and update.effective_user:
        context.bot.send_message(
            chat_id=update.effective_user.id,
            text="⚠️ متأسفم، خطایی رخ داد. لطفاً دوباره امتحان کنید."
        )

def cb_admin_manage_users(update: Update, context: CallbackContext) -> None:
    """Show user management panel."""
    buttons = [
        [InlineKeyboardButton("➕ افزودن توکن به کاربر", callback_data='admin_grant_tokens')],
        [InlineKeyboardButton("🚫 غیرفعال کردن کاربر", callback_data='admin_disable_user')],
        [InlineKeyboardButton("✅ فعال کردن کاربر", callback_data='admin_enable_user')],
        [InlineKeyboardButton("↩️ بازگشت به پنل ادمین", callback_data='admin_panel')],
    ]
    send_reply(update, "👥 مدیریت کاربران:", reply_markup=InlineKeyboardMarkup(buttons))

def cb_admin_grant_tokens(update: Update, context: CallbackContext) -> int:
    """Initialize process to add tokens to a user."""
    send_reply(update, "لطفاً آیدی عددی کاربر و تعداد توکن را وارد کنید (مثال: 1234567 50).")
    return ENTER_NEW_CODE

def enter_grant_tokens(update: Update, context: CallbackContext) -> int:
    try:
        user_id, tokens = map(int, update.message.text.strip().split())
        db.grant_tokens(user_id, tokens)
        send_reply(update, f"✅ {tokens} توکن به کاربر با آیدی {user_id} افزوده شد.")
    except (ValueError, TypeError):
        send_reply(update, "❌ لطفاً یک آیدی عددی معتبر و تعداد توکن صحیح وارد کنید.")
    return ConversationHandler.END

def cb_admin_process_ip(update: Update, context: CallbackContext) -> int:
    send_reply(update, "لطفاً یک آدرس IPv4 و کشور مربوطه را وارد کنید (مثال: [PING OK] 39.62.163.207 -> 🇵🇰 Pakistan).")
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
            db.add_ipv4_address(country_name.strip(), flag.strip(), ip_address.strip())
            send_reply(update, "✅ آدرس IPv4 پردازش شد و افزوده گردید.")
        else:
            send_reply(update, "❌ فرمت وارد شده نادرست است. لطفاً مجدد تلاش کنید.")
    except Exception as e:
        send_reply(update, f"❌ مشکلی در پردازش وجود دارد: {e}")
    return ConversationHandler.END

def main() -> None:
    # ادغام کلیدهای تکراری کشورها
    # ایجاد دیکشنری موقت برای ذخیره کلیدهای نرمال‌شده
    normalized_keys = {}
    for country_code in list(db.ipv4_data.keys()):
        normalized_key = country_code.lower()
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
        else:
            normalized_keys[normalized_key] = country_code

    # ذخیره تغییرات
    db.save_database()

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('help', support_command)) # Changed help command handler
    dp.add_handler(CallbackQueryHandler(support_command, pattern='^support$')) #Added support callback handler

    # کانورسیشن هندلرها
    activate_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_activate, pattern='^activate$')],
        states={ENTER_ACTIVATION: [MessageHandler(Filters.text & ~Filters.command, enter_activation)]},
        fallbacks=[CallbackQueryHandler(cb_back, pattern='^back$')],
    )

    addcode_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_add_code, pattern='^admin_add_code$')],
        states={
            CHOOSE_CODE_TYPE: [CallbackQueryHandler(cb_code_type_selected, pattern='^code_type_')],
            ENTER_TOKEN_COUNT: [MessageHandler(Filters.text & ~Filters.command, enter_token_count)],
            ENTER_NEW_CODE: [MessageHandler(Filters.text & ~Filters.command, enter_new_code)]
        },
        fallbacks=[CallbackQueryHandler(cb_back, pattern='^back$')],
    )

    addipv4_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_add_ipv4, pattern='^admin_add_ipv4$')],
        states={
            ENTER_COUNTRY_NAME: [MessageHandler(Filters.text & ~Filters.command, enter_country_name)],
            ENTER_COUNTRY_FLAG: [MessageHandler(Filters.text & ~Filters.command, enter_country_flag)],
            ENTER_NEW_IPV4: [MessageHandler(Filters.text & ~Filters.command, enter_new_ipv4)],
        },
        fallbacks=[CallbackQueryHandler(cb_back, pattern='^back$')],
    )

    # Add grant tokens conversation handler
    grant_tokens_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_grant_tokens, pattern='^admin_grant_tokens$')],
        states={
            ENTER_NEW_CODE: [MessageHandler(Filters.text & ~Filters.command, enter_grant_tokens)]
        },
        fallbacks=[CallbackQueryHandler(cb_back, pattern='^back$')],
    )

    # Add process IP conversation handler
    process_ip_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_process_ip, pattern='^admin_process_ip$')],
        states={
            ENTER_NEW_IPV4: [MessageHandler(Filters.text & ~Filters.command, process_ipv4_entry)]
        },
        fallbacks=[CallbackQueryHandler(cb_back, pattern='^back$')],
    )

    # کانورسیشن هندلر برای غیرفعال کردن کاربر
    disable_user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_disable_user, pattern='^admin_disable_user$')],
        states={
            ENTER_NEW_CODE: [MessageHandler(Filters.text & ~Filters.command, disable_user)]
        },
        fallbacks=[CallbackQueryHandler(cb_back, pattern='^back$')],
    )

    # کانورسیشن هندلر برای فعال کردن کاربر
    enable_user_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_admin_enable_user, pattern='^admin_enable_user$')],
        states={
            ENTER_NEW_CODE: [MessageHandler(Filters.text & ~Filters.command, enable_user)]
        },
        fallbacks=[CallbackQueryHandler(cb_back, pattern='^back$')],
    )

    # ثبت همه کانورسیشن هندلرها
    dp.add_handler(activate_conv)
    dp.add_handler(addcode_conv)
    dp.add_handler(addipv4_conv)
    dp.add_handler(grant_tokens_conv)
    dp.add_handler(process_ip_conv)
    dp.add_handler(disable_user_conv)
    dp.add_handler(enable_user_conv)

    # سایر هندلرها
    dp.add_handler(CallbackQueryHandler(cb_admin_panel, pattern='^admin_panel$'))
    dp.add_handler(CallbackQueryHandler(cb_generate, pattern='^generate_ipv6$'))
    dp.add_handler(CallbackQueryHandler(cb_generate_option, pattern='^gen_'))
    dp.add_handler(CallbackQueryHandler(cb_get_ipv4, pattern='^get_ipv4$'))
    dp.add_handler(CallbackQueryHandler(cb_country_ips, pattern='^country_'))
    dp.add_handler(CallbackQueryHandler(cb_admin_stats, pattern='^admin_stats$'))
    dp.add_handler(CallbackQueryHandler(cb_back, pattern='^back$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_shutdown, pattern='^admin_shutdown$'))
    dp.add_handler(CallbackQueryHandler(lambda u, c: None, pattern='^noop$'))
    dp.add_handler(CallbackQueryHandler(cb_user_account, pattern='^user_account$'))
    dp.add_handler(CallbackQueryHandler(cb_subscription_status, pattern='^subscription_status$'))
    dp.add_handler(CallbackQueryHandler(cb_admin_startup, pattern='^admin_startup$'))

    # هندلرهای مدیریت کاربران
    dp.add_handler(CallbackQueryHandler(cb_admin_manage_users, pattern='^admin_manage_users$'))

    # هندلرهای مدیریت لوکیشن‌ها
    dp.add_handler(CallbackQueryHandler(cb_admin_manage_locations, pattern='^admin_manage_locations$'))
    dp.add_handler(CallbackQueryHandler(cb_disable_locations, pattern='^disable_locations$'))
    dp.add_handler(CallbackQueryHandler(cb_enable_locations, pattern='^enable_locations$'))

    # هندلرهای حذف آدرس IP
    dp.add_handler(CallbackQueryHandler(cb_admin_remove_ipv4, pattern='^admin_remove_ipv4$'))
    dp.add_handler(CallbackQueryHandler(cb_remove_country_ips, pattern='^remove_country_'))
    dp.add_handler(CallbackQueryHandler(cb_remove_ip, pattern='^remove_ip_'))

    # هندلر خطاها
    dp.add_error_handler(error_handler)

    logger.info("Bot start✅✅✅")
    updater.start_polling()
    updater.idle()

def cb_admin_shutdown(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        send_reply(update, "🤖 ربات در حال بروزرسانی و بهینه شدن میباشد بعدا تلاش کنید.")
        # Shutdown code here, temporarily disable message processing
        def shutdown():
            # context.bot.updater.stop()  Removed this line
            logger.info("Bot has been shutdown by admin.")

        if update.message:
            update.message.reply_text("ربات خاموش شد. برای راه‌اندازی مجدد دوباره /start بزنید.")
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
            buttons.append([InlineKeyboardButton(f"{flag} {country} ({len(ips)})", callback_data=f"remove_country_{country_code}")])

    if not has_countries_with_ips:
        send_reply(update, "❌ هیچ کشوری با آدرس IP وجود ندارد.")
        return ConversationHandler.END
        
    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='admin_panel')])
    send_reply(update, "🌍 انتخاب کشور برای حذف آدرس:", reply_markup=InlineKeyboardMarkup(buttons))
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
        buttons.append([InlineKeyboardButton(f"❌ {ip}", callback_data=f"remove_ip_{ip}")])

    buttons.append([InlineKeyboardButton("↩️ بازگشت", callback_data='admin_remove_ipv4')])
    send_reply(update, "📡 انتخاب آدرس برای حذف:", reply_markup=InlineKeyboardMarkup(buttons))
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
    buttons = [[InlineKeyboardButton("↩️ بازگشت به پنل ادمین", callback_data='admin_panel')]]
    update.callback_query.message.reply_text("عملیات حذف به پایان رسید.", reply_markup=InlineKeyboardMarkup(buttons))

    return ConversationHandler.END

def cb_admin_manage_locations(update: Update, context: CallbackContext) -> None:
    """مدیریت لوکیشن‌ها."""
    buttons = [
        [InlineKeyboardButton("🔍 مشاهده همه لوکیشن‌ها", callback_data='view_all_locations')],
        [InlineKeyboardButton("❌ غیرفعال کردن لوکیشن‌ها", callback_data='disable_locations')],
        [InlineKeyboardButton("✅ فعال کردن لوکیشن‌ها", callback_data='enable_locations')],
        [InlineKeyboardButton("↩️ بازگشت به پنل ادمین", callback_data='admin_panel')],
    ]
    send_reply(update, "🌐 مدیریت لوکیشن‌ها:", reply_markup=InlineKeyboardMarkup(buttons))

def cb_disable_locations(update: Update, context: CallbackContext) -> None:
    """غیرفعال کردن لوکیشن‌ها."""
    # این قسمت می‌تواند به‌روز شود تا واقعاً لوکیشن‌ها را غیرفعال کند
    # در این مثال فقط یک پیام نمایش می‌دهیم
    send_reply(update, "✅ لوکیشن‌ها با موفقیت غیرفعال شدند.")

    # بازگشت به منوی مدیریت لوکیشن‌ها
    buttons = [[InlineKeyboardButton("↩️ بازگشت", callback_data='admin_manage_locations')]]
    update.callback_query.message.reply_text("چه کاری انجام دهیم؟", reply_markup=InlineKeyboardMarkup(buttons))

def cb_enable_locations(update: Update, context: CallbackContext) -> None:
    """فعال کردن لوکیشن‌ها."""
    # این قسمت می‌تواند به‌روز شود تا واقعاً لوکیشن‌ها را فعال کند
    # در این مثال فقط یک پیام نمایش می‌دهیم
    send_reply(update, "✅ لوکیشن‌ها با موفقیت فعال شدند.")

    # بازگشت به منوی مدیریت لوکیشن‌ها
    buttons = [[InlineKeyboardButton("↩️ بازگشت", callback_data='admin_manage_locations')]]
    update.callback_query.message.reply_text("چه کاری انجام دهیم؟", reply_markup=InlineKeyboardMarkup(buttons))

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


if __name__ == '__main__':
    main()
