"""Игровые операции: результат и награда сохраняются одной транзакцией."""
import random
import time
from sqlalchemy import select, text
from bot.config import COOLDOWN, TEST_ID
from database.base import async_session, User, Event, Object, Level


async def roof(user_id):
    async with async_session() as session:
        await session.execute(text('BEGIN IMMEDIATE'))
        user = await session.get(User, user_id)
        event = await session.scalar(select(Event).where(Event.activated.is_(True)))
        now = time.time()
        remaining = max(600, COOLDOWN + (event.cd_event if event else 0)
                        - user.cd_lvl + user.cd_items) - (now - user.last_roof_time)
        if remaining > 0 and user_id != TEST_ID:
            return remaining, None
        level = user.level + user.lvl_items + (event.lvl_event if event else 0)
        objects = (await session.scalars(select(Object).where(Object.last_level > level))).all()
        if not objects:
            return 0, None
        obj = random.choices(objects, weights=[1 / max(1, o.floors) ** 2 for o in objects])[0]
        risk = max(0, min(1, obj.prim - user.prim_lvl + user.prim_items + (event.prim_event if event else 0)))
        success = random.random() > risk
        xp = round(obj.floors * obj.prim) if success else -round(obj.floors * (1 - obj.prim) / 2)
        requirement = await session.get(Level, user.level + 1)
        if success and requirement and requirement.object == obj.name:
            user.object_status = True
        user.xp = user.xp + xp if user_id != TEST_ID else 0
        user.last_roof_time = now if user_id != TEST_ID else 0
        await session.commit()
        return 0, dict(name=obj.name, image=obj.image, status=success, xp=xp)
