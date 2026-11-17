"""Ограничения частоты и кеши в памяти процесса."""
import time
from collections import OrderedDict, deque


class RateLimiter:
    """Не более `limit` событий за `window` секунд на ключ."""

    def __init__(self, limit: int, window: float, max_keys: int = 50000):
        self.limit, self.window, self.max_keys = limit, window, max_keys
        self._hits: OrderedDict = OrderedDict()

    def hit(self, key) -> float:
        """Регистрирует попытку. Возвращает 0, если разрешено, иначе секунды до разблокировки."""
        now = time.monotonic()
        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
        self._hits.move_to_end(key)
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return self.window - (now - hits[0])
        hits.append(now)
        return 0

    def reset(self):
        self._hits.clear()


class TTLCache:
    """Небольшой кеш с временем жизни записей и ограничением размера."""

    def __init__(self, ttl: float, max_size: int = 50000):
        self.ttl, self.max_size = ttl, max_size
        self._data: OrderedDict = OrderedDict()

    def get(self, key, default=None):
        entry = self._data.get(key)
        if entry is None or entry[0] < time.monotonic():
            self._data.pop(key, None)
            return default
        return entry[1]

    def set(self, key, value):
        self._data[key] = (time.monotonic() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def pop(self, key):
        self._data.pop(key, None)

    def clear(self):
        self._data.clear()


# /promo: 5 попыток за 10 минут защищают короткие коды от перебора.
promo_limiter = RateLimiter(limit=5, window=600)
# /paysupport: 3 обращения в час.
support_limiter = RateLimiter(limit=3, window=3600)
