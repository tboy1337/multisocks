"""Proxy information class for SOCKS proxy configuration."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProxyInfo:
    """Class representing a SOCKS proxy configuration"""

    protocol: str  # socks4, socks4a, socks5, or socks5h
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    weight: int = 1

    # For tracking proxy health
    alive: bool = True
    fail_count: int = 0
    latency: float = 0.0

    def __str__(self) -> str:
        """String representation of the proxy for display"""
        auth = f"{self.username}:{self.password}@" if self.username else ""
        weight_str = f"/{self.weight}" if self.weight != 1 else ""
        return f"{self.protocol}://{auth}{self.host}:{self.port}{weight_str}"

    def connection_string(self) -> str:
        """Get the connection string without the weight"""
        auth = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    def get_protocol_version(self) -> int:
        """Get the SOCKS protocol version as an integer"""
        if self.protocol.startswith("socks4"):
            return 4
        if self.protocol in ("socks5", "socks5h"):
            return 5
        raise ValueError(f"Unsupported protocol: {self.protocol}")

    def mark_failed(self) -> None:
        """Mark the proxy as having failed a connection attempt"""
        self.fail_count += 1
        if self.fail_count >= 3:  # Consider a proxy dead after 3 failures
            self.alive = False

    def mark_successful(self) -> None:
        """Reset failure counter after a successful connection"""
        self.fail_count = 0
        self.alive = True

    def update_latency(self, latency: float) -> None:
        """Update the proxy's latency (in seconds)"""
        # Simple smoothing to avoid drastic changes
        if self.latency == 0.0:
            self.latency = latency
        else:
            self.latency = (self.latency * 0.7) + (latency * 0.3)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProxyInfo):
            return False
        return (
            self.protocol == other.protocol
            and self.host == other.host
            and self.port == other.port
            and self.username == other.username
            and self.password == other.password
            and self.weight == other.weight
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.protocol,
                self.host,
                self.port,
                self.username,
                self.password,
                self.weight,
            )
        )
