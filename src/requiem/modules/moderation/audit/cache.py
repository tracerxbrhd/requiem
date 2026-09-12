import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class TTLCache[K, V]:
    def __init__(self, limit: int, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.ttl, self.clock = limit, ttl, clock
        self.items: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def expire(self) -> None:
        now = self.clock()
        while self.items and next(iter(self.items.values()))[0] <= now:
            self.items.popitem(last=False)

    def put(self, key: K, value: V) -> None:
        self.expire()
        self.items.pop(key, None)
        self.items[key] = (self.clock() + self.ttl, value)
        while len(self.items) > self.limit:
            self.items.popitem(last=False)

    def get(self, key: K) -> V | None:
        self.expire()
        entry = self.items.get(key)
        return entry[1] if entry else None

    def pop(self, key: K) -> V | None:
        value = self.get(key)
        self.items.pop(key, None)
        return value


EchoKey = tuple[int, str, int]


class EchoSuppressor:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.cache: TTLCache[EchoKey, object] = TTLCache(10000, 30, clock)

    @contextmanager
    def expect(self, keys: tuple[EchoKey, ...]) -> Iterator[None]:
        token = object()
        for key in keys:
            self.cache.put(key, token)
        try:
            yield
        except BaseException:
            for key in keys:
                if self.cache.get(key) is token:
                    self.cache.pop(key)
            raise

    def consume(self, key: EchoKey) -> bool:
        return self.cache.pop(key) is not None
