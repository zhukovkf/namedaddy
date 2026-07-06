"""
Telegram-бот проверки названия на схожесть с зарегистрированными товарными
знаками (открытые данные Роспатента) + эвристическая оценка вероятности
регистрации.

Запуск:
    export BOT_TOKEN=xxxx  (или положите в .env)
    python bot.py
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from dotenv import load_dotenv

from db import get_conn, count_records, candidate_search, init_db
from similarity import assess, normalize, phonetic_key

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DISCLAIMER = (
    "\n\n⚠️ Это автоматическая эвристическая оценка по открытым данным "
    "Роспатента, а не юридическое заключение. Для реальной подачи заявки "
    "рекомендуется проверка у патентного поверенного."
)


class Form(StatesGroup):
    waiting_classes = State()


def format_assessment(a) -> str:
    lines = [f"🔎 Запрос: <b>{a.query}</b>\n"]

    if not a.matches:
        lines.append("Похожих зарегистрированных знаков не найдено в базе.")
    else:
        lines.append("Похожие знаки:")
        for m in a.matches:
            status_ru = {
                "active": "действующий",
                "pending": "заявка на рассмотрении",
                "expired": "срок истёк",
                "terminated": "прекращён досрочно",
            }.get(m.status, m.status)
            lines.append(
                f"• <b>{m.name}</b> — классы МКТУ: {m.mktu_classes or '—'}; "
                f"статус: {status_ru}; правообладатель: {m.holder}\n"
                f"  сходство текст/фонетика: {m.text_sim:.0%} / {m.phonetic_sim:.0%}"
            )

    lines.append(
        f"\n📊 Оценка вероятности успешной регистрации: "
        f"<b>{a.registration_probability:.0f}%</b> ({a.risk_label})"
    )
    return "\n".join(lines) + DISCLAIMER


async def run_check(name: str, classes_raw: str) -> str:
    with get_conn() as conn:
        if count_records(conn) == 0:
            return (
                "База данных пуста. Загрузите открытые данные Роспатента "
                "(ingest.py) или демо-данные (load_sample.py) — см. README."
            )
        rows = candidate_search(conn, normalize(name), phonetic_key(name))
        result = assess(name, classes_raw, rows)
    return format_assessment(result)


def register_handlers(dp: Dispatcher):
    """
    Регистрирует все хендлеры бота на переданном Dispatcher. Используется
    и в polling-режиме (запуск ниже, для VPS/локали), и в webhook-режиме
    (webhook_app.py, для деплоя на Render) — логика бота одна и та же,
    отличается только способ доставки апдейтов от Telegram.
    """

    @dp.message(CommandStart())
    async def cmd_start(message: Message, state: FSMContext):
        await state.clear()
        await message.answer(
            "Привет! Пришлите название бренда, которое хотите проверить.\n\n"
            "Можно сразу указать классы МКТУ через запятую вторым сообщением "
            "(например: 25, 35) — это повысит точность оценки, либо "
            "отправьте «-», чтобы пропустить."
        )

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(
            "1. Отправьте название бренда.\n"
            "2. Укажите классы МКТУ через запятую или «-», если не знаете.\n"
            "3. Получите список похожих знаков и оценку вероятности регистрации."
            + DISCLAIMER
        )

    @dp.message(Form.waiting_classes)
    async def got_classes(message: Message, state: FSMContext):
        data = await state.get_data()
        name = data.get("name", "")
        classes_raw = "" if message.text.strip() == "-" else message.text
        await state.clear()
        await message.answer("Ищу похожие знаки…")
        result = await run_check(name, classes_raw)
        await message.answer(result)

    @dp.message(F.text)
    async def got_name(message: Message, state: FSMContext):
        name = message.text.strip()
        if len(name) < 2:
            await message.answer("Название слишком короткое, попробуйте ещё раз.")
            return
        await state.update_data(name=name)
        await state.set_state(Form.waiting_classes)
        await message.answer(
            "Классы МКТУ через запятую (например: 25, 35) или «-», чтобы пропустить."
        )


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Не задан BOT_TOKEN (переменная окружения или .env)")

    init_db()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp)

    log.info("Бот запущен (long polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
