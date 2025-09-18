"""SOCKS proxy server that dispatches to remote proxies."""

import asyncio
import logging
import socket
import struct
import time
from typing import Any, Optional, Tuple

from python_socks.async_.asyncio import Proxy
from python_socks import ProxyType

from .proxy_manager import ProxyManager

# pylint: disable=broad-exception-caught

logger = logging.getLogger(__name__)

# SOCKS protocol constants
SOCKS_VERSION_5 = 0x05
SOCKS_VERSION_4 = 0x04

# SOCKS5 auth methods
SOCKS5_AUTH_NONE = 0x00
SOCKS5_AUTH_GSSAPI = 0x01
SOCKS5_AUTH_USERNAME_PASSWORD = 0x02
SOCKS5_AUTH_NO_ACCEPTABLE_METHODS = 0xFF

# SOCKS5 command codes
SOCKS5_CMD_CONNECT = 0x01
SOCKS5_CMD_BIND = 0x02
SOCKS5_CMD_UDP_ASSOCIATE = 0x03

# SOCKS5 address types
SOCKS5_ATYP_IPV4 = 0x01
SOCKS5_ATYP_DOMAIN = 0x03
SOCKS5_ATYP_IPV6 = 0x04

# SOCKS5 response codes
SOCKS5_RESP_SUCCESS = 0x00
SOCKS5_RESP_GENERAL_FAILURE = 0x01
SOCKS5_RESP_CONNECTION_NOT_ALLOWED = 0x02
SOCKS5_RESP_NETWORK_UNREACHABLE = 0x03
SOCKS5_RESP_HOST_UNREACHABLE = 0x04
SOCKS5_RESP_CONNECTION_REFUSED = 0x05
SOCKS5_RESP_TTL_EXPIRED = 0x06
SOCKS5_RESP_COMMAND_NOT_SUPPORTED = 0x07
SOCKS5_RESP_ADDRESS_TYPE_NOT_SUPPORTED = 0x08

# SOCKS4 response codes
SOCKS4_RESP_SUCCESS = 0x5A
SOCKS4_RESP_REJECTED = 0x5B


class SocksServer:
    """SOCKS proxy server that dispatches to remote proxies"""

    def __init__(self, proxy_manager: ProxyManager) -> None:
        """Initialize with a proxy manager"""
        self.proxy_manager = proxy_manager
        self.server: Optional[asyncio.Server] = None

    async def start(self, host: str, port: int) -> None:
        """Start the SOCKS server"""
        self.server = await asyncio.start_server(
            self._handle_client, host, port, family=socket.AF_INET, reuse_address=True
        )

        if self.server and self.server.sockets:
            addr = self.server.sockets[0].getsockname()
        else:
            addr = (host, port)
        logger.info("SOCKS server started on %s:%s", addr[0], addr[1])

        if self.server:
            async with self.server:
                await self.server.serve_forever()

    async def stop(self) -> None:
        """Stop the SOCKS server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("SOCKS server stopped")

        await self.proxy_manager.stop()

    async def _handle_client(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        """Handle a client connection"""
        client_addr = client_writer.get_extra_info("peername")
        logger.debug("New connection from %s", client_addr)

        try:
            # Read first byte to determine SOCKS version
            version_byte = await client_reader.readexactly(1)
            version = version_byte[0]

            if version == SOCKS_VERSION_5:
                await self._handle_socks5(client_reader, client_writer)
            elif version == SOCKS_VERSION_4:
                await self._handle_socks4(version_byte, client_reader, client_writer)
            else:
                logger.warning("Unsupported SOCKS version: %s", version)
                client_writer.close()

        except asyncio.IncompleteReadError:
            logger.debug("Client %s disconnected during handshake", client_addr)
        except Exception as e:
            logger.error("Error handling client %s: %s", client_addr, e)
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass
            logger.debug("Connection from %s closed", client_addr)

    async def _handle_socks5(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle SOCKS5 protocol"""
        client_addr = writer.get_extra_info("peername")

        # Handle authentication negotiation
        if not await self._handle_socks5_auth(reader, writer, client_addr):
            return

        # Read and validate the connect request
        dest_addr, dest_port = await self._handle_socks5_request(reader, writer)
        if not dest_addr:
            return

        logger.info(
            "SOCKS5 connect request from %s to %s:%s", client_addr, dest_addr, dest_port
        )

        # Connect through proxy and handle data transfer
        await self._handle_socks5_connect(reader, writer, dest_addr, dest_port)

    async def _handle_socks5_auth(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, client_addr: Any
    ) -> bool:
        """Handle SOCKS5 authentication negotiation. Returns True if successful."""
        # Read authentication methods
        num_methods = (await reader.readexactly(1))[0]
        methods = await reader.readexactly(num_methods)

        # We only support no authentication for now
        if SOCKS5_AUTH_NONE not in methods:
            logger.warning(
                "Client %s requested unsupported auth methods: %s", client_addr, methods
            )
            await self._send_socks5_response(writer, SOCKS5_AUTH_NO_ACCEPTABLE_METHODS)
            return False

        # Accept no authentication
        await self._send_socks5_response(writer, SOCKS5_AUTH_NONE)
        return True

    async def _handle_socks5_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> Tuple[Optional[str], int]:
        """Handle SOCKS5 connect request. Returns (dest_addr, dest_port) or (None, 0) on error."""
        # Read the request
        header = await reader.readexactly(4)
        _, cmd, _, atyp = struct.unpack("!BBBB", header)

        if cmd != SOCKS5_CMD_CONNECT:
            logger.warning("Unsupported SOCKS5 command: %s", cmd)
            await self._send_socks5_error_response(writer, SOCKS5_RESP_COMMAND_NOT_SUPPORTED)
            return None, 0

        # Parse destination address
        dest_addr, dest_port = await self._parse_socks5_address(reader, atyp)
        if not dest_addr:
            await self._send_socks5_error_response(writer, SOCKS5_RESP_ADDRESS_TYPE_NOT_SUPPORTED)
            return None, 0

        return dest_addr, dest_port

    async def _handle_socks5_connect(
        self,         reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
        dest_addr: str, dest_port: int
    ) -> None:
        """Handle the actual proxy connection for SOCKS5."""
        try:
            # Get proxy and connect
            proxy_info = await self.proxy_manager.get_proxy(dest_addr, dest_port)
            logger.debug(
                "Using proxy %s to connect to %s:%s", proxy_info, dest_addr, dest_port
            )

            target_stream = await self._connect_through_proxy(proxy_info, dest_addr, dest_port)

            # Send success response
            await self._send_socks5_success_response(writer)

            # Start bidirectional proxy
            await self._proxy_data(reader, writer, target_stream)

        except Exception as e:
            logger.error(
                "Error connecting to destination %s:%s: %s", dest_addr, dest_port, e
            )
            await self._send_socks5_error_response(writer, SOCKS5_RESP_GENERAL_FAILURE)

    async def _send_socks5_response(self, writer: asyncio.StreamWriter, response_code: int) -> None:
        """Send a simple SOCKS5 response (for auth negotiation)."""
        writer.write(struct.pack("!BB", SOCKS_VERSION_5, response_code))
        await writer.drain()

    async def _send_socks5_error_response(self, writer: asyncio.StreamWriter, error_code: int) -> None:
        """Send a SOCKS5 error response."""
        writer.write(
            struct.pack(
                "!BBBBIH",
                SOCKS_VERSION_5,
                error_code,
                0,
                SOCKS5_ATYP_IPV4,
                0,
                0,
            )
        )
        await writer.drain()

    async def _send_socks5_success_response(self, writer: asyncio.StreamWriter) -> None:
        """Send a SOCKS5 success response."""
        bind_addr = socket.inet_aton("0.0.0.0")
        writer.write(
            struct.pack(
                "!BBBB4sH",
                SOCKS_VERSION_5,
                SOCKS5_RESP_SUCCESS,
                0,
                SOCKS5_ATYP_IPV4,
                bind_addr,
                0,
            )
        )
        await writer.drain()

    async def _connect_through_proxy(self, proxy_info: Any, dest_addr: str, dest_port: int) -> Any:
        """Create proxy connection and handle timing/errors."""
        # Create a proxy connector
        proxy_type = ProxyType.SOCKS5 if proxy_info.protocol in ("socks5", "socks5h") else ProxyType.SOCKS4
        rdns = proxy_info.protocol in ("socks4a", "socks5h")

        proxy = Proxy(
            proxy_type=proxy_type,
            host=proxy_info.host,
            port=proxy_info.port,
            username=proxy_info.username,
            password=proxy_info.password,
            rdns=rdns,
        )

        # Connect to the destination through the proxy
        start_time = time.time()
        try:
            target_stream = await asyncio.wait_for(
                proxy.connect(dest_host=dest_addr, dest_port=dest_port), timeout=10
            )
            connection_time = time.time() - start_time
            logger.debug(
                "Connected to %s:%s through %s in %.3fs", dest_addr, dest_port, proxy_info, connection_time
            )

            # Update proxy latency
            proxy_info.update_latency(connection_time)
            proxy_info.mark_successful()
            return target_stream
        except Exception as e:
            logger.warning(
                "Failed to connect to %s:%s through %s: %s", dest_addr, dest_port, proxy_info, e
            )
            proxy_info.mark_failed()
            raise

    async def _handle_socks4(
        self,
        version_byte: bytes,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle SOCKS4 protocol"""
        client_addr = writer.get_extra_info("peername")
        # version_byte parameter is provided for consistency but not used in SOCKS4
        _ = version_byte

        # Parse SOCKS4 request
        dest_addr, dest_port = await self._parse_socks4_request(reader, writer)
        if not dest_addr:
            return

        logger.info(
            "SOCKS4 connect request from %s to %s:%s", client_addr, dest_addr, dest_port
        )

        # Connect through proxy and handle data transfer
        await self._handle_socks4_connect(reader, writer, dest_addr, dest_port)

    async def _parse_socks4_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> Tuple[Optional[str], int]:
        """Parse SOCKS4 request. Returns (dest_addr, dest_port) or (None, 0) on error."""
        # Read the request (cmd, port, ip)
        request_data = await reader.readexactly(7)
        cmd, port_high, port_low, ip1, ip2, ip3, ip4 = struct.unpack("!BBBBBB", request_data)
        dest_port = (port_high << 8) + port_low
        dest_ip = f"{ip1}.{ip2}.{ip3}.{ip4}"

        # Read user ID null-terminated string
        await self._read_null_terminated_string(reader)  # We don't use user_id

        # Check if this is SOCKS4A (with hostname)
        dest_addr = dest_ip
        if ip1 == 0 and ip2 == 0 and ip3 == 0 and ip4 != 0:
            # This is SOCKS4A, read the hostname
            hostname_bytes = await self._read_null_terminated_string(reader)
            dest_addr = hostname_bytes.decode("utf-8", errors="ignore")

        if cmd != SOCKS5_CMD_CONNECT:
            logger.warning("Unsupported SOCKS4 command: %s", cmd)
            await self._send_socks4_response(writer, SOCKS4_RESP_REJECTED, dest_port, dest_ip)
            return None, 0

        return dest_addr, dest_port

    async def _handle_socks4_connect(
        self,         reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
        dest_addr: str, dest_port: int
    ) -> None:
        """Handle the actual proxy connection for SOCKS4."""
        try:
            # Get proxy and connect
            proxy_info = await self.proxy_manager.get_proxy(dest_addr, dest_port)
            logger.debug(
                "Using proxy %s to connect to %s:%s", proxy_info, dest_addr, dest_port
            )

            target_stream = await self._connect_through_proxy(proxy_info, dest_addr, dest_port)

            # Send success response
            await self._send_socks4_response(writer, SOCKS4_RESP_SUCCESS, dest_port, "0.0.0.0")

            # Start bidirectional proxy
            await self._proxy_data(reader, writer, target_stream)

        except Exception as e:
            logger.error(
                "Error connecting to destination %s:%s: %s", dest_addr, dest_port, e
            )
            await self._send_socks4_response(writer, SOCKS4_RESP_REJECTED, dest_port, "0.0.0.0")

    async def _read_null_terminated_string(self, reader: asyncio.StreamReader) -> bytes:
        """Read a null-terminated string from the reader."""
        result = b""
        while True:
            byte_val = await reader.readexactly(1)
            if byte_val == b"\0":
                break
            result += byte_val
        return result

    async def _send_socks4_response(
        self, writer: asyncio.StreamWriter, response_code: int, dest_port: int, dest_ip: str
    ) -> None:
        """Send a SOCKS4 response."""
        writer.write(
            struct.pack(
                "!BBH4s",
                0,
                response_code,
                dest_port,
                socket.inet_aton(dest_ip),
            )
        )
        await writer.drain()

    async def _parse_socks5_address(
        self, reader: asyncio.StreamReader, atyp: int
    ) -> Tuple[Optional[str], int]:
        """Parse SOCKS5 address and port from stream"""
        if atyp == SOCKS5_ATYP_IPV4:
            # IPv4 address
            addr_bytes = await reader.readexactly(4)
            dest_addr = socket.inet_ntoa(addr_bytes)
        elif atyp == SOCKS5_ATYP_DOMAIN:
            # Domain name
            length = (await reader.readexactly(1))[0]
            addr_bytes = await reader.readexactly(length)
            dest_addr = addr_bytes.decode("utf-8", errors="ignore")
        elif atyp == SOCKS5_ATYP_IPV6:
            # IPv6 address
            addr_bytes = await reader.readexactly(16)
            dest_addr = socket.inet_ntop(socket.AF_INET6, addr_bytes)
        else:
            logger.warning("Unsupported address type: %s", atyp)
            return None, 0

        # Read port (2 bytes, big endian)
        port_bytes = await reader.readexactly(2)
        dest_port = int.from_bytes(port_bytes, byteorder="big")

        return dest_addr, dest_port

    async def _proxy_data(
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
        target_stream: Any,
    ) -> None:
        """Proxy data between client and target"""
        # Get target reader and writer
        target_reader, target_writer = target_stream.reader, target_stream.writer

        # Create tasks for bidirectional data flow
        client_to_target = asyncio.create_task(self._pipe(client_reader, target_writer))
        target_to_client = asyncio.create_task(self._pipe(target_reader, client_writer))

        # Wait for either direction to complete
        done, pending = await asyncio.wait(
            [client_to_target, target_to_client], return_when=asyncio.FIRST_COMPLETED
        )

        # Cancel pending tasks
        for task in pending:
            task.cancel()

        # Clean up and handle exceptions
        for task in done:
            try:
                task.result()
            except Exception as e:
                logger.debug("Pipe task error: %s", e)

    async def _pipe(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Pipe data from reader to writer"""
        try:
            while True:
                # Read data
                data = await reader.read(8192)
                if not data:
                    break

                # Write data
                writer.write(data)
                await writer.drain()
        except (
            asyncio.CancelledError,
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
        ):
            # These are expected when connections close
            pass
        except Exception as e:
            logger.error("Pipe error: %s", e)
        finally:
            try:
                writer.close()
                # Wait for the writer to close if it's not already closed
                if not writer.is_closing():
                    await writer.wait_closed()
            except Exception:
                pass
