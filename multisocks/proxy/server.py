import asyncio
import logging
import socket
import struct
import time
from typing import Optional, Tuple

from python_socks.async_.asyncio import Proxy

from .proxy_info import ProxyInfo
from .proxy_manager import ProxyManager

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
    
    def __init__(self, proxy_manager: ProxyManager):
        """Initialize with a proxy manager"""
        self.proxy_manager = proxy_manager
        self.server = None
        
    async def start(self, host: str, port: int) -> None:
        """Start the SOCKS server"""
        self.server = await asyncio.start_server(
            self._handle_client,
            host,
            port,
            family=socket.AF_INET,
            reuse_address=True
        )
        
        addr = self.server.sockets[0].getsockname()
        logger.info(f"SOCKS server started on {addr[0]}:{addr[1]}")
        
        async with self.server:
            await self.server.serve_forever()
    
    async def stop(self) -> None:
        """Stop the SOCKS server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("SOCKS server stopped")
        
        await self.proxy_manager.stop()
    
    async def _handle_client(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        """Handle a client connection"""
        client_addr = client_writer.get_extra_info('peername')
        logger.debug(f"New connection from {client_addr}")
        
        try:
            # Read first byte to determine SOCKS version
            version_byte = await client_reader.readexactly(1)
            version = version_byte[0]
            
            if version == SOCKS_VERSION_5:
                await self._handle_socks5(client_reader, client_writer)
            elif version == SOCKS_VERSION_4:
                await self._handle_socks4(version_byte, client_reader, client_writer)
            else:
                logger.warning(f"Unsupported SOCKS version: {version}")
                client_writer.close()
                
        except asyncio.IncompleteReadError:
            logger.debug(f"Client {client_addr} disconnected during handshake")
        except Exception as e:
            logger.error(f"Error handling client {client_addr}: {e}")
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass
            logger.debug(f"Connection from {client_addr} closed")
    
    async def _handle_socks5(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle SOCKS5 protocol"""
        client_addr = writer.get_extra_info('peername')
        
        # Read authentication methods
        num_methods = (await reader.readexactly(1))[0]
        methods = await reader.readexactly(num_methods)
        
        # We only support no authentication for now
        if SOCKS5_AUTH_NONE not in methods:
            logger.warning(f"Client {client_addr} requested unsupported auth methods: {methods}")
            writer.write(struct.pack('!BB', SOCKS_VERSION_5, SOCKS5_AUTH_NO_ACCEPTABLE_METHODS))
            await writer.drain()
            return
        
        # Accept no authentication
        writer.write(struct.pack('!BB', SOCKS_VERSION_5, SOCKS5_AUTH_NONE))
        await writer.drain()
        
        # Read the request
        header = await reader.readexactly(4)
        version, cmd, _, atyp = struct.unpack('!BBBB', header)
        
        if cmd != SOCKS5_CMD_CONNECT:
            logger.warning(f"Unsupported SOCKS5 command: {cmd}")
            writer.write(struct.pack('!BBBBIH', SOCKS_VERSION_5, SOCKS5_RESP_COMMAND_NOT_SUPPORTED, 0, SOCKS5_ATYP_IPV4, 0, 0))
            await writer.drain()
            return
        
        # Parse destination address
        dest_addr, dest_port = await self._parse_socks5_address(reader, atyp)
        if not dest_addr:
            writer.write(struct.pack('!BBBBIH', SOCKS_VERSION_5, SOCKS5_RESP_ADDRESS_TYPE_NOT_SUPPORTED, 0, SOCKS5_ATYP_IPV4, 0, 0))
            await writer.drain()
            return
        
        logger.info(f"SOCKS5 connect request from {client_addr} to {dest_addr}:{dest_port}")
        
        # Connect to destination through a proxy
        try:
            proxy_info = await self.proxy_manager.get_proxy(dest_addr, dest_port)
            logger.debug(f"Using proxy {proxy_info} to connect to {dest_addr}:{dest_port}")
            
            # Create a proxy connector
            proxy_type = 2 if proxy_info.protocol in ("socks5", "socks5h") else 1  # SOCKS4 = 1, SOCKS5 = 2
            
            # Determine if remote DNS resolution should be used
            # For SOCKS5h, DNS resolution should happen on the proxy server
            rdns = proxy_info.protocol in ('socks4a', 'socks5h')
            
            proxy = Proxy(
                proxy_type=proxy_type,
                host=proxy_info.host,
                port=proxy_info.port,
                username=proxy_info.username,
                password=proxy_info.password,
                rdns=rdns
            )
            
            # Connect to the destination through the proxy
            start_time = time.time()
            try:
                target_stream = await asyncio.wait_for(
                    proxy.connect(dest_host=dest_addr, dest_port=dest_port),
                    timeout=10
                )
                connection_time = time.time() - start_time
                logger.debug(f"Connected to {dest_addr}:{dest_port} through {proxy_info} in {connection_time:.3f}s")
                
                # Update proxy latency
                proxy_info.update_latency(connection_time)
                proxy_info.mark_successful()
            except Exception as e:
                logger.warning(f"Failed to connect to {dest_addr}:{dest_port} through {proxy_info}: {e}")
                proxy_info.mark_failed()
                writer.write(struct.pack('!BBBBIH', SOCKS_VERSION_5, SOCKS5_RESP_HOST_UNREACHABLE, 0, SOCKS5_ATYP_IPV4, 0, 0))
                await writer.drain()
                return
            
            # Send success response
            bind_addr = socket.inet_aton('0.0.0.0')
            bind_port = 0
            writer.write(struct.pack('!BBBB4sH', SOCKS_VERSION_5, SOCKS5_RESP_SUCCESS, 0, SOCKS5_ATYP_IPV4, bind_addr, bind_port))
            await writer.drain()
            
            # Start bidirectional proxy
            await self._proxy_data(reader, writer, target_stream)
            
        except Exception as e:
            logger.error(f"Error connecting to destination {dest_addr}:{dest_port}: {e}")
            writer.write(struct.pack('!BBBBIH', SOCKS_VERSION_5, SOCKS5_RESP_GENERAL_FAILURE, 0, SOCKS5_ATYP_IPV4, 0, 0))
            await writer.drain()
    
    async def _handle_socks4(self, version_byte: bytes, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle SOCKS4 protocol"""
        client_addr = writer.get_extra_info('peername')
        
        # Read the request (cmd, port, ip)
        data = await reader.readexactly(7)
        cmd, port_high, port_low, ip1, ip2, ip3, ip4 = struct.unpack('!BBBBBB', data)
        dest_port = (port_high << 8) + port_low
        dest_ip = f"{ip1}.{ip2}.{ip3}.{ip4}"
        
        # Read user ID null-terminated string
        user_id = b''
        while True:
            b = await reader.readexactly(1)
            if b == b'\0':
                break
            user_id += b
        
        # Check if this is SOCKS4A (with hostname)
        dest_addr = dest_ip
        if ip1 == 0 and ip2 == 0 and ip3 == 0 and ip4 != 0:
            # This is SOCKS4A, read the hostname
            hostname = b''
            while True:
                b = await reader.readexactly(1)
                if b == b'\0':
                    break
                hostname += b
            dest_addr = hostname.decode('utf-8', errors='ignore')
        
        if cmd != SOCKS5_CMD_CONNECT:
            logger.warning(f"Unsupported SOCKS4 command: {cmd}")
            writer.write(struct.pack('!BBH4s', 0, SOCKS4_RESP_REJECTED, dest_port, socket.inet_aton(dest_ip)))
            await writer.drain()
            return
        
        logger.info(f"SOCKS4 connect request from {client_addr} to {dest_addr}:{dest_port}")
        
        # Connect to destination through a proxy
        try:
            proxy_info = await self.proxy_manager.get_proxy(dest_addr, dest_port)
            logger.debug(f"Using proxy {proxy_info} to connect to {dest_addr}:{dest_port}")
            
            # Create a proxy connector
            proxy_type = 2 if proxy_info.protocol in ("socks5", "socks5h") else 1  # SOCKS4 = 1, SOCKS5 = 2
            
            # Determine if remote DNS resolution should be used
            rdns = proxy_info.protocol in ('socks4a', 'socks5h')
            
            proxy = Proxy(
                proxy_type=proxy_type,
                host=proxy_info.host,
                port=proxy_info.port,
                username=proxy_info.username,
                password=proxy_info.password,
                rdns=rdns
            )
            
            # Connect to the destination through the proxy
            start_time = time.time()
            try:
                target_stream = await asyncio.wait_for(
                    proxy.connect(dest_host=dest_addr, dest_port=dest_port),
                    timeout=10
                )
                connection_time = time.time() - start_time
                logger.debug(f"Connected to {dest_addr}:{dest_port} through {proxy_info} in {connection_time:.3f}s")
                
                # Update proxy latency
                proxy_info.update_latency(connection_time)
                proxy_info.mark_successful()
            except Exception as e:
                logger.warning(f"Failed to connect to {dest_addr}:{dest_port} through {proxy_info}: {e}")
                proxy_info.mark_failed()
                writer.write(struct.pack('!BBH4s', 0, SOCKS4_RESP_REJECTED, dest_port, socket.inet_aton('0.0.0.0')))
                await writer.drain()
                return
            
            # Send success response
            writer.write(struct.pack('!BBH4s', 0, SOCKS4_RESP_SUCCESS, dest_port, socket.inet_aton('0.0.0.0')))
            await writer.drain()
            
            # Start bidirectional proxy
            await self._proxy_data(reader, writer, target_stream)
            
        except Exception as e:
            logger.error(f"Error connecting to destination {dest_addr}:{dest_port}: {e}")
            writer.write(struct.pack('!BBH4s', 0, SOCKS4_RESP_REJECTED, dest_port, socket.inet_aton('0.0.0.0')))
            await writer.drain()
    
    async def _parse_socks5_address(self, reader: asyncio.StreamReader, atyp: int) -> Tuple[Optional[str], int]:
        """Parse SOCKS5 address and port from stream"""
        if atyp == SOCKS5_ATYP_IPV4:
            # IPv4 address
            addr_bytes = await reader.readexactly(4)
            dest_addr = socket.inet_ntoa(addr_bytes)
        elif atyp == SOCKS5_ATYP_DOMAIN:
            # Domain name
            length = (await reader.readexactly(1))[0]
            addr_bytes = await reader.readexactly(length)
            dest_addr = addr_bytes.decode('utf-8', errors='ignore')
        elif atyp == SOCKS5_ATYP_IPV6:
            # IPv6 address
            addr_bytes = await reader.readexactly(16)
            dest_addr = socket.inet_ntop(socket.AF_INET6, addr_bytes)
        else:
            logger.warning(f"Unsupported address type: {atyp}")
            return None, 0
        
        # Read port (2 bytes, big endian)
        port_bytes = await reader.readexactly(2)
        dest_port = int.from_bytes(port_bytes, byteorder='big')
        
        return dest_addr, dest_port
    
    async def _proxy_data(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter, 
                          target_stream) -> None:
        """Proxy data between client and target"""
        # Get target reader and writer
        target_reader, target_writer = target_stream.reader, target_stream.writer
        
        # Create tasks for bidirectional data flow
        client_to_target = asyncio.create_task(self._pipe(client_reader, target_writer))
        target_to_client = asyncio.create_task(self._pipe(target_reader, client_writer))
        
        # Wait for either direction to complete
        done, pending = await asyncio.wait(
            [client_to_target, target_to_client],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel pending tasks
        for task in pending:
            task.cancel()
        
        # Clean up and handle exceptions
        for task in done:
            try:
                task.result()
            except Exception as e:
                logger.debug(f"Pipe task error: {e}")
    
    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
        except (asyncio.CancelledError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # These are expected when connections close
            pass
        except Exception as e:
            logger.error(f"Pipe error: {e}")
        finally:
            try:
                writer.close()
                # Wait for the writer to close if it's not already closed
                if not writer.is_closing():
                    await writer.wait_closed()
            except Exception:
                pass 