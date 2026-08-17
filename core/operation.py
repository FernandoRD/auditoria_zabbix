"""Per-operation lifecycle and cooperative cancellation primitives."""

from dataclasses import dataclass, field
from enum import Enum
import threading
from typing import Callable, Optional, TypeVar
from uuid import uuid4


class OperationCancelled(Exception):
    """Raised when a running operation observes a cancellation request."""


class OperationState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETING = "completing"
    FINISHED = "finished"


_T = TypeVar("_T")


@dataclass
class OperationContext:
    """State owned by exactly one background operation.

    Contexts and their cancellation events are deliberately never reset or
    reused.  The small lock also makes publishing a report chunk atomic with
    respect to accepting a cancellation request.
    """

    id: str = field(default_factory=lambda: uuid4().hex)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    thread: Optional[threading.Thread] = field(default=None, repr=False)
    state: OperationState = OperationState.PENDING
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def attach_thread(self, thread: threading.Thread) -> None:
        with self._lock:
            if self.thread is not None:
                raise RuntimeError("A thread da operação já foi definida.")
            self.thread = thread

    def mark_running(self) -> None:
        with self._lock:
            if self.state is not OperationState.PENDING:
                raise RuntimeError("A operação não está pendente.")
            self.state = OperationState.RUNNING

    def request_cancel(self) -> bool:
        with self._lock:
            if self.state not in (OperationState.PENDING, OperationState.RUNNING):
                return False
            self.cancel_event.set()
            self.state = OperationState.CANCELLING
            return True

    def mark_finished(self) -> None:
        with self._lock:
            self.state = OperationState.FINISHED

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise OperationCancelled("Operação cancelada pelo usuário.")

    def run_if_active(self, callback: Callable[[], _T]) -> bool:
        """Run callback only while cancellation has not been accepted."""
        with self._lock:
            if self.cancel_event.is_set() or self.state is not OperationState.RUNNING:
                return False
            callback()
            return True

    def begin_completion(self) -> bool:
        """Linearize successful completion against a concurrent cancellation."""
        with self._lock:
            if self.cancel_event.is_set() or self.state is not OperationState.RUNNING:
                return False
            self.state = OperationState.COMPLETING
            return True
