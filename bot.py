import os
import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError
from upstash_redis import Redis

# ---------------------- تنظیمات ----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

# کانال‌هایی که کاربر باید عضو باشه (یوزرنیم با @)
REQUIRED_CHANNELS = [
    # مثال:
     "@nakama_iran",
     "@nakamairan_chat",
]

redis = Redis(
    url=os.getenv("UPSTASH_REDIS_REST_URL"),
    token=os.getenv("UPSTASH_REDIS_REST_TOKEN")
)

def generate_code(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def check_membership(bot, user_id: int) -> bool:
    """چک می‌کنه کاربر عضو همه کانال‌های اجباری هست یا نه"""
    if not REQUIRED_CHANNELS:
        return True  # اگر کانالی تعریف نشده باشه، آزاد باشه

    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except TelegramError:
            return False
    return True

def get_join_keyboard():
    """دکمه‌های عضویت در کانال‌ها"""
    buttons = []
    for channel in REQUIRED_CHANNELS:
        username = channel.lstrip("@")
        buttons.append([InlineKeyboardButton(
            text=f"عضویت در {channel}",
            url=f"https://t.me/{username}"
        )])
    
    buttons.append([InlineKeyboardButton(
        text="✅ عضو شدم، بررسی کن",
        callback_data="check_join"
    )])
    return InlineKeyboardMarkup(buttons)

# ---------------------- دستور /start ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    # اگر با پارامتر اومده (لینک فایل)
    if args:
        code = args[0]
        file_id = redis.get(code)

        if not file_id:
            await update.message.reply_text("❌ فایل پیدا نشد یا منقضی شده.")
            return

        # چک عضویت
        is_member = await check_membership(context.bot, user.id)
        if not is_member:
            await update.message.reply_text(
                "⚠️ برای دریافت فایل باید در کانال‌های زیر عضو شوید:",
                reply_markup=get_join_keyboard()
            )
            # کد فایل رو موقتاً ذخیره می‌کنیم تا بعد از عضویت بفرسته
            context.user_data["pending_code"] = code
            return

        # ارسال فایل
        try:
            await update.message.reply_document(
                document=file_id,
                caption="✅ فایل شما آماده است"
            )
        except Exception:
            await update.message.reply_text("❌ مشکلی در ارسال فایل پیش آمد.")
        return

    # پیام عادی
    if is_admin(user.id):
        await update.message.reply_text(
            "سلام ادمین 👋\n\n"
            "• فایل بفرست تا لینک بسازم\n"
            "• /list → لیست فایل‌ها"
        )
    else:
        await update.message.reply_text(
            "سلام 👋\n"
            "برای دریافت فایل، از لینک‌های داخل کانال استفاده کنید."
        )

# ---------------------- بررسی عضویت (دکمه) ----------------------
async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    is_member = await check_membership(context.bot, user_id)

    if not is_member:
        await query.edit_message_text(
            "هنوز در همه کانال‌ها عضو نشدی. لطفاً عضو شو و دوباره دکمه رو بزن.",
            reply_markup=get_join_keyboard()
        )
        return

    # اگر کد در انتظار داشت
    code = context.user_data.get("pending_code")
    if code:
        file_id = redis.get(code)
        if file_id:
            try:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=file_id,
                    caption="✅ فایل شما آماده است"
                )
                await query.edit_message_text("✅ عضویت تأیید شد. فایل براتون ارسال شد.")
            except Exception:
                await query.edit_message_text("❌ مشکلی در ارسال فایل پیش آمد.")
        else:
            await query.edit_message_text("❌ فایل پیدا نشد.")
        context.user_data.pop("pending_code", None)
    else:
        await query.edit_message_text("✅ عضویت شما تأیید شد.")

# ---------------------- لیست فایل‌ها (فقط ادمین) ----------------------
async def list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_admin(user.id):
        await update.message.reply_text("شما دسترسی ندارید.")
        return

    keys = redis.keys("*")
    if not keys:
        await update.message.reply_text("هنوز هیچ فایلی ذخیره نشده.")
        return

    bot_username = (await context.bot.get_me()).username
    text = f"📋 لیست فایل‌ها ({len(keys)} مورد):\n\n"

    for i, code in enumerate(keys, 1):
        link = f"https://t.me/{bot_username}?start={code}"
        text += f"{i}. `{code}`\n{link}\n\n"

        # جلوگیری از پیام خیلی طولانی
        if i % 15 == 0:
            await update.message.reply_text(text, parse_mode="Markdown")
            text = ""

    if text:
        await update.message.reply_text(text, parse_mode="Markdown")

# ---------------------- دریافت فایل از ادمین ----------------------
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_admin(user.id):
        await update.message.reply_text("شما اجازه آپلود ندارید.")
        return

    file_id = None
    file_name = "فایل"

    if update.message.document:
        file_id = update.message.document.file_id
        file_name = update.message.document.file_name or "document"
    elif update.message.video:
        file_id = update.message.video.file_id
        file_name = "ویدیو"
    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_name = "آهنگ"
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_name = "عکس"
    else:
        await update.message.reply_text("این نوع فایل پشتیبانی نمی‌شود.")
        return

    code = generate_code()
    while redis.get(code):
        code = generate_code()

    redis.set(code, file_id)

    bot_username = (await context.bot.get_me()).username
    deep_link = f"https://t.me/{bot_username}?start={code}"

    await update.message.reply_text(
        f"✅ فایل ذخیره شد!\n\n"
        f"📁 نام: {file_name}\n"
        f"🔗 لینک آماده:\n`{deep_link}`\n\n"
        f"این لینک رو توی کانال بذار.",
        parse_mode="Markdown"
    )

# ---------------------- اجرای ربات ----------------------
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_files))
    application.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO,
        handle_file
    ))
    application.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))

    PORT = int(os.environ.get("PORT", 8443))
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

    if WEBHOOK_URL:
        print("در حال اجرا با Webhook...")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        print("در حال اجرا با Polling...")
        application.run_polling()

if __name__ == "__main__":
    main()
