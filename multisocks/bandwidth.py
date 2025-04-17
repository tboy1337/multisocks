#!/usr/bin/env python3
import asyncio
import aiohttp
import logging
import time
import random
from typing import List, Optional, Tuple
import statistics

logger = logging.getLogger(__name__)

class BandwidthTester:
    """Measures connection bandwidth and provides optimal proxy counts"""
    
    # Test URLs - large files from various CDNs
    TEST_URLS = [
        "https://speed.cloudflare.com/100mb.bin",  # Cloudflare
        "https://proof.ovh.net/files/100Mb.dat",   # OVH
        "https://speedtest.tele2.net/100MB.zip",   # Tele2
    ]
    
    # Test duration in seconds
    TEST_DURATION = 5
    
    def __init__(self, max_proxies: int = 100):
        """Initialize the bandwidth tester
        
        Args:
            max_proxies: Maximum number of proxies to use regardless of bandwidth
        """
        self.max_proxies = max_proxies
        self.user_bandwidth_mbps = 0
        self.proxy_avg_bandwidth_mbps = 0
        self.optimal_proxy_count = 1
    
    async def measure_connection_speed(self) -> float:
        """Measure the user's direct connection speed in Mbps"""
        url = random.choice(self.TEST_URLS)
        total_bytes = 0
        start_time = time.time()
        end_time = start_time + self.TEST_DURATION
        
        try:
            timeout = aiohttp.ClientTimeout(total=self.TEST_DURATION + 2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    while time.time() < end_time:
                        chunk = await response.content.read(1024 * 1024)  # Read 1MB at a time
                        if not chunk:
                            break
                        total_bytes += len(chunk)
        except asyncio.TimeoutError:
            # This is expected as we're canceling after TEST_DURATION
            pass
        except Exception as e:
            logger.error(f"Error measuring connection speed: {e}")
            return 0
        
        elapsed_time = time.time() - start_time
        if elapsed_time <= 0:
            return 0
            
        # Calculate speed in Mbps (megabits per second)
        mbps = (total_bytes * 8) / (elapsed_time * 1000 * 1000)
        logger.info(f"Direct connection speed: {mbps:.2f} Mbps")
        self.user_bandwidth_mbps = mbps
        return mbps
    
    async def measure_proxy_speeds(self, proxies: List) -> float:
        """Measure the average bandwidth of proxies in Mbps
        
        This is a simplified estimation - in a real implementation, you would
        need to test through each proxy using the SOCKS protocol
        """
        # This is a placeholder - in a real implementation, you'd test 
        # each proxy with small downloads and average the results
        # For now, we'll assume each proxy provides ~5-10 Mbps on average
        proxy_speeds = []
        for proxy in proxies[:min(5, len(proxies))]:  # Test up to 5 proxies
            # Simulated proxy speed test - in a real implementation,
            # you would actually test the proxy's performance
            if hasattr(proxy, 'latency') and proxy.latency > 0:
                # Estimate bandwidth based on latency (inverse relationship)
                # A rough approximation - real testing would be better
                speed = 10.0 / max(0.1, proxy.latency)  # Mbps
                proxy_speeds.append(min(10.0, max(1.0, speed)))  # Clamp between 1-10 Mbps
        
        if not proxy_speeds:
            # Default assumption if we have no data
            return 5.0
            
        avg_speed = statistics.mean(proxy_speeds)
        logger.info(f"Average proxy speed: {avg_speed:.2f} Mbps")
        self.proxy_avg_bandwidth_mbps = avg_speed
        return avg_speed
    
    def calculate_optimal_proxy_count(self, available_proxies: List) -> int:
        """Calculate how many proxies we need to saturate the connection"""
        if self.user_bandwidth_mbps <= 0 or self.proxy_avg_bandwidth_mbps <= 0:
            # Default to using all available proxies if we don't have bandwidth data
            return min(len(available_proxies), self.max_proxies)
        
        # Calculate how many proxies we need to saturate the connection
        # Add a 20% buffer to account for overhead
        needed_proxies = int((self.user_bandwidth_mbps * 1.2) / self.proxy_avg_bandwidth_mbps)
        
        # Ensure we use at least 1 proxy and no more than max_proxies
        optimal_count = max(1, min(needed_proxies, self.max_proxies, len(available_proxies)))
        
        logger.info(f"Optimal proxy count: {optimal_count} " 
                   f"(User: {self.user_bandwidth_mbps:.2f} Mbps, "
                   f"Proxy avg: {self.proxy_avg_bandwidth_mbps:.2f} Mbps)")
        
        self.optimal_proxy_count = optimal_count
        return optimal_count 