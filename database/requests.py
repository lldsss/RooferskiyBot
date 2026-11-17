import asyncio
import logging
import time
from asyncio import Lock
from typing import Any

from sqlalchemy import select, delete, text, cast, String

from database.base import async_session, User, Chat, Channel, Event, Level, Item, Code, Payment

from weakref import WeakValueDictionary

_user_locks = WeakValueDictionary()


def lock_user(user_id: int) -> Lock:
    lock = _user_locks.get(user_id)
    if lock is None:
        lock = Lock()
        _user_locks[user_id] = lock
    return lock


async def execute_db_operation(operation, *args, write=True, **kwargs) -> Any:
    async with async_session() as session:
        if write:
            await session.execute(text("BEGIN IMMEDIATE"))
        return await operation(session, *args, **kwargs)


# Пользователи и чаты
async def setup_entity(entity_type: str, tg_id: int, name: str) -> None:
    model = {'user': User, 'chat': Chat}.get(entity_type)
    if model is None:
        return

    async def operation(session):
        entity = await session.get(model, tg_id)
        if not entity:
            session.add(model(tg_id=tg_id, name=name))
        elif entity.name != name:
            entity.name = name
        await session.commit()

    if entity_type == 'user':
        async with lock_user(tg_id):
            await execute_db_operation(operation)
    else:
        await execute_db_operation(operation)


async def set_user(tg_id: int, name: str) -> None:
    await setup_entity('user', tg_id, name)


async def set_chat(tg_id: int, name: str) -> None:
    await setup_entity('chat', tg_id, name)


async def delete_chat(chat_id: int) -> None:
    async def operation(session):
        chat = await session.get(Chat, chat_id)
        if chat:
            await session.delete(chat)
            await session.commit()

    await execute_db_operation(operation)


async def get_chats() -> list:
    async def operation(session):
        result = await session.scalars(select(Chat.tg_id).where(Chat.tg_id < 0))
        return result.all()

    return await execute_db_operation(operation, write=False) or []


# Ивенты
async def set_event(setting: str, value) -> None:
    await set_event_settings({setting: value})


async def set_event_settings(values):
    async def operation(session):
        event = await session.scalar(select(Event))
        if not event:
            event = Event(name='Ивент')
            session.add(event)
        for setting, value in values.items():
            if setting not in ('name', 'description', 'cd_event', 'prim_event', 'lvl_event', 'activated'):
                raise ValueError('Неизвестная настройка события')
            setattr(event, setting, value)
        await session.commit()
    await execute_db_operation(operation)


async def get_event_settings(for_admin: bool) -> dict:
    async def operation(session):
        event = await session.scalar(select(Event))
        if event and (for_admin or event.activated):
            return {
                'name': event.name, 'description': event.description,
                'cd': event.cd_event, 'prim': event.prim_event,
                'lvl': event.lvl_event, 'activated': event.activated
            }
        return {'name': 'Ивент', 'description': '', 'cd': 0, 'prim': 0, 'lvl': 0, 'activated': False}

    return await execute_db_operation(operation, write=False)


# Каналы
DEFAULT_CHANNELS = [dict(tg_id=-1003041436132, name='Канал разработчика', link='https://t.me/rooferskiybotchannel')]


async def get_channels() -> list:
    async def operation(session):
        channels = await session.scalars(select(Channel))
        return [{'tg_id': c.tg_id, 'name': c.name, 'link': c.link} for c in channels]

    return await execute_db_operation(operation, write=False)


async def add_channel(tg_id: int, name: str, link: str) -> None:
    async def operation(session):
        await session.merge(Channel(tg_id=tg_id, name=name, link=link))
        await session.commit()

    await execute_db_operation(operation)


async def reset_channels() -> None:
    async def operation(session):
        await session.execute(delete(Channel))
        session.add_all([Channel(**channel) for channel in DEFAULT_CHANNELS])
        await session.commit()

    await execute_db_operation(operation)


# Игроки
async def get_user_info(tg_id: int) -> dict:
    async def operation(session):
        user = await session.get(User, tg_id)
        if not user:
            return {'name': 'Неизвестный', 'xp': 0, 'level': 0, 'cd': 0, 'prim': 0, 'object_status': False,
                    'cd_items': 0}
        return {
            'name': user.name, 'xp': user.xp, 'level': user.level, 'cd': user.cd_lvl,
            'prim': user.prim_lvl, 'object_status': user.object_status, 'cd_items': user.cd_items
        }

    return await execute_db_operation(operation, write=False)


# Уровни
async def manage_levels(tg_id: int, action: str) -> bool | dict | None:
    empty = False if action in ('able', 'update') else {'object_status': False, 'object_req': '',
                                                         'xp_status': False, 'xp_req': 0}
    async with async_session() as session:
        if action == 'update':
            await session.execute(text('BEGIN IMMEDIATE'))
        user = await session.get(User, tg_id)
        if not user or user.level >= 10:
            return empty
        level_req = await session.get(Level, user.level + 1)
        if not level_req:
            return empty
        if action == 'able':
            return user.object_status and user.xp >= level_req.xp
        if action == 'about':
            return {
                'object_status': user.object_status, 'object_req': level_req.object,
                'xp_status': user.xp >= level_req.xp, 'xp_req': level_req.xp
            }
        if action == 'update' and user.object_status and user.xp >= level_req.xp:
            user.xp = 0
            user.level += 1
            user.cd_lvl += 180
            user.prim_lvl += 0.05
            user.object_status = False
            await session.commit()
            return True
        return False


async def able_to_update(tg_id: int) -> bool:
    return await manage_levels(tg_id, 'able')


async def about_level_updating(tg_id: int) -> dict:
    return await manage_levels(tg_id, 'about')


async def update_level(tg_id: int) -> bool:
    return await manage_levels(tg_id, 'update')


async def top() -> list:
    """Возвращает топ-10 пользователей по опыту"""

    async def operation(session):
        top_users = await session.scalars(select(User).order_by(User.xp.desc(), User.tg_id).limit(10))
        return [{'name': user.name, 'xp': user.xp, 'level': user.level} for user in top_users]

    return await execute_db_operation(operation, write=False)


# Предметы
def refresh_items(user, configs, now):
    """Поддерживает старые ключи по названию, убирает истёкшие усиления и пересчитывает эффекты.

    Поля меняются только при реальном изменении, чтобы не переписывать строку без нужды.
    """
    by_key = {key: item for item in configs for key in (item.key, item.name)}
    current = dict(user.items or {})
    active = {}
    expired = []
    for key, purchased in current.items():
        item = by_key.get(key)
        duration = item.duration if item else 86400
        if purchased <= 0 or now - purchased >= duration:
            expired.append(item.name if item else key)
        elif item:
            active[item.key] = max(active.get(item.key, 0), purchased)
    if active != current or user.items is None:
        user.items = active
    for field, attribute in (('cd_items', 'cd'), ('prim_items', 'prim'), ('lvl_items', 'lvl')):
        value = sum(getattr(by_key[key], attribute) for key in active)
        if getattr(user, field) != value:
            setattr(user, field, value)
    return expired


def item_expires_at(item, purchased: float) -> float:
    return purchased + item.duration


async def get_items() -> list:
    async def operation(session):
        return (await session.scalars(select(Item))).all()

    return await execute_db_operation(operation, write=False)


async def get_item(key) -> dict | None:
    async def operation(session):
        item = await session.scalar(select(Item).where(Item.key == key))
        if not item:
            return None
        return {'name': item.name, 'description': item.description, 'key': item.key, 'price': item.price,
                'duration': item.duration,
                'available': item.enabled and (not item.available_until or time.time() < item.available_until)}

    return await execute_db_operation(operation, write=False)


async def user_items(tg_id: int) -> dict:
    """Активные усиления игрока: {ключ предмета: время окончания}."""
    async def operation(session):
        user = await session.get(User, tg_id)
        if not user:
            return {}
        configs = (await session.scalars(select(Item))).all()
        refresh_items(user, configs, time.time())
        await session.commit()
        by_key = {item.key: item for item in configs}
        return {key: item_expires_at(by_key[key], purchased) for key, purchased in user.items.items()}

    return await execute_db_operation(operation)


async def expire_items() -> list[tuple[int, str]]:
    """Снимает истёкшие усиления. Смотрит только игроков с непустым инвентарём."""
    async def operation(session):
        users = await session.scalars(select(User).where(
            User.items.is_not(None), cast(User.items, String).not_in(['{}', 'null'])))
        configs = (await session.scalars(select(Item))).all()
        now = time.time()
        notices = []
        for user in users:
            notices.extend((user.tg_id, name) for name in refresh_items(user, configs, now))
        await session.commit()
        return notices

    return await execute_db_operation(operation)


async def notify_expired(bot, notices) -> None:
    from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
    from html import escape
    for user_id, item_name in notices:
        text_ = f'⏰ <b>Усиление закончилось</b>\n\n{escape(item_name)} · срок действия истёк.\nПродлить: /buy'
        for attempt in range(2):
            try:
                await bot.send_message(user_id, text_, parse_mode='HTML')
                break
            except TelegramRetryAfter as error:
                if attempt == 0:
                    await asyncio.sleep(error.retry_after)
            except TelegramAPIError:
                break
        await asyncio.sleep(0.05)


async def reset_users_items(bot) -> None:
    while True:
        try:
            await notify_expired(bot, await expire_items())
        except Exception:
            logging.exception('Не удалось обновить сроки предметов')
        await asyncio.sleep(300)  # Проверка каждые 5 минут


# Промокоды
async def manage_promo(action: str, name: str = None, limit: int = None, promo_xp: int = None, tg_id: int = None,
                       promo: str = None) -> str | bool | None:
    async def operation(session):
        if action == 'add':
            if await session.get(Code, name):
                return False
            session.add(Code(name=name, limit=limit, activations=0, xp=promo_xp, users=[]))
            await session.commit()
            return True

        elif action == 'use':
            if promo == 'empty': return '❌ Промокод не может быть пустым'
            code = await session.get(Code, promo)
            user = await session.get(User, tg_id)
            if not user: return 'Сначала запусти /start'
            if not code: return '❌ Такого кода не существует'
            if tg_id in code.users: return '🚫 Ты уже активировал этот код'
            if code.activations >= code.limit: return '❌ Код достиг лимита активаций'
            code.activations += 1
            code.users.append(tg_id)
            user.xp += code.xp
            await session.commit()
            return f'✅ Ты успешно активировал код!\n<b>+{code.xp} очков</b>'
        return None

    return await execute_db_operation(operation)


async def add_promo(name: str, limit: int, xp: int) -> bool:
    return await manage_promo('add', name=name.upper(), limit=limit, promo_xp=xp)


async def use_promo(tg_id: int, promo: str) -> str:
    return await manage_promo('use', tg_id=tg_id, promo=promo) or '❌ Ошибка активации промокода'


# Платежи
async def fulfill_payment(user_id, payment):
    """Выдаёт или продлевает усиление. Возвращает время окончания или False при повторной доставке.

    Повторная доставка того же платежа не выдаёт усиление второй раз.
    """
    async with async_session() as session:
        await session.execute(text('BEGIN IMMEDIATE'))
        if await session.get(Payment, payment.telegram_payment_charge_id):
            return False
        item = await session.scalar(select(Item).where(Item.key == payment.invoice_payload))
        user = await session.get(User, user_id)
        if not item or not user or payment.currency != 'XTR' or payment.total_amount != item.price:
            raise ValueError('Параметры оплаченного счёта не совпадают с товаром')
        configs = (await session.scalars(select(Item))).all()
        now = time.time()
        refresh_items(user, configs, now)
        # Повторная покупка продлевает срок, сохраняя одну копию эффекта.
        if item.key in user.items:
            user.items[item.key] += item.duration
        else:
            user.items[item.key] = now
        refresh_items(user, configs, now)
        expires = item_expires_at(item, user.items[item.key])
        session.add(Payment(charge_id=payment.telegram_payment_charge_id, user_id=user_id,
                            item_key=item.key, amount=payment.total_amount))
        await session.commit()
        return expires


async def get_payment(charge_id: str) -> dict | None:
    async def operation(session):
        payment = await session.get(Payment, charge_id)
        if not payment:
            return None
        return {'charge_id': payment.charge_id, 'user_id': payment.user_id, 'item_key': payment.item_key,
                'amount': payment.amount, 'refunded': payment.refunded}

    return await execute_db_operation(operation, write=False)


async def user_payments(user_id: int, limit: int = 5) -> list[dict]:
    async def operation(session):
        rows = await session.scalars(select(Payment).where(Payment.user_id == user_id)
                                     .order_by(Payment.created_at.desc()).limit(limit))
        return [{'charge_id': p.charge_id, 'item_key': p.item_key, 'amount': p.amount,
                 'refunded': p.refunded, 'created_at': p.created_at} for p in rows]

    return await execute_db_operation(operation, write=False)


async def revoke_payment(charge_id: str) -> bool:
    """После возврата Stars отмечает платёж и отнимает оплаченный им срок усиления."""
    async with async_session() as session:
        await session.execute(text('BEGIN IMMEDIATE'))
        payment = await session.get(Payment, charge_id)
        if not payment or payment.refunded:
            return False
        payment.refunded = True
        user = await session.get(User, payment.user_id)
        item = await session.scalar(select(Item).where(Item.key == payment.item_key))
        if user and item and item.key in (user.items or {}):
            user.items[item.key] -= item.duration
            refresh_items(user, (await session.scalars(select(Item))).all(), time.time())
        await session.commit()
        return True
