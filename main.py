import asyncio
import logging
from contextlib import suppress
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from bot.config import TOKEN
from bot.handlers import router
from database.requests import reset_users_items
from database.base import base_run, add_items, add_objects, add_levels, engine


async def main():
    if not TOKEN:
        raise RuntimeError('Укажите BOT_TOKEN в файле .env в корне проекта или в переменных окружения')
    bot = Bot(token=TOKEN)
    task = None
    try:
        await base_run()
        await add_items()
        await add_levels()
        await add_objects()
        task = asyncio.create_task(reset_users_items(bot))
        dp = Dispatcher(events_isolation=SimpleEventIsolation())
        dp.include_router(router)
        await dp.start_polling(bot)
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await bot.session.close()
        await engine.dispose()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
