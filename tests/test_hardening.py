import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///:memory:'
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetChatMember
from database.base import Base, engine, base_run, add_items, add_objects, add_levels, async_session, User
import database.requests as rq
import bot.common as common
from bot.limits import RateLimiter, promo_limiter, support_limiter


def tg_user(user_id=123, name='Tester'):
    return SimpleNamespace(id=user_id, first_name=name, full_name=name, username=None)


def fake_message(chat_type='private', text='', user=None):
    bot = SimpleNamespace(refund_star_payment=AsyncMock(), send_message=AsyncMock(),
                          get_chat_member=AsyncMock(), me=AsyncMock(return_value=SimpleNamespace(username='testbot')))
    return SimpleNamespace(chat=SimpleNamespace(id=-100 if chat_type != 'private' else 123, type=chat_type, title='Chat'),
                           from_user=user or tg_user(), text=text, bot=bot,
                           answer=AsyncMock(), reply=AsyncMock(), delete=AsyncMock())


def payment(charge='c1', key='boltorez', amount=20):
    return SimpleNamespace(telegram_payment_charge_id=charge, invoice_payload=key,
                           currency='XTR', total_amount=amount)


class HardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await base_run()
        await add_items()
        await add_objects()
        await add_levels()
        await rq.set_user(123, 'Tester')
        promo_limiter.reset()
        support_limiter.reset()
        common.invalidate_channels()
        common._admin_alerts.clear()
        common._known_users.clear()

    # 1. Оплата, которую нельзя выдать, возвращается
    async def test_failed_fulfillment_is_refunded(self):
        from bot.routers.shop import successful_payment
        message = fake_message()
        message.successful_payment = payment(amount=1)  # сумма не совпадает с ценой
        with patch('bot.routers.shop.notify_admins', AsyncMock()) as notify:
            await successful_payment(message)
        message.bot.refund_star_payment.assert_awaited_once_with(user_id=123, telegram_payment_charge_id='c1')
        self.assertIn('возвращены', message.answer.call_args.args[0])
        notify.assert_awaited_once()
        self.assertEqual(await rq.user_items(123), {})

    # Продление
    async def test_owned_item_can_be_extended(self):
        from bot.routers.shop import pre_checkout_query
        first = await rq.fulfill_payment(123, payment('c1'))
        pcq = SimpleNamespace(invoice_payload='boltorez', from_user=tg_user(), currency='XTR',
                              total_amount=20, answer=AsyncMock())
        await pre_checkout_query(pcq)
        self.assertTrue(pcq.answer.call_args.kwargs['ok'])
        second = await rq.fulfill_payment(123, payment('c2'))
        self.assertAlmostEqual(second - first, 86400)
        self.assertEqual((await rq.get_user_info(123))['cd_items'], -600)
        self.assertAlmostEqual((await rq.user_items(123))['boltorez'], second)

    async def test_revoke_payment_removes_paid_time(self):
        await rq.fulfill_payment(123, payment('c1'))
        await rq.fulfill_payment(123, payment('c2'))
        self.assertTrue(await rq.revoke_payment('c2'))
        self.assertFalse(await rq.revoke_payment('c2'))
        self.assertTrue((await rq.get_payment('c2'))['refunded'])
        self.assertAlmostEqual((await rq.user_items(123))['boltorez'] - time.time(), 86400, delta=5)
        self.assertTrue(await rq.revoke_payment('c1'))
        self.assertEqual(await rq.user_items(123), {})
        self.assertEqual((await rq.get_user_info(123))['cd_items'], 0)

    # 2. /paysupport
    async def test_paysupport_forwards_to_admins(self):
        from bot.routers.shop import pay_support
        await rq.fulfill_payment(123, payment('charge-xyz'))
        message = fake_message()
        with patch('bot.routers.shop.notify_admins', AsyncMock()) as notify:
            await pay_support(message, SimpleNamespace(args=None))
            notify.assert_not_awaited()
            await pay_support(message, SimpleNamespace(args='не пришёл <b>болторез</b>'))
        text = notify.call_args.args[1]
        self.assertIn('charge-xyz', text)
        self.assertIn('&lt;b&gt;', text)

    # 3. Промокоды не активируются в группе
    async def test_promo_in_group_is_hidden_and_not_activated(self):
        from bot.routers.game import promo_use
        await rq.add_promo('SECRET1', 5, 100)
        message = fake_message('supergroup', '/promo SECRET1')
        await promo_use(message, SimpleNamespace(args='SECRET1'))
        message.delete.assert_awaited_once()
        self.assertEqual((await rq.get_user_info(123))['xp'], 0)

    async def test_promo_in_private_works(self):
        from bot.routers.game import promo_use
        await rq.add_promo('SECRET1', 5, 100)
        message = fake_message('private')
        with patch('bot.routers.game.check_prerequisites', AsyncMock(return_value=True)):
            await promo_use(message, SimpleNamespace(args='secret1'))
        self.assertEqual((await rq.get_user_info(123))['xp'], 100)

    # 4. Перебор промокодов
    async def test_promo_bruteforce_is_limited(self):
        from bot.routers.game import promo_use
        await rq.add_promo('SECRET1', 5, 100)
        message = fake_message('private')
        with patch('bot.routers.game.check_prerequisites', AsyncMock(return_value=True)):
            for guess in ('AAAAAA', 'BBBBBB', 'CCCCCC', 'DDDDDD', 'EEEEEE'):
                await promo_use(message, SimpleNamespace(args=guess))
            await promo_use(message, SimpleNamespace(args='SECRET1'))
        self.assertIn('Слишком много попыток', message.reply.call_args.args[0])
        self.assertEqual((await rq.get_user_info(123))['xp'], 0)

    def test_promo_minimum_length(self):
        from bot.routers.panel import parse_management
        with self.assertRaises(ValueError):
            parse_management('promo', 'name', 'ABC')
        self.assertEqual(parse_management('promo', 'name', 'abcdef'), 'ABCDEF')

    def test_rate_limiter_window(self):
        limiter = RateLimiter(limit=2, window=60)
        self.assertEqual(limiter.hit(1), 0)
        self.assertEqual(limiter.hit(1), 0)
        self.assertGreater(limiter.hit(1), 0)
        self.assertEqual(limiter.hit(2), 0)

    # 5. Антиспам и кеши
    async def test_throttling_middleware(self):
        from aiogram.types import Message, Chat, User as TgUser
        from bot.middlewares import ThrottlingMiddleware
        middleware = ThrottlingMiddleware(interval=60)
        handler = AsyncMock()

        def msg(text):
            return Message(message_id=1, date=0, chat=Chat(id=-1, type='group'), text=text,
                           from_user=TgUser(id=555, is_bot=False, first_name='Spam'))
        await middleware(handler, msg('/me'), {})
        await middleware(handler, msg('/me'), {})
        await middleware(handler, msg('просто текст'), {})
        self.assertEqual(handler.await_count, 2)

    async def test_known_user_is_written_once(self):
        with patch('bot.common.rq.set_user', AsyncMock()) as set_user:
            for _ in range(3):
                await common.ensure_user(tg_user())
            await common.ensure_user(tg_user(name='Renamed'))
        self.assertEqual(set_user.await_count, 2)

    async def test_subscription_is_cached(self):
        await rq.add_channel(-1001, 'Канал', 'https://t.me/x')
        message = fake_message('supergroup')
        message.bot.get_chat_member.return_value = SimpleNamespace(status='member', is_member=True)
        for _ in range(3):
            self.assertTrue(await common.check_prerequisites(message))
        self.assertEqual(message.bot.get_chat_member.await_count, 1)

    async def test_unsubscribed_user_is_blocked(self):
        await rq.add_channel(-1001, 'Канал', 'https://t.me/x')
        message = fake_message('supergroup')
        message.bot.get_chat_member.return_value = SimpleNamespace(status='left', is_member=False)
        self.assertFalse(await common.check_prerequisites(message))

    # 6. Потерян доступ к каналу: игра работает, админ получает одно уведомление
    async def test_broken_channel_alerts_admins_once(self):
        await rq.add_channel(-1001, 'Канал', 'https://t.me/x')
        message = fake_message('supergroup')
        message.bot.get_chat_member.side_effect = TelegramBadRequest(
            method=GetChatMember(chat_id=-1001, user_id=123), message='chat not found')
        with patch('bot.common.notify_admins', AsyncMock()) as notify:
            for _ in range(5):
                self.assertTrue(await common.check_prerequisites(message))
        notify.assert_awaited_once()

    # 11. /level и /buy проверяют условия
    async def test_level_requires_group(self):
        from bot.routers.game import command_level
        message = fake_message('private')
        with patch('bot.routers.game.rq.able_to_update', AsyncMock()) as able:
            await command_level(message)
        able.assert_not_awaited()

    async def test_buy_checks_subscription(self):
        from bot.routers.shop import command_buy
        message = fake_message('private')
        with patch('bot.routers.shop.check_prerequisites', AsyncMock(return_value=False)) as check:
            await command_buy(message)
        self.assertTrue(check.call_args.kwargs['allow_private'])
        message.reply.assert_not_awaited()

    # 12. Фоновая задача видит только игроков с усилениями
    async def test_expire_items_only_touches_inventories(self):
        await rq.set_user(456, 'Empty')
        await rq.fulfill_payment(123, payment('c1'))
        async with async_session() as session:
            (await session.get(User, 123)).items = {'boltorez': 1}
            await session.commit()
        notices = await rq.expire_items()
        self.assertEqual(notices, [(123, 'болторез')])
        self.assertEqual(await rq.expire_items(), [])
        self.assertEqual((await rq.get_user_info(123))['cd_items'], 0)
