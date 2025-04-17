# MultiSocks

A SOCKS proxy that aggregates multiple remote SOCKS proxies, increasing your bandwidth by distributing traffic across them.

## Features

- Supports multiple remote SOCKS proxies
- Round-robin or weighted load balancing
- Automatic handling of failed or slow proxies
- Support for SOCKS4, SOCKS4a, SOCKS5, and SOCKS5h protocols
- Detailed logging

## Installation

### From PyPI

```bash
pip install multisocks
```

### From Source

```bash
git clone https://github.com/yourusername/multisocks.git
cd multisocks
pip install -e .
```

## Usage

```bash
# Show help
multisocks --help

# Show version
multisocks --version

# Start the proxy server with multiple remote proxies
multisocks start --port 1080 --proxies socks5://user:pass@proxy1.example.com:1080/10 socks5h://proxy2.example.com:1080/5
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

## Development

### Setup Development Environment

```bash
git clone https://github.com/yourusername/multisocks.git
cd multisocks
pip install -e .
```

### Run Tests

```bash
python -m unittest discover tests
```

## PyPI Package

This project is available on PyPI: [multisocks](https://pypi.org/project/multisocks/)

## License

This project is licensed under the MIT License - see the LICENSE file for details.
