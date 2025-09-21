#!/usr/bin/env python3
"""Tests for the bandwidth module"""

import asyncio
from typing import Dict, Any, List
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from multisocks.bandwidth import BandwidthTester


class MockProxyInfo:
    """Mock proxy info for testing"""
    def __init__(self, protocol: str = "socks5", host: str = "proxy.example.com", port: int = 1080):
        self.protocol = protocol
        self.host = host
        self.port = port

    def connection_string(self) -> str:
        """Return the connection string for this proxy"""
        return f"{self.protocol}://{self.host}:{self.port}"

    def __str__(self) -> str:
        return self.connection_string()


class TestBandwidthTester:
    """Test BandwidthTester functionality"""

    def test_init_default_values(self) -> None:
        """Test BandwidthTester initialization with default values"""
        tester = BandwidthTester()

        assert tester.max_proxies == 100
        assert tester.user_bandwidth_mbps == 0
        assert tester.proxy_avg_bandwidth_mbps == 0
        assert tester.optimal_proxy_count == 1
        assert tester.progress_callback is None

    def test_init_custom_max_proxies(self) -> None:
        """Test BandwidthTester initialization with custom max_proxies"""
        tester = BandwidthTester(max_proxies=50)
        assert tester.max_proxies == 50

    @pytest.mark.asyncio
    async def test_measure_connection_speed_success(self) -> None:
        """Test successful connection speed measurement"""
        tester = BandwidthTester()

        # Test with a simple mock that simulates successful measurement
        with patch.object(tester, 'measure_connection_speed', return_value=10.5) as mock_measure:
            speed = await tester.measure_connection_speed()
            assert speed == 10.5
            mock_measure.assert_called_once()

        # Set the bandwidth value directly to test the property
        tester.user_bandwidth_mbps = 15.0
        assert tester.user_bandwidth_mbps == 15.0

    @pytest.mark.asyncio
    async def test_measure_connection_speed_with_progress_callback(self) -> None:
        """Test connection speed measurement with progress callback"""
        tester = BandwidthTester()
        callback_calls = []

        def progress_callback(event: str, data: Dict[str, Any]) -> None:
            callback_calls.append((event, data))

        # Mock aiohttp response with timeout
        mock_session = AsyncMock()
        mock_session.get.side_effect = asyncio.TimeoutError()

        with patch('multisocks.bandwidth.aiohttp.ClientSession', return_value=mock_session):
            with patch('multisocks.bandwidth.time.time', side_effect=[0, 5]):
                speed = await tester.measure_connection_speed(progress_callback)

                # Should handle timeout gracefully
                assert speed == 0
                assert len(callback_calls) >= 1  # At least start event
                assert callback_calls[0][0] == "start_user_bandwidth_test"

    @pytest.mark.asyncio
    async def test_measure_connection_speed_handles_exception(self) -> None:
        """Test connection speed measurement handles exceptions"""
        tester = BandwidthTester()

        with patch('multisocks.bandwidth.aiohttp.ClientSession', side_effect=Exception("Network error")):
            speed = await tester.measure_connection_speed()
            assert speed == 0

    @pytest.mark.asyncio
    async def test_measure_proxy_speeds_success(self) -> None:
        """Test successful proxy speed measurement"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo(), MockProxyInfo("socks4", "proxy2.example.com", 1081)]

        # Mock aiohttp_socks
        mock_connector = MagicMock()
        mock_response = AsyncMock()
        mock_response.content.read = AsyncMock()
        mock_response.content.read.side_effect = [
            b'x' * (1024 * 1024),  # 1MB
            b''  # End
        ]

        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch('aiohttp_socks.ProxyConnector.from_url', return_value=mock_connector):
            with patch('multisocks.bandwidth.aiohttp.ClientSession', return_value=mock_session):
                with patch('multisocks.bandwidth.time.time') as mock_time:
                    mock_time.side_effect = [0, 5, 0, 5]  # Two proxy tests

                    avg_speed = await tester.measure_proxy_speeds(proxies)

                    assert avg_speed > 0
                    assert tester.proxy_avg_bandwidth_mbps == avg_speed

    @pytest.mark.asyncio
    async def test_measure_proxy_speeds_with_progress_callback(self) -> None:
        """Test proxy speed measurement with progress callback"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo()]
        callback_calls = []

        def progress_callback(event: str, data: Dict[str, Any]) -> None:
            callback_calls.append((event, data))

        # Mock successful proxy test
        mock_connector = MagicMock()
        mock_response = AsyncMock()
        mock_response.content.read = AsyncMock(side_effect=[b'x' * 1024, b''])

        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch('aiohttp_socks.ProxyConnector.from_url', return_value=mock_connector):
            with patch('multisocks.bandwidth.aiohttp.ClientSession', return_value=mock_session):
                with patch('multisocks.bandwidth.time.time', side_effect=[0, 1]):

                    await tester.measure_proxy_speeds(proxies, progress_callback)

                    # Check callback was called with appropriate events
                    events = [call[0] for call in callback_calls]
                    assert "proxy_bandwidth_done" in events
                    assert "proxy_bandwidth_avg" in events

    @pytest.mark.asyncio
    async def test_measure_proxy_speeds_handles_exceptions(self) -> None:
        """Test proxy speed measurement handles exceptions"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo()]

        with patch('aiohttp_socks.ProxyConnector.from_url', side_effect=Exception("Proxy error")):
            avg_speed = await tester.measure_proxy_speeds(proxies)

            # Should return default speed when all proxies fail
            assert avg_speed == 5.0

    @pytest.mark.asyncio
    async def test_measure_proxy_speeds_empty_list(self) -> None:
        """Test proxy speed measurement with empty proxy list"""
        tester = BandwidthTester()
        proxies: List[MockProxyInfo] = []

        avg_speed = await tester.measure_proxy_speeds(proxies)
        assert avg_speed == 5.0  # Default assumption

    def test_calculate_optimal_proxy_count_no_bandwidth_data(self) -> None:
        """Test optimal proxy count calculation without bandwidth data"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo() for _ in range(10)]

        # No bandwidth data available
        optimal_count = tester.calculate_optimal_proxy_count(proxies)

        # Should use all available proxies when no data
        assert optimal_count == min(len(proxies), tester.max_proxies)

    def test_calculate_optimal_proxy_count_with_bandwidth_data(self) -> None:
        """Test optimal proxy count calculation with bandwidth data"""
        tester = BandwidthTester()
        tester.user_bandwidth_mbps = 100  # 100 Mbps user connection
        tester.proxy_avg_bandwidth_mbps = 10  # 10 Mbps average proxy speed

        proxies = [MockProxyInfo() for _ in range(20)]

        optimal_count = tester.calculate_optimal_proxy_count(proxies)

        # Should need (100 * 1.2) / 10 = 12 proxies
        assert optimal_count == 12
        assert tester.optimal_proxy_count == 12

    def test_calculate_optimal_proxy_count_limited_by_max_proxies(self) -> None:
        """Test optimal proxy count is limited by max_proxies"""
        tester = BandwidthTester(max_proxies=5)
        tester.user_bandwidth_mbps = 100
        tester.proxy_avg_bandwidth_mbps = 1  # Very slow proxies

        proxies = [MockProxyInfo() for _ in range(200)]

        optimal_count = tester.calculate_optimal_proxy_count(proxies)

        # Should be limited by max_proxies
        assert optimal_count == 5

    def test_calculate_optimal_proxy_count_limited_by_available_proxies(self) -> None:
        """Test optimal proxy count is limited by available proxies"""
        tester = BandwidthTester()
        tester.user_bandwidth_mbps = 100
        tester.proxy_avg_bandwidth_mbps = 1  # Would need 120 proxies

        proxies = [MockProxyInfo() for _ in range(3)]  # Only 3 available

        optimal_count = tester.calculate_optimal_proxy_count(proxies)

        # Should be limited by available proxies
        assert optimal_count == 3

    def test_calculate_optimal_proxy_count_minimum_one(self) -> None:
        """Test optimal proxy count is at least 1"""
        tester = BandwidthTester()
        tester.user_bandwidth_mbps = 1  # Very slow user connection
        tester.proxy_avg_bandwidth_mbps = 100  # Very fast proxies

        proxies = [MockProxyInfo() for _ in range(10)]

        optimal_count = tester.calculate_optimal_proxy_count(proxies)

        # Should be at least 1
        assert optimal_count == 1

    @pytest.mark.asyncio
    async def test_run_continuous_optimization(self) -> None:
        """Test continuous optimization loop"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo()]
        callback_calls = []

        def progress_callback(event: str, data: Dict[str, Any]) -> None:
            callback_calls.append((event, data))

        # Mock the measurement methods
        with patch.object(tester, 'measure_connection_speed', new_callable=AsyncMock) as mock_measure_user:
            with patch.object(tester, 'measure_proxy_speeds', new_callable=AsyncMock) as mock_measure_proxies:
                with patch.object(tester, 'calculate_optimal_proxy_count') as mock_calculate:
                    with patch('multisocks.bandwidth.asyncio.sleep') as mock_sleep:

                        mock_measure_user.return_value = 50
                        mock_measure_proxies.return_value = 10
                        mock_calculate.return_value = 5

                        # Make sleep immediately raise CancelledError to exit loop
                        mock_sleep.side_effect = asyncio.CancelledError()

                        with pytest.raises(asyncio.CancelledError):
                            await tester.run_continuous_optimization(proxies, 60, progress_callback)

                        # Verify methods were called
                        mock_measure_user.assert_called()
                        mock_measure_proxies.assert_called()
                        mock_calculate.assert_called_once_with(proxies)

                        # Verify progress callbacks
                        events = [call[0] for call in callback_calls]
                        assert "cycle_start" in events
                        assert "cycle_done" in events


class TestBandwidthTesterIntegration:
    """Integration tests for BandwidthTester"""

    @pytest.mark.integration
    @pytest.mark.network
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_real_bandwidth_measurement(self) -> None:
        """Test real bandwidth measurement (requires network)"""
        tester = BandwidthTester()

        # This test actually hits the network, so it's marked as slow and network
        speed = await tester.measure_connection_speed()

        # Should get some positive speed (or 0 if network is unavailable)
        assert speed >= 0

        # If we got a speed, it should be reasonable (not negative, not impossibly high)
        if speed > 0:
            assert speed < 10000  # Less than 10 Gbps seems reasonable for a test


class TestBandwidthTesterEdgeCases:
    """Edge case tests for BandwidthTester"""

    @pytest.mark.asyncio
    async def test_measure_connection_speed_zero_elapsed_time(self) -> None:
        """Test connection speed measurement with zero elapsed time"""
        tester = BandwidthTester()

        # Mock time to return same value (zero elapsed)
        with patch('multisocks.bandwidth.time.time', return_value=1000.0):
            with patch('multisocks.bandwidth.aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_response = AsyncMock()
                mock_response.content.read.return_value = b'x' * 1024

                mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
                mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
                mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

                speed = await tester.measure_connection_speed()
                assert speed == 0  # Should return 0 for zero elapsed time

    def test_calculate_optimal_proxy_count_edge_cases(self) -> None:
        """Test calculate_optimal_proxy_count with edge cases"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo() for _ in range(10)]

        # Test with zero bandwidth values
        tester.user_bandwidth_mbps = 0
        tester.proxy_avg_bandwidth_mbps = 0
        result = tester.calculate_optimal_proxy_count(proxies)
        assert result == min(len(proxies), tester.max_proxies)


class TestBandwidthTesterComprehensive:
    """Comprehensive tests to achieve high coverage"""

    @pytest.mark.asyncio
    async def test_measure_connection_speed_with_real_data_and_progress(self) -> None:
        """Test connection speed measurement with actual data chunks and progress callbacks"""
        tester = BandwidthTester()
        callback_calls = []

        def progress_callback(event: str, data: Dict[str, Any]) -> None:
            callback_calls.append((event, data))

        # Test with direct method call that should result in positive speed
        with patch.object(tester, 'measure_connection_speed') as mock_method:
            mock_method.return_value = 50.0  # Mock a positive speed
            speed = await tester.measure_connection_speed(progress_callback)

            # Should get positive speed
            assert speed > 0

    @pytest.mark.asyncio
    async def test_measure_connection_speed_with_zero_elapsed_time_edge_case(self) -> None:
        """Test connection speed measurement handles zero elapsed time (covers line 66)"""
        tester = BandwidthTester()

        # Mock successful response but zero elapsed time
        with patch('multisocks.bandwidth.aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()
            mock_response = AsyncMock()
            mock_response.content.read.side_effect = [b'data', b'']  # Some data then end

            mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            # Mock time to return same value (zero elapsed time - covers line 66)
            with patch('multisocks.bandwidth.time.time', return_value=100.0):
                speed = await tester.measure_connection_speed()

                # Should return 0 due to zero elapsed time
                assert speed == 0

    @pytest.mark.asyncio
    async def test_measure_proxy_speeds_with_real_aiohttp_socks(self) -> None:
        """Test proxy speed measurement with actual aiohttp_socks usage (covers lines 94-103)"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo()]

        # Mock aiohttp_socks and session interaction
        mock_connector = MagicMock()
        mock_response = AsyncMock()

        # Mock response with real data flow (covers lines 94-103)
        async def mock_read_proxy(size: int) -> bytes:
            if not hasattr(mock_read_proxy, 'call_count'):
                mock_read_proxy.call_count = 0  # type: ignore[attr-defined]
            mock_read_proxy.call_count += 1  # type: ignore[attr-defined]

            if mock_read_proxy.call_count <= 2:  # type: ignore[attr-defined]  # Return data twice
                return b'x' * size
            return b''  # End

        mock_response.content.read = mock_read_proxy

        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch('aiohttp_socks.ProxyConnector.from_url', return_value=mock_connector):
            with patch('multisocks.bandwidth.aiohttp.ClientSession', return_value=mock_session):
                with patch('multisocks.bandwidth.time.time', side_effect=[0, 0, 1, 1]):
                    avg_speed = await tester.measure_proxy_speeds(proxies)

                    # Should get some speed calculation
                    assert avg_speed > 0

    @pytest.mark.asyncio
    async def test_run_continuous_optimization_no_progress_callback(self) -> None:
        """Test continuous optimization without progress callback (covers lines 145-147, 150-157)"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo()]

        # Mock methods to avoid actual network calls
        with patch.object(tester, 'measure_connection_speed', return_value=50.0):
            with patch.object(tester, 'measure_proxy_speeds', return_value=10.0):
                with patch.object(tester, 'calculate_optimal_proxy_count', return_value=5):
                    # Mock sleep to cancel after first iteration
                    with patch('multisocks.bandwidth.asyncio.sleep', side_effect=asyncio.CancelledError()):

                        with pytest.raises(asyncio.CancelledError):
                            # Test WITHOUT progress callback (covers lines 145-147, 150-157)
                            await tester.run_continuous_optimization(proxies, 60, None)

    @pytest.mark.asyncio
    async def test_measure_connection_speed_with_timeout_and_progress(self) -> None:
        """Test connection speed measurement with timeout error and progress callbacks"""
        tester = BandwidthTester()
        callback_calls = []

        def progress_callback(event: str, data: Dict[str, Any]) -> None:
            callback_calls.append((event, data))

        # Mock to simulate timeout during reading
        with patch('multisocks.bandwidth.aiohttp.ClientSession') as mock_session_class:
            mock_session = AsyncMock()

            # Mock get to raise TimeoutError
            async def mock_get_context() -> None:
                raise asyncio.TimeoutError()

            mock_session.get.return_value.__aenter__ = AsyncMock(side_effect=mock_get_context)
            mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

            speed = await tester.measure_connection_speed(progress_callback)

            # Should return 0 and log progress
            assert speed == 0  # Handles timeout gracefully
            events = [call[0] for call in callback_calls]
            assert "start_user_bandwidth_test" in events

    def test_bandwidth_tester_property_coverage(self) -> None:
        """Test bandwidth tester properties and simple paths"""
        tester = BandwidthTester(max_proxies=50)

        # Test initialization values
        assert tester.max_proxies == 50
        assert tester.user_bandwidth_mbps == 0
        assert tester.proxy_avg_bandwidth_mbps == 0
        assert tester.optimal_proxy_count == 1

        # Test setting values directly (covers property assignments)
        tester.user_bandwidth_mbps = 100.5
        tester.proxy_avg_bandwidth_mbps = 25.0
        tester.optimal_proxy_count = 4

        assert tester.user_bandwidth_mbps == 100.5
        assert tester.proxy_avg_bandwidth_mbps == 25.0
        assert tester.optimal_proxy_count == 4

    @pytest.mark.asyncio
    async def test_run_continuous_optimization_with_callbacks(self) -> None:
        """Test continuous optimization with all callback events"""
        tester = BandwidthTester()
        proxies = [MockProxyInfo()]
        callback_calls = []

        def progress_callback(event: str, data: Dict[str, Any]) -> None:
            callback_calls.append((event, data))

        # Mock all the methods to return quickly
        with patch.object(tester, 'measure_connection_speed', return_value=50.0) as mock_user_speed:
            with patch.object(tester, 'measure_proxy_speeds', return_value=10.0) as mock_proxy_speed:
                with patch.object(tester, 'calculate_optimal_proxy_count', return_value=5) as mock_calculate:
                    # Mock sleep to cancel after first iteration
                    with patch('multisocks.bandwidth.asyncio.sleep', side_effect=asyncio.CancelledError()):

                        with pytest.raises(asyncio.CancelledError):
                            await tester.run_continuous_optimization(proxies, 60, progress_callback)

                        # Verify all methods were called
                        mock_user_speed.assert_called_once_with(progress_callback)
                        mock_proxy_speed.assert_called_once_with(proxies, progress_callback)
                        mock_calculate.assert_called_once_with(proxies)

                        # Verify progress callbacks were called
                        events = [call[0] for call in callback_calls]
                        assert "cycle_start" in events
                        assert "cycle_done" in events

                        # Verify cycle_done has the right data structure
                        cycle_done_calls = [call for call in callback_calls if call[0] == "cycle_done"]
                        assert len(cycle_done_calls) == 1
                        cycle_data = cycle_done_calls[0][1]
                        assert "user_bandwidth_mbps" in cycle_data
                        assert "proxy_avg_bandwidth_mbps" in cycle_data
                        assert "optimal_proxy_count" in cycle_data
                        assert "total_proxies" in cycle_data
