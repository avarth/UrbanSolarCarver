"""GPU/Warp session management for UrbanSolarCarver.

Provides CarverSession, a long-lived context manager that keeps a CUDA
(or CPU) context alive and caches tensors across multiple pipeline runs.
(Compiled Warp kernels are cached by Warp itself, per module, on disk.)
A weak-reference registry ensures at most one session per device index
exists at any time.

Key public API:
    CarverSession  -- context manager for device lifecycle and caching.
    session_cache  -- decorator that memoises tensor results on the
                      active session to avoid redundant GPU computation.
"""

import contextlib
import functools
import logging
import weakref
from typing import Optional, Union, Dict, Callable
from .load_config import user_config

import torch

_log = logging.getLogger(__name__)


def _device_key(device: torch.device) -> int:
    """Stable registry key: CUDA index (defaulting to 0) or -1 for CPU.

    ``torch.device("cuda")`` has ``.index == None`` while
    ``torch.device("cuda:0")`` has ``.index == 0``.  Both refer to the
    same GPU, so we normalise None → 0.
    """
    if device.type == "cuda":
        return device.index if device.index is not None else 0
    return -1

class CarverSession(contextlib.AbstractContextManager["CarverSession"]):
    """
    A long-lived GPU/Warp session that keeps the CUDA context alive
    and caches tensors across pipeline runs.

    Use this to avoid repeated GPU startup and recomputation overhead
    across multiple runs.
    """

    # Registry of live sessions, keyed by device index (-1 for CPU)
    _sessions: "weakref.WeakValueDictionary[int, CarverSession]" = weakref.WeakValueDictionary()

    def __init__(
        self,
        device: Union[str, torch.device, None] = None,
    ):
        """
        device: 
          - "auto" (default) to use CUDA if available, otherwise CPU
          - "cuda" or "cpu" to force a hardware target
          - a torch.device object
        """
        if isinstance(device, str):
            pref = device.lower()
            if pref == "auto":
                target = "cuda" if torch.cuda.is_available() else "cpu"
            elif pref in ("cuda", "cpu"):
                target = pref
            else:
                raise ValueError(f"Unknown device preference: {device!r}")
            self.device = torch.device(target)
        elif isinstance(device, torch.device):
            self.device = device
        elif device is None:
            target = "cuda" if torch.cuda.is_available() else "cpu"
            self.device = torch.device(target)
        else:
            raise TypeError(f"device must be str, torch.device, or None, not {type(device)}")

        # Tensor cache (use get_tensor to populate)
        self.tensors: Dict[str, torch.Tensor] = {}

        # Register this session for retrieval
        CarverSession._sessions[_device_key(self.device)] = self

        # cache generation for tensors only
        self._gen = 0

    def bump(self, flush: bool = False) -> None:
        """
        Invalidate the session tensor cache between independent runs.
        Optionally free CUDA memory.
        """
        self.tensors.clear()
        if flush and self.device.type == "cuda":
            torch.cuda.empty_cache()
        self._gen += 1

    def __enter__(self) -> "CarverSession":
        """
        Initialize CUDA context on first entry. No automatic warm-ups.
        """
        if self.device.type == "cuda":
            torch.cuda.init()
        return self

    def __exit__(
        self, exc_type, exc_value, traceback
    ) -> bool:
        """
        Exit context; caches remain alive until explicit close().
        """
        return False  # propagate any exceptions
    
    @classmethod
    def from_config(cls, cfg: user_config) -> "CarverSession":
        """
        Construct a CarverSession using the `device` field in a user_config.
        The `device` value in cfg may be "auto", "cuda" or "cpu".
        """
        return cls(device=cfg.device)

    def get_tensor(
        self,
        key: str,
        factory: Callable[[], torch.Tensor],
    ) -> torch.Tensor:
        """
        Cache or retrieve a tensor by key. The factory callable is invoked
        once per cache generation (bumped between pipeline runs). The result
        is moved to self.device automatically.

        Args:
            key: Cache lookup identifier.
            factory: Zero-argument callable that produces the tensor.

        Returns:
            Cached or freshly computed tensor on self.device.
        """
        key = f"{key}|g{self._gen}"
        if key not in self.tensors:
            value = factory()
            # move to GPU only for tensors
            if isinstance(value, torch.Tensor):
                value = value.to(self.device)
            self.tensors[key] = value
        return self.tensors[key]

    def close(self, flush: bool = True) -> None:
        """
        Clear the in-memory tensor cache. If on CUDA and flush=True,
        empties torch's cache.
        """
        self.tensors.clear()
        if flush and self.device.type == "cuda":
            torch.cuda.empty_cache()


def get_active_session(
    device: Union[str, torch.device, None] = None,
) -> Optional[CarverSession]:
    """
    Fetch an existing CarverSession for the specified device, or None if
    none exists.

    Returns:
        The CarverSession for the specified device, or None if no session
        is registered.
    """
    if device is None or (isinstance(device, str) and device == "auto"):
        # No device requested: a single active session wins regardless of
        # device, so a CPU session on a CUDA machine still gets its cache.
        if len(CarverSession._sessions) == 1:
            return next(iter(CarverSession._sessions.values()))
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        dev = torch.device(device)
    return CarverSession._sessions.get(_device_key(dev))


# urbansolarcarver/session.py
def session_cache(key_template: str):
    """
    Decorator that memoises a function's return value in the active
    CarverSession's tensor cache. The key_template is formatted with
    {args} and {kwargs} to produce a unique cache key per call signature.
    If no session is active, the function runs without caching.

    Example::

        @session_cache('tregenza_dirs')
        def fetch_dirs(device): ...
    """
    def decorator(fn):
        warned = False

        @functools.wraps(fn)
        def wrapper(*args, session: "CarverSession | None" = None, **kw):
            nonlocal warned
            sess = session or get_active_session()
            if sess is None:
                return fn(*args, **kw)          # fallback, no cache
            # Build cache key by substituting {args}/{kwargs} in the template.
            # E.g., 'tregenza_dirs' (constant) or 'weights_{args[0]}' (dynamic).
            # If the template references missing kwargs or attributes,
            # fall back to uncached execution — but say so ONCE, loudly:
            # a silently dead cache is a performance bug that is otherwise
            # invisible.
            try:
                key = key_template.format(args=args, kwargs=kw)
            except (KeyError, IndexError, AttributeError):
                if not warned:
                    _log.warning(
                        "session_cache: key template %r does not match how %s "
                        "was called (e.g. positional vs keyword arguments) — "
                        "running uncached. This warning is shown once.",
                        key_template, fn.__name__,
                    )
                    warned = True
                return fn(*args, **kw)
            return sess.get_tensor(key, lambda: fn(*args, **kw))
        return wrapper
    return decorator
