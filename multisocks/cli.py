#!/usr/bin/env python3
import argparse
import asyncio
import logging
import re
import sys
from typing import List, Optional, Tuple

from colorama import Fore, Style, init as colorama_init

from multisocks.proxy import ProxyManager, ProxyInfo, SocksServer

# Initialize colorama for cross-platform colored terminal output
colorama_init()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('multisocks')

def parse_proxy_string(proxy_str: str) -> ProxyInfo:
    """Parse a proxy string in the format protocol://[user:pass@]host:port[/weight]"""
    # Parse weight if present
    weight_parts = proxy_str.split('/', 1)
    weight = 1
    if len(weight_parts) > 1:
        try:
            weight = int(weight_parts[1])
            if weight <= 0:
                raise ValueError("Weight must be a positive integer")
        except ValueError:
            raise ValueError(f"Invalid weight format in proxy specification: {proxy_str}")
        proxy_str = weight_parts[0]
    
    # Match protocol://[user:pass@]host:port
    match = re.match(r'^(socks[45]a?h?)://(?:([^:@]+)(?::([^@]+))?@)?([^:]+):(\d+)$', proxy_str)
    if not match:
        raise ValueError(f"Invalid proxy format: {proxy_str}")
    
    protocol, username, password, host, port_str = match.groups()
    
    # Validate protocol
    if protocol not in ('socks4', 'socks4a', 'socks5', 'socks5h'):
        raise ValueError(f"Unsupported protocol: {protocol}")
    
    try:
        port = int(port_str)
        if port < 1 or port > 65535:
            raise ValueError()
    except ValueError:
        raise ValueError(f"Invalid port number: {port_str}")
    
    return ProxyInfo(
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password=password,
        weight=weight
    )

async def start_server(bind_host: str, bind_port: int, proxies: List[ProxyInfo], debug: bool, auto_optimize: bool) -> None:
    """Start the SOCKS proxy server"""
    # Configure debug logging if enabled
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    proxy_manager = ProxyManager(proxies, auto_optimize=auto_optimize)
    server = SocksServer(proxy_manager)

    async def progress_callback(event: str, data: dict):
        if event == "cycle_start":
            print(f"{Fore.YELLOW}--- Bandwidth/Proxy Optimization Cycle Started ---{Style.RESET_ALL}")
        elif event == "user_bandwidth_progress":
            print(f"{Fore.CYAN}Testing user bandwidth: {data.get('bytes', 0)//1024//1024} MB downloaded...{Style.RESET_ALL}", end='\r')
        elif event == "user_bandwidth_done":
            print(f"{Fore.GREEN}User bandwidth: {data.get('mbps', 0):.2f} Mbps{Style.RESET_ALL}")
        elif event == "proxy_bandwidth_progress":
            print(f"{Fore.CYAN}Testing proxy {data.get('proxy', '')}: {data.get('bytes', 0)//1024//1024} MB...{Style.RESET_ALL}", end='\r')
        elif event == "proxy_bandwidth_done":
            print(f"{Fore.GREEN}Proxy {data.get('proxy', '')} bandwidth: {data.get('mbps', 0):.2f} Mbps{Style.RESET_ALL}")
        elif event == "proxy_bandwidth_avg":
            print(f"{Fore.GREEN}Average proxy bandwidth: {data.get('mbps', 0):.2f} Mbps{Style.RESET_ALL}")
        elif event == "cycle_done":
            print(f"{Fore.YELLOW}Cycle done. User: {data.get('user_bandwidth_mbps', 0):.2f} Mbps, Proxy avg: {data.get('proxy_avg_bandwidth_mbps', 0):.2f} Mbps, Optimal proxies: {data.get('optimal_proxy_count', 0)}/{data.get('total_proxies', 0)}{Style.RESET_ALL}")

    try:
        if auto_optimize:
            # Start continuous optimization in the background
            asyncio.create_task(proxy_manager.start_continuous_optimization(progress_callback=progress_callback))
        await server.start(bind_host, bind_port)
    except asyncio.CancelledError:
        logger.info("Server shutdown initiated")
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        await server.stop()

def read_proxies_from_file(file_path: str) -> List[str]:
    """Read proxy strings from a text file (one per line)"""
    try:
        with open(file_path, 'r') as f:
            # Read lines, strip whitespace, and filter out empty lines and comments
            return [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    except Exception as e:
        raise ValueError(f"Failed to read proxies from file {file_path}: {e}")

def main() -> None:
    parser = argparse.ArgumentParser(description="A SOCKS proxy that aggregates multiple remote SOCKS proxies")
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug logging')
    parser.add_argument('--version', '-v', action='store_true', help='Show version information')
    
    subparsers = parser.add_subparsers(dest='command')
    
    # Start command
    start_parser = subparsers.add_parser('start', help='Start the SOCKS proxy server')
    start_parser.add_argument('--host', default='127.0.0.1', 
                              help='Which IP to accept connections from (default: 127.0.0.1)')
    start_parser.add_argument('--port', '-p', type=int, default=1080,
                             help='Which port to listen on for connections (default: 1080)')
    start_parser.add_argument('--auto-optimize', '-a', action='store_true',
                             help='Automatically optimize the number of proxies used based on connection speed')
    
    # Create a mutually exclusive group for proxy specification
    proxy_group = start_parser.add_mutually_exclusive_group(required=True)
    proxy_group.add_argument('--proxies', '-x', nargs='+',
                             help='Remote proxies to dispatch to, in the form of protocol://[user:pass@]host:port[/weight]')
    proxy_group.add_argument('--proxy-file', '-f', 
                             help='Path to a text file containing proxy strings (one per line)')
    
    args = parser.parse_args()
    
    if args.version:
        from multisocks import __version__
        print(f"MultiSocks version {__version__}")
        return
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'start':
        try:
            # Get proxy strings, either from command line or from file
            if args.proxies:
                proxy_strings = args.proxies
            else:  # args.proxy_file is set due to mutually exclusive group
                proxy_strings = read_proxies_from_file(args.proxy_file)
                
                if not proxy_strings:
                    print(f"{Fore.RED}Error: No valid proxy strings found in file {args.proxy_file}{Style.RESET_ALL}")
                    sys.exit(1)
            
            # Parse proxy strings
            proxies = [parse_proxy_string(p) for p in proxy_strings]
            
            # Start proxy server
            print(f"{Fore.GREEN}Starting SOCKS proxy server on {args.host}:{args.port}{Style.RESET_ALL}")
            
            if args.auto_optimize:
                print(f"{Fore.YELLOW}Auto-optimization enabled: The proxy will dynamically adjust how many proxies to use{Style.RESET_ALL}")
            
            print(f"Loaded {len(proxies)} proxies:")
            for proxy in proxies[:5]:  # Show first 5 proxies
                print(f"  - {Fore.CYAN}{proxy}{Style.RESET_ALL}")
            
            if len(proxies) > 5:
                print(f"  - {Fore.CYAN}... and {len(proxies) - 5} more{Style.RESET_ALL}")
            
            # Run the event loop
            asyncio.run(start_server(args.host, args.port, proxies, args.debug, args.auto_optimize))
        except ValueError as e:
            print(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")
            sys.exit(1)
        except KeyboardInterrupt:
            print(f"{Fore.YELLOW}Server stopped by user{Style.RESET_ALL}")
    else:
        parser.print_help()

if __name__ == '__main__':
    main() 