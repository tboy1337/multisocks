#!/usr/bin/env python3
"""Shared pytest configuration and fixtures"""

import asyncio
import socket
import time
from typing import Generator, Any, List, Callable, Tuple, Optional
from unittest.mock import MagicMock, AsyncMock

import pytest

from multisocks.proxy.proxy_info import ProxyInfo
from multisocks.proxy.proxy_manager import ProxyManager


@pytest.fixture
def sample_proxy() -> ProxyInfo:
    """Create a sample ProxyInfo for testing"""
    return ProxyInfo("socks5", "proxy.example.com", 1080)


@pytest.fixture
def sample_proxy_with_auth() -> ProxyInfo:
    """Create a sample ProxyInfo with authentication for testing"""
    return ProxyInfo("socks5", "proxy.example.com", 1080, "testuser", "testpass")


@pytest.fixture
def sample_proxy_list() -> List[ProxyInfo]:
    """Create a list of sample proxies for testing"""
    return [
        ProxyInfo("socks5", "proxy1.example.com", 1080, weight=2),
        ProxyInfo("socks4", "proxy2.example.com", 1080, weight=3),
        ProxyInfo("socks5h", "proxy3.example.com", 1081, "user", "pass", weight=1),
    ]


@pytest.fixture
def mock_proxy_manager(proxy_list: List[ProxyInfo]) -> ProxyManager:
    """Create a mock ProxyManager for testing"""
    return ProxyManager(proxy_list)


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for async tests"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture
def mock_aiohttp_session() -> MagicMock:
    """Create a mock aiohttp session for testing"""
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock()
    session.get.return_value.__aexit__ = AsyncMock()
    return session


@pytest.fixture
def mock_bandwidth_response() -> MagicMock:
    """Create a mock bandwidth test response"""
    response = MagicMock()
    response.content.read = AsyncMock()
    # Return chunks of 1MB each, then empty to signal end
    response.content.read.side_effect = [
        b'x' * (1024 * 1024),  # 1MB
        b'x' * (1024 * 1024),  # 1MB
        b''  # End
    ]
    return response


# Pytest configuration
def pytest_configure(config: Any) -> None:
    """Configure pytest with custom markers"""
    config.addinivalue_line("markers", "unit: Unit tests that don't require external resources")
    config.addinivalue_line("markers", "integration: Integration tests that may require external resources")
    config.addinivalue_line("markers", "network: Tests that require network access")
    config.addinivalue_line("markers", "slow: Slow tests that take more time to run")


def pytest_collection_modifyitems(config: Any, items: List[Any]) -> None:  # pylint: disable=unused-argument
    """Modify test collection to add default markers"""
    for item in items:
        # Add unit marker by default
        if not any(marker.name in ['integration', 'network', 'slow']
                  for marker in item.iter_markers()):
            item.add_marker(pytest.mark.unit)


# Custom assertions for testing
class ProxyAssertions:
    """Custom assertions for proxy-related testing"""

    @staticmethod
    def assert_proxy_equal(proxy1: ProxyInfo, proxy2: ProxyInfo) -> None:
        """Assert two proxies are equal including all fields"""
        assert proxy1.protocol == proxy2.protocol
        assert proxy1.host == proxy2.host
        assert proxy1.port == proxy2.port
        assert proxy1.username == proxy2.username
        assert proxy1.password == proxy2.password
        assert proxy1.weight == proxy2.weight

    @staticmethod
    def assert_proxy_alive(proxy: ProxyInfo) -> None:
        """Assert proxy is marked as alive and healthy"""
        assert proxy.alive is True
        assert proxy.fail_count == 0

    @staticmethod
    def assert_proxy_dead(proxy: ProxyInfo) -> None:
        """Assert proxy is marked as dead"""
        assert proxy.alive is False
        assert proxy.fail_count >= 3


@pytest.fixture
def proxy_assertions() -> ProxyAssertions:
    """Provide proxy assertion helpers"""
    return ProxyAssertions()


# Async test helpers
class AsyncTestHelpers:
    """Helper functions for async testing"""

    @staticmethod
    async def wait_for_condition(condition_func: Callable[[], bool], timeout: float = 1.0) -> bool:
        """Wait for a condition to become true within timeout"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if condition_func():
                return True
            await asyncio.sleep(0.01)  # Small delay

        return False

    @staticmethod
    def create_mock_stream_pair() -> Tuple[MagicMock, MagicMock]:
        """Create a pair of connected mock streams for testing"""
        reader = MagicMock()
        writer = MagicMock()

        # Configure writer mock
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()
        writer.get_extra_info = MagicMock(return_value=('127.0.0.1', 12345))
        writer.is_closing = MagicMock(return_value=False)

        # Configure reader mock
        reader.read = AsyncMock(return_value=b'')
        reader.readexactly = AsyncMock()

        return reader, writer


@pytest.fixture
def async_helpers() -> AsyncTestHelpers:
    """Provide async test helper functions"""
    return AsyncTestHelpers()


# Network-related fixtures
@pytest.fixture
def mock_proxy_connector() -> MagicMock:
    """Create a mock proxy connector for testing"""
    connector = MagicMock()
    connector.connect = AsyncMock()

    # Mock successful stream
    mock_stream = MagicMock()
    mock_stream.reader = AsyncMock()
    mock_stream.writer = MagicMock()
    mock_stream.writer.write = MagicMock()
    mock_stream.writer.drain = AsyncMock()
    mock_stream.close = AsyncMock()

    connector.connect.return_value = mock_stream
    return connector


# Error simulation fixtures
@pytest.fixture
def network_error() -> Exception:
    """Create a network error for testing"""
    return socket.error("Network unreachable")


@pytest.fixture
def timeout_error() -> Exception:
    """Create a timeout error for testing"""
    return asyncio.TimeoutError("Operation timed out")


# Performance testing fixtures
@pytest.fixture
def performance_timer() -> Any:
    """Timer for performance testing"""

    class Timer:
        """Simple timer class for performance testing"""
        def __init__(self) -> None:
            self.start_time: Optional[float] = None
            self.end_time: Optional[float] = None

        def start(self) -> None:
            """Start the timer"""
            self.start_time = time.time()

        def stop(self) -> None:
            """Stop the timer"""
            self.end_time = time.time()

        @property
        def elapsed(self) -> float:
            """Get the elapsed time between start and stop"""
            if self.start_time is None or self.end_time is None:
                return 0.0
            return self.end_time - self.start_time

    return Timer()


# Logging fixtures for testing logging behavior
@pytest.fixture
def mock_logger() -> MagicMock:
    """Create a mock logger for testing logging calls"""
    return MagicMock()
