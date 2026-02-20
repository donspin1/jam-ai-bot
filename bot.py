import os
import asyncio
import logging
from io import BytesIO
import time
from datetime import datetime, timedelta

import google.generativeai as genai
from PIL import Image
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from aiohttp import web
import aiohttp
from dotenv import load_dotenv

# ========== НАСТРОЙКА ЛОГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== ЗАГРУЗКА НАСТРОЕК ==========
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", "10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Ошибка: Не найдены TELEGRAM_TOKEN или GEMINI_API_KEY в .env файле!")

# ========== НАСТРОЙКА GEMINI ==========
genai.configure(api_key=GEMINI_API_KEY)

# Модель для ответов
model = genai.GenerativeModel('models/gemini-2.5-flash')
logger.info("✅ Модель Gemini 2.5 Flash загружена")

# ========== КОНСТАНТЫ ==========
PIN_CODE = "0215221123"
AUTH_STATE = "AUTH_STATE"
AUTHORIZED_USERS = {}

# ========== СИСТЕМА ОТСЛЕЖИВАНИЯ ЛИМИТОВ ==========
class RateLimitTracker:
    def __init__(self):
        self.rpd_limit = 1500
        self.rpm_limit = 60
        self.daily_requests = 0
        self.minute_requests = 0
        self.last_minute_reset = time.time()
        self.last_day_reset = time.time()
    
    def reset_minute_if_needed(self):
        current_time = time.time()
        if current_time - self.last_minute_reset >= 60:
            self.minute_requests = 0
            self.last_minute_reset = current_time
    
    def reset_day_if_needed(self):
        current_time = time.time()
        if current_time - self.last_day_reset >= 86400:
            self.daily_requests = 0
            self.last_day_reset = current_time
    
    def add_request(self):
        self.reset_minute_if_needed()
        self.reset_day_if_needed()
        self.daily_requests += 1
        self.minute_requests += 1
    
    def get_limits_info(self):
        self.reset_minute_if_needed()
        self.reset_day_if_needed()
        
        next_minute_reset = 60 - (time.time() - self.last_minute_reset)
        next_day_reset = 86400 - (time.time() - self.last_day_reset)
        
        minute_reset_str = str(timedelta(seconds=int(next_minute_reset)))
        day_reset_str = str(timedelta(seconds=int(next_day_reset)))
        
        daily_bar = self._create_progress_bar(self.daily_requests, self.rpd_limit)
        minute_bar = self._create_progress_bar(self.minute_requests, self.rpm_limit)
        
        return (
            f"\n\n📊 **ДНЕВНОЙ ЛИМИТ GEMINI**\n"
            f" {daily_bar}\n"
            f" {self.daily_requests}/{self.rpd_limit} запросов\n"
        )
    
    def _create_progress_bar(self, current, total, length=15):
        filled = int((current / total) * length) if total > 0 else 0
        filled = min(filled, length)
        bar = '█' * filled + '░' * (length - filled)
        percentage = (current / total) * 100 if total > 0 else 0
        return f"`{bar}` {percentage:.1f}%"

limit_tracker = RateLimitTracker()

# ========== HTTP-СЕРВЕР ==========
async def handle_health(request):
    return web.Response(text="JAM AI Bot is alive! 🤖")

async def start_http_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ HTTP сервер запущен на порту {PORT}")

async def ping_self(context: ContextTypes.DEFAULT_TYPE):
    if not RENDER_URL:
        return
    
    url = f"{RENDER_URL.rstrip('/')}/health"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                logger.info(f"🔄 Самопинг {url} -> {resp.status}")
    except Exception as e:
        logger.error(f"❌ Ошибка пинга: {e}")

# ========== АВТОРИЗАЦИЯ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    # Если пользователь уже авторизован
    if user_id in AUTHORIZED_USERS and AUTHORIZED_USERS[user_id]:
        limits_info = limit_tracker.get_limits_info()
        await update.message.reply_text(
            "👋 Добро пожаловать в **JAM AI**!\n\n"
            "Я готов к работе. Отправь мне текст или фото с вопросом." +
            limits_info,
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    # Если не авторизован - запрашиваем PIN-код
    await update.message.reply_text(
        "🔐 **JAM AI**\n\n"
        "PIN-код введи, а то мало ли левый чувак какой-то)\n"
        "_(Не ссы, PIN-код удалю как отправишь сразу же!)_",
        parse_mode="Markdown"
    )
    return AUTH_STATE

async def check_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка введенного PIN-кода"""
    user_id = update.effective_user.id
    user_input = update.message.text.strip()
    
    if user_input == PIN_CODE:
        # Правильный PIN
        AUTHORIZED_USERS[user_id] = True
        
        # Удаляем сообщение с PIN-кодом
        await update.message.delete()
        
        limits_info = limit_tracker.get_limits_info()
        await update.message.reply_text(
            "✅ **Ну свои получается! 😎**\n\n"
            "Используй 👉 **JAM AI**!\n\n"
            "Вот что умеет ботяра:\n"
            "📝 Отвечать на текстовые запросы\n"
            "🖼️ Анализировать фото\n"
            "📊 /limits - показать лимиты" +
            limits_info,
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    else:
        # Неправильный PIN - удаляем сообщение и просим снова
        await update.message.delete()
        
        await update.message.reply_text(
            "❌ **Неверный PIN-код!**\n\n"
            "Попробуйте еще раз:",
            parse_mode="Markdown"
        )
        return AUTH_STATE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена ввода PIN-кода"""
    await update.message.reply_text(
        "🚫 Доступ отменен. Отправьте /start для начала работы."
    )
    return ConversationHandler.END

def is_authorized(user_id):
    return user_id in AUTHORIZED_USERS and AUTHORIZED_USERS[user_id]

# ========== ОБРАБОТКА ТЕКСТА ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text
    
    if not is_authorized(user_id):
        # Если не авторизован
        await update.message.reply_text(
            "🔐 **Требуется авторизация!**\n"
            "Отправьте /start для ввода PIN-кода.",
            parse_mode="Markdown"
        )
        return
    
    # Обычный текстовый запрос
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        response = model.generate_content(user_message)
        limit_tracker.add_request()
        limits_info = limit_tracker.get_limits_info()
        await update.message.reply_text(
            response.text + limits_info,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка Gemini: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# ========== ОБРАБОТКА ФОТО ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text(
            "🔐 **Требуется авторизация!**\n"
            "Отправьте /start для ввода PIN-кода.",
            parse_mode="Markdown"
        )
        return
    
    photo_file = await update.message.photo[-1].get_file()
    caption = update.message.caption or "Опиши, что изображено на этой картинке"
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    try:
        image_bytes = BytesIO()
        await photo_file.download_to_memory(image_bytes)
        image_bytes.seek(0)
        
        img = Image.open(image_bytes)
        response = model.generate_content([caption, img])
        
        limit_tracker.add_request()
        limits_info = limit_tracker.get_limits_info()
        await update.message.reply_text(
            response.text + limits_info,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка обработки фото: {e}")
        await update.message.reply_text("❌ Ошибка при обработке изображения.")

# ========== КОМАНДА ДЛЯ ПРОВЕРКИ ЛИМИТОВ ==========
async def limits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_authorized(user_id):
        await update.message.reply_text(
            "🔐 **Требуется авторизация!**\n"
            "Отправьте /start для ввода PIN-кода.",
            parse_mode="Markdown"
        )
        return
    
    limits_info = limit_tracker.get_limits_info()
    await update.message.reply_text(
        "📊 **ТЕКУЩИЕ ЛИМИТЫ GEMINI**" + limits_info,
        parse_mode="Markdown"
    )

# ========== ЗАПУСК ==========
async def main():
    await start_http_server()
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Создаем ConversationHandler для PIN-кода
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AUTH_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_pin)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", lambda u,c: u.message.reply_text(
        "🤖 **JAM AI - Помощь**\n\n"
        "/start - Начать работу\n"
        "/help - Показать это сообщение\n"
        "/limits - Показать текущие лимиты\n"
        "/cancel - Отменить ввод PIN-кода\n\n"
        "**Как использовать:**\n"
        "📝 Текст: просто отправь сообщение\n"
        "🖼️ Анализ фото: отправь фото с вопросом",
        parse_mode="Markdown")))
    application.add_handler(CommandHandler("limits", limits_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    if RENDER_URL:
    if application.job_queue:
        application.job_queue.run_repeating(ping_self, interval=600, first=10)
        logger.info("✅ Самопинг активирован")
    else:
        logger.warning("⚠️ JobQueue не доступен, самопинг отключён. Убедись, что установлен python-telegram-bot[job-queue]")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())