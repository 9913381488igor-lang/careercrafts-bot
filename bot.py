import logging
import asyncio
import html
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
from database import Database
from jobs import JobsFetcher

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
# httpx пишет в лог каждый запрос вместе с токеном бота — оставляем только предупреждения
logging.getLogger("httpx").setLevel(logging.WARNING)

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

# Кнопки внизу экрана (постоянная клавиатура)
BTN_LATEST = "📋 Вакансии сейчас"
BTN_SETTINGS = "⚙️ Настройки"
BTN_PAUSE = "⏸ Пауза"
BTN_RESUME = "▶️ Возобновить"
BTN_CHANNEL = "📢 Наш канал"
CHANNEL_URL = "https://t.me/careercrafts"
BTN_STATS = "📊 Статистика"
ADMIN_ID = int(os.environ.get("ADMIN_ID", "457704932"))   # кто видит статистику


def main_keyboard(active: bool = True, admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [[BTN_LATEST], [BTN_SETTINGS, BTN_PAUSE if active else BTN_RESUME], [BTN_CHANNEL]]
    if admin:
        rows.append([BTN_STATS])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def is_admin(update: Update) -> bool:
    return bool(update.effective_user) and update.effective_user.id == ADMIN_ID


def format_job(job: dict) -> str:
    e = lambda x: html.escape(str(x or ""))
    desc = (job.get("description") or "").strip()
    if len(desc) > 300:
        desc = desc[:300].rsplit(" ", 1)[0] + "…"
    return (
        f"💼 <b>{e(job['title'])}</b>\n"
        f"🏢 {e(job.get('company'))}\n"
        f"💰 <b>{e(job.get('salary', 'не указана'))}</b>\n"
        f"🏠 {e(job.get('format', 'Удалёнка'))}\n\n"
        + (f"{e(desc)}\n\n" if desc else "")
        + f'👉 <a href="{e(job["url"])}">Открыть вакансию</a>'
        + (f"  ·  {e(job['source'])}" if job.get("source") else "")
    )


ERROR_TEXT = ("⚠️ Сейчас не удалось получить вакансии — источник временно недоступен. "
              "Попробуй через 10–15 минут: /latest")
EMPTY_TEXT = ("Свежих удалённых вакансий по твоим настройкам пока нет. "
              "Попробуй выбрать «Любая зарплата» или другую специализацию: /start")


async def get_jobs(context_or_app, user: dict):
    """Поиск в отдельном потоке, чтобы бот не «зависал» на время запросов."""
    fetcher = context_or_app.bot_data["fetcher"]
    return await asyncio.to_thread(fetcher.fetch, user["category"], user["salary"])


async def send_jobs(bot, chat_id: int, jobs: list, limit: int = 5):
    for job in jobs[:limit]:
        await bot.send_message(chat_id=chat_id, text=format_job(job), parse_mode="HTML",
                               disable_web_page_preview=True)
        await asyncio.sleep(0.1)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    user = db.get_user(update.effective_user.id)
    name = update.effective_user.first_name or "друг"
    if user:
        await update.message.reply_text(
            f"👋 С возвращением, {name}! "
            + ("Ты подписан на вакансии." if user.get("active") else "Рассылка на паузе.")
            + "\n\nКнопки управления — внизу 👇",
            reply_markup=main_keyboard(bool(user.get("active")), is_admin(update)))
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
    await context.bot.send_message(update.effective_user.id, "Кнопки управления — внизу 👇",
                                   reply_markup=main_keyboard(True, is_admin(update)))
    return ConversationHandler.END


async def settings_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [[InlineKeyboardButton(c, callback_data=f"cat_{i}")] for i, c in enumerate(CATEGORIES)]
    await update.message.reply_text(
        "📂 *Шаг 1/3: Специализация*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons))
    return CHOOSE_CATEGORY


async def channel_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Свежие подборки удалённых вакансий каждый день — в канале «Удаленка для тебя» 👇",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Перейти в канал", url=CHANNEL_URL)]]))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    db = context.bot_data["db"]
    with db._conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
        today = conn.execute("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', 'start of day')").fetchone()[0]
        week = conn.execute("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-7 days')").fetchone()[0]
        sent = conn.execute("SELECT COUNT(*) FROM sent_jobs").fetchone()[0]
        cats = conn.execute("SELECT category, COUNT(*) FROM users GROUP BY category ORDER BY 2 DESC LIMIT 3").fetchall()
    top = "\n".join(f"  • {c or '—'}: {n}" for c, n in cats) or "  —"
    await update.message.reply_text(
        f"📊 Статистика бота\n\n"
        f"Подписчиков всего: {total}\n"
        f"Активных (не на паузе): {active}\n"
        f"Новых сегодня: {today}\n"
        f"Новых за 7 дней: {week}\n"
        f"Отправлено вакансий: {sent}\n\n"
        f"Популярные специализации:\n{top}",
        reply_markup=main_keyboard(True, True))


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["db"].set_active(update.effective_user.id, False)
    await update.message.reply_text("⏸ Рассылка приостановлена. Нажми «▶️ Возобновить», когда захочешь снова получать вакансии.",
                                    reply_markup=main_keyboard(False, is_admin(update)))


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data["db"].set_active(update.effective_user.id, True)
    await update.message.reply_text("▶️ Рассылка возобновлена!", reply_markup=main_keyboard(True, is_admin(update)))


async def latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = context.bot_data["db"]
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала настрой подписку: /start")
        return
    await update.message.reply_text("🔍 Ищу вакансии... это может занять до минуты")
    jobs, error = await get_jobs(context, user)
    if error:
        logger.error(f"/latest for {user['user_id']}: {error}")
        await update.message.reply_text(ERROR_TEXT)
        return
    if not jobs:
        await update.message.reply_text(EMPTY_TEXT)
        return
    await send_jobs(context.bot, update.effective_user.id, jobs)
    for job in jobs[:5]:
        db.mark_job_sent(user["user_id"], job["id"])


async def pause_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.bot_data["db"].set_active(update.effective_user.id, False)
    await query.edit_message_text("⏸ Рассылка приостановлена. /resume чтобы возобновить.")


async def latest_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = context.bot_data["db"]
    user = db.get_user(update.effective_user.id)
    if not user:
        await query.edit_message_text("Сначала настрой подписку: /start")
        return
    await query.edit_message_text("🔍 Ищу вакансии... это может занять до минуты")
    jobs, error = await get_jobs(context, user)
    if error:
        await context.bot.send_message(update.effective_user.id, ERROR_TEXT)
        return
    if not jobs:
        await context.bot.send_message(update.effective_user.id, EMPTY_TEXT)
        return
    await send_jobs(context.bot, update.effective_user.id, jobs)


async def broadcast(app: Application):
    db = app.bot_data["db"]
    for user in db.get_all_active_users():
        try:
            jobs, error = await get_jobs(app, user)
            if error:
                logger.error(f"Broadcast fetch error for {user['user_id']}: {error}")
                continue
            new = db.filter_new_jobs(user["user_id"], jobs)
            await send_jobs(app.bot, user["user_id"], new, limit=3)
            for job in new[:3]:
                db.mark_job_sent(user["user_id"], job["id"])
        except Exception as e:
            logger.error(f"Broadcast error for {user['user_id']}: {e}")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Unhandled error: {context.error}", exc_info=context.error)


def main():
    from config import BOT_TOKEN, JOB_SEND_INTERVAL_HOURS
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    import os
    db_path = os.environ.get("DB_PATH", "users.db")   # на Railway: /data/users.db (Volume)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    db = Database(db_path)
    logger.info(f"База подписчиков: {db_path}")
    fetcher = JobsFetcher()

    async def post_init(application: Application):
        from datetime import datetime, timedelta
        scheduler = AsyncIOScheduler()
        scheduler.add_job(broadcast, "interval", hours=JOB_SEND_INTERVAL_HOURS, args=[application],
                          next_run_time=datetime.now() + timedelta(minutes=2))
        scheduler.start()
        application.bot_data["scheduler"] = scheduler
        await application.bot.set_my_commands([
            BotCommand("start", "Главное меню"),
            BotCommand("latest", "Вакансии сейчас"),
            BotCommand("pause", "Приостановить рассылку"),
            BotCommand("resume", "Возобновить рассылку"),
        ])

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.bot_data["db"] = db
    app.bot_data["fetcher"] = fetcher

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(setup_start, pattern="^setup$"),
                      MessageHandler(filters.Text([BTN_SETTINGS]), settings_msg)],
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
    app.add_handler(MessageHandler(filters.Text([BTN_LATEST]), latest))
    app.add_handler(MessageHandler(filters.Text([BTN_PAUSE]), pause))
    app.add_handler(MessageHandler(filters.Text([BTN_RESUME]), resume))
    app.add_handler(MessageHandler(filters.Text([BTN_CHANNEL]), channel_msg))
    app.add_handler(MessageHandler(filters.Text([BTN_STATS]), stats))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(pause_cb,  pattern="^pause$"))
    app.add_handler(CallbackQueryHandler(latest_cb, pattern="^latest$"))
    app.add_error_handler(on_error)

    logger.info(f"Бот запущен! hh.ru: {'включён (HH_TOKEN)' if fetcher.hh_token else 'выключен — нет HH_TOKEN'}")
    app.run_polling()


if __name__ == "__main__":
    main()
