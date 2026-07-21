"""Scanner-private authenticated proxy relay with a credential-free browser URL.

The browser connects to an ephemeral loopback HTTP proxy.  Only this process
ever sees the authenticated upstream URL; diagnostics deliberately expose
neither upstream identity nor authentication material.
"""

from __future__ import annotations

import base64
import ipaddress
import select
import socket
import ssl
import threading
from time import monotonic
from types import TracebackType
from typing import Mapping, Optional, Tuple, Type
from urllib.parse import unquote, urlsplit


_SUPPORTED_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})
_MAX_HEADER_BYTES = 65536
_SOCKET_TIMEOUT = 5.0
_GENERIC_BAD_GATEWAY = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
_GENERIC_BAD_REQUEST = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"
_CONNECT_ONLY = b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n"


class _RelayFailure(Exception):
    """Internal failure whose details must never cross the relay boundary."""


class AuthenticatedProxyRelay:
    """Relay browser CONNECT requests through one authenticated upstream proxy.

    Instances are single-use context managers in normal scanner operation, but
    :meth:`start` and :meth:`close` are idempotent to make launch-failure cleanup
    straightforward.
    """

    def __init__(
        self,
        upstream_proxy_url: str,
        *,
        upstream_tls_context: Optional[ssl.SSLContext] = None,
        worker_join_timeout: float = 2.0,
    ) -> None:
        scheme, host, port, username, password = self._parse_upstream(
            upstream_proxy_url
        )
        if worker_join_timeout < 0:
            raise ValueError("Worker join timeout must not be negative")

        self._scheme = scheme
        self._upstream_host = host
        self._upstream_port = port
        self._username = username
        self._password = password
        self._tls_context = upstream_tls_context
        self._worker_join_timeout = float(worker_join_timeout)

        self._state_lock = threading.RLock()
        self._connection_lock = threading.Lock()
        self._observation_lock = threading.Lock()
        self._stop = threading.Event()
        self._listener: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._workers: set[threading.Thread] = set()
        self._connections: set[socket.socket] = set()
        self._dns_observations: list[dict[str, str]] = []
        self._browser_proxy_url: Optional[str] = None

    @staticmethod
    def _parse_upstream(
        value: str,
    ) -> Tuple[str, str, int, Optional[str], Optional[str]]:
        if not isinstance(value, str) or not value:
            raise ValueError("Upstream proxy URL is invalid")
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except (TypeError, ValueError):
            raise ValueError("Upstream proxy URL is invalid") from None

        scheme = parsed.scheme.lower()
        if (
            scheme not in _SUPPORTED_SCHEMES
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Upstream proxy URL is invalid")

        if port is None:
            port = 443 if scheme == "https" else (1080 if scheme.startswith("socks") else 80)
        if not 1 <= port <= 65535:
            raise ValueError("Upstream proxy URL is invalid")

        username = unquote(parsed.username) if parsed.username is not None else None
        password = unquote(parsed.password) if parsed.password is not None else None
        if username is None and password is not None:
            raise ValueError("Upstream proxy URL is invalid")
        if username is not None and password is None:
            password = ""
        if scheme.startswith("socks") and username is not None:
            if len(username.encode("utf-8")) > 255 or len((password or "").encode("utf-8")) > 255:
                raise ValueError("Upstream proxy credentials are invalid")
        return scheme, parsed.hostname, port, username, password

    def __repr__(self) -> str:
        state = "running" if self.is_running else "stopped"
        local = f", browser_proxy_url={self._browser_proxy_url!r}" if self.is_running else ""
        return f"AuthenticatedProxyRelay(state={state!r}{local})"

    def __enter__(self) -> "AuthenticatedProxyRelay":
        return self.start()

    def __exit__(
        self,
        _exc_type: Optional[Type[BaseException]],
        _exc: Optional[BaseException],
        _traceback: Optional[TracebackType],
    ) -> None:
        self.close()

    @property
    def browser_proxy_url(self) -> str:
        with self._state_lock:
            if not self.is_running or self._browser_proxy_url is None:
                raise RuntimeError("Proxy relay is not running")
            return self._browser_proxy_url

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._listener is not None and not self._stop.is_set()

    @property
    def active_worker_count(self) -> int:
        with self._connection_lock:
            return sum(worker.is_alive() for worker in self._workers)

    @property
    def dns_observations(self) -> tuple[Mapping[str, str], ...]:
        """Return safe DNS-delegation metadata without destination names."""

        with self._observation_lock:
            return tuple(dict(item) for item in self._dns_observations)

    def start(self) -> "AuthenticatedProxyRelay":
        with self._state_lock:
            if self.is_running:
                return self
            listener: Optional[socket.socket] = None
            try:
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                listener.settimeout(0.2)
                port = listener.getsockname()[1]
                self._stop.clear()
                self._listener = listener
                self._browser_proxy_url = f"http://127.0.0.1:{port}"
                self._accept_thread = threading.Thread(
                    target=self._accept_loop,
                    name="proxy-auth-relay-listener",
                    daemon=True,
                )
                self._accept_thread.start()
                return self
            except Exception:
                if listener is not None:
                    self._close_socket(listener)
                self._listener = None
                self._browser_proxy_url = None
                self._stop.set()
                raise RuntimeError("Proxy relay could not start") from None

    def close(self) -> None:
        with self._state_lock:
            listener = self._listener
            accept_thread = self._accept_thread
            if listener is None and accept_thread is None:
                self._stop.set()
                return
            self._stop.set()
            self._listener = None
            self._accept_thread = None

        if listener is not None:
            self._close_socket(listener)
        self._close_active_connections()

        deadline = monotonic() + self._worker_join_timeout
        current = threading.current_thread()
        if accept_thread is not None and accept_thread is not current:
            accept_thread.join(max(0.0, deadline - monotonic()))

        while True:
            with self._connection_lock:
                workers = [
                    worker
                    for worker in self._workers
                    if worker is not current and worker.is_alive()
                ]
            if not workers:
                break
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            for worker in workers:
                worker.join(max(0.0, deadline - monotonic()))
                if monotonic() >= deadline:
                    break
            self._close_active_connections()

        with self._state_lock:
            self._browser_proxy_url = None

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            with self._state_lock:
                listener = self._listener
            if listener is None:
                return
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            client.settimeout(_SOCKET_TIMEOUT)
            worker = threading.Thread(
                target=self._handle_client,
                args=(client,),
                name="proxy-auth-relay-client",
                daemon=True,
            )
            with self._connection_lock:
                self._connections.add(client)
                self._workers.add(worker)
            worker.start()

    def _handle_client(self, client: socket.socket) -> None:
        upstream: Optional[socket.socket] = None
        response_started = False
        try:
            header, _remainder = self._read_headers(client)
            request_line = header.split(b"\r\n", 1)[0]
            parts = request_line.split(b" ")
            if len(parts) != 3:
                self._send_safe(client, _GENERIC_BAD_REQUEST)
                return
            try:
                method = parts[0].decode("ascii")
                target = parts[1].decode("ascii")
            except UnicodeDecodeError:
                self._send_safe(client, _GENERIC_BAD_REQUEST)
                return
            if method.upper() != "CONNECT":
                self._send_safe(client, _CONNECT_ONLY)
                return

            destination_host, destination_port = self._parse_authority(target)
            upstream, initial_data = self._connect_upstream(
                destination_host, destination_port
            )
            self._send_safe(client, b"HTTP/1.1 200 Connection Established\r\n\r\n")
            response_started = True
            if initial_data:
                self._send_safe(client, initial_data)
            client.settimeout(None)
            upstream.settimeout(None)
            self._tunnel(client, upstream)
        except Exception:
            if not response_started:
                self._send_safe(client, _GENERIC_BAD_GATEWAY)
        finally:
            if upstream is not None:
                self._discard_connection(upstream)
                self._close_socket(upstream)
            self._discard_connection(client)
            self._close_socket(client)
            current = threading.current_thread()
            with self._connection_lock:
                self._workers.discard(current)

    @staticmethod
    def _parse_authority(authority: str) -> Tuple[str, int]:
        try:
            if authority.startswith("["):
                bracket = authority.index("]")
                host = authority[1:bracket]
                if authority[bracket + 1 : bracket + 2] != ":":
                    raise ValueError
                port_text = authority[bracket + 2 :]
            else:
                host, port_text = authority.rsplit(":", 1)
                if ":" in host:
                    raise ValueError
            port = int(port_text)
            if (
                not host
                or not 1 <= port <= 65535
                or any(character.isspace() for character in host)
                or any(character in host for character in "/@")
            ):
                raise ValueError
            return host, port
        except (ValueError, IndexError):
            raise _RelayFailure("invalid destination") from None

    def _connect_upstream(
        self, destination_host: str, destination_port: int
    ) -> Tuple[socket.socket, bytes]:
        try:
            raw = socket.create_connection(
                (self._upstream_host, self._upstream_port), timeout=_SOCKET_TIMEOUT
            )
        except Exception:
            raise _RelayFailure("upstream unavailable") from None
        self._add_connection(raw)

        stream: socket.socket = raw
        try:
            if self._scheme == "https":
                context = self._tls_context or ssl.create_default_context()
                stream = context.wrap_socket(raw, server_hostname=self._upstream_host)
                self._discard_connection(raw)
                self._add_connection(stream)
            if self._scheme in {"http", "https"}:
                initial_data = self._http_connect(
                    stream, destination_host, destination_port
                )
            else:
                self._socks5_connect(stream, destination_host, destination_port)
                initial_data = b""
            return stream, initial_data
        except Exception:
            self._discard_connection(stream)
            if stream is not raw:
                self._discard_connection(raw)
            self._close_socket(stream)
            raise _RelayFailure("upstream negotiation failed") from None

    def _http_connect(
        self, upstream: socket.socket, destination_host: str, destination_port: int
    ) -> bytes:
        authority = self._format_authority(destination_host, destination_port)
        lines = [
            f"CONNECT {authority} HTTP/1.1",
            f"Host: {authority}",
            "Proxy-Connection: Keep-Alive",
        ]
        if self._username is not None:
            credentials = f"{self._username}:{self._password or ''}".encode("utf-8")
            token = base64.b64encode(credentials).decode("ascii")
            lines.append(f"Proxy-Authorization: Basic {token}")
        request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")
        upstream.sendall(request)
        response, remainder = self._read_headers(upstream)
        first_line = response.split(b"\r\n", 1)[0].split(b" ")
        if len(first_line) < 2 or not first_line[1].isdigit():
            raise _RelayFailure("invalid upstream response")
        status = int(first_line[1])
        if not 200 <= status < 300:
            raise _RelayFailure("upstream rejected request")
        self._record_dns_observation(destination_host, "upstream")
        return remainder

    def _socks5_connect(
        self, upstream: socket.socket, destination_host: str, destination_port: int
    ) -> None:
        authenticated = self._username is not None
        method = 2 if authenticated else 0
        upstream.sendall(bytes((5, 1, method)))
        if self._recv_exact(upstream, 2) != bytes((5, method)):
            raise _RelayFailure("SOCKS authentication method rejected")

        if authenticated:
            username = (self._username or "").encode("utf-8")
            password = (self._password or "").encode("utf-8")
            upstream.sendall(
                bytes((1, len(username)))
                + username
                + bytes((len(password),))
                + password
            )
            if self._recv_exact(upstream, 2) != b"\x01\x00":
                raise _RelayFailure("SOCKS authentication rejected")

        address_type, address, delegation, destination_type = self._socks_address(
            destination_host, destination_port
        )
        upstream.sendall(
            b"\x05\x01\x00" + bytes((address_type,)) + address + destination_port.to_bytes(2, "big")
        )
        version, reply, _reserved, reply_type = self._recv_exact(upstream, 4)
        if version != 5 or reply != 0:
            raise _RelayFailure("SOCKS CONNECT rejected")
        self._consume_socks_address(upstream, reply_type)
        self._recv_exact(upstream, 2)
        self._record_observation(delegation, destination_type)

    def _socks_address(
        self, host: str, port: int
    ) -> Tuple[int, bytes, str, str]:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if self._scheme == "socks5h":
                try:
                    encoded = host.encode("idna")
                except UnicodeError:
                    raise _RelayFailure("invalid destination name") from None
                if not encoded or len(encoded) > 255:
                    raise _RelayFailure("invalid destination name")
                return 3, bytes((len(encoded),)) + encoded, "upstream", "hostname"
            try:
                answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            except OSError:
                raise _RelayFailure("destination resolution failed") from None
            for family, _socktype, _protocol, _canonname, sockaddr in answers:
                if family == socket.AF_INET:
                    return 1, socket.inet_pton(socket.AF_INET, sockaddr[0]), "local", "hostname"
                if family == socket.AF_INET6:
                    return 4, socket.inet_pton(socket.AF_INET6, sockaddr[0]), "local", "hostname"
            raise _RelayFailure("destination resolution failed")
        if address.version == 4:
            return 1, address.packed, "not_applicable", "ip"
        return 4, address.packed, "not_applicable", "ip"

    @classmethod
    def _consume_socks_address(cls, upstream: socket.socket, address_type: int) -> None:
        if address_type == 1:
            cls._recv_exact(upstream, 4)
        elif address_type == 4:
            cls._recv_exact(upstream, 16)
        elif address_type == 3:
            cls._recv_exact(upstream, cls._recv_exact(upstream, 1)[0])
        else:
            raise _RelayFailure("invalid SOCKS response")

    def _record_dns_observation(self, host: str, hostname_delegation: str) -> None:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            self._record_observation(hostname_delegation, "hostname")
        else:
            self._record_observation("not_applicable", "ip")

    def _record_observation(self, delegation: str, destination_type: str) -> None:
        with self._observation_lock:
            self._dns_observations.append(
                {"delegation": delegation, "destination_type": destination_type}
            )

    def _tunnel(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets = (client, upstream)
        while not self._stop.is_set():
            try:
                readable, _, _ = select.select(sockets, (), (), 0.2)
            except (OSError, ValueError):
                return
            for source in readable:
                destination = upstream if source is client else client
                try:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination.sendall(data)
                except (OSError, ssl.SSLError):
                    return

    @staticmethod
    def _read_headers(sock: socket.socket) -> Tuple[bytes, bytes]:
        data = bytearray()
        while True:
            marker = data.find(b"\r\n\r\n")
            if marker >= 0:
                end = marker + 4
                return bytes(data[:end]), bytes(data[end:])
            if len(data) >= _MAX_HEADER_BYTES:
                raise _RelayFailure("headers too large")
            chunk = sock.recv(min(4096, _MAX_HEADER_BYTES - len(data)))
            if not chunk:
                raise _RelayFailure("connection closed")
            data.extend(chunk)

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise _RelayFailure("connection closed")
            data.extend(chunk)
        return bytes(data)

    @staticmethod
    def _format_authority(host: str, port: int) -> str:
        return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"

    def _add_connection(self, connection: socket.socket) -> None:
        with self._connection_lock:
            self._connections.add(connection)

    def _discard_connection(self, connection: socket.socket) -> None:
        with self._connection_lock:
            self._connections.discard(connection)

    def _close_active_connections(self) -> None:
        with self._connection_lock:
            connections = list(self._connections)
        for connection in connections:
            self._close_socket(connection)

    @staticmethod
    def _close_socket(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    @staticmethod
    def _send_safe(sock: socket.socket, data: bytes) -> None:
        try:
            sock.sendall(data)
        except OSError:
            pass
