"""Антиспам: не чаще одной команды или нажатия кнопки за интервал на пользователя."""
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import ADMIN_IDS

COMMAND_INTERVAL = 1.5


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, interval: float = COMMAND_INTERVAL, max_users: int = 50000):
        self.interval, self.max_users = interval, max_users
        self._last: dict[tuple[str, int], float] = {}

    def _allowed(self, kind: str, user_id: int) -> bool:
        now = time.monotonic()
        key = (kind, user_id)
        if now - self._last.get(key, -self.interval) < self.interval:
            return False
        if len(self._last) >= self.max_users:
            self._last = {k: t for k, t in self._last.items() if now - t < self.interval}
        self._last[key] = now
        return True

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, 'from_user', None)
        if user is None or user.id in ADMIN_IDS:
            return await handler(event, data)
        if isinstance(event, Message):
            # Оплаты, ответы мастерам и прочие не-команды не ограничиваем.
            if (event.text or '').startswith('/') and not self._allowed('message', user.id):
                return None
        elif isinstance(event, CallbackQuery):
            if not self._allowed('callback', user.id):
                await event.answer('Не так быстро 🙂')
                return None
        return await handler(event, data)
