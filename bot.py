import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler
)
from database import Database
from jobs import JobsFetcher

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

CHOOSE_CATEGORY, CHOOSE_SALARY, CHOOSE_FORMAT, CONFIRM = range(4)

CATEGORIES = [
    "Разработка / IT", "Маркетинг / SMM", "Дизайн",
    "Продажи / менеджмент", "Копирайтинг / контент",
    "Бухгалтерия / финансы", "HR / рекрутинг", "Другое"
]
SALARY_RANGES = [
    "Любая зарплата", "от 30 000 ₽", "от 50 000 ₽",
    "от 80 000 ₽", "от 120 000 ₽", "от 200 000 ₽"
]
FORMATS = ["Полная удалёнка", "Гибрид", "Любой формат"]


def format_job(job: dict) -> str:
    return (
        f"💼 *{job['title']}*\n"
        f"🏢 {job.get('company', '')}\n"
        f"💰 {job.get('salary', 'не указана')}\n"
        f"🏠 {job.get('format', 'Удалёнка')}\n\n"
        f"{job.get('description', '')[:200]}...\n\n"
        f"👉 [Открыть вакансию]({job['url']})"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    user = db.get_user(update.effective_user.id)
    name = update.effective_user.first_name or "друг"
    if user and user.get("active"):
        kb = [
            [InlineKeyboardButton("⚙️ Изменить настройки", callback_data="setup")],
            [InlineKeyboardButton("⏸ Приостановить", callback_data="pause")],
            [InlineKeyboardButton("📋 Последние вакансии", callback_data="latest")],
        ]
        await update.message.reply_text(
            f"👋 С возвращением, {name}! Ты подписан на вакансии.",
            reply_markup=InlineKeyboardMarkup(kb))
    else:
        kb = [[InlineKeyboardButton("🚀 Настроить подписку", callback_data="setup")]]
        await update.message.reply_text(
            f"👋 Привет, {name}!\n\nЯ бот канала *careercrafts* — "
            f"нахожу удалённые вакансии и присылаю только подходящие.\n\n"
            f"Настрой подписку за 1 минуту 👇",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))


async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{i}")] for i, c in enumerate(CATEGORIES)]
    await query.edit_message_text(
        "📂 *Шаг 1/3: Специализация*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSE_CATEGORY


async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["category"] = CATEGORIES[idx]
    buttons = [[InlineKeyboardButton(s, callback_data=f"sal_{i}")] for i, s in enumerate(SALARY_RANGES)]
    await query.edit_message_text(
        f"✅ {CATEGORIES[idx]}\n\n💰 *Шаг 2/3: Минимальная зарплата?*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSE_SALARY


async def choose_salary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["salary"] = SALARY_RANGES[idx]
    buttons = [[InlineKeyboardButton(f, callback_data=f"fmt_{i}")] for i, f in enumerate(FORMATS)]
    await query.edit_message_text(
        f"✅ {SALARY_RANGES[idx]}\n\n🏠 *Шаг 3/3: Формат работы?*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSE_FORMAT


async def choose_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["format"] = FORMATS[idx]
    kb = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm")],
        [InlineKeyboardButton("🔄 Заново", callback_data="setup")],
    ]
    await query.edit_message_text(
        f"📋 *Проверь настройки:*\n\n"
        f"📂 {context.user_data['category']}\n"
        f"💰 {context.user_data['salary']}\n"
        f"🏠 {context.user_data['format']}\n\nВсё верно?",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return CONFIRM


async def confirm_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = context.bot_data["db"]
    db.save_user(update.effective_user.id, {
        "name": update.effective_user.first_name or "",
        **{k: context.user_data[k] for k in ["category", "salary", "format"]}
    })
    await query.edit_message_text(
        "🎉 *Подписка активирована!*\n\n"
        "Буду присылать подходящие вакансии автоматически.\n\n"
        "/pause — пауза\n/resume — возобновить\n/latest — вакансии сейчас",
        parse_mode="Markdown")
    return ConversationHandler.END


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["db"].set_active(update.effective_user.id, False)
    await update.message.reply_text("⏸ Рассылка приостановлена. /resume чтобы возобновить.")


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["db"].set_active(update.effective_user.id, True)
    await update.message.reply_text("▶️ Рассылка возобновлена!")


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    fetcher = context.bot_data["fetcher"]
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала настрой подписку: /start")
        return
    await update.message.reply_text("🔍 Ищу вакансии...")
    jobs = fetcher.fetch(user["category"], user["salary"])
    if not jobs:
        await update.message.reply_text("Пока новых вакансий нет. Загляни позже!")
        return
    for job in jobs[:5]:
        await update.message.reply_text(format_job(job), parse_mode="Markdown",
                                        disable_web_page_preview=True)


async def pause_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.bot_data["db"].set_active(update.effective_user.id, False)
    await query.edit_message_text("⏸ Рассылка приостановлена. /resume чтобы возобновить.")


async def latest_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = context.bot_data["db"]
    fetcher = context.bot_data["fetcher"]
    user = db.get_user(update.effective_user.id)
    jobs = fetcher.fetch(user["category"], user["salary"])
    await query.edit_message_text("📋 Отправляю последние вакансии...")
    for job in (jobs or [])[:5]:
        await context.bot.send_message(
            chat_id=update.effective_user.id, text=format_job(job),
            parse_mode="Markdown", disable_web_page_preview=True)


async def broadcast(app: Application):
    db = app.bot_data["db"]
    fetcher = app.bot_data["fetcher"]
    for user in db.get_all_active_users():
        try:
            jobs = db.filter_new_jobs(user["user_id"], fetcher.fetch(user["category"], user["salary"]))
            for job in jobs[:3]:
                await app.bot.send_message(chat_id=user["user_id"], text=format_job(job),
                                           parse_mode="Markdown", disable_web_page_preview=True)
                db.mark_job_sent(user["user_id"], job["id"])
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Broadcast error for {user['user_id']}: {e}")


def main():
    from config import BOT_TOKEN, JOB_SEND_INTERVAL_HOURS
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    db = Database("users.db")
    fetcher = JobsFetcher()

    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["db"] = db
    app.bot_data["fetcher"] = fetcher

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(setup_start, pattern="^setup$")],
        states={
            CHOOSE_CATEGORY: [CallbackQueryHandler(choose_category, pattern="^cat_")],
            CHOOSE_SALARY:   [CallbackQueryHandler(choose_salary,   pattern="^sal_")],
            CHOOSE_FORMAT:   [CallbackQueryHandler(choose_format,   pattern="^fmt_")],
            CONFIRM: [
                CallbackQueryHandler(confirm_settings, pattern="^confirm$"),
                CallbackQueryHandler(setup_start,      pattern="^setup$"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("pause",  pause))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CommandHandler("latest", latest))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(pause_cb,  pattern="^pause$"))
    app.add_handler(CallbackQueryHandler(latest_cb, pattern="^latest$"))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(broadcast, "interval", hours=JOB_SEND_INTERVAL_HOURS, args=[app])
    scheduler.start()

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
