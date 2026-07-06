"""
Точка входа для деплоя на Render.com (бесплатный Web Service).

Render не даёт бесплатный "always-on" процесс с long polling — зато даёт
бесплатный веб-сервис, который поднимается по входящему HTTP-запросу.
Поэтому здесь бот работает через вебхук: Telegram сам стучится на наш URL,
когда приходит сообщение.

Render автоматически прокидывает:
- PORT              — порт, на котором нужно слушать
- RENDER_EXTERNAL_URL — публичный HTTPS-адрес сервиса

Локально/на VPS для разработки удобнее bot.py (long polling) — этот файл
нужен только для Render-деплоя.
"""

import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from dotenv import load_dotenv

from db import init_db

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhook"


async def on_startup(bot: Bot, base_url: str):
    await bot.set_webhook(f"{base_url}{WEBHOOK_PATH}")
    log.info("Webhook установлен: %s%s", base_url, WEBHOOK_PATH)


def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задан BOT_TOKEN (переменная окружения Render)")

    base_url = os.getenv("RENDER_EXTERNAL_URL")
    if not base_url:
        raise SystemExit(
            "Не найден RENDER_EXTERNAL_URL — этот файл предназначен для запуска на Render."
        )

    port = int(os.getenv("PORT", "10000"))

    init_db()

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())

    # регистрируем те же хендлеры, что и в bot.py (polling-версии)
    from bot import register_handlers
    register_handlers(dp)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    async def _health(request):
        return web.Response(text="ok")

    app.router.add_get("/", _health)

    dp.startup.register(lambda: on_startup(bot, base_url))

    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
