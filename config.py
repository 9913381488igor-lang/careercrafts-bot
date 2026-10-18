import os

# Токен бота — устанавливается через переменную окружения на сервере
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Как часто рассылать новые вакансии (в часах)
JOB_SEND_INTERVAL_HOURS = 4

# Часовой пояс
TIMEZONE = "Europe/Moscow"
