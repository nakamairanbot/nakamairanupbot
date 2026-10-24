import os
import json
import random
import string
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ---------------------- تنظیمات ----------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")

# لیست آیدی ادمین‌ها (با کاما جدا کن)
# مثال: 123456789,987654321,111222333
ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

FILES_DB = "files.json"

file_map = {}

def load_files():
    global file_map
    if os.path.exists(FILES_DB):
        try:
            with open(FILES_DB, "r", encoding="utf-8") as f:
                file_map = json.load(f)
        except:
            file_map = {}

def save_files():
    with open(FILES_DB, "w", encoding="utf-8") as f:
        json.dump(file_map, f, ensure_ascii=False, indent=2)

def generate_code(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---------------------- دستور /start ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    # اگر با پارامتر اومده (از لینک کانال)
    if args:
        code = args[0]
        if code in file_map:
            file_id = file_map[code]
            try:
                await update.message.reply_document(
                    document=file_id,
                    caption="✅ فایل شما آماده است"
                )
            except Exception:
                await update.message.reply_text("❌ مشکلی در ارسال فایل پیش آمد.")
        else:
            await update.message.reply_text("❌ فایل پیدا نشد یا منقضی شده.")
        return

    # پیام عادی
    if is_admin(user.id):
        await update.message.reply_text(
            "سلام ادمین 👋\n"
            "فایل رو برام بفرست تا لینک دانلود بسازم."
        )
    else:
        await update.message.reply_text(
            "سلام 👋\n"
            "برای دریافت فایل، از لینک‌های داخل کانال استفاده کنید."
        )

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

    # ساخت کد یکتا
    code = generate_code()
    while code in file_map:
        code = generate_code()

    file_map[code] = file_id
    save_files()

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
    load_files()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO,
        handle_file
    ))

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