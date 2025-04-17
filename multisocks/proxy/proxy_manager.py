import asyncio
import logging
import random
import time
from typing import Dict, List, Optional, Tuple
import socket

from .proxy_info import ProxyInfo

logger = logging.getLogger(__name__)

class ProxyManager:
    """Manages multiple SOCKS proxies, handling dispatch and health monitoring"""
    
    def __init__(self, proxies: List[ProxyInfo]):
        """Initialize with a list of proxies"""
        if not proxies:
            raise ValueError("At least one proxy must be provided")
        
        self.proxies = proxies
        self._index = 0
        self._total_weight = sum(p.weight for p in proxies)
        self._lock = asyncio.Lock()
        
        # Start health check task
        self._health_check_task = asyncio.create_task(self._health_check_loop())
    
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
            # First try to select from only healthy proxies
            healthy_proxies = [p for p in self.proxies if p.alive]
            
            # If no healthy proxies, try to use any proxy
            if not healthy_proxies:
                logger.warning("No healthy proxies available, trying to use any proxy")
                healthy_proxies = self.proxies
            
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
        """Periodically check the health of all proxies"""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                await self._check_all_proxies()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
    
    async def _check_all_proxies(self) -> None:
        """Check the health of all proxies"""
        tasks = []
        for proxy in self.proxies:
            tasks.append(self._check_proxy(proxy))
        
        # Run health checks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Update proxy statuses
        alive_count = 0
        for i, proxy in enumerate(self.proxies):
            if isinstance(results[i], Exception):
                logger.debug(f"Health check for {proxy} failed: {results[i]}")
                proxy.mark_failed()
            else:
                alive_count += 1
        
        logger.info(f"Health check completed: {alive_count}/{len(self.proxies)} proxies alive")
    
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