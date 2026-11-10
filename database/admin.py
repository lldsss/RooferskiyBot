import time
import uuid
from sqlalchemy import select, text, func
from database.base import async_session, Item, User, Chat, Code


async def create_item(data):
    async with async_session() as session:
        await session.execute(text('BEGIN IMMEDIATE'))
        if await session.get(Item, data['name']):
            return False
        values = dict(data)
        hours = values.pop('sale_hours')
        session.add(Item(**values, key=uuid.uuid4().hex,
                         available_until=time.time() + hours * 3600 if hours else 0))
        await session.commit()
        return True


async def toggle_item(key):
    async with async_session() as session:
        await session.execute(text('BEGIN IMMEDIATE'))
        item = await session.scalar(select(Item).where(Item.key == key))
        if item:
            item.enabled = not item.enabled
            await session.commit()


async def summary():
    async with async_session() as session:
        return {label: await session.scalar(select(func.count()).select_from(model))
                for label, model in [('Игроки', User), ('Чаты', Chat), ('Предметы', Item), ('Промокоды', Code)]}


async def create_promo(data):
    async with async_session() as session:
        await session.execute(text('BEGIN IMMEDIATE'))
        if await session.get(Code, data['name']):
            return False
        session.add(Code(**data, activations=0, users=[]))
        await session.commit()
        return True


async def remove_channel(channel_id):
    from database.base import Channel
    async with async_session() as session:
        channel = await session.get(Channel, channel_id)
        if channel:
            await session.delete(channel)
            await session.commit()
