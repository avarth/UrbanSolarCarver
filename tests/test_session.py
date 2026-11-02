"""Tests for CarverSession: caching, the cache size limit, bump(), device key, session_cache decorator."""
import weakref

import numpy as np
import pytest
import torch
from unittest.mock import MagicMock

from urbansolarcarver.session import (
    CarverSession,
    get_active_session,
    session_cache,
)


# ---------------------------------------------------------------------------
# Device key normalization
# ---------------------------------------------------------------------------

class TestDeviceKey:
    @pytest.mark.gpu
    @pytest.mark.parametrize("opened_on, asked_for", [("cuda", "cuda:0"), ("cuda:0", "cuda")])
    def test_a_session_opened_on_cuda_serves_cuda_0(self, opened_on, asked_for):
        """"cuda" means "cuda:0": the daemon's session must serve a run that names the device either way."""
        with CarverSession(device=opened_on) as sess:
            assert get_active_session(asked_for) is sess


# ---------------------------------------------------------------------------
# CarverSession lifecycle
# ---------------------------------------------------------------------------

class TestCarverSessionLifecycle:
    @pytest.mark.parametrize("device", ["auto", None])
    def test_auto_device_resolves(self, device):
        sess = CarverSession(device=device)
        assert sess.device.type == ("cuda" if torch.cuda.is_available() else "cpu")
        sess.close()

    def test_invalid_device_raises(self):
        with pytest.raises(ValueError, match="tpu"):
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

    def test_runs_uncached_without_session(self, monkeypatch):
        # An empty registry for this test only: clearing the class-level one would drop a session another test opened.
        monkeypatch.setattr(CarverSession, "_sessions", weakref.WeakValueDictionary())

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

        # A key that fails to format must not raise; the call runs uncached.
        result = my_func(5.0)
        assert result.item() == 5.0
        sess.close()


class TestCacheRespectsDevice:
    @pytest.mark.gpu
    def test_cpu_request_inside_cuda_session_gets_cpu_tensor(self):
        """The daemon's session is on CUDA; a run configured for CPU must
        not receive cached CUDA tensors."""
        from urbansolarcarver.sky_patches import fetch_tregenza_patch_directions
        with CarverSession(device="cuda"):
            gpu = fetch_tregenza_patch_directions(torch.device("cuda"))
            cpu = fetch_tregenza_patch_directions(torch.device("cpu"))
        assert gpu.device.type == "cuda" and cpu.device.type == "cpu"

    def test_leaving_with_block_unregisters_session(self):
        with CarverSession(device="cpu") as sess:
            assert get_active_session("cpu") is sess
        assert get_active_session("cpu") is None


class TestCacheBudget:
    def _session(self, budget):
        from urbansolarcarver.session import CarverSession
        return CarverSession(device="cpu", max_cache_bytes=budget)

    def test_least_recently_used_entry_is_dropped(self):
        sess = self._session(budget=3 * 400)
        for k in "abc":
            sess.get_tensor(k, lambda: torch.zeros(100))  # 400 bytes each
        sess.get_tensor("a", lambda: pytest.fail("a should still be cached"))
        sess.get_tensor("d", lambda: torch.zeros(100))     # evicts b, the oldest use
        assert list(sess.tensors) == ["c", "a", "d"]
        assert sess.cache_bytes == 1200
        sess.close()

    def test_value_over_budget_is_returned_but_not_cached(self):
        sess = self._session(budget=100)
        big = sess.get_tensor("big", lambda: np.zeros(1000))
        assert big.shape == (1000,) and "big" not in sess.tensors
        assert sess.cache_bytes == 0
        sess.close()

    def test_nested_values_are_sized(self):
        from urbansolarcarver.session import _nbytes
        value = (torch.zeros(10, dtype=torch.uint8), np.zeros(3), 2.0, {"k": np.zeros(2)})
        assert _nbytes(value) == 10 + 24 + 16
