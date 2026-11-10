import asyncio
import random
import time
from asyncio import Lock
from typing import Any

from sqlalchemy import select, delete, text

from database.base import async_session, User, Chat, Channel, Event, Level, Item, Code, Object, Payment
from bot.config import TEST_ID, OBJECTS, STANDARD_ITEMS

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


# Универсальные функции
async def setup_entity(entity_type: str, tg_id: int, name: str) -> None:
    async def operation(session):
        if entity_type == 'user':
            model, id_field = User, User.tg_id
        elif entity_type == 'chat':
            model, id_field = Chat, Chat.tg_id
        else:
            return

        entity = await session.scalar(select(model).where(id_field == tg_id))
        if not entity:
            entity = model(tg_id=tg_id, name=name)
            session.add(entity)
        else:
            entity.name = name
        await session.commit()

    lock = lock_user(tg_id) if entity_type == 'user' else None
    if lock:
        async with lock:
            await execute_db_operation(operation)
    else:
        await execute_db_operation(operation)


async def set_user(tg_id: int, name: str) -> None:
    await setup_entity('user', tg_id, name)


async def set_chat(tg_id: int, name: str) -> None:
    await setup_entity('chat', tg_id, name)


async def delete_chat(chat_id: int) -> None:
    async def operation(session):
        chat = await session.scalar(select(Chat).where(Chat.tg_id == chat_id))
        if chat:
            await session.delete(chat)
            await session.commit()

    await execute_db_operation(operation)


async def get_chats() -> list:
    async def operation(session):
        result = await session.scalars(select(Chat.tg_id).where(Chat.tg_id < 0))
        return result.all()

    return await execute_db_operation(operation, write=False) or []


async def manage_user_time_and_xp(tg_id: int, action: str, value: int = None) -> float:
    async def operation(session):
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            return 0.0 if action == 'get_time' else None

        if action == 'update_time':
            user.last_roof_time = 0 if tg_id == TEST_ID else time.time()
        elif action == 'get_time':
            return user.last_roof_time
        elif action == 'update_xp':
            user.xp = 0 if tg_id == TEST_ID else user.xp + round(value)

        await session.commit()
        return None

    result = await execute_db_operation(operation)
    return result if action == 'get_time' else None


async def update_time(tg_id: int) -> None:
    await manage_user_time_and_xp(tg_id, 'update_time')


async def get_time(tg_id: int) -> float:
    return await manage_user_time_and_xp(tg_id, 'get_time')


async def update_xp(tg_id: int, value: int) -> None:
    await manage_user_time_and_xp(tg_id, 'update_xp', value)


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
async def manage_channels(action: str, tg_id: int = None, name: str = None, link: str = None) -> list:
    async def operation(session):
        if action == 'get':
            channels = await session.scalars(select(Channel))
            return [{'tg_id': c.tg_id, 'name': c.name, 'link': c.link} for c in channels]
        elif action == 'add':
            await session.merge(Channel(tg_id=tg_id, name=name, link=link))
        elif action == 'reset':
            await session.execute(delete(Channel))
            session.add_all(
                [Channel(tg_id=-1003041436132, name='Канал разработчика', link='https://t.me/rooferskiybotchannel')])
        await session.commit()
        return []

    return await execute_db_operation(operation, write=False)


async def get_channels() -> list:
    return await manage_channels('get')


async def add_channel(tg_id: int, name: str, link: str) -> None:
    await manage_channels('add', tg_id, name, link)


async def reset_channels() -> None:
    await manage_channels('reset')


# Игровые функции
def _get_empty_object_response() -> dict:
    return {'name': '', 'floors': 0, 'image': '', 'status': False, 'prim': 0}


def _select_random_object(objects: list) -> Object:
    weights = [1 / obj.floors ** 2 for obj in objects]
    return random.choices(objects, weights=weights, k=1)[0]


async def manage_objects(action: str, tg_id: int = None) -> dict | None:
    async def operation(session):
        if action == 'get':
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            event = await session.scalar(select(Event))

            if not user:
                return _get_empty_object_response()

            modified_level = user.level + (event.lvl_event if event and event.activated else 0) + user.lvl_items
            objects = await session.scalars(select(Object).where(Object.last_level > modified_level))
            objects = objects.all()

            if not objects:
                return _get_empty_object_response()

            obj = _select_random_object(objects)
            success_probability = max(0, min(1, obj.prim - user.prim_lvl + (event.prim_event if event and event.activated else 0) + user.prim_items))
            is_success = random.random() > success_probability

            if is_success and user.level < 10:
                level_req = await session.scalar(select(Level).where(Level.level == user.level + 1))
                if level_req and level_req.object == obj.name:
                    user.object_status = True

            await session.commit()
            return {'name': obj.name, 'floors': obj.floors, 'image': obj.image, 'status': is_success, 'prim': obj.prim}
        elif action == 'reset':
            await session.execute(delete(Object))
            objects = []
            for obj in OBJECTS:
                objects.append(Object(
                    name=obj['name'],
                    floors=obj['floors'],
                    prim=obj['prim'],
                    last_level=obj['last_level'],
                    image=obj['image'],
                ))
            session.add_all(objects)
            await session.commit()
        return None

    return await execute_db_operation(operation)


async def get_object(tg_id: int) -> dict:
    return await manage_objects('get', tg_id=tg_id)


async def get_user_info(tg_id: int) -> dict:
    async def operation(session):
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
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
    async with async_session() as session:
        await session.execute(text('BEGIN IMMEDIATE'))
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if not user or user.level >= 10:
            return False if action in ('able', 'update') else {'object_status': False, 'object_req': '', 'xp_status': False,
                                                   'xp_req': 0}

        level_req = await session.scalar(select(Level).where(Level.level == user.level + 1))
        if not level_req:
            return False if action in ('able', 'update') else {'object_status': False, 'object_req': '', 'xp_status': False,
                                                   'xp_req': 0}
        if action == 'able':
            return user.object_status and user.xp >= level_req.xp
        elif action == 'about':
            return {
                'object_status': user.object_status, 'object_req': level_req.object,
                'xp_status': user.xp >= level_req.xp, 'xp_req': level_req.xp
            }
        elif action == 'update':
            if user.object_status and user.xp >= level_req.xp:
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
    """Возвращает топ-10 пользователей по опыту с медальками"""

    async def operation(session):
        top_users = await session.scalars(select(User).order_by(User.xp.desc(), User.tg_id).limit(10))

        return [
            {
                'name': user.name,
                'xp': user.xp,
                'level': user.level
            }
            for user in top_users
        ]

    return await execute_db_operation(operation, write=False)


# Предметы и промокоды
async def manage_items(action: str, tg_id: int = None, name: str = None, bot=None, key: str = None,
                       description: str = None,
                       price: int = None,
                       limit: int = None, cd: int = None, prim: float = None, lvl: int = None) -> dict | list | None:
    async def operation(session):
        item = await session.scalar(select(Item).where((Item.key == name) | (Item.name == name)))
        if action == 'reset_all_items':
            items = []
            for i in STANDARD_ITEMS:
                items.append(Item(name=i['name'],
                                  description=i['description'],
                                  key=i['key'],
                                  price=i['price'],
                                  limit=i['limit'],
                                  cd=i['cd'],
                                  prim=i['prim'],
                                  lvl=i['lvl'],
                                  ))
            for entry in items:
                await session.merge(entry)
            await session.commit()
        elif action == 'get_all':
            items = await session.scalars(select(Item))
            items_list = items.all()
            return items_list
        elif action == 'get_one':
            item = await session.scalar(select(Item).where(Item.key == name))
            if not item:
                return None
            return {'name': item.name, 'description': item.description, 'key': item.key, 'price': item.price, 'duration': item.duration, 'available': item.enabled and (not item.available_until or time.time() < item.available_until)}
        elif action == 'add':
            session.add(Item(
                name=name,
                description=description,
                key=key,
                price=price,
                limit=limit,
                cd=cd,
                prim=prim,
                lvl=lvl,
            ))
            await session.commit()

        elif action == 'bought':
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if not user or not item:
                return None
            configs = (await session.scalars(select(Item))).all()
            refresh_items(user, configs, time.time())
            if item.key in user.items:
                return None
            user.items[item.key] = time.time()
            refresh_items(user, configs, time.time())

        elif action == 'reset_users':
            users = await session.scalars(select(User))
            configs = (await session.scalars(select(Item))).all()
            now = time.time()
            notices = []
            for user in users:
                expired = refresh_items(user, configs, now)
                notices.extend((user.tg_id, name) for name in expired)
            await session.commit()
            if bot:
                from aiogram.exceptions import TelegramAPIError
                from html import escape
                for user_id, item_name in notices:
                    try:
                        await bot.send_message(user_id, f'⏰ <b>Усиление закончилось</b>\n\n{escape(item_name)} · срок действия истёк.\nПродлить: /buy', parse_mode='HTML')
                    except TelegramAPIError:
                        pass

        elif action == 'user_list':
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
            if not user:
                return []
            configs = (await session.scalars(select(Item))).all()
            refresh_items(user, configs, time.time())
            await session.commit()
            return list(user.items.keys())

        await session.commit()
        return None

    return await execute_db_operation(operation, write=False)


async def get_items() -> list:
    return await manage_items('get_all')


async def get_item(key) -> dict:
    return await manage_items('get_one', name=key)


async def bought_item(tg_id: int, item: str) -> None:
    await manage_items('bought', tg_id, item)


async def user_items(tg_id: int) -> list:
    return await manage_items('user_list', tg_id) or []


async def reset_users_items(bot) -> None:
    while True:
        try:
            await manage_items('reset_users', bot=bot)
        except Exception:
            import logging
            logging.exception('Не удалось обновить сроки предметов')
        await asyncio.sleep(300)  # Проверка каждые 5 минут


async def manage_promo(action: str, name: str = None, limit: int = None, promo_xp: int = None, tg_id: int = None,
                       promo: str = None) -> str | None:
    async def operation(session):
        if action == 'add':
            if await session.scalar(select(Code).where(Code.name == name)): return None
            code = Code(name=name, limit=limit, activations=0, xp=promo_xp, users=[])
            session.add(code)
            await session.commit()
            return None

        elif action == 'use':
            if promo == 'empty': return '❌ Промокод не может быть пустым'
            code = await session.scalar(select(Code).where(Code.name == promo))
            user = await session.scalar(select(User).where(User.tg_id == tg_id))
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


async def add_promo(name: str, limit: int, xp: int) -> None:
    await manage_promo('add', name=name.upper(), limit=limit, promo_xp=xp)


async def use_promo(tg_id: int, promo: str) -> str:
    return await manage_promo('use', tg_id=tg_id, promo=promo) or '❌ Ошибка активации промокода'


def refresh_items(user, configs, now):
    """Поддерживает старые ключи по названию и пересчитывает эффекты."""
    by_key = {key: item for item in configs for key in (item.key, item.name)}
    active = {}
    expired = []
    for key, purchased in user.items.items():
        item = by_key.get(key)
        duration = item.duration if item else 86400
        if purchased <= 0 or now - purchased >= duration:
            expired.append(item.name if item else key)
        elif item:
            active[item.key] = max(active.get(item.key, 0), purchased)
    user.items = active
    user.cd_items = sum(by_key[key].cd for key in active)
    user.prim_items = sum(by_key[key].prim for key in active)
    user.lvl_items = sum(by_key[key].lvl for key in active)
    return expired


async def fulfill_payment(user_id, payment):
    """Повторная доставка платежа не выдаёт усиление второй раз."""
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
        # Два оплаченных счёта на один товар продлевают срок, сохраняя одну копию эффекта.
        if item.key in user.items:
            user.items[item.key] += item.duration
        else:
            user.items[item.key] = now
        refresh_items(user, configs, now)
        session.add(Payment(charge_id=payment.telegram_payment_charge_id, user_id=user_id,
                            item_key=item.key, amount=payment.total_amount))
        await session.commit()
        return True
