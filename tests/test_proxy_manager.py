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
        
        # Mock the health check task to prevent it from running in background
        with patch.object(ProxyManager, '_health_check_loop', return_value=asyncio.Future()):
            self.manager = ProxyManager(self.proxies)
            self.manager._health_check_task = asyncio.Future()
    
    @patch('multisocks.bandwidth.BandwidthTester')
    def test_initialize_with_auto_optimize(self, mock_bandwidth_tester):
        """Test initializing the proxy manager with auto-optimization enabled"""
        # Mock the bandwidth tester
        mock_tester_instance = MagicMock()
        mock_bandwidth_tester.return_value = mock_tester_instance
        
        # Create proxy manager with auto-optimization
        with patch.object(ProxyManager, '_health_check_loop', return_value=asyncio.Future()):
            manager = ProxyManager(self.proxies, auto_optimize=True)
            manager._health_check_task = asyncio.Future()
        
        # Verify the bandwidth tester was created
        self.assertTrue(manager.auto_optimize)
        self.assertIsNotNone(manager.bandwidth_tester)
        
        # Verify all proxies are initially active
        self.assertEqual(len(manager.active_proxies), 5)
        self.assertEqual(len(manager.all_proxies), 5)
    
    @patch('multisocks.proxy.proxy_manager.BandwidthTester')
    async def test_optimize_proxy_usage(self, mock_bandwidth_tester):
        """Test optimizing proxy usage based on bandwidth"""
        # Configure mock bandwidth tester
        mock_tester = MagicMock()
        mock_tester.measure_connection_speed = AsyncMock(return_value=50.0)  # 50 Mbps
        mock_tester.measure_proxy_speeds = AsyncMock(return_value=5.0)  # 5 Mbps per proxy
        mock_tester.calculate_optimal_proxy_count = MagicMock(return_value=3)  # Need 3 proxies
        mock_bandwidth_tester.return_value = mock_tester
        
        # Create proxy manager with auto-optimization and the mock bandwidth tester
        with patch.object(ProxyManager, '_health_check_loop', return_value=asyncio.Future()):
            manager = ProxyManager(self.proxies, auto_optimize=True)
            manager._health_check_task = asyncio.Future()
            manager.bandwidth_tester = mock_tester
        
        # Mark all proxies as alive with varying latencies
        for i, proxy in enumerate(manager.all_proxies):
            proxy.alive = True
            proxy.latency = (i + 1) * 0.1  # 0.1s, 0.2s, 0.3s, etc.
        
        # Run the optimization
        await manager._optimize_proxy_usage()
        
        # Verify the active proxies were updated
        self.assertEqual(len(manager.active_proxies), 3)
        
        # Should select the 3 proxies with lowest latency
        self.assertEqual(manager.active_proxies[0].latency, 0.1)
        self.assertEqual(manager.active_proxies[1].latency, 0.2)
        self.assertEqual(manager.active_proxies[2].latency, 0.3)
    
    @patch('multisocks.proxy.proxy_manager.BandwidthTester')
    async def test_get_proxy_with_active_proxies(self, mock_bandwidth_tester):
        """Test that get_proxy uses active proxies when available"""
        # Set up the manager with auto-optimization
        with patch.object(ProxyManager, '_health_check_loop', return_value=asyncio.Future()):
            manager = ProxyManager(self.proxies, auto_optimize=True)
            manager._health_check_task = asyncio.Future()
        
        # Mark all proxies as alive
        for proxy in manager.all_proxies:
            proxy.alive = True
        
        # Set only the first 2 proxies as active
        manager.active_proxies = manager.all_proxies[:2]
        
        # Get a proxy 10 times
        selected_proxies = []
        for _ in range(10):
            proxy = await manager.get_proxy("example.com", 80)
            selected_proxies.append(proxy)
        
        # We should only get proxies from the active set
        unique_proxies = set(selected_proxies)
        self.assertLessEqual(len(unique_proxies), 2)
        
        # Verify we only got the active proxies
        for proxy in unique_proxies:
            self.assertIn(proxy, manager.active_proxies)
    
    @patch('multisocks.proxy.proxy_manager.BandwidthTester')
    async def test_get_proxy_failover(self, mock_bandwidth_tester):
        """Test that get_proxy falls back to all proxies if no active ones are healthy"""
        # Set up the manager with auto-optimization
        with patch.object(ProxyManager, '_health_check_loop', return_value=asyncio.Future()):
            manager = ProxyManager(self.proxies, auto_optimize=True)
            manager._health_check_task = asyncio.Future()
        
        # Mark active proxies as not alive
        manager.active_proxies = manager.all_proxies[:2]
        for proxy in manager.active_proxies:
            proxy.alive = False
        
        # Mark some inactive proxies as alive
        for proxy in manager.all_proxies[2:]:
            proxy.alive = True
        
        # Get a proxy
        proxy = await manager.get_proxy("example.com", 80)
        
        # Should get a healthy proxy from the full list
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