from collections import OrderedDict
from typing import Optional

class LRUCache:
    """Simple LRU Cache implementation"""
    def __init__(self, capacity: int = 1000):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key: str) -> Optional[str]:
        if key not in self.cache:
            return None
        # Move to end to mark as recently used
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: str):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            # Remove oldest item
            self.cache.popitem(last=False)

    def clear(self):
        self.cache.clear()

    def size(self) -> int:
        return len(self.cache)
