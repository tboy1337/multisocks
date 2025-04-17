import unittest
from multisocks.proxy.proxy_info import ProxyInfo

class TestProxyInfo(unittest.TestCase):
    def test_proxy_info_creation(self):
        """Test creating a ProxyInfo object"""
        proxy = ProxyInfo(
            protocol="socks5",
            host="example.com",
            port=1080,
            username="user",
            password="pass",
            weight=10
        )
        
        self.assertEqual(proxy.protocol, "socks5")
        self.assertEqual(proxy.host, "example.com")
        self.assertEqual(proxy.port, 1080)
        self.assertEqual(proxy.username, "user")
        self.assertEqual(proxy.password, "pass")
        self.assertEqual(proxy.weight, 10)
        self.assertTrue(proxy.alive)
        
    def test_proxy_info_string_representation(self):
        """Test the string representation of ProxyInfo"""
        proxy = ProxyInfo(
            protocol="socks5",
            host="example.com",
            port=1080,
            username="user",
            password="pass",
            weight=10
        )
        
        expected = "socks5://user:pass@example.com:1080/10"
        self.assertEqual(str(proxy), expected)
        
    def test_protocol_version(self):
        """Test getting the protocol version"""
        socks4_proxy = ProxyInfo(protocol="socks4", host="example.com", port=1080)
        socks4a_proxy = ProxyInfo(protocol="socks4a", host="example.com", port=1080)
        socks5_proxy = ProxyInfo(protocol="socks5", host="example.com", port=1080)
        socks5h_proxy = ProxyInfo(protocol="socks5h", host="example.com", port=1080)
        
        self.assertEqual(socks4_proxy.get_protocol_version(), 4)
        self.assertEqual(socks4a_proxy.get_protocol_version(), 4)
        self.assertEqual(socks5_proxy.get_protocol_version(), 5)
        self.assertEqual(socks5h_proxy.get_protocol_version(), 5)
        
    def test_mark_failed(self):
        """Test marking a proxy as failed"""
        proxy = ProxyInfo(protocol="socks5", host="example.com", port=1080)
        self.assertTrue(proxy.alive)
        
        proxy.mark_failed()
        self.assertTrue(proxy.alive)  # Should still be alive after 1 failure
        self.assertEqual(proxy.fail_count, 1)
        
        proxy.mark_failed()
        proxy.mark_failed()  # 3rd failure
        self.assertFalse(proxy.alive)  # Should be dead after 3 failures
        
    def test_mark_successful(self):
        """Test marking a proxy as successful"""
        proxy = ProxyInfo(protocol="socks5", host="example.com", port=1080)
        proxy.mark_failed()
        proxy.mark_failed()
        self.assertEqual(proxy.fail_count, 2)
        
        proxy.mark_successful()
        self.assertEqual(proxy.fail_count, 0)
        self.assertTrue(proxy.alive)

if __name__ == '__main__':
    unittest.main() 