#!/usr/bin/env python3
"""Tests for the ProxyInfo class"""

import pytest
from multisocks.proxy.proxy_info import ProxyInfo


class TestProxyInfo:  # pylint: disable=too-many-public-methods
    """Test ProxyInfo class functionality"""

    def test_init_minimal(self) -> None:
        """Test ProxyInfo initialization with minimal parameters"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        assert proxy.protocol == "socks5"
        assert proxy.host == "proxy.example.com"
        assert proxy.port == 1080
        assert proxy.username is None
        assert proxy.password is None
        assert proxy.weight == 1
        assert proxy.alive is True
        assert proxy.fail_count == 0
        assert proxy.latency == 0.0

    def test_init_with_auth(self) -> None:
        """Test ProxyInfo initialization with authentication"""
        proxy = ProxyInfo(
            "socks5", "proxy.example.com", 1080,
            username="user", password="pass"
        )

        assert proxy.username == "user"
        assert proxy.password == "pass"

    def test_init_with_weight(self) -> None:
        """Test ProxyInfo initialization with weight"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080, weight=5)
        assert proxy.weight == 5

    def test_str_without_auth(self) -> None:
        """Test string representation without authentication"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        assert str(proxy) == "socks5://proxy.example.com:1080"

    def test_str_with_auth(self) -> None:
        """Test string representation with authentication"""
        proxy = ProxyInfo(
            "socks5", "proxy.example.com", 1080,
            username="user", password="pass"
        )
        assert str(proxy) == "socks5://user:pass@proxy.example.com:1080"

    def test_str_with_weight(self) -> None:
        """Test string representation with weight"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080, weight=5)
        assert str(proxy) == "socks5://proxy.example.com:1080/5"

    def test_str_with_auth_and_weight(self) -> None:
        """Test string representation with auth and weight"""
        proxy = ProxyInfo(
            "socks5", "proxy.example.com", 1080,
            username="user", password="pass", weight=3
        )
        assert str(proxy) == "socks5://user:pass@proxy.example.com:1080/3"

    def test_connection_string_without_auth(self) -> None:
        """Test connection string without authentication"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080, weight=5)
        assert proxy.connection_string() == "socks5://proxy.example.com:1080"

    def test_connection_string_with_auth(self) -> None:
        """Test connection string with authentication"""
        proxy = ProxyInfo(
            "socks5", "proxy.example.com", 1080,
            username="user", password="pass", weight=5
        )
        assert proxy.connection_string() == "socks5://user:pass@proxy.example.com:1080"

    def test_get_protocol_version_socks4(self) -> None:
        """Test protocol version for SOCKS4"""
        proxy = ProxyInfo("socks4", "proxy.example.com", 1080)
        assert proxy.get_protocol_version() == 4

    def test_get_protocol_version_socks4a(self) -> None:
        """Test protocol version for SOCKS4a"""
        proxy = ProxyInfo("socks4a", "proxy.example.com", 1080)
        assert proxy.get_protocol_version() == 4

    def test_get_protocol_version_socks5(self) -> None:
        """Test protocol version for SOCKS5"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        assert proxy.get_protocol_version() == 5

    def test_get_protocol_version_socks5h(self) -> None:
        """Test protocol version for SOCKS5h"""
        proxy = ProxyInfo("socks5h", "proxy.example.com", 1080)
        assert proxy.get_protocol_version() == 5

    def test_get_protocol_version_invalid(self) -> None:
        """Test protocol version for invalid protocol"""
        proxy = ProxyInfo("invalid", "proxy.example.com", 1080)
        with pytest.raises(ValueError, match="Unsupported protocol"):
            proxy.get_protocol_version()

    def test_mark_failed_increments_count(self) -> None:
        """Test mark_failed increments failure count"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        assert proxy.fail_count == 0
        assert proxy.alive is True

        proxy.mark_failed()
        assert proxy.fail_count == 1
        assert proxy.alive is True

        proxy.mark_failed()
        assert proxy.fail_count == 2
        assert proxy.alive is True

    def test_mark_failed_sets_dead_after_threshold(self) -> None:
        """Test mark_failed sets proxy as dead after threshold"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        # Fail 3 times to reach threshold
        proxy.mark_failed()  # 1
        proxy.mark_failed()  # 2
        proxy.mark_failed()  # 3

        assert proxy.fail_count == 3
        assert proxy.alive is False

    def test_mark_successful_resets_failure_count(self) -> None:
        """Test mark_successful resets failure count and sets alive"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        # Fail it first
        proxy.mark_failed()
        proxy.mark_failed()
        assert proxy.fail_count == 2

        # Mark successful should reset
        proxy.mark_successful()
        assert proxy.fail_count == 0
        assert proxy.alive is True

    def test_mark_successful_revives_dead_proxy(self) -> None:
        """Test mark_successful can revive a dead proxy"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        # Kill the proxy
        proxy.mark_failed()
        proxy.mark_failed()
        proxy.mark_failed()
        assert proxy.alive is False

        # Revive it
        proxy.mark_successful()
        assert proxy.alive is True
        assert proxy.fail_count == 0  # type: ignore[unreachable]

    def test_update_latency_initial_value(self) -> None:
        """Test updating latency from initial zero value"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        assert proxy.latency == 0.0

        proxy.update_latency(0.5)
        assert proxy.latency == 0.5

    def test_update_latency_smoothing(self) -> None:
        """Test latency smoothing with multiple updates"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        # First update sets the value
        proxy.update_latency(1.0)
        assert proxy.latency == 1.0

        # Second update should use smoothing: (1.0 * 0.7) + (2.0 * 0.3) = 1.3
        proxy.update_latency(2.0)
        assert abs(proxy.latency - 1.3) < 0.001

        # Third update: (1.3 * 0.7) + (0.5 * 0.3) = 0.91 + 0.15 = 1.06
        proxy.update_latency(0.5)
        assert abs(proxy.latency - 1.06) < 0.001  # Account for floating point precision

    def test_equality_identical_proxies(self) -> None:
        """Test equality with identical proxies"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080, "user", "pass", 2)
        proxy2 = ProxyInfo("socks5", "proxy.example.com", 1080, "user", "pass", 2)

        assert proxy1 == proxy2

    def test_equality_different_protocols(self) -> None:
        """Test equality with different protocols"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy2 = ProxyInfo("socks4", "proxy.example.com", 1080)

        assert proxy1 != proxy2

    def test_equality_different_hosts(self) -> None:
        """Test equality with different hosts"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080)

        assert proxy1 != proxy2

    def test_equality_different_ports(self) -> None:
        """Test equality with different ports"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy.example.com", 1081)

        assert proxy1 != proxy2

    def test_equality_different_usernames(self) -> None:
        """Test equality with different usernames"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080, "user1", "pass")
        proxy2 = ProxyInfo("socks5", "proxy.example.com", 1080, "user2", "pass")

        assert proxy1 != proxy2

    def test_equality_different_passwords(self) -> None:
        """Test equality with different passwords"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080, "user", "pass1")
        proxy2 = ProxyInfo("socks5", "proxy.example.com", 1080, "user", "pass2")

        assert proxy1 != proxy2

    def test_equality_different_weights(self) -> None:
        """Test equality with different weights"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080, weight=1)
        proxy2 = ProxyInfo("socks5", "proxy.example.com", 1080, weight=2)

        assert proxy1 != proxy2

    def test_equality_with_non_proxy_object(self) -> None:
        """Test equality with non-ProxyInfo object"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)

        assert proxy != "not a proxy"
        assert proxy != 123
        assert proxy is not None

    def test_equality_ignores_dynamic_fields(self) -> None:
        """Test equality ignores dynamic fields like alive, fail_count, latency"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy.example.com", 1080)

        # Modify dynamic fields
        proxy1.alive = False
        proxy1.fail_count = 5
        proxy1.latency = 1.5

        proxy2.alive = True
        proxy2.fail_count = 0
        proxy2.latency = 0.0

        # Should still be equal
        assert proxy1 == proxy2

    def test_hash_identical_proxies(self) -> None:
        """Test hash function with identical proxies"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080, "user", "pass", 2)
        proxy2 = ProxyInfo("socks5", "proxy.example.com", 1080, "user", "pass", 2)

        assert hash(proxy1) == hash(proxy2)

    def test_hash_different_proxies(self) -> None:
        """Test hash function with different proxies"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy2 = ProxyInfo("socks4", "proxy.example.com", 1080)

        # Different proxies should have different hashes (most of the time)
        assert hash(proxy1) != hash(proxy2)

    def test_hash_consistency(self) -> None:
        """Test hash function consistency"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080, "user", "pass", 3)

        # Hash should be consistent
        hash1 = hash(proxy)
        hash2 = hash(proxy)
        assert hash1 == hash2

        # Modifying dynamic fields shouldn't change hash
        proxy.alive = False
        proxy.fail_count = 10
        proxy.latency = 2.5
        hash3 = hash(proxy)
        assert hash1 == hash3

    def test_hash_allows_set_usage(self) -> None:
        """Test that ProxyInfo can be used in sets"""
        proxy1 = ProxyInfo("socks5", "proxy1.example.com", 1080)
        proxy2 = ProxyInfo("socks5", "proxy2.example.com", 1080)
        proxy3 = ProxyInfo("socks5", "proxy1.example.com", 1080)  # Same as proxy1

        proxy_set = {proxy1, proxy2, proxy3}

        # Should only have 2 unique proxies
        assert len(proxy_set) == 2
        assert proxy1 in proxy_set
        assert proxy2 in proxy_set
        assert proxy3 in proxy_set  # Same as proxy1

    def test_hash_allows_dict_usage(self) -> None:
        """Test that ProxyInfo can be used as dictionary keys"""
        proxy1 = ProxyInfo("socks5", "proxy.example.com", 1080)
        proxy2 = ProxyInfo("socks4", "proxy.example.com", 1080)

        proxy_dict = {proxy1: "value1", proxy2: "value2"}

        assert proxy_dict[proxy1] == "value1"
        assert proxy_dict[proxy2] == "value2"
        assert len(proxy_dict) == 2
