from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    type: str
    payload: dict[str, Any]
    sequence: int


class EventBus:
    def __init__(self, *, backlog_size: int = 200, subscriber_queue_size: int = 100):
        self.backlog_size = backlog_size
        self.subscriber_queue_size = subscriber_queue_size
        self._lock = threading.Lock()
        self._sequence = 0
        self._backlog: deque[Event] = deque(maxlen=backlog_size)
        self._subscribers: list[queue.Queue[Event]] = []

    def publish(self, event_type: str, payload: dict[str, Any]) -> Event:
        with self._lock:
            self._sequence += 1
            event = Event(event_type, payload, self._sequence)
            self._backlog.append(event)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(event)
                except queue.Full:
                    pass
        return event

    def subscribe(self) -> queue.Queue[Event]:
        subscriber: queue.Queue[Event] = queue.Queue(maxsize=self.subscriber_queue_size)
        with self._lock:
            self._subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[Event]) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)
