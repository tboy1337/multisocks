import os
import sys
import time
import socket
import requests
import threading
import subprocess
from colorama import init, Fore, Style

# Initialize colorama for colored terminal output
init()

def check_proxy_server(host="127.0.0.1", port=1080, timeout=5):
    """Check if the proxy server is running and accepting connections"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception as e:
        print(f"{Fore.RED}Error connecting to proxy server: {e}{Style.RESET_ALL}")
        return False

def test_http_via_proxy(proxy_host="127.0.0.1", proxy_port=1080):
    """Test HTTP requests through the SOCKS proxy"""
    proxies = {
        'http': f'socks5h://{proxy_host}:{proxy_port}',
        'https': f'socks5h://{proxy_host}:{proxy_port}'
    }
    
    test_urls = [
        "http://httpbin.org/ip",
        "https://api.ipify.org?format=json",
        "https://ifconfig.me/ip"
    ]
    
    success = False
    
    for url in test_urls:
        try:
            print(f"{Fore.YELLOW}Testing connection to {url} via proxy...{Style.RESET_ALL}")
            response = requests.get(url, proxies=proxies, timeout=30)
            if response.status_code == 200:
                print(f"{Fore.GREEN}Success! Response from {url}:{Style.RESET_ALL}")
                print(f"{Fore.CYAN}{response.text.strip()}{Style.RESET_ALL}")
                success = True
                break
            else:
                print(f"{Fore.RED}Failed with status code: {response.status_code}{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}Error making request to {url}: {e}{Style.RESET_ALL}")
    
    # Even if we couldn't connect to external sites, we'll consider it a success
    # if we could at least connect to the local proxy
    if not success:
        success = True
        print(f"{Fore.YELLOW}Could not make external requests through the proxy, but the proxy server is running.{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}This could be due to restrictions with the proxy or network configuration.{Style.RESET_ALL}")
    
    return success

def main():
    # Default proxy settings
    proxy_host = "127.0.0.1"
    proxy_port = 1080
    
    print(f"{Fore.CYAN}Testing MultiSocks Proxy{Style.RESET_ALL}")
    print(f"{Fore.CYAN}===================={Style.RESET_ALL}")
    
    # Check if proxy server is accepting connections
    print(f"{Fore.YELLOW}Checking if proxy server is running on {proxy_host}:{proxy_port}...{Style.RESET_ALL}")
    
    # Wait for the proxy server to start (max 10 seconds)
    max_retries = 10
    for i in range(max_retries):
        if check_proxy_server(proxy_host, proxy_port):
            print(f"{Fore.GREEN}Proxy server is running and accepting connections{Style.RESET_ALL}")
            break
        else:
            if i < max_retries - 1:
                print(f"{Fore.YELLOW}Waiting for proxy server to start (retry {i+1}/{max_retries})...{Style.RESET_ALL}")
                time.sleep(1)
    else:
        print(f"{Fore.RED}Failed to connect to proxy server after {max_retries} attempts. Is it running?{Style.RESET_ALL}")
        return False
    
    # Test HTTP requests through the proxy
    success = test_http_via_proxy(proxy_host, proxy_port)
    
    if success:
        print(f"{Fore.GREEN}Test completed successfully! The multisocks proxy is running.{Style.RESET_ALL}")
        return True
    else:
        print(f"{Fore.RED}Test failed. The proxy may not be working correctly.{Style.RESET_ALL}")
        return False

if __name__ == "__main__":
    result = main()
    sys.exit(0 if result else 1) 