"""In-memory seat holds for one event."""

import threading


class SeatMap:
    """Tracks which seats are held and by whom; every method is safe to call from many threads."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._held: dict[str, str] = {}
        self._lock = threading.Lock()

    def hold(self, seat: str, owner: str) -> bool:
        """Hold one seat for an owner; return False when it is taken or the event is full."""
        with self._lock:
            if seat in self._held or len(self._held) >= self._capacity:
                return False
            self._held[seat] = owner
            return True

    def release(self, seat: str, owner: str) -> bool:
        """Release a seat; only the owner that holds it can release it."""
        with self._lock:
            if self._held.get(seat) != owner:
                return False
            del self._held[seat]
            return True

    def holder(self, seat: str) -> str | None:
        with self._lock:
            return self._held.get(seat)
