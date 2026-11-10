import os
import unittest
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///:memory:'
from database.base import Base, engine, base_run, add_items, add_levels, add_objects, async_session, User
import database.requests as rq
from bot.services import roof
from bot.messages import profile, cooldown


class GameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await base_run()
        await add_items()
        await add_objects()
        await add_levels()
        await rq.set_user(123, 'Tester')

    async def test_purchase_and_expiry(self):
        await rq.bought_item(123, 'boltorez')
        await rq.bought_item(123, 'boltorez')
        self.assertEqual((await rq.get_user_info(123))['cd_items'], -600)
        async with async_session() as session:
            user = await session.get(User, 123)
            user.items = {'boltorez': 1}
            await session.commit()
        await rq.manage_items('reset_users')
        self.assertEqual((await rq.get_user_info(123))['cd_items'], 0)

    async def test_roof_cooldown_and_inactive_event(self):
        await rq.set_event('lvl_event', 10000)
        remaining, result = await roof(123)
        self.assertIsNotNone(result)
        self.assertEqual((await rq.get_user_info(123))['xp'], result['xp'])
        remaining, result = await roof(123)
        self.assertGreater(remaining, 0)
        self.assertIsNone(result)

    async def test_promo_once_and_level_guard(self):
        await rq.add_promo('test', 1, 100)
        await rq.use_promo(123, 'TEST')
        await rq.use_promo(123, 'TEST')
        self.assertEqual((await rq.get_user_info(123))['xp'], 100)
        self.assertFalse(await rq.update_level(123))

    async def test_seed_preserves_data(self):
        await add_items()
        self.assertEqual(len(await rq.get_items()), 6)

    def test_formatting(self):
        self.assertIn('&lt;', profile('<name>', {'level': 0, 'xp': 5}))
        self.assertIn('1 с', cooldown(.1))

    async def test_temporary_item_lifecycle(self):
        import time
        from database.admin import create_item, toggle_item
        from database.base import Item
        from sqlalchemy import select
        from bot.keyboards import shop
        data = dict(name='Тестовый', description='Тест', price=5, cd=-60,
                    prim=-0.1, lvl=1, duration=3600, sale_hours=1)
        self.assertTrue(await create_item(data))
        self.assertFalse(await create_item(data))
        item = next(i for i in await rq.get_items() if i.name == 'Тестовый')
        self.assertTrue((await rq.get_item(item.key))['available'])
        await rq.bought_item(123, item.key)
        async with async_session() as session:
            row = await session.get(Item, item.name)
            row.available_until = time.time() - 1
            user = await session.get(User, 123)
            user.items = {item.key: time.time() - 1800}
            await session.commit()
        self.assertFalse((await rq.get_item(item.key))['available'])
        self.assertNotIn('buy_' + item.key, [b.callback_data for row in (await shop()).inline_keyboard for b in row])
        await rq.manage_items('reset_users')
        self.assertIn(item.key, await rq.user_items(123))
        async with async_session() as session:
            user = await session.get(User, 123)
            user.items = {item.key: time.time() - 3601}
            await session.commit()
        await rq.manage_items('reset_users')
        self.assertNotIn(item.key, await rq.user_items(123))
        self.assertEqual((await rq.get_user_info(123))['cd_items'], 0)

    def test_admin_validation(self):
        from bot.routers.panel import parse_value
        self.assertEqual(parse_value('cd', '10'), -600)
        self.assertEqual(parse_value('prim', '20'), -0.2)
        self.assertEqual(parse_value('duration', '2'), 7200)
        for field, value in [('price', '0'), ('sale_hours', '-1'), ('name', ''), ('lvl', '11')]:
            with self.assertRaises(ValueError):
                parse_value(field, value)

    async def test_inline_admin_channel_and_promo(self):
        from database.admin import create_promo, remove_channel
        from bot.routers.panel import parse_management
        self.assertEqual(parse_management('promo', 'name', 'roof_10'), 'ROOF_10')
        for kind, field, value in [('channel', 'tg_id', '123'), ('channel', 'link', 'https://example.com'), ('promo', 'name', '<bad>'), ('promo', 'limit', '0')]:
            with self.assertRaises(ValueError):
                parse_management(kind, field, value)
        channel = dict(tg_id=-1001234567890, name='Канал', link='https://t.me/test')
        await rq.add_channel(**channel)
        await rq.add_channel(**dict(channel, name='Обновлён'))
        self.assertEqual(len(await rq.get_channels()), 1)
        self.assertEqual((await rq.get_channels())[0]['name'], 'Обновлён')
        await remove_channel(channel['tg_id'])
        self.assertEqual(await rq.get_channels(), [])
        promo = dict(name='ROOF_10', limit=2, xp=10)
        self.assertTrue(await create_promo(promo))
        self.assertFalse(await create_promo(promo))
        await rq.use_promo(123, 'ROOF_10')
        self.assertEqual((await rq.get_user_info(123))['xp'], 10)

    async def test_inline_wizard_confirmation_and_cancel(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        from aiogram.fsm.storage.memory import MemoryStorage
        from aiogram.fsm.storage.base import StorageKey
        from aiogram.fsm.context import FSMContext
        from bot.routers.panel import panel_action, management_value, Management
        storage = MemoryStorage()
        state = FSMContext(storage, StorageKey(bot_id=1, chat_id=1, user_id=1))
        message = SimpleNamespace(answer=AsyncMock(), text='INLINE')
        callback = SimpleNamespace(answer=AsyncMock(), data='admin_promo_new', message=message)
        await panel_action(callback, state)
        self.assertEqual(await state.get_state(), Management.value.state)
        for value in ('INLINE', '5', '25'):
            message.text = value
            await management_value(message, state)
        self.assertEqual(await state.get_state(), Management.confirm.state)
        callback.data = 'admin_manage_save'
        await panel_action(callback, state)
        self.assertIsNone(await state.get_state())
        await rq.use_promo(123, 'INLINE')
        self.assertEqual((await rq.get_user_info(123))['xp'], 25)
        callback.data = 'admin_channel_new'
        await panel_action(callback, state)
        callback.data = 'admin_cancel'
        await panel_action(callback, state)
        self.assertIsNone(await state.get_state())
        self.assertEqual(await state.get_data(), {})
        await storage.close()
