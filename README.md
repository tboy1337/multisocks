# MultiSocks

A SOCKS proxy that aggregates multiple remote SOCKS proxies, distributing traffic across them to increase overall bandwidth.

## What MultiSocks Can Do

- **Connection Distribution**: Routes different TCP connections through different proxies using a round-robin or weighted load balancing approach
- **Increased Total Bandwidth**: Improves overall throughput for applications that make multiple concurrent connections
- **Automatic Proxy Management**: Handles failed or slow proxies by routing around them
- **Dynamic Optimization**: Automatically adjusts how many proxies to use based on your bandwidth needs
- **Protocol Support**: Works with SOCKS4, SOCKS4a, SOCKS5, and SOCKS5h protocols
- **Detailed Logging**: Provides visibility into proxy performance and connection routing

## What MultiSocks Cannot Do

- **True Channel Bonding**: Cannot split a single TCP connection across multiple proxies (single-connection speeds won't increase)
- **UDP Bonding**: Does not currently support UDP traffic distribution
- **Transport Layer Bonding**: Doesn't combine connections at the packet level like MPTCP or VPN bonding solutions
- **Custom Protocols**: Only works with applications that support SOCKS proxy configuration

## Ideal Use Cases

MultiSocks works best with:
- Web browsers (which open many connections to different resources)
- Download managers that support multiple connections
- Applications that establish multiple TCP connections
- Scenarios where anonymity through multiple exit points is desired

## Features

- Supports multiple remote SOCKS proxies
- Round-robin or weighted load balancing
- Automatic handling of failed or slow proxies
- Support for SOCKS4, SOCKS4a, SOCKS5, and SOCKS5h protocols
- Detailed logging
- Load proxies from command line or text file
- Auto-optimization to dynamically adjust proxy usage based on bandwidth

## Installation

### From PyPI

```bash
pip install multisocks
```

### From Source

```bash
git clone https://github.com/tboy1337/multisocks.git
cd multisocks
pip install -r requirements.txt
```

## Usage

```bash
# Show help
multisocks --help

# Show version
multisocks --version

# Start the proxy server with multiple remote proxies specified on the command line
multisocks start --port 1080 --proxies socks5://user:pass@proxy1.example.com:1080/10 socks5h://proxy2.example.com:1080/5

# Start the proxy server with proxies loaded from a text file
multisocks start --port 1080 --proxy-file proxies.txt

# Start with auto-optimization (automatically adjusts how many proxies to use based on your connection speed)
multisocks start --port 1080 --proxy-file proxies.txt --auto-optimize
```

### Proxy Format

Proxies are specified in the format: `protocol://[username:password@]hostname:port[/weight]`

- `protocol`: Either `socks4`, `socks4a`, `socks5`, or `socks5h`
- `username:password`: Optional authentication for SOCKS5/SOCKS5h
- `hostname`: The proxy server hostname or IP address
- `port`: The proxy server port
- `weight`: Optional priority weight (default: 1)

### Protocol Information

- `socks4`: Basic SOCKS4 protocol with IP addresses only
- `socks4a`: Extended SOCKS4 with hostname resolution on the proxy server
- `socks5`: SOCKS5 protocol with hostname resolution on the client
- `socks5h`: SOCKS5 protocol with hostname resolution on the proxy server (useful for avoiding DNS leaks)

### Proxy File Format

You can specify proxies in a text file, with one proxy per line:

```
# This is a comment
socks5://user:pass@proxy1.example.com:1080/10
socks5h://proxy2.example.com:1080/5
socks4://proxy3.example.com:1080
```

- Empty lines are ignored
- Lines starting with `#` are treated as comments and ignored

### Auto-Optimization

When enabled with the `--auto-optimize` flag, MultiSocks will:

1. Measure your direct connection speed
2. Test the speed of your proxies
3. Automatically determine how many proxies to use to saturate your connection
4. Periodically adjust the active proxy count based on network conditions

This feature is especially useful when:
- You have a large list of proxies but don't want to manually configure how many to use
- Your internet connection speed varies throughout the day
- You want to maximize your connection bandwidth without manual tuning

Auto-optimization is re-evaluated every 10 minutes to adjust to changing network conditions.

## Development

### Setup Development Environment

```bash
git clone https://github.com/tboy1337/multisocks.git
cd multisocks
pip install -r requirements.txt
```

### Run Tests

```bash
python -m unittest discover tests
```

## License

This project is licensed under the CRL License - see the [LICENSE.md](LICENSE.md) file for details.
