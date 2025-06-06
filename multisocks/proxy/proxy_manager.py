import asyncio
import logging
import random
import time
from typing import Dict, List, Optional, Tuple, Set, Callable
import socket

from .proxy_info import ProxyInfo

logger = logging.getLogger(__name__)

class ProxyManager:
    """Manages multiple SOCKS proxies, handling dispatch and health monitoring"""
    
    def __init__(self, proxies: List[ProxyInfo], auto_optimize: bool = False):
        """Initialize with a list of proxies
        
        Args:
            proxies: List of ProxyInfo objects representing available proxies
            auto_optimize: Whether to automatically optimize proxy usage based on bandwidth
        """
        if not proxies:
            raise ValueError("At least one proxy must be provided")
        
        self.all_proxies = proxies  # All available proxies
        self.active_proxies = list(proxies)  # Currently active proxies
        self._index = 0
        self._total_weight = sum(p.weight for p in proxies)
        self._lock = asyncio.Lock()
        self.auto_optimize = auto_optimize
        
        # For bandwidth optimization
        self.bandwidth_tester = None
        self.last_optimization_time = 0
        self.optimization_interval = 600  # Optimize every 10 minutes
        
        # Import here to avoid circular imports
        if auto_optimize:
            try:
                from multisocks.bandwidth import BandwidthTester
                self.bandwidth_tester = BandwidthTester()
            except ImportError:
                logger.warning("BandwidthTester not available, auto-optimization disabled")
                self.auto_optimize = False
        
        # Remove health check task creation from __init__
        self._health_check_task = None
    
    async def stop(self):
        """Stop the health check task"""
        if hasattr(self, '_health_check_task'):
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
    
    async def get_proxy(self, target_host: str, target_port: int) -> ProxyInfo:
        """Get the next available proxy using weighted round-robin"""
        async with self._lock:
            # First try to select from only healthy active proxies
            healthy_proxies = [p for p in self.active_proxies if p.alive]
            
            # If no healthy proxies in active set, try all healthy proxies
            if not healthy_proxies:
                logger.warning("No healthy proxies in active set, checking all proxies")
                healthy_proxies = [p for p in self.all_proxies if p.alive]
            
            # If still no healthy proxies, try to use any active proxy
            if not healthy_proxies:
                logger.warning("No healthy proxies available, trying to use any active proxy")
                healthy_proxies = self.active_proxies
            
            # Last resort: try any proxy
            if not healthy_proxies:
                logger.warning("No active proxies available, trying any proxy")
                healthy_proxies = self.all_proxies
            
            if not healthy_proxies:
                raise RuntimeError("No proxies available")
            
            # Simple weighted round-robin selection
            total_weight = sum(p.weight for p in healthy_proxies)
            if total_weight == 0:
                # If all weights are 0, use equal weights
                selected = healthy_proxies[self._index % len(healthy_proxies)]
                self._index = (self._index + 1) % len(healthy_proxies)
            else:
                # Weighted selection
                r = random.randint(1, total_weight)
                for proxy in healthy_proxies:
                    r -= proxy.weight
                    if r <= 0:
                        selected = proxy
                        break
                else:
                    # Fallback if something went wrong with the weighting
                    selected = random.choice(healthy_proxies)
            
            logger.debug(f"Selected proxy {selected} for {target_host}:{target_port}")
            return selected
    
    async def _health_check_loop(self) -> None:
        """Periodically check the health of all proxies and optimize if needed"""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                await self._check_all_proxies()
                
                # Optimize proxy usage if auto-optimize is enabled
                if self.auto_optimize and self.bandwidth_tester:
                    current_time = time.time()
                    if current_time - self.last_optimization_time >= self.optimization_interval:
                        await self._optimize_proxy_usage()
                        self.last_optimization_time = current_time
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
    
    async def _check_all_proxies(self) -> None:
        """Check the health of all proxies"""
        tasks = []
        for proxy in self.all_proxies:
            tasks.append(self._check_proxy(proxy))
        
        # Run health checks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Update proxy statuses
        alive_count = 0
        for i, proxy in enumerate(self.all_proxies):
            if isinstance(results[i], Exception):
                logger.debug(f"Health check for {proxy} failed: {results[i]}")
                proxy.mark_failed()
            else:
                alive_count += 1
        
        logger.info(f"Health check completed: {alive_count}/{len(self.all_proxies)} proxies alive")
    
    async def _optimize_proxy_usage(self) -> None:
        """Dynamically adjust which proxies are active based on bandwidth needs"""
        logger.info("Optimizing proxy usage based on bandwidth")
        
        try:
            # Measure user's direct connection speed
            user_bandwidth = await self.bandwidth_tester.measure_connection_speed()
            if user_bandwidth <= 0:
                logger.warning("Couldn't measure user bandwidth, using all healthy proxies")
                return
                
            # Measure average proxy speed using a sample of proxies
            healthy_proxies = [p for p in self.all_proxies if p.alive]
            if not healthy_proxies:
                logger.warning("No healthy proxies available for optimization")
                return
                
            await self.bandwidth_tester.measure_proxy_speeds(healthy_proxies)
            
            # Calculate how many proxies we need
            optimal_count = self.bandwidth_tester.calculate_optimal_proxy_count(healthy_proxies)
            
            # Select best proxies based on latency
            sorted_proxies = sorted(healthy_proxies, key=lambda p: p.latency)
            self.active_proxies = sorted_proxies[:optimal_count]
            
            logger.info(f"Optimized to use {len(self.active_proxies)} proxies out of {len(healthy_proxies)} healthy proxies")
        except Exception as e:
            logger.error(f"Error optimizing proxy usage: {e}")
            # Fallback to using all healthy proxies
            self.active_proxies = [p for p in self.all_proxies if p.alive]
    
    async def _check_proxy(self, proxy: ProxyInfo) -> bool:
        """Check if a proxy is alive by connecting to a known host"""
        from python_socks.async_.asyncio import Proxy
        
        test_host = "1.1.1.1"  # Cloudflare DNS as a reliable test target
        test_port = 53  # DNS port
        
        # Map protocol to proxy type (SOCKS4 = 1, SOCKS5 = 2)
        proxy_type = 1 if proxy.protocol.startswith('socks4') else 2
        
        # Determine if remote DNS resolution should be used
        # For SOCKS4a and SOCKS5h, DNS resolution should happen on the proxy server
        rdns = proxy.protocol in ('socks4a', 'socks5h')
        
        try:
            # Create a proxy connector
            proxy_connector = Proxy(
                proxy_type=proxy_type,
                host=proxy.host,
                port=proxy.port,
                username=proxy.username,
                password=proxy.password,
                rdns=rdns
            )
            
            start_time = time.time()
            
            # Try to connect through the proxy
            stream = await asyncio.wait_for(
                proxy_connector.connect(dest_host=test_host, dest_port=test_port),
                timeout=5  # 5 second timeout
            )
            
            # Measure latency
            latency = time.time() - start_time
            proxy.update_latency(latency)
            
            # Close the connection
            await stream.close()
            
            # Mark proxy as successful
            proxy.mark_successful()
            logger.debug(f"Proxy {proxy} is alive (latency: {latency:.3f}s)")
            return True
            
        except (asyncio.TimeoutError, socket.error) as e:
            logger.debug(f"Proxy {proxy} health check failed: {e}")
            proxy.mark_failed()
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking proxy {proxy}: {e}")
            proxy.mark_failed()
            return False
    
    async def start(self):
        """Start the health check task. Must be called from an async context."""
        if self._health_check_task is None:
            self._health_check_task = asyncio.create_task(self._health_check_loop())
    
    async def start_continuous_optimization(self, interval: int = 60, progress_callback: Optional[Callable[[str, dict], None]] = None):
        """Start continuous bandwidth/proxy optimization with progress reporting."""
        if not self.bandwidth_tester:
            from multisocks.bandwidth import BandwidthTester
            self.bandwidth_tester = BandwidthTester()
        await self.bandwidth_tester.run_continuous_optimization(self.all_proxies, interval, progress_callback) 