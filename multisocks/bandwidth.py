#!/usr/bin/env python3
"""Bandwidth testing and optimization for proxy selection."""
import asyncio
import logging
import random
import statistics
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import aiohttp
import aiohttp_socks

if TYPE_CHECKING:
    from .proxy.proxy_info import ProxyInfo

logger = logging.getLogger(__name__)


class BandwidthTester:
    """Measures connection bandwidth and provides optimal proxy counts"""

    # Test URLs - large files from various CDNs
    TEST_URLS = [
        "https://speed.cloudflare.com/100mb.bin",  # Cloudflare
        "https://proof.ovh.net/files/100Mb.dat",  # OVH
        "https://speedtest.tele2.net/100MB.zip",  # Tele2
    ]

    # Test duration in seconds
    TEST_DURATION = 5

    def __init__(self, max_proxies: int = 100):
        """Initialize the bandwidth tester

        Args:
            max_proxies: Maximum number of proxies to use regardless of bandwidth
        """
        self.max_proxies = max_proxies
        self.user_bandwidth_mbps: float = 0.0
        self.proxy_avg_bandwidth_mbps: float = 0.0
        self.optimal_proxy_count = 1
        self.progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None

    async def measure_connection_speed(
        self, progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> float:
        """Measure the user's direct connection speed in Mbps"""
        url = random.choice(self.TEST_URLS)
        total_bytes = 0
        start_time = time.time()
        end_time = start_time + self.TEST_DURATION
        if progress_callback:
            progress_callback("start_user_bandwidth_test", {"url": url})
        try:
            timeout = aiohttp.ClientTimeout(total=self.TEST_DURATION + 2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    while time.time() < end_time:
                        chunk = await response.content.read(1024 * 1024)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if progress_callback:
                            elapsed = time.time() - start_time
                            progress_callback(
                                "user_bandwidth_progress",
                                {"bytes": total_bytes, "elapsed": elapsed},
                            )
        except asyncio.TimeoutError:
            # This is expected as we're canceling after TEST_DURATION
            pass
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error measuring connection speed: %s", e)
            return 0

        elapsed_time = time.time() - start_time
        if elapsed_time <= 0:
            return 0

        # Calculate speed in Mbps (megabits per second)
        mbps = (total_bytes * 8) / (elapsed_time * 1000 * 1000)
        logger.info("Direct connection speed: %.2f Mbps", mbps)
        self.user_bandwidth_mbps = mbps
        if progress_callback:
            progress_callback("user_bandwidth_done", {"mbps": mbps})
        return mbps

    async def measure_proxy_speeds(
        self,
        proxies: List['ProxyInfo'],
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> float:
        """Measure the average bandwidth of proxies in Mbps

        This is a simplified estimation - in a real implementation, you would
        need to test through each proxy using the SOCKS protocol
        """
        proxy_speeds = []
        test_url = random.choice(self.TEST_URLS)
        for idx, proxy in enumerate(proxies[: min(5, len(proxies))]):
            speed = 0.0
            try:
                timeout = aiohttp.ClientTimeout(total=self.TEST_DURATION + 2)
                connector = aiohttp_socks.ProxyConnector.from_url(
                    proxy.connection_string()
                )
                start_time = time.time()
                total_bytes = 0
                async with aiohttp.ClientSession(
                    connector=connector, timeout=timeout
                ) as session:
                    async with session.get(test_url) as response:
                        while time.time() - start_time < self.TEST_DURATION:
                            chunk = await response.content.read(1024 * 1024)
                            if not chunk:
                                break
                            total_bytes += len(chunk)
                            if progress_callback:
                                progress_callback(
                                    "proxy_bandwidth_progress",
                                    {
                                        "proxy": str(proxy),
                                        "bytes": total_bytes,
                                        "idx": idx,
                                    },
                                )
                elapsed = time.time() - start_time
                if elapsed > 0:
                    speed = (total_bytes * 8) / (elapsed * 1000 * 1000)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Error testing proxy %s: %s", proxy, e)
                speed = 0.0
            proxy_speeds.append(speed)
            if progress_callback:
                progress_callback(
                    "proxy_bandwidth_done",
                    {"proxy": str(proxy), "mbps": speed, "idx": idx},
                )

        if not proxy_speeds:
            # Default assumption if we have no data
            return 5.0

        avg_speed = statistics.mean([s for s in proxy_speeds if s > 0] or [5.0])
        logger.info("Average proxy speed: %.2f Mbps", avg_speed)
        self.proxy_avg_bandwidth_mbps = avg_speed
        if progress_callback:
            progress_callback("proxy_bandwidth_avg", {"mbps": avg_speed})
        return avg_speed

    def calculate_optimal_proxy_count(self, available_proxies: List['ProxyInfo']) -> int:
        """Calculate how many proxies we need to saturate the connection"""
        if self.user_bandwidth_mbps <= 0 or self.proxy_avg_bandwidth_mbps <= 0:
            # Default to using all available proxies if we don't have bandwidth data
            return min(len(available_proxies), self.max_proxies)

        # Calculate how many proxies we need to saturate the connection
        # Add a 20% buffer to account for overhead
        needed_proxies = int(
            (self.user_bandwidth_mbps * 1.2) / self.proxy_avg_bandwidth_mbps
        )

        # Ensure we use at least 1 proxy and no more than max_proxies
        optimal_count = max(
            1, min(needed_proxies, self.max_proxies, len(available_proxies))
        )

        logger.info(
            "Optimal proxy count: %d (User: %.2f Mbps, Proxy avg: %.2f Mbps)",
            optimal_count,
            self.user_bandwidth_mbps,
            self.proxy_avg_bandwidth_mbps
        )

        self.optimal_proxy_count = optimal_count
        return optimal_count

    async def run_continuous_optimization(
        self,
        proxies: List['ProxyInfo'],
        interval: int = 60,
        progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        """Continuously test and optimize proxies until bandwidth is saturated. Calls progress_callback with status."""
        while True:
            if progress_callback:
                progress_callback("cycle_start", {})
            await self.measure_connection_speed(progress_callback)
            await self.measure_proxy_speeds(proxies, progress_callback)
            optimal_count = self.calculate_optimal_proxy_count(proxies)
            if progress_callback:
                progress_callback(
                    "cycle_done",
                    {
                        "user_bandwidth_mbps": self.user_bandwidth_mbps,
                        "proxy_avg_bandwidth_mbps": self.proxy_avg_bandwidth_mbps,
                        "optimal_proxy_count": optimal_count,
                        "total_proxies": len(proxies),
                    },
                )
            await asyncio.sleep(interval)
