"""
_tk_compat.py
Tkinter compatibility layer replacing PySide6/Qt signal-slot and threading patterns.
Provides thread-safe signal emission via a queue polled by the main window's after() loop.
"""
import queue
import threading

# Global queue: worker threads put (callback, args) tuples here;
# the main window drains it in its after() polling loop.
_signal_queue = queue.Queue()


class Signal:
    """Mimics a Qt Signal.  connect() registers callbacks; emit() posts them
    to the global queue so the main thread can dispatch them safely."""

    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def disconnect(self, callback=None):
        if callback is None:
            self._callbacks.clear()
        elif callback in self._callbacks:
            self._callbacks.remove(callback)

    def emit(self, *args):
        for cb in self._callbacks:
            _signal_queue.put((cb, args))


class WorkerSignals:
    """Mimics Qt WorkerSignals used by the three worker classes."""
    def __init__(self):
        self.finished      = Signal()
        self.progressEvent = Signal()
        self.errorEvent    = Signal()


# Qt flag constants referenced in data2bids_main.py (kept as no-ops)
class _QtFlags:
    AlignCenter        = 0
    Checked            = 2
    Unchecked          = 0
    ItemIsSelectable   = 1
    ItemIsUserCheckable = 4
    RichText           = 1

QtFlags = _QtFlags()
