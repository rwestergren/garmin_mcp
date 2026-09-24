"""Concurrent callers must not race the shared Garmin token set."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from garmin_mcp import _GarminProxy


def test_timed_out_worker_retains_lock_for_raw_client_calls():
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    raw_called = threading.Event()

    def slow_request():
        entered.set()
        try:
            assert release.wait(5)
        finally:
            finished.set()

    proxy = _GarminProxy(
        SimpleNamespace(
            get_devices=slow_request,
            client=SimpleNamespace(connectapi=raw_called.set),
        ),
        timeout=0.1,
    )
    try:
        with pytest.raises(TimeoutError, match="abandoned"):
            proxy.get_devices()
        assert entered.is_set()
        with pytest.raises(TimeoutError, match="still running"):
            proxy.client.connectapi()
        assert not raw_called.is_set()
    finally:
        release.set()
        assert finished.wait(5)

    proxy.client.connectapi()
    assert raw_called.is_set()


def test_simultaneous_calls_share_one_lock():
    entered = threading.Event()
    release = threading.Event()
    raw_called = threading.Event()

    def request():
        entered.set()
        assert release.wait(5)

    proxy = _GarminProxy(
        SimpleNamespace(get_devices=request, client=SimpleNamespace(connectapi=raw_called.set)),
        timeout=2,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(proxy.get_devices)
        try:
            assert entered.wait(2)
            second = pool.submit(proxy.client.connectapi)
            assert not raw_called.wait(0.1)
        finally:
            release.set()
        first.result()
        second.result()
    assert raw_called.is_set()
