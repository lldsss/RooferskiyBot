import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from database.base import Base, User, Item, Object, Level, add_objects
import database.requests as rq


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine('sqlite+aiosqlite:///' + str(Path(self.temp.name) / 'test.db'))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.patches = [patch('database.requests.async_session', self.sessions),
                        patch('database.base.async_session', self.sessions)]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        await self.engine.dispose()
        self.temp.cleanup()

    async def test_payment_and_inventory_refresh_keep_both_purchases(self):
        async with self.sessions() as session:
            session.add(User(tg_id=123, name='Tester'))
            for key in ('one', 'two'):
                session.add(Item(name=key, key=key, price=10, cd=-60))
            await session.commit()
        payments = [SimpleNamespace(telegram_payment_charge_id=key, invoice_payload=key,
                                    currency='XTR', total_amount=10) for key in ('one', 'two')]
        await asyncio.gather(*(rq.fulfill_payment(123, p) for p in payments),
                             *(rq.user_items(123) for _ in range(10)),
                             rq.manage_items('reset_users'))
        async with self.sessions() as session:
            user = await session.get(User, 123)
            self.assertEqual(set(user.items), {'one', 'two'})
            self.assertEqual(user.cd_items, -120)

    async def test_object_rename_preserves_settings_and_requirements(self):
        async with self.sessions() as session:
            session.add(Object(name='панельку-1', floors=99))
            session.add(Level(level=1, object='панельку-1'))
            await session.commit()
        await add_objects()
        await add_objects()
        async with self.sessions() as session:
            self.assertIsNone(await session.get(Object, 'панельку-1'))
            self.assertEqual((await session.get(Object, 'Панелька-1')).floors, 99)
            self.assertEqual((await session.get(Level, 1)).object, 'Панелька-1')
            names = list(await session.scalars(select(Object.name)))
            self.assertFalse(any('панельку-' in name for name in names))

    async def test_denied_callback_cannot_change_level(self):
        from bot.routers.game import level_up
        callback = SimpleNamespace(answer=AsyncMock(), from_user=SimpleNamespace(id=123))
        with patch('bot.routers.game.check_callback_prerequisites', AsyncMock(return_value=False)), \
             patch('bot.routers.game.rq.update_level', AsyncMock()) as update:
            await level_up(callback)
            update.assert_not_awaited()

    async def test_callback_checks_clicking_user(self):
        from aiogram.types import Message, User as TelegramUser, Chat
        from bot.common import check_callback_prerequisites
        message = Message(message_id=1, date=0, chat=Chat(id=-1, type='group'),
                          from_user=TelegramUser(id=999, is_bot=True, first_name='Bot'))
        callback = SimpleNamespace(message=message, from_user=TelegramUser(id=123, is_bot=False, first_name='Player'))
        with patch('bot.common.check_prerequisites', AsyncMock(return_value=True)) as check:
            self.assertTrue(await check_callback_prerequisites(callback))
            self.assertEqual(check.call_args.args[0].from_user.id, 123)
            self.assertEqual(message.from_user.id, 999)
