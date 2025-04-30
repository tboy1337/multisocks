import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

from multisocks.proxy.proxy_manager import ProxyManager
from multisocks.proxy.proxy_info import ProxyInfo
from multisocks.bandwidth import BandwidthTester

class TestProxyManager(unittest.TestCase):
    def setUp(self):
        # Create test proxies
        self.proxies = [
            ProxyInfo(protocol="socks5", host=f"proxy{i}.example.com", port=1080, weight=1)
            for i in range(1, 6)  # 5 proxies
        ]

    @patch('multisocks.bandwidth.BandwidthTester')
    def test_initialize_with_auto_optimize(self, mock_bandwidth_tester):
        """Test initializing the proxy manager with auto-optimization enabled"""
        # Mock the bandwidth tester
        mock_tester_instance = MagicMock()
        mock_bandwidth_tester.return_value = mock_tester_instance
        # Create proxy manager with auto-optimization
        manager = ProxyManager(self.proxies, auto_optimize=True)
        # Verify the bandwidth tester was created
        self.assertTrue(manager.auto_optimize)
        self.assertIsNotNone(manager.bandwidth_tester)
        # Verify all proxies are initially active
        self.assertEqual(len(manager.active_proxies), 5)
        self.assertEqual(len(manager.all_proxies), 5)

class TestProxyManagerAsync(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.proxies = [
            ProxyInfo(protocol="socks5", host=f"proxy{i}.example.com", port=1080, weight=1)
            for i in range(1, 6)
        ]

    @patch('multisocks.bandwidth.BandwidthTester')
    async def test_optimize_proxy_usage(self, mock_bandwidth_tester):
        mock_tester = MagicMock()
        mock_tester.measure_connection_speed = AsyncMock(return_value=50.0)
        mock_tester.measure_proxy_speeds = AsyncMock(return_value=5.0)
        mock_tester.calculate_optimal_proxy_count = MagicMock(return_value=3)
        mock_bandwidth_tester.return_value = mock_tester
        manager = ProxyManager(self.proxies, auto_optimize=True)
        manager.bandwidth_tester = mock_tester
        await manager.start()
        for i, proxy in enumerate(manager.all_proxies):
            proxy.alive = True
            proxy.latency = (i + 1) * 0.1
        await manager._optimize_proxy_usage()
        self.assertEqual(len(manager.active_proxies), 3)
        self.assertAlmostEqual(manager.active_proxies[0].latency, 0.1, places=6)
        self.assertAlmostEqual(manager.active_proxies[1].latency, 0.2, places=6)
        self.assertAlmostEqual(manager.active_proxies[2].latency, 0.3, places=6)

    @patch('multisocks.bandwidth.BandwidthTester')
    async def test_get_proxy_with_active_proxies(self, mock_bandwidth_tester):
        manager = ProxyManager(self.proxies, auto_optimize=True)
        await manager.start()
        for proxy in manager.all_proxies:
            proxy.alive = True
        manager.active_proxies = manager.all_proxies[:2]
        selected_proxies = []
        for _ in range(10):
            proxy = await manager.get_proxy("example.com", 80)
            selected_proxies.append(proxy)
        unique_proxies = set(selected_proxies)
        self.assertLessEqual(len(unique_proxies), 2)
        for proxy in unique_proxies:
            self.assertIn(proxy, manager.active_proxies)

    @patch('multisocks.bandwidth.BandwidthTester')
    async def test_get_proxy_failover(self, mock_bandwidth_tester):
        manager = ProxyManager(self.proxies, auto_optimize=True)
        await manager.start()
        manager.active_proxies = manager.all_proxies[:2]
        for proxy in manager.active_proxies:
            proxy.alive = False
        for proxy in manager.all_proxies[2:]:
            proxy.alive = True
        proxy = await manager.get_proxy("example.com", 80)
        self.assertIn(proxy, manager.all_proxies[2:])
        self.assertTrue(proxy.alive)

# Run the tests asynchronously
def run_async_test(test_case):
    """Helper function to run async test methods"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(test_case())
    finally:
        loop.close()

if __name__ == '__main__':
    unittest.main() 