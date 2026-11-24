"""Log yang bisa diarahkan ke job web (per-thread) atau ke stderr."""
import sys
import threading

_local = threading.local()


def set_sink(fn):
    _local.sink = fn


def log(msg):
    sink = getattr(_local, "sink", None)
    if sink:
        sink(str(msg))
    else:
        print(msg, file=sys.stderr)
