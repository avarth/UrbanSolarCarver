"""Long-lived compute session shared by consecutive pipeline runs.

``CarverSession`` keeps the CUDA context alive (the daemon holds one for its
whole lifetime) and caches values that are expensive to rebuild, such as
voxel grids and sky-patch weights.  Compiled Warp kernels are cached by Warp
itself, on disk.

Cache keys must describe everything the cached value depends on, including
the device it lives on; ``bump()`` clears the cache between independent runs.

Public API:
    CarverSession       context manager owning the cache
    get_active_session  the session registered for a device, if any
    session_cache       decorator caching a function's result in the session
"""

import contextlib
import functools
import logging
import weakref
from typing import Any, Callable, Dict, Optional, Union

import torch

_log = logging.getLogger(__name__)


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

    def __init__(self, device: Union[str, torch.device, None] = None):
        """*device*: "auto" or None (CUDA if available, else CPU), "cuda", "cpu", or a torch.device."""
        if device is None or (isinstance(device, str) and device.lower() == "auto"):
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        elif isinstance(device, str):
            if device.lower() not in ("cuda", "cpu"):
                raise ValueError(f"Unknown device preference: {device!r}")
            self.device = torch.device(device.lower())
        elif isinstance(device, torch.device):
            self.device = device
        else:
            raise TypeError(f"device must be str, torch.device, or None, not {type(device)}")

        self.tensors: Dict[str, Any] = {}
        self._gen = 0  # number of bump() calls, for diagnostics
        CarverSession._sessions[_device_key(self.device)] = self

    def bump(self, flush: bool = False) -> None:
        """Clear the cache between independent runs; *flush* also frees cached CUDA memory."""
        self.tensors.clear()
        if flush and self.device.type == "cuda":
            torch.cuda.empty_cache()
        self._gen += 1

    def __enter__(self) -> "CarverSession":
        if self.device.type == "cuda":
            torch.cuda.init()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False

    def get_tensor(self, key: str, factory: Callable[[], Any]) -> Any:
        """Return the cached value for *key*, computing it with *factory* on a miss.

        The value is stored as returned: the key must identify its device.
        """
        if key not in self.tensors:
            self.tensors[key] = factory()
        return self.tensors[key]

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
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        dev = torch.device(device)
    return CarverSession._sessions.get(_device_key(dev))


def session_cache(key: Union[str, Callable[..., str]]):
    """Cache a function's return value in the active session.

    *key* is a format string over ``args`` and ``kwargs`` (e.g.
    ``"tregenza_dirs:{args[0]}"``) or a callable ``key(args, kwargs) -> str``
    for keys that need computing (e.g. a hash of mesh contents).  The key
    must cover everything the result depends on, including its device.
    Without an active session the function simply runs.
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
