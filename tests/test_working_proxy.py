#!/usr/bin/env python3
import asyncio
import sys
import logging
import time

from multisocks.proxy import ProxyInfo, ProxyManager, SocksServer

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('multisocks.test')

async def start_test():
    """Test multisocks with only the working proxy"""
    # Define the one working proxy directly
    proxies = [
        ProxyInfo(
            protocol="socks5",
            host="198.23.239.134",
            port=6540,
            username="ycbsecom",
            password="2ko7lmoinygi",
            weight=1
        )
    ]
    
    print(f"Starting proxy manager with the working proxy:")
    for proxy in proxies:
        print(f"  - {proxy}")
    
    # Create and start the proxy manager
    proxy_manager = ProxyManager(proxies)
    await proxy_manager.start()
    
    # Create and start the SOCKS server
    server = SocksServer(proxy_manager)
    
    bind_host = "127.0.0.1"
    bind_port = 1080
    
    try:
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