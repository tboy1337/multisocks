#!/usr/bin/env python3
"""Command-line interface for MultiSocks proxy server."""
import argparse
import asyncio
import logging
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from colorama import Fore, Style
from colorama import init as colorama_init

from multisocks.proxy import ProxyInfo, ProxyManager, SocksServer
from multisocks import __version__

# Initialize colorama for cross-platform colored terminal output
colorama_init()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("multisocks")


def _extract_weight(proxy_str: str) -> Tuple[str, int]:
    """Extract weight from proxy string, return (proxy_str_without_weight, weight)"""
    weight = 1
    weight_match = re.search(r"/(-?\d+)$", proxy_str)
    if weight_match:
        try:
            potential_weight = int(weight_match.group(1))
            if potential_weight <= 0:
                raise ValueError("Weight must be a positive integer")
            weight = potential_weight
            proxy_str = proxy_str[: weight_match.start()]
        except ValueError as e:
            if "Weight must be a positive integer" in str(e):
                raise e
    return proxy_str, weight


def _validate_protocol(protocol: str) -> None:
    """Validate that the protocol is supported"""
    if protocol not in ("socks4", "socks4a", "socks5", "socks5h"):
        raise ValueError(f"Unsupported protocol: {protocol}")


def _parse_auth(auth_part: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse authentication part, return (username, password)"""
    if not auth_part:
        return None, None
    if ":" in auth_part:
        parts = auth_part.split(":", 1)
        return parts[0], parts[1] if len(parts) > 1 else None
    return auth_part, None


def _validate_port(port_str: str) -> int:
    """Validate and parse port number"""
    try:
        port = int(port_str)
        if port < 1 or port > 65535:
            raise ValueError(f"Invalid port number: {port_str}")
        return port
    except ValueError as exc:
        raise ValueError(f"Invalid port number: {port_str}") from exc


def parse_proxy_string(proxy_str: str) -> ProxyInfo:
    """Parse a proxy string in the format protocol://[user:pass@]host:port[/weight]"""
    original_proxy_str = proxy_str

    # Extract weight
    proxy_str, weight = _extract_weight(proxy_str)

    # Split by '://' to separate protocol from the rest
    if "://" not in proxy_str:
        raise ValueError(f"Invalid proxy format: {original_proxy_str}")

    protocol_part, rest = proxy_str.split("://", 1)
    _validate_protocol(protocol_part)

    # Find the last '@' to separate auth from host:port
    auth_part, host_port = rest.rsplit("@", 1) if "@" in rest else (None, rest)

    # Parse host and port
    if ":" not in host_port:
        raise ValueError(f"Invalid proxy format: {original_proxy_str}")

    host, port_str = host_port.rsplit(":", 1)
    if not host:
        raise ValueError(f"Invalid proxy format: {original_proxy_str}")

    # Parse authentication and port
    username, password = _parse_auth(auth_part)
    port = _validate_port(port_str)

    return ProxyInfo(
        protocol=protocol_part,
        host=host,
        port=port,
        username=username,
        password=password,
        weight=weight,
    )


async def start_server(
    bind_host: str,
    bind_port: int,
    proxies: List[ProxyInfo],
    debug: bool,
    auto_optimize: bool,
) -> None:
    """Start the SOCKS proxy server"""
    # Configure debug logging if enabled
    if debug:
        logging.getLogger().setLevel(logging.DEBUG)

    proxy_manager = ProxyManager(proxies, auto_optimize=auto_optimize)
    await proxy_manager.start()
    server = SocksServer(proxy_manager)

    def progress_callback(event: str, data: Dict[str, Any]) -> None:
        if event == "cycle_start":
            print(
                f"{Fore.YELLOW}--- Bandwidth/Proxy Optimization Cycle Started ---{Style.RESET_ALL}"
            )
        elif event == "user_bandwidth_progress":
            mb_downloaded = data.get('bytes', 0) // 1024 // 1024
            print(
                f"{Fore.CYAN}Testing user bandwidth: {mb_downloaded} MB downloaded..."
                f"{Style.RESET_ALL}",
                end="\r",
            )
        elif event == "user_bandwidth_done":
            print(
                f"{Fore.GREEN}User bandwidth: {data.get('mbps', 0):.2f} Mbps{Style.RESET_ALL}"
            )
        elif event == "proxy_bandwidth_progress":
            proxy = data.get('proxy', '')
            mb_downloaded = data.get('bytes', 0) // 1024 // 1024
            print(
                f"{Fore.CYAN}Testing proxy {proxy}: {mb_downloaded} MB...{Style.RESET_ALL}",
                end="\r",
            )
        elif event == "proxy_bandwidth_done":
            print(
                f"{Fore.GREEN}Proxy {data.get('proxy', '')} bandwidth: {data.get('mbps', 0):.2f} Mbps{Style.RESET_ALL}"
            )
        elif event == "proxy_bandwidth_avg":
            print(
                f"{Fore.GREEN}Average proxy bandwidth: {data.get('mbps', 0):.2f} Mbps{Style.RESET_ALL}"
            )
        elif event == "cycle_done":
            user_mbps = data.get('user_bandwidth_mbps', 0)
            proxy_avg_mbps = data.get('proxy_avg_bandwidth_mbps', 0)
            optimal_count = data.get('optimal_proxy_count', 0)
            total_proxies = data.get('total_proxies', 0)
            print(
                f"{Fore.YELLOW}Cycle done. User: {user_mbps:.2f} Mbps, "
                f"Proxy avg: {proxy_avg_mbps:.2f} Mbps, "
                f"Optimal proxies: {optimal_count}/{total_proxies}{Style.RESET_ALL}"
            )

    try:
        if auto_optimize:
            # Start continuous optimization in the background
            asyncio.create_task(
                proxy_manager.start_continuous_optimization(
                    progress_callback=progress_callback
                )
            )
        await server.start(bind_host, bind_port)
    except asyncio.CancelledError:
        logger.info("Server shutdown initiated")
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Server error: %s", e)
    finally:
        await server.stop()


def read_proxies_from_file(file_path: str) -> List[str]:
    """Read proxy strings from a text file (one per line)"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            # Read lines, strip whitespace, and filter out empty lines and comments
            return [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    except Exception as e:
        raise ValueError(f"Failed to read proxies from file {file_path}: {e}") from e


def main() -> None:
    """Main entry point for the CLI application."""
    parser = argparse.ArgumentParser(
        description="A SOCKS proxy that aggregates multiple remote SOCKS proxies"
    )
    parser.add_argument(
        "--debug", "-d", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "--version", "-v", action="store_true", help="Show version information"
    )

    subparsers = parser.add_subparsers(dest="command")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start the SOCKS proxy server")
    start_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Which IP to accept connections from (default: 127.0.0.1)",
    )
    start_parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=1080,
        help="Which port to listen on for connections (default: 1080)",
    )
    start_parser.add_argument(
        "--auto-optimize",
        "-a",
        action="store_true",
        help="Automatically optimize the number of proxies used based on connection speed",
    )

    # Create a mutually exclusive group for proxy specification
    proxy_group = start_parser.add_mutually_exclusive_group(required=True)
    proxy_group.add_argument(
        "--proxies",
        "-x",
        nargs="+",
        help="Remote proxies to dispatch to, in the form of protocol://[user:pass@]host:port[/weight]",
    )
    proxy_group.add_argument(
        "--proxy-file",
        "-f",
        help="Path to a text file containing proxy strings (one per line)",
    )

    args = parser.parse_args()

    if args.version:
        print(f"MultiSocks version {__version__}")
        return

    if not args.command:
        parser.print_help()
        return

    if args.command == "start":
        try:
            # Get proxy strings, either from command line or from file
            if args.proxies:
                proxy_strings = args.proxies
            else:  # args.proxy_file is set due to mutually exclusive group
                proxy_strings = read_proxies_from_file(args.proxy_file)

                if not proxy_strings:
                    print(
                        f"{Fore.RED}Error: No valid proxy strings found in file {args.proxy_file}{Style.RESET_ALL}"
                    )
                    sys.exit(1)

            # Parse proxy strings
            proxies = [parse_proxy_string(p) for p in proxy_strings]

            # Start proxy server
            print(
                f"{Fore.GREEN}Starting SOCKS proxy server on {args.host}:{args.port}{Style.RESET_ALL}"
            )

            if args.auto_optimize:
                print(
                    f"{Fore.YELLOW}Auto-optimization enabled: The proxy will dynamically "
                    f"adjust how many proxies to use{Style.RESET_ALL}"
                )

            print(f"Loaded {len(proxies)} proxies:")
            for proxy in proxies[:5]:  # Show first 5 proxies
                print(f"  - {Fore.CYAN}{proxy}{Style.RESET_ALL}")

            if len(proxies) > 5:
                print(
                    f"  - {Fore.CYAN}... and {len(proxies) - 5} more{Style.RESET_ALL}"
                )

            # Run the event loop
            asyncio.run(
                start_server(
                    args.host, args.port, proxies, args.debug, args.auto_optimize
                )
            )
        except ValueError as e:
            print(f"{Fore.RED}Error: {e}{Style.RESET_ALL}")
            sys.exit(1)
        except KeyboardInterrupt:
            print(f"{Fore.YELLOW}Server stopped by user{Style.RESET_ALL}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
