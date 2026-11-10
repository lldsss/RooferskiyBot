import html

import asyncio
import logging
from aiogram.types import Message
from aiogram.exceptions import (TelegramForbiddenError, TelegramBadRequest,
                                TelegramMigrateToChat, TelegramRetryAfter, TelegramAPIError)
from aiogram.fsm.state import State, StatesGroup
import bot.keyboards as kb
import database.requests as rq
from bot.config import ADMIN_ID


class Form(StatesGroup):
    add_event_settings = State()


# Вспомогательные функции
async def setup_user_and_chat(message: Message) -> None:
    await rq.set_user(message.from_user.id, message.from_user.full_name)
    if message.chat.type in ('group', 'supergroup'):
        await rq.set_chat(message.chat.id, message.chat.title or message.from_user.full_name)


async def check_prerequisites(message: Message) -> bool:
    if message.chat.type == 'private':
        await message.answer(
            '👋 Привет! Я работаю <b>только в группах, и только если ты подписан на каналы разработчика и спонсоров</b>',
            parse_mode='HTML', reply_markup=kb.start_button)
        return False

    channels = await rq.get_channels()
    for channel in channels:
        try:
            user_status = await message.bot.get_chat_member(chat_id=channel['tg_id'], user_id=message.from_user.id)
            if user_status.status in ('left', 'kicked') or (user_status.status == 'restricted' and not user_status.is_member):
                await message.reply('❗️ Для работы подпишись на канал разработчика и каналы спонсоров',
                                    reply_markup=await kb.channels())
                return False
        except (TelegramBadRequest, TelegramForbiddenError):
            try:
                await message.bot.send_message(ADMIN_ID, f'Не удалось проверить канал {channel["name"]}')
            except TelegramAPIError:
                logging.exception('Не удалось уведомить администратора')
            await message.reply('Не удалось проверить подписку. Попробуй позже.')
            return False
    return True


async def process_roof_result(message: Message, obj: dict) -> None:
    title = '🎉 Успешный руф' if obj['status'] else '👮 Тебя приняли'
    caption = f"<b>{title}</b>\n\n🏙 {html.escape(obj['name'])}\n⭐ Очки: <b>{obj['xp']:+d}</b>"
    try:
        await message.reply_photo(obj['image'], caption=caption, parse_mode='HTML', reply_markup=kb.stats)
    except TelegramBadRequest:
        await message.reply(caption, parse_mode='HTML', reply_markup=kb.stats)


async def send_to_all_chats(bot, text: str, parse_mode: str = 'html') -> None:
    chats = await rq.get_chats()
    for chat_id in chats:
        for attempt in range(2):
            try:
                await bot.send_message(chat_id, text, parse_mode=parse_mode)
                break
            except TelegramRetryAfter as error:
                if attempt == 0:
                    await asyncio.sleep(error.retry_after)
            except TelegramMigrateToChat as error:
                await rq.set_chat(error.migrate_to_chat_id, '')
                await rq.delete_chat(chat_id)
                chat_id = error.migrate_to_chat_id
            except TelegramForbiddenError:
                await rq.delete_chat(chat_id)
                break
            except TelegramAPIError:
                logging.exception('Не удалось отправить сообщение в чат %s', chat_id)
                break
