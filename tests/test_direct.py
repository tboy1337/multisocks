#!/usr/bin/env python3
import asyncio
import sys
import logging
import socket
import time
from typing import List

from multisocks.proxy import ProxyInfo, ProxyManager, SocksServer

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('multisocks.test')

async def test_proxy_connection(proxy_info):
    """Test direct connection to a proxy to verify it's working"""
    try:
        print(f"Testing direct connection to proxy: {proxy_info}")
        start_time = time.time()
        
        # Create a socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        
        # Connect to the proxy
        print(f"Connecting to {proxy_info.host}:{proxy_info.port}...")
        sock.connect((proxy_info.host, proxy_info.port))
        print(f"Connected successfully to {proxy_info.host}:{proxy_info.port}!")
        
        # Close the socket
        sock.close()
        
        duration = time.time() - start_time
        print(f"Connection test completed in {duration:.2f} seconds")
        return True
    except Exception as e:
        print(f"Error connecting to proxy {proxy_info.host}:{proxy_info.port}: {e}")
        return False

async def start_test():
    """Test multisocks with our proxies directly without relying on CLI parsing"""
    # Define proxies directly
    proxies = [
        ProxyInfo(
            protocol="socks5",
            host="198.23.239.134",
            port=6540,
            username="ycbsecom",
            password="2ko7lmoinygi",
            weight=1
        ),
        ProxyInfo(
            protocol="socks5",
            host="207.244.217.165",
            port=6712,
            username="ycbsecom",
            password="2ko7lmoinygi",
            weight=1
        ),
        ProxyInfo(
            protocol="socks5",
            host="107.172.163.27",
            port=6543,
            username="ycbsecom",
            password="2ko7lmoinygi",
            weight=1
        ),
        # Add more if needed
    ]
    
    print(f"Starting test with {len(proxies)} proxies")
    
    # First, test direct connections to each proxy
    print("\n=== Testing direct connections to proxies ===")
    working_proxies = []
    for proxy in proxies:
        result = await test_proxy_connection(proxy)
        if result:
            working_proxies.append(proxy)
    
    print(f"\nFound {len(working_proxies)}/{len(proxies)} working proxies")
    
    if not working_proxies:
        print("No working proxies found. Cannot start the server.")
        return
    
    print("\n=== Starting SOCKS server with working proxies ===")
    proxy_manager = ProxyManager(working_proxies)
    
    try:
        print("Starting proxy manager...")
        await proxy_manager.start()
        
        print("Creating SOCKS server...")
        server = SocksServer(proxy_manager)
        
        bind_host = "127.0.0.1"
        bind_port = 1080
        
        print(f"Starting SOCKS server on {bind_host}:{bind_port}")
        await server.start(bind_host, bind_port)
        print(f"Server started successfully! Press Ctrl+C to stop.")
        
        # Keep the server running until interrupted
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Server shutdown initiated by user")
    except Exception as e:
        print(f"Server error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Stopping server...")
        try:
            await server.stop()
            print("Server stopped")
        except Exception as e:
            print(f"Error stopping server: {e}")

def main():
    """Main entry point"""
    try:
        asyncio.run(start_test())
    except KeyboardInterrupt:
        print("Test interrupted by user")
        return 0
    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main()) 