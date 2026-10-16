"""Long-lived compute session shared by consecutive pipeline runs.

``CarverSession`` keeps the CUDA context alive (the daemon holds one for its
whole lifetime) and caches values that are expensive to rebuild, such as
voxel grids and the Tregenza patch directions and solid angles.  Compiled Warp kernels are cached
by Warp itself, on disk.

Cache keys must describe everything the cached value depends on, including
the device it lives on, so an entry can be reused by any later run.  The
cache holds at most ``max_cache_bytes`` of arrays and tensors and drops the
least recently used entries beyond that; ``bump()`` clears it.

Public API:
    CarverSession       context manager owning the cache
    get_active_session  the session registered for a device, if any
    session_cache       decorator caching a function's result in the session
"""

import contextlib
import functools
import logging
import weakref
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Union

import torch

from .compute_device import resolve_compute_device

_log = logging.getLogger(__name__)


DEFAULT_CACHE_BYTES = 1 << 30  # 1 GiB


def _nbytes(value: Any) -> int:
    """Memory held by the tensors and arrays in *value* (nested tuples, lists, dicts)."""
    if isinstance(value, torch.Tensor):
        return value.element_size() * value.nelement()
    if hasattr(value, "nbytes") and not isinstance(value, (str, bytes)):
        return int(value.nbytes)
    if isinstance(value, (tuple, list)):
        return sum(_nbytes(v) for v in value)
    if isinstance(value, dict):
        return sum(_nbytes(v) for v in value.values())
    return 0


def _device_key(device: torch.device) -> int:
    """Registry key: CUDA index (``cuda`` means ``cuda:0``) or -1 for CPU."""
    if device.type == "cuda":
        return device.index if device.index is not None else 0
    return -1


class CarverSession(contextlib.AbstractContextManager["CarverSession"]):
    """A compute session with a value cache, registered per device.

    Creating a session registers it as the active one for its device
    (replacing any earlier one); leaving its ``with`` block, or ``close()``,
    clears the cache and unregisters it.
    """

    _sessions: "weakref.WeakValueDictionary[int, CarverSession]" = weakref.WeakValueDictionary()

    def __init__(self, device: Union[str, torch.device, None] = None,
                 max_cache_bytes: int = DEFAULT_CACHE_BYTES):
        """*device*: "auto" or None (CUDA if available, else CPU), "cpu",
        "cuda", "cuda:N" or a torch.device, resolved by
        :func:`~urbansolarcarver.compute_device.resolve_compute_device`.

        *max_cache_bytes*: memory the cache may hold; a value larger than this
        on its own is returned but not cached.
        """
        self.device = resolve_compute_device(device)

        self.max_cache_bytes = int(max_cache_bytes)
        self.tensors: "OrderedDict[str, Any]" = OrderedDict()  # oldest use first
        self._sizes: Dict[str, int] = {}
        self.cache_bytes = 0
        self._gen = 0  # number of bump() calls, for diagnostics
        CarverSession._sessions[_device_key(self.device)] = self

    def bump(self, flush: bool = False) -> None:
        """Clear the cache; *flush* also returns unused CUDA memory to the driver."""
        self.tensors.clear()
        self._sizes.clear()
        self.cache_bytes = 0
        if flush:
            self.release_memory()
        self._gen += 1

    def release_memory(self) -> None:
        """Return CUDA memory not held by live tensors (including cached ones) to the driver."""
        if self.device.type == "cuda":
            torch.cuda.empty_cache()

    def __enter__(self) -> "CarverSession":
        if self.device.type == "cuda":
            torch.cuda.init()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False

    def get_tensor(self, key: str, factory: Callable[[], Any]) -> Any:
        """Return the cached value for *key*, computing it with *factory* on a miss.

        The value is stored as returned, so callers must not modify it in
        place, and the key must identify its device.  Storing it may drop the
        least recently used entries to stay within ``max_cache_bytes``.
        """
        if key in self.tensors:
            self.tensors.move_to_end(key)
            return self.tensors[key]
        value = factory()
        size = _nbytes(value)
        if size > self.max_cache_bytes:
            return value
        self.tensors[key] = value
        self._sizes[key] = size
        self.cache_bytes += size
        while self.cache_bytes > self.max_cache_bytes:
            old_key, _ = self.tensors.popitem(last=False)
            self.cache_bytes -= self._sizes.pop(old_key)
        return value

    def close(self, flush: bool = True) -> None:
        """Clear the cache and stop being the active session for this device."""
        self.bump(flush=flush)
        key = _device_key(self.device)
        if CarverSession._sessions.get(key) is self:
            del CarverSession._sessions[key]


def get_active_session(device: Union[str, torch.device, None] = None) -> Optional[CarverSession]:
    """The session registered for *device*, or None.

    With no device (or "auto"), a single registered session is returned
    whatever its device; otherwise the session for the default device.
    """
    if device is None or (isinstance(device, str) and device == "auto"):
        if len(CarverSession._sessions) == 1:
            return next(iter(CarverSession._sessions.values()))
        dev = resolve_compute_device(None)
    else:
        dev = resolve_compute_device(device)
    return CarverSession._sessions.get(_device_key(dev))


def session_cache(key: Union[str, Callable[..., str]]):
    """Cache a function's return value in the active session.

    *key* is a format string over ``args`` and ``kwargs`` (e.g.
    ``"{args[0]}"`` for a device passed positionally) or a callable
    ``key(args, kwargs) -> str`` for keys that need computing (e.g. a hash of
    mesh contents).  The function name is prefixed to the key.  The key must
    cover everything the result depends on, including its device.

    The wrapped function accepts an extra ``session=`` keyword; otherwise the
    active session is used.  Without a session the function simply runs, and
    if the key cannot be formatted from the call's arguments it runs
    uncached, with a one-time log warning.
    """
    def decorator(fn):
        warned = False

        @functools.wraps(fn)
        def wrapper(*args, session: "CarverSession | None" = None, **kw):
            nonlocal warned
            sess = session or get_active_session()
            if sess is None:
                return fn(*args, **kw)
            try:
                cache_key = key(args, kw) if callable(key) else key.format(args=args, kwargs=kw)
            except (KeyError, IndexError, AttributeError, ValueError):
                if not warned:
                    _log.warning(
                        "session_cache: key %r does not match how %s was called; "
                        "running uncached (shown once).", key, fn.__name__,
                    )
                    warned = True
                return fn(*args, **kw)
            return sess.get_tensor(f"{fn.__name__}:{cache_key}", lambda: fn(*args, **kw))
        return wrapper
    return decorator
