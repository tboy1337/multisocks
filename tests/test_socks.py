#!/usr/bin/env python3
import sys
import time
import socket
import logging
import argparse
import requests
from urllib.parse import urlparse

try:
    import socks
except ImportError:
    print("PySocks module not found. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PySocks"])
    import socks

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('socks_test')

def parse_proxy_line(line):
    """Parse a proxy line from the proxies.txt file"""
    parts = line.strip().split(':')
    if len(parts) != 4:
        return None
    
    host = parts[0]
    port = int(parts[1])
    username = parts[2]
    password = parts[3]
    
    return {
        'host': host,
        'port': port,
        'username': username,
        'password': password
    }

def test_proxy_connection(proxy_info):
    """Test direct TCP connection to a proxy"""
    try:
        host = proxy_info['host']
        port = proxy_info['port']
        
        logger.info(f"Testing direct connection to {host}:{port}...")
        start_time = time.time()
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))
        sock.close()
        
        duration = time.time() - start_time
        logger.info(f"✓ Connected successfully in {duration:.2f} seconds")
        return True
    except Exception as e:
        logger.error(f"✗ Connection failed: {e}")
        return False

def test_socks_proxy(proxy_info, test_url="https://api.ipify.org?format=json"):
    """Test a SOCKS proxy by making a request through it"""
    try:
        host = proxy_info['host']
        port = proxy_info['port']
        username = proxy_info['username']
        password = proxy_info['password']
        
        logger.info(f"Testing SOCKS5 proxy {host}:{port} with auth...")
        
        # Parse the URL to get the hostname and path
        parsed_url = urlparse(test_url)
        hostname = parsed_url.netloc
        path = parsed_url.path
        if not path:
            path = "/"
        if parsed_url.query:
            path += "?" + parsed_url.query
            
        # Set up a new default socket that uses our proxy
        socks.set_default_proxy(
            proxy_type=socks.SOCKS5, 
            addr=host, 
            port=port,
            username=username,
            password=password
        )
        socket.socket = socks.socksocket
        
        # Make the request using requests (which will use our proxied socket)
        start_time = time.time()
        response = requests.get(test_url, timeout=30)
        duration = time.time() - start_time
        
        if response.status_code == 200:
            logger.info(f"✓ SOCKS proxy test successful in {duration:.2f} seconds")
            logger.info(f"✓ Response: {response.text.strip()}")
            return True
        else:
            logger.error(f"✗ SOCKS proxy test failed with status code: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"✗ SOCKS proxy test failed: {e}")
        return False
    finally:
        # Reset the socket to the default
        socket.socket = socket.socket

def main():
    parser = argparse.ArgumentParser(description="Test SOCKS proxies")
    parser.add_argument('--proxy-file', '-f', default='tests/proxies.txt',
                        help='Path to the proxy file (default: tests/proxies.txt)')
    parser.add_argument('--test-url', '-u', default='https://api.ipify.org?format=json',
                        help='URL to test the proxy with (default: https://api.ipify.org?format=json)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Read the proxies from the file
    try:
        with open(args.proxy_file, 'r') as f:
            proxy_lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except Exception as e:
        logger.error(f"Error reading proxy file: {e}")
        return 1
    
    logger.info(f"Found {len(proxy_lines)} proxies in {args.proxy_file}")
    
    # Parse and test each proxy
    working_proxies = []
    for i, line in enumerate(proxy_lines):
        logger.info(f"Testing proxy {i+1}/{len(proxy_lines)}: {line}")
        proxy_info = parse_proxy_line(line)
        
        if not proxy_info:
            logger.error(f"✗ Invalid proxy format: {line}")
            continue
        
        # First test direct connection
        if test_proxy_connection(proxy_info):
            # Then test SOCKS protocol
            if test_socks_proxy(proxy_info, args.test_url):
                working_proxies.append(proxy_info)
        
        # Add a small delay between tests
        time.sleep(1)
    
    # Summary
    logger.info(f"\n=== Summary ===")
    logger.info(f"Total proxies: {len(proxy_lines)}")
    logger.info(f"Working proxies: {len(working_proxies)}")
    
    if working_proxies:
        logger.info("Working proxies:")
        for i, proxy in enumerate(working_proxies):
            logger.info(f"{i+1}. {proxy['host']}:{proxy['port']}")
        return 0
    else:
        logger.error("No working proxies found")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 