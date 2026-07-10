"""Tests for CarverSession: caching, bump(), device key, session_cache decorator."""
import pytest
import torch
from unittest.mock import MagicMock

from urbansolarcarver.session import (
    CarverSession,
    _device_key,
    get_active_session,
    session_cache,
)


# ---------------------------------------------------------------------------
# Device key normalization
# ---------------------------------------------------------------------------

class TestDeviceKey:
    def test_cuda_no_index(self):
        assert _device_key(torch.device("cuda")) == 0

    def test_cuda_explicit_zero(self):
        assert _device_key(torch.device("cuda:0")) == 0

    def test_cpu(self):
        assert _device_key(torch.device("cpu")) == -1


# ---------------------------------------------------------------------------
# CarverSession lifecycle
# ---------------------------------------------------------------------------

class TestCarverSessionLifecycle:
    def test_cpu_session_creation(self):
        sess = CarverSession(device="cpu")
        assert sess.device == torch.device("cpu")
        assert sess._gen == 0
        sess.close()

    def test_auto_device_resolves(self):
        sess = CarverSession(device="auto")
        assert sess.device.type in ("cpu", "cuda")
        sess.close()

    def test_none_device_resolves(self):
        sess = CarverSession(device=None)
        assert sess.device.type in ("cpu", "cuda")
        sess.close()

    def test_invalid_device_raises(self):
        with pytest.raises(ValueError, match="Unknown device"):
            CarverSession(device="tpu")

    def test_wrong_type_device_raises(self):
        with pytest.raises(TypeError):
            CarverSession(device=42)


# ---------------------------------------------------------------------------
# Tensor caching
# ---------------------------------------------------------------------------

class TestTensorCache:
    def test_factory_called_once(self):
        sess = CarverSession(device="cpu")
        factory = MagicMock(return_value=torch.tensor([1.0, 2.0]))
        sess.get_tensor("test_key", factory)
        sess.get_tensor("test_key", factory)
        factory.assert_called_once()
        sess.close()

    def test_different_keys_call_factory_separately(self):
        sess = CarverSession(device="cpu")
        f1 = MagicMock(return_value=torch.tensor([1.0]))
        f2 = MagicMock(return_value=torch.tensor([2.0]))
        sess.get_tensor("k1", f1)
        sess.get_tensor("k2", f2)
        f1.assert_called_once()
        f2.assert_called_once()
        sess.close()

    def test_bump_clears_tensor_cache(self):
        sess = CarverSession(device="cpu")
        factory = MagicMock(return_value=torch.tensor([1.0]))
        sess.get_tensor("mykey", factory)
        assert factory.call_count == 1
        sess.bump()
        sess.get_tensor("mykey", factory)
        assert factory.call_count == 2, "Factory should be called again after bump()"
        sess.close()

    def test_bump_increments_generation(self):
        sess = CarverSession(device="cpu")
        g0 = sess._gen
        sess.bump()
        assert sess._gen == g0 + 1
        sess.close()

    def test_tensor_moved_to_device(self):
        sess = CarverSession(device="cpu")
        t = sess.get_tensor("dev_test", lambda: torch.tensor([3.14]))
        assert t.device == torch.device("cpu")
        sess.close()


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_clears_tensor_cache(self):
        sess = CarverSession(device="cpu")
        sess.get_tensor("t1", lambda: torch.tensor([1.0]))
        sess.close()
        assert len(sess.tensors) == 0


# ---------------------------------------------------------------------------
# session_cache decorator
# ---------------------------------------------------------------------------

class TestSessionCacheDecorator:
    def test_caches_with_active_session(self):
        sess = CarverSession(device="cpu")

        call_count = 0

        @session_cache("test_func")
        def my_func():
            nonlocal call_count
            call_count += 1
            return torch.tensor([42.0])

        result1 = my_func()
        result2 = my_func()
        assert call_count == 1, "Function should be called only once when cached"
        assert torch.equal(result1, result2)
        sess.close()

    def test_runs_uncached_without_session(self):
        # Ensure no active session
        CarverSession._sessions.clear()

        call_count = 0

        @session_cache("no_sess_func")
        def my_func():
            nonlocal call_count
            call_count += 1
            return torch.tensor([7.0])

        my_func()
        my_func()
        assert call_count == 2, "Without session, function should run each time"

    def test_bad_key_template_falls_back(self):
        sess = CarverSession(device="cpu")

        @session_cache("bad_{args[99]}")  # will fail to format
        def my_func(x):
            return torch.tensor([x])

        # Should not crash — falls back to uncached
        result = my_func(5.0)
        assert result.item() == 5.0
        sess.close()
