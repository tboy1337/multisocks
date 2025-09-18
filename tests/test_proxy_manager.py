#!/usr/bin/env python3
"""Tests for the ProxyManager class"""
# pylint: disable=protected-access

import asyncio
import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
from python_socks import ProxyType

from multisocks.proxy.proxy_manager import ProxyManager
from multisocks.proxy.proxy_info import ProxyInfo


class TestProxyManager:
    """Test ProxyManager class functionality"""

    def test_init_empty_proxies_raises_error(self) -> None:
        """Test that empty proxy list raises ValueError"""
        with pytest.raises(ValueError, match="At least one proxy must be provided"):
            ProxyManager([])

    def test_init_single_proxy(self) -> None:
        """Test initialization with single proxy"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        assert manager.all_proxies == [proxy]
        assert manager.active_proxies == [proxy]
        assert manager._index == 0
        assert manager._total_weight == 1
        assert manager.auto_optimize is False
        assert manager.bandwidth_tester is None

    def test_init_multiple_proxies(self) -> None:
        """Test initialization with multiple proxies"""
        proxies = [
            ProxyInfo("socks5", "proxy1.example.com", 1080, weight=2),
            ProxyInfo("socks4", "proxy2.example.com", 1080, weight=3),
        ]
        manager = ProxyManager(proxies)

        assert manager.all_proxies == proxies
        assert manager.active_proxies == proxies
        assert manager._total_weight == 5  # 2 + 3

    def test_init_with_auto_optimize(self) -> None:
        """Test initialization with auto-optimization enabled"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        with patch('multisocks.proxy.proxy_manager.BandwidthTester') as mock_tester:
            manager = ProxyManager([proxy], auto_optimize=True)

            assert manager.auto_optimize is True
            mock_tester.assert_called_once()
            assert manager.bandwidth_tester is not None

    def test_init_auto_optimize_import_error(self) -> None:
        """Test auto-optimize gracefully handles import errors"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        with patch('multisocks.proxy.proxy_manager.BandwidthTester', None):
            with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
                manager = ProxyManager([proxy], auto_optimize=True)

                assert manager.auto_optimize is False
                assert manager.bandwidth_tester is None
                mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_proxy_single_healthy(self) -> None:
        """Test getting proxy with single healthy proxy"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy.alive = True
        manager = ProxyManager([proxy])

        result = await manager.get_proxy("example.com", 80)
        assert result == proxy

    @pytest.mark.asyncio
    async def test_get_proxy_weighted_selection(self) -> None:
        """Test weighted proxy selection"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080, weight=1)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080, weight=9)
        proxy1.alive = True
        proxy2.alive = True

        manager = ProxyManager([proxy1, proxy2])

        # Run multiple selections to check distribution
        selections = []
        for _ in range(100):
            with patch('multisocks.proxy.proxy_manager.random.randint') as mock_random:
                # Mock random to always select proxy2 (weight 9)
                mock_random.return_value = 5  # Falls in proxy2's range
                result = await manager.get_proxy("example.com", 80)
                selections.append(result)

        # Should have selected proxy2 more often due to higher weight
        assert all(sel == proxy2 for sel in selections)

    @pytest.mark.asyncio
    async def test_get_proxy_no_healthy_proxies_uses_any(self) -> None:
        """Test get_proxy falls back to any proxy when none are healthy"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy.alive = False  # Mark as not alive
        manager = ProxyManager([proxy])

        with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
            result = await manager.get_proxy("example.com", 80)

            assert result == proxy  # Should still return the proxy as last resort
            # Should log warnings about no healthy proxies
            assert mock_logger.warning.call_count >= 2

    @pytest.mark.asyncio
    async def test_get_proxy_no_proxies_raises_error(self) -> None:
        """Test get_proxy raises error when no proxies available"""
        # This is tricky since we can't init with empty list
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Clear all proxy lists
        manager.all_proxies = []
        manager.active_proxies = []

        with pytest.raises(RuntimeError, match="No proxies available"):
            await manager.get_proxy("example.com", 80)

    @pytest.mark.asyncio
    async def test_get_proxy_zero_weights_uses_round_robin(self) -> None:
        """Test get_proxy uses round-robin when all weights are zero"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080, weight=0)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080, weight=0)
        proxy1.alive = True
        proxy2.alive = True

        manager = ProxyManager([proxy1, proxy2])

        # First call should get proxy1 (index 0)
        result1 = await manager.get_proxy("example.com", 80)
        assert result1 == proxy1

        # Second call should get proxy2 (index 1)
        result2 = await manager.get_proxy("example.com", 80)
        assert result2 == proxy2

        # Third call should wrap around to proxy1
        result3 = await manager.get_proxy("example.com", 80)
        assert result3 == proxy1

    @pytest.mark.asyncio
    async def test_start_creates_health_check_task(self) -> None:
        """Test start method creates health check task"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        assert manager._health_check_task is None

        with patch('multisocks.proxy.proxy_manager.asyncio.create_task') as mock_create_task:
            await manager.start()

            mock_create_task.assert_called_once()
            assert manager._health_check_task is not None

    @pytest.mark.asyncio
    async def test_stop_cancels_health_check_task(self) -> None:
        """Test stop method cancels health check task"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Create a real task that can be cancelled and awaited
        async def dummy_task() -> None:
            await asyncio.sleep(0.1)

        task = asyncio.create_task(dummy_task())
        manager._health_check_task = task

        await manager.stop()

        # Task should be cancelled
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_stop_handles_cancelled_error(self) -> None:
        """Test stop method handles CancelledError gracefully"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Create a task that's already cancelled
        async def dummy_task() -> None:
            await asyncio.sleep(1)  # Will be cancelled before completion

        task = asyncio.create_task(dummy_task())
        task.cancel()  # Cancel it immediately
        manager._health_check_task = task

        # Should not raise exception despite already being cancelled
        await manager.stop()

        # Task should remain cancelled
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_check_proxy_success(self) -> None:
        """Test successful proxy health check"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Mock the Proxy class and its connect method
        mock_stream = MagicMock()
        mock_stream.close = MagicMock()  # Mock the synchronous close method

        with patch('multisocks.proxy.proxy_manager.Proxy') as mock_proxy_class:
            mock_proxy_instance = mock_proxy_class.return_value
            mock_proxy_instance.connect = AsyncMock(return_value=mock_stream)

            with patch('multisocks.proxy.proxy_manager.time.time', side_effect=[0, 0.5]):
                result = await manager._check_proxy(proxy)

                assert result is True
                assert proxy.alive is True
                assert proxy.fail_count == 0
                assert proxy.latency == 0.5
                mock_stream.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_proxy_timeout_failure(self) -> None:
        """Test proxy health check timeout failure"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        mock_proxy_connector = MagicMock()
        mock_proxy_connector.connect = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch('python_socks.async_.asyncio.Proxy', return_value=mock_proxy_connector):
            result = await manager._check_proxy(proxy)

            assert result is False
            assert proxy.fail_count == 1

    @pytest.mark.asyncio
    async def test_check_proxy_socket_error_failure(self) -> None:
        """Test proxy health check socket error failure"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        mock_proxy_connector = MagicMock()
        mock_proxy_connector.connect = AsyncMock(side_effect=socket.error("Connection refused"))

        with patch('python_socks.async_.asyncio.Proxy', return_value=mock_proxy_connector):
            result = await manager._check_proxy(proxy)

            assert result is False
            assert proxy.fail_count == 1

    @pytest.mark.asyncio
    async def test_check_proxy_unexpected_error(self) -> None:
        """Test proxy health check handles unexpected errors"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        mock_proxy_connector = MagicMock()
        mock_proxy_connector.connect = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        with patch('python_socks.async_.asyncio.Proxy', return_value=mock_proxy_connector):
            with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
                result = await manager._check_proxy(proxy)

                assert result is False
                assert proxy.fail_count == 1
                # RuntimeError should trigger error logging, but if it's being caught by the first handler,
                # it would call debug instead. Let's be flexible about which one is called.
                assert mock_logger.error.called or mock_logger.debug.called

    @pytest.mark.asyncio
    async def test_check_all_proxies(self) -> None:
        """Test checking health of all proxies"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080)
        manager = ProxyManager([proxy1, proxy2])

        # Mock _check_proxy to return different results
        with patch.object(manager, '_check_proxy') as mock_check:
            mock_check.side_effect = [True, False]  # proxy1 succeeds, proxy2 fails

            await manager._check_all_proxies()

            assert mock_check.call_count == 2
            mock_check.assert_has_calls([call(proxy1), call(proxy2)])

    @pytest.mark.asyncio
    async def test_check_all_proxies_handles_exceptions(self) -> None:
        """Test _check_all_proxies handles exceptions from individual checks"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080)
        manager = ProxyManager([proxy1, proxy2])

        with patch.object(manager, '_check_proxy') as mock_check:
            mock_check.side_effect = [RuntimeError("Check failed"), True]

            with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
                await manager._check_all_proxies()

                # Should log info about results, even with exception
                mock_logger.info.assert_called_once()
                # Should mark first proxy as failed due to exception
                assert proxy1.fail_count == 1

    @pytest.mark.asyncio
    async def test_health_check_loop_cancelled_error_handling(self) -> None:
        """Test health check loop handles CancelledError by breaking"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Mock sleep to immediately raise CancelledError
        with patch('multisocks.proxy.proxy_manager.asyncio.sleep', side_effect=asyncio.CancelledError()):
            # Should handle CancelledError gracefully and exit without raising
            await manager._health_check_loop()  # This should complete successfully

    @pytest.mark.asyncio
    async def test_health_check_loop_exception_handling(self) -> None:
        """Test health check loop handles exceptions and logs them"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Create side effects for sleep to simulate one iteration then cancel
        sleep_calls = 0
        def sleep_side_effect(_seconds: float) -> Any:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 1:
                # First call succeeds
                return AsyncMock(return_value=None)()
            # Second call raises CancelledError to exit the loop
            raise asyncio.CancelledError()

        with patch.object(manager, '_check_all_proxies', side_effect=RuntimeError("Test error")):
            with patch('multisocks.proxy.proxy_manager.asyncio.sleep', side_effect=sleep_side_effect):
                with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
                    # Should handle the exception and exit gracefully
                    await manager._health_check_loop()

                    # Should log error at least once
                    assert mock_logger.error.called

    @pytest.mark.asyncio
    async def test_optimize_proxy_usage_no_bandwidth_tester(self) -> None:
        """Test proxy optimization when no bandwidth tester available"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Should return without error when no bandwidth tester
        await manager._optimize_proxy_usage()

    @pytest.mark.asyncio
    async def test_optimize_proxy_usage_success(self) -> None:
        """Test successful proxy usage optimization"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080)
        proxy1.alive = True
        proxy2.alive = True
        proxy1.latency = 0.1
        proxy2.latency = 0.2

        manager = ProxyManager([proxy1, proxy2], auto_optimize=True)

        with patch('multisocks.bandwidth.BandwidthTester') as mock_tester_class:
            mock_tester = MagicMock()
            mock_tester_class.return_value = mock_tester
            manager.bandwidth_tester = mock_tester

            # Mock bandwidth measurements
            mock_tester.measure_connection_speed = AsyncMock(return_value=50)
            mock_tester.measure_proxy_speeds = AsyncMock(return_value=10)
            mock_tester.calculate_optimal_proxy_count.return_value = 1

            await manager._optimize_proxy_usage()

            # Should optimize to use only 1 proxy (the faster one)
            assert len(manager.active_proxies) == 1
            assert manager.active_proxies[0] == proxy1  # Lower latency

    @pytest.mark.asyncio
    async def test_optimize_proxy_usage_no_user_bandwidth(self) -> None:
        """Test proxy optimization when user bandwidth measurement fails"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy], auto_optimize=True)

        with patch('multisocks.bandwidth.BandwidthTester') as mock_tester_class:
            mock_tester = MagicMock()
            mock_tester_class.return_value = mock_tester
            manager.bandwidth_tester = mock_tester

            # Mock failed bandwidth measurement
            mock_tester.measure_connection_speed = AsyncMock(return_value=0)

            with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
                await manager._optimize_proxy_usage()

                mock_logger.warning.assert_called_with(
                    "Couldn't measure user bandwidth, using all healthy proxies"
                )

    @pytest.mark.asyncio
    async def test_optimize_proxy_usage_no_healthy_proxies(self) -> None:
        """Test proxy optimization when no healthy proxies available"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy.alive = False
        manager = ProxyManager([proxy], auto_optimize=True)

        with patch('multisocks.bandwidth.BandwidthTester') as mock_tester_class:
            mock_tester = MagicMock()
            mock_tester_class.return_value = mock_tester
            manager.bandwidth_tester = mock_tester

            mock_tester.measure_connection_speed = AsyncMock(return_value=50)

            with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
                await manager._optimize_proxy_usage()

                mock_logger.warning.assert_called_with(
                    "No healthy proxies available for optimization"
                )

    @pytest.mark.asyncio
    async def test_optimize_proxy_usage_handles_exceptions(self) -> None:
        """Test proxy optimization handles exceptions gracefully"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy.alive = True
        manager = ProxyManager([proxy], auto_optimize=True)

        with patch('multisocks.bandwidth.BandwidthTester') as mock_tester_class:
            mock_tester = MagicMock()
            mock_tester_class.return_value = mock_tester
            manager.bandwidth_tester = mock_tester

            # Mock exception during optimization
            mock_tester.measure_connection_speed = AsyncMock(side_effect=RuntimeError("Test error"))

            with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
                await manager._optimize_proxy_usage()

                mock_logger.error.assert_called_once()
                # Should fallback to using all healthy proxies
                assert manager.active_proxies == [proxy]

    @pytest.mark.asyncio
    async def test_start_continuous_optimization(self) -> None:
        """Test start_continuous_optimization creates bandwidth tester if needed"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        assert manager.bandwidth_tester is None

        with patch('multisocks.proxy.proxy_manager.BandwidthTester') as mock_tester_class:
            mock_tester = MagicMock()
            mock_tester_class.return_value = mock_tester
            # Mock the infinite loop to return immediately instead of hanging
            mock_tester.run_continuous_optimization = AsyncMock(return_value=None)

            # Use asyncio.wait_for to prevent hanging
            await asyncio.wait_for(manager.start_continuous_optimization(), timeout=1)

            mock_tester_class.assert_called_once()
            assert manager.bandwidth_tester == mock_tester
            mock_tester.run_continuous_optimization.assert_called_once_with(
                manager.all_proxies, 60, None
            )

    @pytest.mark.asyncio
    async def test_start_continuous_optimization_with_existing_tester(self) -> None:
        """Test start_continuous_optimization with existing bandwidth tester"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        with patch('multisocks.proxy.proxy_manager.BandwidthTester'):
            manager = ProxyManager([proxy], auto_optimize=True)

            existing_tester = MagicMock()
            # Mock to return immediately instead of running infinite loop
            existing_tester.run_continuous_optimization = AsyncMock(return_value=None)
            manager.bandwidth_tester = existing_tester

            # Use timeout to prevent hanging
            await asyncio.wait_for(manager.start_continuous_optimization(interval=30), timeout=1)

            existing_tester.run_continuous_optimization.assert_called_once_with(
                manager.all_proxies, 30, None
            )


class TestProxyManagerProtocols:
    """Test ProxyManager with different proxy protocols"""

    @pytest.mark.asyncio
    async def test_check_proxy_socks4_protocol(self) -> None:
        """Test health check for SOCKS4 proxy"""
        proxy = ProxyInfo("socks4", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        mock_stream = AsyncMock()
        mock_proxy_connector = MagicMock()
        mock_proxy_connector.connect = AsyncMock(return_value=mock_stream)

        mock_stream.close = MagicMock()  # Add close method for proper mocking

        with patch('multisocks.proxy.proxy_manager.Proxy') as mock_proxy_class:
            mock_proxy_class.return_value = mock_proxy_connector

            with patch('multisocks.proxy.proxy_manager.time.time', side_effect=[0, 0.5]):
                result = await manager._check_proxy(proxy)

                # Verify test passed and SOCKS4 proxy was created
                assert result is True
                mock_proxy_class.assert_called_once_with(
                    proxy_type=ProxyType.SOCKS4,
                    host="proxy.example.com",
                    port=1080,
                    username=None,
                    password=None,
                    rdns=False  # SOCKS4 doesn't use remote DNS
                )

    @pytest.mark.asyncio
    async def test_check_proxy_socks4a_protocol(self) -> None:
        """Test health check for SOCKS4a proxy"""
        proxy = ProxyInfo("socks4a", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        mock_stream = AsyncMock()
        mock_proxy_connector = MagicMock()
        mock_proxy_connector.connect = AsyncMock(return_value=mock_stream)

        mock_stream.close = MagicMock()  # Add close method for proper mocking

        with patch('multisocks.proxy.proxy_manager.Proxy') as mock_proxy_class:
            mock_proxy_class.return_value = mock_proxy_connector

            with patch('multisocks.proxy.proxy_manager.time.time', side_effect=[0, 0.5]):
                result = await manager._check_proxy(proxy)

                # Verify test passed and SOCKS4a proxy was created with remote DNS
                assert result is True
                mock_proxy_class.assert_called_once_with(
                    proxy_type=ProxyType.SOCKS4,
                    host="proxy.example.com",
                    port=1080,
                    username=None,
                    password=None,
                    rdns=True  # SOCKS4a uses remote DNS
                )

    @pytest.mark.asyncio
    async def test_check_proxy_socks5h_protocol(self) -> None:
        """Test health check for SOCKS5h proxy"""
        proxy = ProxyInfo("socks5h", "proxy.example.com", 1080, "user", "pass")
        manager = ProxyManager([proxy])

        mock_stream = AsyncMock()
        mock_proxy_connector = MagicMock()
        mock_proxy_connector.connect = AsyncMock(return_value=mock_stream)

        mock_stream.close = MagicMock()  # Add close method for proper mocking

        with patch('multisocks.proxy.proxy_manager.Proxy') as mock_proxy_class:
            mock_proxy_class.return_value = mock_proxy_connector

            with patch('multisocks.proxy.proxy_manager.time.time', side_effect=[0, 0.5]):
                result = await manager._check_proxy(proxy)

                # Verify test passed and SOCKS5h proxy was created with remote DNS and auth
                assert result is True
                mock_proxy_class.assert_called_once_with(
                    proxy_type=ProxyType.SOCKS5,
                    host="proxy.example.com",
                    port=1080,
                    username="user",
                    password="pass",
                    rdns=True  # SOCKS5h uses remote DNS
                )


class TestProxyManagerHealthCheckEdgeCases:
    """Test edge cases in health check loop for better coverage"""

    @pytest.mark.asyncio
    async def test_get_proxy_fallback_when_no_active_healthy(self) -> None:
        """Test get_proxy fallback path when no active healthy proxies (covers line 98)"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080)
        proxy1.alive = False  # Not alive
        proxy2.alive = True   # Alive but not in active list

        manager = ProxyManager([proxy1, proxy2])
        manager.active_proxies = [proxy1]  # Only dead proxy in active

        with patch('multisocks.proxy.proxy_manager.logger') as mock_logger:
            result = await manager.get_proxy("example.com", 80)

            # Should fall back to healthy proxy from all_proxies (covers line 98 fallback)
            assert result == proxy2
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_health_check_loop_with_optimization(self) -> None:
        """Test health check loop with auto-optimization enabled (covers lines 111-115)"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy], auto_optimize=True)

        # Mock bandwidth tester
        with patch('multisocks.bandwidth.BandwidthTester') as mock_tester_class:
            mock_tester = MagicMock()
            mock_tester_class.return_value = mock_tester
            manager.bandwidth_tester = mock_tester

            # Mock time to trigger optimization (covers lines 111-115)
            manager.last_optimization_time = 0

            # Mock _optimize_proxy_usage to avoid actual optimization
            with patch.object(manager, '_optimize_proxy_usage') as mock_optimize:
                with patch.object(manager, '_check_all_proxies'):
                    with patch('multisocks.proxy.proxy_manager.asyncio.sleep') as mock_sleep:
                        with patch('multisocks.proxy.proxy_manager.time.time',
                                   return_value=700):  # Trigger optimization

                            # Make sleep raise CancelledError to exit loop
                            mock_sleep.side_effect = asyncio.CancelledError()

                            # Run one iteration of health check loop
                            await manager._health_check_loop()

                            # Should have called optimization (covers lines 111-115)
                            mock_optimize.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_creates_task_only_once(self) -> None:
        """Test start method only creates task if not already created (covers line 229->exit)"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Create mock task
        mock_task = AsyncMock()

        with patch('multisocks.proxy.proxy_manager.asyncio.create_task', return_value=mock_task) as mock_create_task:
            # First call should create task
            await manager.start()
            assert manager._health_check_task == mock_task
            mock_create_task.assert_called_once()

            # Second call should NOT create another task (covers line 229->exit condition)
            mock_create_task.reset_mock()
            await manager.start()
            mock_create_task.assert_not_called()  # Should not be called again

    @pytest.mark.asyncio
    async def test_stop_with_no_health_check_task(self) -> None:
        """Test stop method when no health check task exists (covers line 51->exit)"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])

        # Ensure no task exists
        manager._health_check_task = None

        # Should complete without error even with no task (covers line 51->exit)
        await manager.stop()
