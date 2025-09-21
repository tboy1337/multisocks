#!/usr/bin/env python3
"""Tests for the SocksServer class"""
# pylint: disable=protected-access

import asyncio
import socket
import struct
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any
import pytest

from multisocks.proxy.server import SocksServer, SOCKS_VERSION_5, SOCKS_VERSION_4
from multisocks.proxy.proxy_manager import ProxyManager
from multisocks.proxy.proxy_info import ProxyInfo


class MockStreamReader:
    """Mock StreamReader for testing"""
    def __init__(self, data: bytes = b''):
        self.data = data
        self.position = 0

    async def readexactly(self, n: int) -> bytes:
        """Read exactly n bytes"""
        if self.position + n > len(self.data):
            raise asyncio.IncompleteReadError(partial=b'', expected=n)
        result = self.data[self.position:self.position + n]
        self.position += n
        return result

    async def read(self, n: int) -> bytes:
        """Read up to n bytes"""
        if self.position >= len(self.data):
            return b''
        result = self.data[self.position:self.position + n]
        self.position += len(result)
        return result


class MockStreamWriter:
    """Mock StreamWriter for testing"""
    def __init__(self) -> None:
        self.written_data = b''
        self.closed = False
        self.peername = ('127.0.0.1', 12345)

    def write(self, data: bytes) -> None:
        """Write data to stream"""
        self.written_data += data

    async def drain(self) -> None:
        """Drain write buffer"""

    def close(self) -> None:
        """Close the stream"""
        self.closed = True

    async def wait_closed(self) -> None:
        """Wait for stream to be closed"""

    def get_extra_info(self, name: str) -> Any:
        """Get extra connection info"""
        if name == 'peername':
            return self.peername
        return None

    def is_closing(self) -> bool:
        """Check if stream is closing"""
        return self.closed


class TestSocksServer:
    """Test SocksServer class functionality"""

    def test_init(self) -> None:
        """Test SocksServer initialization"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        assert server.proxy_manager == manager
        assert server.server is None

    @pytest.mark.asyncio
    async def test_start_server(self) -> None:
        """Test server startup"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        mock_server = AsyncMock()
        mock_socket = MagicMock()
        mock_socket.getsockname.return_value = ('127.0.0.1', 1080)
        mock_server.sockets = [mock_socket]
        mock_server.serve_forever = AsyncMock(side_effect=asyncio.CancelledError())

        with patch('multisocks.proxy.server.asyncio.start_server', return_value=mock_server):
            with pytest.raises(asyncio.CancelledError):
                await server.start('127.0.0.1', 1080)

            mock_server.serve_forever.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_server(self) -> None:
        """Test server shutdown"""
        manager = AsyncMock()
        server = SocksServer(manager)

        mock_server = AsyncMock()
        server.server = mock_server

        await server.stop()

        mock_server.close.assert_called_once()
        mock_server.wait_closed.assert_called_once()
        manager.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_server_none(self) -> None:
        """Test stopping server when server is None"""
        manager = AsyncMock()
        server = SocksServer(manager)

        # Should not raise exception
        await server.stop()
        manager.stop.assert_called_once()


class TestSocksServerClientHandling:
    """Test SOCKS server client connection handling"""

    @pytest.mark.asyncio
    async def test_handle_client_socks5(self) -> None:
        """Test handling SOCKS5 client connection"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # SOCKS5 version byte
        reader = MockStreamReader(bytes([SOCKS_VERSION_5]))
        writer = MockStreamWriter()

        with patch.object(server, '_handle_socks5') as mock_handle_socks5:
            await server._handle_client(reader, writer)

            mock_handle_socks5.assert_called_once_with(reader, writer)

    @pytest.mark.asyncio
    async def test_handle_client_socks4(self) -> None:
        """Test handling SOCKS4 client connection"""
        proxy = ProxyInfo("socks4", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # SOCKS4 version byte
        version_byte = bytes([SOCKS_VERSION_4])
        reader = MockStreamReader(version_byte)
        writer = MockStreamWriter()

        with patch.object(server, '_handle_socks4') as mock_handle_socks4:
            await server._handle_client(reader, writer)

            mock_handle_socks4.assert_called_once_with(version_byte, reader, writer)

    @pytest.mark.asyncio
    async def test_handle_client_unsupported_version(self) -> None:
        """Test handling client with unsupported SOCKS version"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # Unsupported version
        reader = MockStreamReader(bytes([0x99]))
        writer = MockStreamWriter()

        with patch('multisocks.proxy.server.logger') as mock_logger:
            await server._handle_client(reader, writer)

            mock_logger.warning.assert_called_once()
            assert writer.closed

    @pytest.mark.asyncio
    async def test_handle_client_incomplete_read(self) -> None:
        """Test handling client with incomplete read"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # Empty reader will cause IncompleteReadError
        reader = MockStreamReader(b'')
        writer = MockStreamWriter()

        with patch('multisocks.proxy.server.logger') as mock_logger:
            await server._handle_client(reader, writer)

            mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_handle_client_exception(self) -> None:
        """Test handling client with exception"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        reader = AsyncMock()
        reader.readexactly.side_effect = RuntimeError("Test error")
        writer = MockStreamWriter()

        with patch('multisocks.proxy.server.logger') as mock_logger:
            await server._handle_client(reader, writer)

            mock_logger.error.assert_called_once()


class TestSocksServerSocks5:
    """Test SOCKS5 protocol handling"""

    @pytest.mark.asyncio
    async def test_handle_socks5_no_auth_ipv4_connect(self) -> None:
        """Test SOCKS5 connection with no auth and IPv4 address"""
        proxy_info = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = AsyncMock()
        manager.get_proxy.return_value = proxy_info
        server = SocksServer(manager)

        # SOCKS5 handshake: 1 method (no auth)
        # SOCKS5 request: connect to 192.168.1.1:80
        data = (
            b'\x01\x00' +  # 1 method, no auth
            b'\x05\x01\x00\x01' +  # version, connect, reserved, IPv4
            socket.inet_aton('192.168.1.1') +  # IPv4 address
            struct.pack('!H', 80)  # port 80
        )

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock successful proxy connection
        mock_stream = MagicMock()
        mock_stream.reader = AsyncMock()
        mock_stream.writer = AsyncMock()

        with patch('multisocks.proxy.server.Proxy') as mock_proxy_class:
            mock_proxy = AsyncMock()
            mock_proxy.connect.return_value = mock_stream
            mock_proxy_class.return_value = mock_proxy

            with patch.object(server, '_proxy_data') as mock_proxy_data:
                await server._handle_socks5(reader, writer)

                # Check auth response (no auth selected)
                assert writer.written_data.startswith(b'\x05\x00')
                # Check connect response (success)
                assert b'\x05\x00' in writer.written_data  # Success response

                mock_proxy_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_socks5_unsupported_auth(self) -> None:
        """Test SOCKS5 with unsupported authentication method"""
        proxy_info = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy_info])
        server = SocksServer(manager)

        # SOCKS5 handshake: 1 method (username/password auth only)
        data = b'\x01\x02'  # 1 method, username/password auth

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        await server._handle_socks5(reader, writer)

        # Should respond with no acceptable methods
        assert writer.written_data == b'\x05\xff'

    @pytest.mark.asyncio
    async def test_handle_socks5_unsupported_command(self) -> None:
        """Test SOCKS5 with unsupported command"""
        proxy_info = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy_info])
        server = SocksServer(manager)

        # SOCKS5 handshake and bind request (not supported)
        data = (
            b'\x01\x00' +  # 1 method, no auth
            b'\x05\x02\x00\x01' +  # version, bind (not connect), reserved, IPv4
            socket.inet_aton('192.168.1.1') +
            struct.pack('!H', 80)
        )

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        await server._handle_socks5(reader, writer)

        # Should respond with command not supported
        response_data = writer.written_data
        assert b'\x05\x00' in response_data  # Auth success
        assert b'\x05\x07' in response_data  # Command not supported

    @pytest.mark.asyncio
    async def test_handle_socks5_domain_name(self) -> None:
        """Test SOCKS5 connection with domain name"""
        proxy_info = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = AsyncMock()
        manager.get_proxy.return_value = proxy_info
        server = SocksServer(manager)

        # SOCKS5 with domain name
        domain = b'example.com'
        data = (
            b'\x01\x00' +  # 1 method, no auth
            b'\x05\x01\x00\x03' +  # version, connect, reserved, domain
            bytes([len(domain)]) + domain +  # domain length and name
            struct.pack('!H', 80)  # port 80
        )

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock successful proxy connection
        mock_stream = MagicMock()
        mock_stream.reader = AsyncMock()
        mock_stream.writer = AsyncMock()

        with patch('multisocks.proxy.server.Proxy') as mock_proxy_class:
            mock_proxy = AsyncMock()
            mock_proxy.connect.return_value = mock_stream
            mock_proxy_class.return_value = mock_proxy

            with patch.object(server, '_proxy_data'):
                await server._handle_socks5(reader, writer)

                # Should have called connect with domain name
                mock_proxy.connect.assert_called_once_with(
                    dest_host='example.com',
                    dest_port=80
                )

    @pytest.mark.asyncio
    async def test_handle_socks5_ipv6(self) -> None:
        """Test SOCKS5 connection with IPv6 address"""
        proxy_info = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = AsyncMock()
        manager.get_proxy.return_value = proxy_info
        server = SocksServer(manager)

        # IPv6 address ::1 (localhost)
        ipv6_addr = socket.inet_pton(socket.AF_INET6, '::1')
        data = (
            b'\x01\x00' +  # 1 method, no auth
            b'\x05\x01\x00\x04' +  # version, connect, reserved, IPv6
            ipv6_addr +  # IPv6 address
            struct.pack('!H', 80)  # port 80
        )

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock successful proxy connection
        mock_stream = MagicMock()
        mock_stream.reader = AsyncMock()
        mock_stream.writer = AsyncMock()

        with patch('multisocks.proxy.server.Proxy') as mock_proxy_class:
            mock_proxy = AsyncMock()
            mock_proxy.connect.return_value = mock_stream
            mock_proxy_class.return_value = mock_proxy

            with patch.object(server, '_proxy_data'):
                await server._handle_socks5(reader, writer)

                # Should have called connect with IPv6 address
                mock_proxy.connect.assert_called_once_with(
                    dest_host='::1',
                    dest_port=80
                )

    @pytest.mark.asyncio
    async def test_handle_socks5_proxy_connection_failure(self) -> None:
        """Test SOCKS5 when proxy connection fails"""
        proxy_info = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = AsyncMock()
        manager.get_proxy.return_value = proxy_info
        server = SocksServer(manager)

        # Standard SOCKS5 request
        data = (
            b'\x01\x00' +  # 1 method, no auth
            b'\x05\x01\x00\x01' +  # version, connect, reserved, IPv4
            socket.inet_aton('192.168.1.1') +
            struct.pack('!H', 80)
        )

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        with patch('multisocks.proxy.server.Proxy') as mock_proxy_class:
            mock_proxy = AsyncMock()
            mock_proxy.connect.side_effect = RuntimeError("Connection failed")
            mock_proxy_class.return_value = mock_proxy

            await server._handle_socks5(reader, writer)

            # Should respond with host unreachable
            response_data = writer.written_data
            assert b'\x05\x00' in response_data  # Auth success
            assert b'\x05\x04' in response_data  # Host unreachable

            # Proxy should be marked as failed
            assert proxy_info.fail_count > 0


class TestSocksServerSocks4:
    """Test SOCKS4 protocol handling"""

    @pytest.mark.asyncio
    async def test_handle_socks4_basic_connect(self) -> None:
        """Test basic SOCKS4 connect request"""
        proxy_info = ProxyInfo("socks4", "proxy.example.com", 1080)
        manager = AsyncMock()
        manager.get_proxy.return_value = proxy_info
        server = SocksServer(manager)

        # SOCKS4 request: connect to 192.168.1.1:80, user ID "user"
        data = (
            b'\x01' +  # connect command
            struct.pack('!H', 80) +  # port
            socket.inet_aton('192.168.1.1') +  # IP
            b'user\x00'  # user ID
        )

        version_byte = bytes([SOCKS_VERSION_4])
        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock successful proxy connection
        mock_stream = MagicMock()
        mock_stream.reader = AsyncMock()
        mock_stream.writer = AsyncMock()

        with patch('multisocks.proxy.server.Proxy') as mock_proxy_class:
            mock_proxy = AsyncMock()
            mock_proxy.connect.return_value = mock_stream
            mock_proxy_class.return_value = mock_proxy

            with patch.object(server, '_proxy_data'):
                await server._handle_socks4(version_byte, reader, writer)

                # Should have called connect with IP address
                mock_proxy.connect.assert_called_once_with(
                    dest_host='192.168.1.1',
                    dest_port=80
                )

                # Should respond with success
                response_data = writer.written_data
                assert b'\x00\x5a' in response_data  # Success response

    @pytest.mark.asyncio
    async def test_handle_socks4a_with_hostname(self) -> None:
        """Test SOCKS4a connect request with hostname"""
        proxy_info = ProxyInfo("socks4a", "proxy.example.com", 1080)
        manager = AsyncMock()
        manager.get_proxy.return_value = proxy_info
        server = SocksServer(manager)

        # SOCKS4a request: 0.0.0.x format indicates hostname follows
        data = (
            b'\x01' +  # connect command
            struct.pack('!H', 80) +  # port
            b'\x00\x00\x00\x01' +  # 0.0.0.1 (indicates hostname)
            b'user\x00' +  # user ID
            b'example.com\x00'  # hostname
        )

        version_byte = bytes([SOCKS_VERSION_4])
        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock successful proxy connection
        mock_stream = MagicMock()
        mock_stream.reader = AsyncMock()
        mock_stream.writer = AsyncMock()

        with patch('multisocks.proxy.server.Proxy') as mock_proxy_class:
            mock_proxy = AsyncMock()
            mock_proxy.connect.return_value = mock_stream
            mock_proxy_class.return_value = mock_proxy

            with patch.object(server, '_proxy_data'):
                await server._handle_socks4(version_byte, reader, writer)

                # Should have called connect with hostname
                mock_proxy.connect.assert_called_once_with(
                    dest_host='example.com',
                    dest_port=80
                )

    @pytest.mark.asyncio
    async def test_handle_socks4_unsupported_command(self) -> None:
        """Test SOCKS4 with unsupported command"""
        proxy_info = ProxyInfo("socks4", "proxy.example.com", 1080)
        manager = ProxyManager([proxy_info])
        server = SocksServer(manager)

        # SOCKS4 bind request (not supported)
        data = (
            b'\x02' +  # bind command
            struct.pack('!H', 80) +  # port
            socket.inet_aton('192.168.1.1') +  # IP
            b'user\x00'  # user ID
        )

        version_byte = bytes([SOCKS_VERSION_4])
        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        await server._handle_socks4(version_byte, reader, writer)

        # Should respond with rejected
        response_data = writer.written_data
        assert b'\x00\x5b' in response_data  # Rejected response

    @pytest.mark.asyncio
    async def test_handle_socks4_proxy_connection_failure(self) -> None:
        """Test SOCKS4 when proxy connection fails"""
        proxy_info = ProxyInfo("socks4", "proxy.example.com", 1080)
        manager = AsyncMock()
        manager.get_proxy.return_value = proxy_info
        server = SocksServer(manager)

        # Standard SOCKS4 request
        data = (
            b'\x01' +  # connect command
            struct.pack('!H', 80) +  # port
            socket.inet_aton('192.168.1.1') +  # IP
            b'user\x00'  # user ID
        )

        version_byte = bytes([SOCKS_VERSION_4])
        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        with patch('multisocks.proxy.server.Proxy') as mock_proxy_class:
            mock_proxy = AsyncMock()
            mock_proxy.connect.side_effect = RuntimeError("Connection failed")
            mock_proxy_class.return_value = mock_proxy

            await server._handle_socks4(version_byte, reader, writer)

            # Should respond with rejected
            response_data = writer.written_data
            assert b'\x00\x5b' in response_data  # Rejected response


class TestSocksServerDataProxying:
    """Test data proxying functionality"""

    @pytest.mark.asyncio
    async def test_proxy_data_bidirectional(self) -> None:
        """Test bidirectional data proxying"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        client_reader = AsyncMock()
        client_writer = MockStreamWriter()

        target_reader = AsyncMock()
        target_writer = MockStreamWriter()

        mock_target_stream = MagicMock()
        mock_target_stream.reader = target_reader
        mock_target_stream.writer = target_writer

        # Mock the pipe operations to complete immediately
        with patch.object(server, '_pipe') as mock_pipe:
            mock_pipe.return_value = AsyncMock()

            with patch('multisocks.proxy.server.asyncio.wait') as mock_wait:
                # Simulate both tasks completing
                task1 = AsyncMock()
                task2 = AsyncMock()
                mock_wait.return_value = ([task1], [task2])

                await server._proxy_data(client_reader, client_writer, mock_target_stream)

                # Should have created two pipe tasks
                assert mock_pipe.call_count == 2
                # Should have cancelled pending tasks
                task2.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipe_data_transfer(self) -> None:
        """Test data transfer in pipe method"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # Mock reader with some data
        reader = AsyncMock()
        reader.read.side_effect = [b'hello', b'world', b'']  # End with empty bytes

        writer = MockStreamWriter()

        await server._pipe(reader, writer)

        # Should have written the data
        assert writer.written_data == b'helloworld'

    @pytest.mark.asyncio
    async def test_pipe_handles_connection_errors(self) -> None:
        """Test pipe handles connection errors gracefully"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        reader = AsyncMock()
        reader.read.side_effect = ConnectionResetError("Connection reset")

        writer = MockStreamWriter()

        # Should not raise exception
        await server._pipe(reader, writer)

    @pytest.mark.asyncio
    async def test_pipe_handles_cancelled_error(self) -> None:
        """Test pipe handles CancelledError gracefully"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        reader = AsyncMock()
        reader.read.side_effect = asyncio.CancelledError()

        writer = MockStreamWriter()

        # Should not raise exception
        await server._pipe(reader, writer)

    @pytest.mark.asyncio
    async def test_pipe_handles_unexpected_error(self) -> None:
        """Test pipe handles unexpected errors"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        reader = AsyncMock()
        reader.read.side_effect = RuntimeError("Unexpected error")

        writer = MockStreamWriter()

        with patch('multisocks.proxy.server.logger') as mock_logger:
            await server._pipe(reader, writer)

            mock_logger.error.assert_called_once()


class TestSocksServerAddressParsing:
    """Test SOCKS5 address parsing"""

    @pytest.mark.asyncio
    async def test_parse_socks5_address_ipv4(self) -> None:
        """Test parsing IPv4 address"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # IPv4 address 192.168.1.1:80
        data = socket.inet_aton('192.168.1.1') + struct.pack('!H', 80)
        reader = MockStreamReader(data)

        addr, port = await server._parse_socks5_address(reader, 1)  # IPv4 type

        assert addr == '192.168.1.1'
        assert port == 80

    @pytest.mark.asyncio
    async def test_parse_socks5_address_domain(self) -> None:
        """Test parsing domain name address"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # Domain name "example.com":80
        domain = b'example.com'
        data = bytes([len(domain)]) + domain + struct.pack('!H', 80)
        reader = MockStreamReader(data)

        addr, port = await server._parse_socks5_address(reader, 3)  # Domain type

        assert addr == 'example.com'
        assert port == 80

    @pytest.mark.asyncio
    async def test_parse_socks5_address_ipv6(self) -> None:
        """Test parsing IPv6 address"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        # IPv6 address ::1:80
        ipv6_addr = socket.inet_pton(socket.AF_INET6, '::1')
        data = ipv6_addr + struct.pack('!H', 80)
        reader = MockStreamReader(data)

        addr, port = await server._parse_socks5_address(reader, 4)  # IPv6 type

        assert addr == '::1'
        assert port == 80

    @pytest.mark.asyncio
    async def test_parse_socks5_address_unsupported_type(self) -> None:
        """Test parsing unsupported address type"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        reader = MockStreamReader(b'')

        with patch('multisocks.proxy.server.logger') as mock_logger:
            addr, port = await server._parse_socks5_address(reader, 99)  # Invalid type

            assert addr is None
            assert port == 0
            mock_logger.warning.assert_called_once()


class TestSocksServerEdgeCases:
    """Test edge cases in SOCKS server for better coverage"""

    @pytest.mark.asyncio
    async def test_handle_socks5_address_type_not_supported(self) -> None:
        """Test SOCKS5 with address type not supported error (covers lines 145-147)"""
        proxy_info = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy_info])
        server = SocksServer(manager)

        # SOCKS5 handshake with unsupported address type
        data = (
            b'\x01\x00' +  # 1 method, no auth
            b'\x05\x01\x00\x99'  # version, connect, reserved, unsupported address type
            # No address data since it's unsupported
        )

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock _parse_socks5_address to return None (unsupported address type)
        with patch.object(server, '_parse_socks5_address', return_value=(None, 0)):
            await server._handle_socks5(reader, writer)

            # Should respond with address type not supported (covers lines 145-147)
            response_data = writer.written_data
            assert b'\x05\x00' in response_data  # Auth success
            assert b'\x05\x08' in response_data  # Address type not supported

    @pytest.mark.asyncio
    async def test_handle_socks5_general_failure_exception(self) -> None:
        """Test SOCKS5 general failure on exception (covers lines 201-204)"""
        manager = AsyncMock()
        server = SocksServer(manager)

        # Standard SOCKS5 request
        data = (
            b'\x01\x00' +  # 1 method, no auth
            b'\x05\x01\x00\x01' +  # version, connect, reserved, IPv4
            socket.inet_aton('192.168.1.1') +
            struct.pack('!H', 80)
        )

        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock get_proxy to raise exception (covers lines 201-204)
        manager.get_proxy.side_effect = Exception("Test error")

        await server._handle_socks5(reader, writer)

        # Should respond with general failure (covers lines 201-204)
        response_data = writer.written_data
        assert b'\x05\x00' in response_data  # Auth success
        assert b'\x05\x01' in response_data  # General failure

    @pytest.mark.asyncio
    async def test_handle_socks4_general_failure_exception(self) -> None:
        """Test SOCKS4 general failure on exception (covers lines 291-294)"""
        manager = AsyncMock()
        server = SocksServer(manager)

        # Standard SOCKS4 request
        data = (
            b'\x01' +  # connect command
            struct.pack('!H', 80) +  # port
            socket.inet_aton('192.168.1.1') +  # IP
            b'user\x00'  # user ID
        )

        version_byte = bytes([SOCKS_VERSION_4])
        reader = MockStreamReader(data)
        writer = MockStreamWriter()

        # Mock get_proxy to raise exception (covers lines 291-294)
        manager.get_proxy.side_effect = Exception("Test error")

        await server._handle_socks4(version_byte, reader, writer)

        # Should respond with rejected (covers lines 291-294)
        response_data = writer.written_data
        assert b'\x00\x5b' in response_data  # Rejected response

    @pytest.mark.asyncio
    async def test_proxy_data_exception_handling(self) -> None:
        """Test proxy data handling with exceptions (covers lines 345-346)"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        client_reader = AsyncMock()
        client_writer = MockStreamWriter()

        target_reader = AsyncMock()
        target_writer = MockStreamWriter()

        mock_target_stream = MagicMock()
        mock_target_stream.reader = target_reader
        mock_target_stream.writer = target_writer

        # Mock the pipe operations to raise an exception
        with patch.object(server, '_pipe', side_effect=Exception("Pipe error")):
            with patch('multisocks.proxy.server.asyncio.wait') as mock_wait:
                # Simulate task completion with exception
                task1 = AsyncMock()
                task1.result.side_effect = Exception("Task error")  # covers lines 345-346
                task2 = AsyncMock()
                mock_wait.return_value = ([task1], [task2])

                # Should handle exception gracefully (covers lines 345-346)
                await server._proxy_data(client_reader, client_writer, mock_target_stream)

                # Should have cancelled pending tasks
                task2.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipe_writer_close_exception(self) -> None:
        """Test pipe writer close with exception (covers line 370)"""
        proxy = ProxyInfo("socks5", "proxy.example.com", 1080)
        manager = ProxyManager([proxy])
        server = SocksServer(manager)

        reader = AsyncMock()
        reader.read.return_value = b''  # End immediately

        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.is_closing = MagicMock(return_value=False)
        writer.wait_closed = AsyncMock(side_effect=Exception("Close error"))  # covers line 370

        # Should handle exception in finally block gracefully (covers line 370)
        await server._pipe(reader, writer)
