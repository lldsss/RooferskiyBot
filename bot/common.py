import html
import time

import asyncio
import logging
from aiogram.types import Message
from aiogram.exceptions import (TelegramForbiddenError, TelegramBadRequest,
                                TelegramMigrateToChat, TelegramRetryAfter, TelegramAPIError)
from aiogram.fsm.state import State, StatesGroup
import bot.keyboards as kb
import database.requests as rq
from bot.config import ADMIN_IDS
from bot.limits import TTLCache

SUBSCRIPTION_TTL = 600     # успешная проверка подписки живёт 10 минут
CHANNELS_TTL = 60          # список обязательных каналов перечитывается раз в минуту
ADMIN_ALERT_INTERVAL = 3600

_known_users = TTLCache(ttl=6 * 3600)
_known_chats = TTLCache(ttl=6 * 3600)
_subscriptions = TTLCache(ttl=SUBSCRIPTION_TTL)
_channels = TTLCache(ttl=CHANNELS_TTL)
_admin_alerts: dict = {}


class Form(StatesGroup):
    add_event_settings = State()


def invalidate_channels() -> None:
    """Вызывать после любого изменения списка обязательных каналов."""
    _channels.clear()
    _subscriptions.clear()


async def get_channels_cached() -> list:
    channels = _channels.get('all')
    if channels is None:
        channels = await rq.get_channels()
        _channels.set('all', channels)
    return channels


async def notify_admins(bot, text: str, parse_mode: str | None = None) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=parse_mode)
        except TelegramAPIError:
            logging.exception('Не удалось уведомить администратора %s', admin_id)


async def _alert_channel_failure(bot, channel: dict) -> None:
    """Не чаще раза в час на канал, чтобы не засыпать админов сообщениями."""
    now = time.monotonic()
    last = _admin_alerts.get(channel['tg_id'])
    if last is not None and now - last < ADMIN_ALERT_INTERVAL:
        return
    _admin_alerts[channel['tg_id']] = now
    await notify_admins(bot, f'⚠️ Не удалось проверить подписку на канал «{channel["name"]}» '
                             f'(ID {channel["tg_id"]}). Проверь, что бот — админ канала. '
                             'Пока проверка не работает, этот канал пропускается.')


# Вспомогательные функции
async def ensure_user(user) -> None:
    """Пишет игрока в базу только при первом появлении или смене имени."""
    if _known_users.get(user.id) != user.full_name:
        await rq.set_user(user.id, user.full_name)
        _known_users.set(user.id, user.full_name)


async def setup_user_and_chat(message: Message) -> None:
    await ensure_user(message.from_user)
    if message.chat.type in ('group', 'supergroup'):
        title = message.chat.title or message.from_user.full_name
        if _known_chats.get(message.chat.id) != title:
            await rq.set_chat(message.chat.id, title)
            _known_chats.set(message.chat.id, title)


async def check_prerequisites(message: Message, allow_private: bool = False) -> bool:
    if message.from_user is None:
        return False
    if message.chat.type == 'private' and not allow_private:
        await message.answer(
            '👋 Привет! Я работаю <b>только в группах, и только если ты подписан на каналы разработчика и спонсоров</b>',
            parse_mode='HTML', reply_markup=kb.start_button)
        return False

    user_id = message.from_user.id
    for channel in await get_channels_cached():
        cache_key = (channel['tg_id'], user_id)
        if _subscriptions.get(cache_key):
            continue
        try:
            member = await message.bot.get_chat_member(chat_id=channel['tg_id'], user_id=user_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            # Бот потерял доступ к каналу: игра не должна вставать во всех группах.
            await _alert_channel_failure(message.bot, channel)
            continue
        if member.status in ('left', 'kicked') or (member.status == 'restricted' and not member.is_member):
            await message.reply('❗️ Для работы подпишись на канал разработчика и каналы спонсоров',
                                reply_markup=await kb.channels())
            return False
        _subscriptions.set(cache_key, True)
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


async def check_callback_prerequisites(callback, allow_private: bool = False) -> bool:
    """Check the clicking user, not the bot that authored the keyboard message."""
    if not isinstance(callback.message, Message):
        return False
    message = callback.message.model_copy(update={'from_user': callback.from_user})
    return await check_prerequisites(message, allow_private=allow_private)
