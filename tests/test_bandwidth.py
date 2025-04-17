import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio

from multisocks.bandwidth import BandwidthTester
from multisocks.proxy.proxy_info import ProxyInfo

class TestBandwidthTester(unittest.TestCase):
    def setUp(self):
        self.tester = BandwidthTester(max_proxies=10)
    
    @patch('aiohttp.ClientSession')
    async def test_measure_connection_speed(self, mock_session):
        """Test measuring connection speed"""
        # Mock the HTTP response
        mock_response = AsyncMock()
        mock_content = AsyncMock()
        mock_content.read.side_effect = [
            b'x' * 1024 * 1024,  # 1MB
            b'x' * 1024 * 1024,  # 1MB
            b'x' * 1024 * 1024,  # 1MB
            b''  # End of stream
        ]
        mock_response.content = mock_content
        
        # Mock the session and context manager
        mock_session_instance = MagicMock()
        mock_session_instance.__aenter__.return_value = mock_response
        mock_session.return_value.__aenter__.return_value = mock_session_instance
        mock_session_instance.get.return_value = mock_session_instance
        
        # Run the test with a reduced test duration
        self.tester.TEST_DURATION = 0.1  # Short duration for testing
        speed = await self.tester.measure_connection_speed()
        
        # Verify the speed is calculated (exact value will depend on timing)
        self.assertGreater(speed, 0)
    
    @patch('time.time')
    async def test_measure_proxy_speeds(self, mock_time):
        """Test measuring proxy speeds"""
        # Mock time.time() to return consistent values
        mock_time.side_effect = [0, 0.5]  # 0.5 second latency
        
        # Create test proxies
        proxies = [
            ProxyInfo(protocol="socks5", host="test1.com", port=1080),
            ProxyInfo(protocol="socks5", host="test2.com", port=1080)
        ]
        
        # Set latency values
        proxies[0].latency = 0.2  # 200ms
        proxies[1].latency = 0.5  # 500ms
        
        # Test the proxy speed measurement
        speed = await self.tester.measure_proxy_speeds(proxies)
        
        # Verify a reasonable speed is returned
        self.assertGreater(speed, 0)
        self.assertLessEqual(speed, 10.0)  # Clamped to 10Mbps in our implementation
    
    def test_calculate_optimal_proxy_count(self):
        """Test calculating the optimal proxy count"""
        # Create test proxies
        proxies = [
            ProxyInfo(protocol="socks5", host=f"test{i}.com", port=1080)
            for i in range(20)
        ]
        
        # Test with zero bandwidth values (should default to max_proxies)
        self.tester.user_bandwidth_mbps = 0
        self.tester.proxy_avg_bandwidth_mbps = 0
        count = self.tester.calculate_optimal_proxy_count(proxies)
        self.assertEqual(count, 10)  # Limited by max_proxies=10
        
        # Test with normal values
        self.tester.user_bandwidth_mbps = 50  # 50 Mbps user connection
        self.tester.proxy_avg_bandwidth_mbps = 5  # 5 Mbps per proxy
        
        # Expected: (50 * 1.2) / 5 = 12, but capped at 10 due to max_proxies
        count = self.tester.calculate_optimal_proxy_count(proxies)
        self.assertEqual(count, 10)
        
        # Test with small bandwidth requirement
        self.tester.user_bandwidth_mbps = 10  # 10 Mbps user connection
        
        # Expected: (10 * 1.2) / 5 = 2.4 -> 2 proxies
        count = self.tester.calculate_optimal_proxy_count(proxies)
        self.assertEqual(count, 2)
        
        # Test with limited available proxies
        small_proxy_list = proxies[:3]  # Only 3 proxies available
        self.tester.user_bandwidth_mbps = 50  # 50 Mbps user connection
        
        # We need more proxies than available, so should return all 3
        count = self.tester.calculate_optimal_proxy_count(small_proxy_list)
        self.assertEqual(count, 3)

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