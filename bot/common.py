import html

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramMigrateToChat
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import bot.keyboards as kb
import database.requests as rq

from time import time

from bot.config import ADMIN_ID, TEST_ID, COOLDOWN, EVENT_CONFIG, STANDARD_ITEMS
from bot.services import roof




class Form(StatesGroup):
    add_event_settings = State()


all_items = ["buy_" + item["key"] for item in STANDARD_ITEMS]


# Вспомогательные функции
async def setup_user_and_chat(message: Message) -> None:
    await rq.set_user(message.from_user.id, message.from_user.full_name)
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
        except TelegramBadRequest:
            await message.bot.send_message(ADMIN_ID, f'Бот не является админом канала {channel["name"]}')
            await message.reply('Не удалось проверить подписку. Попробуй позже.')
            return False
    return True


from bot.messages import cooldown as format_cooldown_message


async def process_roof_result(message: Message, obj: dict, user_id: int) -> None:
    title = '🎉 Успешный руф' if obj['status'] else '👮 Тебя приняли'
    caption = f"<b>{title}</b>\n\n🏙 {html.escape(obj['name'])}\n⭐ Очки: <b>{obj['xp']:+d}</b>"
    try:
        await message.reply_photo(obj['image'], caption=caption, parse_mode='HTML', reply_markup=kb.stats)
    except TelegramBadRequest:
        await message.reply(caption, parse_mode='HTML', reply_markup=kb.stats)


async def send_to_all_chats(bot, text: str, parse_mode: str = 'html') -> None:
    chats = await rq.get_chats()
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, text, parse_mode=parse_mode)
        except (TelegramForbiddenError, TelegramBadRequest, TelegramMigrateToChat):
            await rq.delete_chat(chat_id)


