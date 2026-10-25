import os
import random
import string
import asyncio
from aiohttp import web
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

REQUIRED_CHANNELS = [
    # اینجا کانال‌ها و گروه‌ها رو بنویس
    # "@nakama_iran",
    # "@nakamairan_chat",
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
    if not REQUIRED_CHANNELS:
        return True
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ["left", "kicked"]:
                return False
        except TelegramError:
            return False
    return True

def get_join_keyboard():
    buttons = []
    for channel in REQUIRED_CHANNELS:
        username = str(channel).lstrip("@")
        buttons.append([InlineKeyboardButton(
            text=f"عضویت در {channel}",
            url=f"https://t.me/{username}"
        )])
    buttons.append([InlineKeyboardButton(
        text="✅ عضو شدم، بررسی کن",
        callback_data="check_join"
    )])
    return InlineKeyboardMarkup(buttons)

async def delete_message_after(bot, chat_id: int, message_id: int, delay: int = 180):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

# ---------------------- دستور /start ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    if args:
        code = args[0]
        data = redis.get(code)

        if not data:
            await update.message.reply_text("❌ فایل پیدا نشد یا منقضی شده.")
            return

        file_id = data.split("|||")[0]

        is_member = await check_membership(context.bot, user.id)
        if not is_member:
            await update.message.reply_text(
                "⚠️ برای دریافت فایل باید در کانال‌های زیر عضو شوید:",
                reply_markup=get_join_keyboard()
            )
            context.user_data["pending_code"] = code
            return

        try:
            sent = await update.message.reply_document(
                document=file_id,
                caption="✅ فایل شما آماده است"
            )
            asyncio.create_task(
                delete_message_after(context.bot, update.effective_chat.id, sent.message_id, 180)
            )
        except Exception:
            await update.message.reply_text("❌ مشکلی در ارسال فایل پیش آمد.")
        return

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

# ---------------------- بررسی عضویت ----------------------
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

    code = context.user_data.get("pending_code")
    if code:
        data = redis.get(code)
        if data:
            file_id = data.split("|||")[0]
            try:
                sent = await context.bot.send_document(
                    chat_id=user_id,
                    document=file_id,
                    caption="✅ فایل شما آماده است"
                )
                asyncio.create_task(
                    delete_message_after(context.bot, user_id, sent.message_id, 180)
                )
                await query.edit_message_text("✅ عضویت تأیید شد. فایل براتون ارسال شد.")
            except Exception:
                await query.edit_message_text("❌ مشکلی در ارسال فایل پیش آمد.")
        else:
            await query.edit_message_text("❌ فایل پیدا نشد.")
        context.user_data.pop("pending_code", None)
    else:
        await query.edit_message_text("✅ عضویت شما تأیید شد.")

# ---------------------- لیست فایل‌ها ----------------------
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
        data = redis.get(code)
        if data and "|||" in data:
            file_name = data.split("|||")[1]
        else:
            file_name = "بدون نام"

        link = f"https://t.me/{bot_username}?start={code}"
        text += f"{i}. {file_name}\n{link}\n\n"

        if i % 12 == 0:
            await update.message.reply_text(text)
            text = ""

    if text:
        await update.message.reply_text(text)

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

    # ذخیره همزمان file_id و اسم فایل
    redis.set(code, f"{file_id}|||{file_name}")

    bot_username = (await context.bot.get_me()).username
    deep_link = f"https://t.me/{bot_username}?start={code}"

    await update.message.reply_text(
        f"✅ فایل ذخیره شد!\n\n"
        f"📁 نام: {file_name}\n"
        f"🔗 لینک آماده:\n{deep_link}\n\n"
        f"این لینک رو توی کانال بذار."
    )

# ---------------------- اجرا + Health Check ----------------------
async def health(request):
    return web.Response(text="Bot is alive")

async def telegram_webhook(request):
    application = request.app["application"]
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return web.Response(text="OK")

async def main():
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

    app = web.Application()
    app["application"] = application
    app.router.add_get("/", health)
    app.router.add_post(f"/{BOT_TOKEN}", telegram_webhook)

    await application.initialize()
    await application.bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")

    print("ربات با Health Check آماده است...")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
