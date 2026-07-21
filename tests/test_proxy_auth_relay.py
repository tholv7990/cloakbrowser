from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import ipaddress
import socket
import ssl
import threading

import pytest

from benchmarks.proxy_auth_relay import AuthenticatedProxyRelay


_USERNAME = "docs-user"
_PASSWORD = "p@ss:word%="
_ENCODED_PASSWORD = "p%40ss%3Aword%25%3D"


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise EOFError("socket closed")
        chunks.extend(chunk)
    return bytes(chunks)


def _recv_headers(sock: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError("socket closed before headers")
        data.extend(chunk)
        if len(data) > 65536:
            raise ValueError("headers too large")
    return bytes(data)


def _connect_through_relay(relay: AuthenticatedProxyRelay, authority: str) -> tuple[bytes, bytes]:
    host, port_text = relay.browser_proxy_url.removeprefix("http://").rsplit(":", 1)
    browser = socket.create_connection((host, int(port_text)), timeout=2)
    browser.settimeout(2)
    browser.sendall(
        f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode("ascii")
    )
    response = _recv_headers(browser)
    browser.sendall(b"ping")
    tunneled = _recv_exact(browser, 4)
    browser.close()
    return response, tunneled


def _start_http_connect_upstream(
    listener: socket.socket,
    capture: dict[str, object],
    *,
    tls_context: ssl.SSLContext | None = None,
) -> threading.Thread:
    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                stream = (
                    tls_context.wrap_socket(connection, server_side=True)
                    if tls_context is not None
                    else connection
                )
                with stream if stream is not connection else _null_context(stream):
                    capture["request"] = _recv_headers(stream)
                    stream.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    capture["payload"] = _recv_exact(stream, 4)
                    stream.sendall(b"pong")
        except BaseException as exc:  # surfaced by the assertion helper
            capture["error"] = exc
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


class _null_context:
    def __init__(self, value: socket.socket) -> None:
        self._value = value

    def __enter__(self) -> socket.socket:
        return self._value

    def __exit__(self, *_args: object) -> None:
        return None


def _assert_server_finished(thread: threading.Thread, capture: dict[str, object]) -> None:
    thread.join(2)
    assert not thread.is_alive()
    assert "error" not in capture, repr(capture.get("error"))


@pytest.fixture
def local_tls_contexts(tmp_path):
    cryptography = pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    del cryptography
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "relay-test-cert.pem"
    key_path = tmp_path / "relay-test-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    client_context = ssl.create_default_context(cafile=str(cert_path))
    return server_context, client_context


@pytest.mark.parametrize(
    "invalid_proxy",
    [
        "http://docs-user:secret@127.0.0.1:8080/path-secret",
        "https://docs-user:secret@127.0.0.1:8080/?query-secret",
        "socks5://docs-user:secret@127.0.0.1:1080#fragment-secret",
        "http://docs-user:secret@127.0.0.1:not-a-port",
    ],
)
def test_configuration_errors_never_echo_proxy_input(invalid_proxy: str) -> None:
    with pytest.raises(ValueError) as caught:
        AuthenticatedProxyRelay(invalid_proxy)

    error = str(caught.value)
    assert invalid_proxy not in error
    assert "docs-user" not in error
    assert "secret" not in error
    assert "127.0.0.1" not in error


def test_repr_and_browser_url_hide_upstream_identity_and_credentials() -> None:
    upstream = f"http://{_USERNAME}:{_ENCODED_PASSWORD}@[2001:db8::7]:8080"
    relay = AuthenticatedProxyRelay(upstream)

    before = repr(relay)
    for secret in (_USERNAME, _PASSWORD, _ENCODED_PASSWORD, "2001:db8::7"):
        assert secret not in before

    with relay:
        browser_url = relay.browser_proxy_url
        assert browser_url.startswith("http://127.0.0.1:")
        assert "@" not in browser_url
        assert "2001:db8::7" not in browser_url
        port = int(browser_url.rsplit(":", 1)[1])
        assert port > 0
        running = repr(relay)
        for secret in (_USERNAME, _PASSWORD, _ENCODED_PASSWORD, "2001:db8::7"):
            assert secret not in running

    assert not relay.is_running
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.2)


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize(
    ("password_in_url", "decoded_password"),
    [
        (_ENCODED_PASSWORD, _PASSWORD),
        ("p@ss%3Aword%25%3D", _PASSWORD),
        ("", ""),
    ],
)
def test_http_proxy_connect_adds_basic_auth_only_upstream(
    scheme: str,
    password_in_url: str,
    decoded_password: str,
    local_tls_contexts,
) -> None:
    server_tls, client_tls = local_tls_contexts
    listener = socket.create_server(("127.0.0.1", 0))
    capture: dict[str, object] = {}
    thread = _start_http_connect_upstream(
        listener,
        capture,
        tls_context=server_tls if scheme == "https" else None,
    )
    upstream_port = listener.getsockname()[1]
    upstream = (
        f"{scheme}://{_USERNAME}:{password_in_url}@127.0.0.1:{upstream_port}"
    )

    with AuthenticatedProxyRelay(
        upstream,
        upstream_tls_context=client_tls if scheme == "https" else None,
    ) as relay:
        response, tunneled = _connect_through_relay(relay, "example.test:443")

    _assert_server_finished(thread, capture)
    expected = base64.b64encode(f"{_USERNAME}:{decoded_password}".encode()).decode()
    request = capture["request"]
    assert isinstance(request, bytes)
    assert request.startswith(b"CONNECT example.test:443 HTTP/1.1\r\n")
    assert f"Proxy-Authorization: Basic {expected}\r\n".encode() in request
    assert b"Proxy-Authorization" not in response
    assert response.startswith(b"HTTP/1.1 200")
    assert capture["payload"] == b"ping"
    assert tunneled == b"pong"
    assert relay.dns_observations == (
        {"delegation": "upstream", "destination_type": "hostname"},
    )
    assert relay.active_worker_count == 0


def _start_socks5_upstream(
    listener: socket.socket,
    capture: dict[str, object],
) -> threading.Thread:
    def serve() -> None:
        try:
            connection, _ = listener.accept()
            with connection:
                version, method_count = _recv_exact(connection, 2)
                capture["greeting"] = (version, _recv_exact(connection, method_count))
                connection.sendall(b"\x05\x02")
                auth_version, username_size = _recv_exact(connection, 2)
                username = _recv_exact(connection, username_size)
                password_size = _recv_exact(connection, 1)[0]
                password = _recv_exact(connection, password_size)
                capture["auth"] = (auth_version, username, password)
                connection.sendall(b"\x01\x00")

                version, command, reserved, address_type = _recv_exact(connection, 4)
                if address_type == 1:
                    address = socket.inet_ntop(socket.AF_INET, _recv_exact(connection, 4))
                elif address_type == 4:
                    address = socket.inet_ntop(socket.AF_INET6, _recv_exact(connection, 16))
                elif address_type == 3:
                    size = _recv_exact(connection, 1)[0]
                    address = _recv_exact(connection, size).decode("idna")
                else:
                    raise AssertionError(f"unexpected SOCKS address type {address_type}")
                port = int.from_bytes(_recv_exact(connection, 2), "big")
                capture["connect"] = (version, command, reserved, address_type, address, port)
                connection.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
                capture["payload"] = _recv_exact(connection, 4)
                connection.sendall(b"pong")
        except BaseException as exc:
            capture["error"] = exc
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize(
    ("scheme", "authority", "expected_type", "delegation"),
    [
        ("socks5", "localhost:443", {1, 4}, "local"),
        ("socks5h", "docs.example:443", {3}, "upstream"),
    ],
)
def test_socks5_connect_uses_rfc1929_and_expected_dns_delegation(
    scheme: str,
    authority: str,
    expected_type: set[int],
    delegation: str,
) -> None:
    listener = socket.create_server(("127.0.0.1", 0))
    capture: dict[str, object] = {}
    thread = _start_socks5_upstream(listener, capture)
    port = listener.getsockname()[1]
    upstream = f"{scheme}://{_USERNAME}:{_ENCODED_PASSWORD}@127.0.0.1:{port}"

    with AuthenticatedProxyRelay(upstream) as relay:
        response, tunneled = _connect_through_relay(relay, authority)

    _assert_server_finished(thread, capture)
    assert capture["greeting"] == (5, b"\x02")
    assert capture["auth"] == (1, _USERNAME.encode(), _PASSWORD.encode())
    connect = capture["connect"]
    assert isinstance(connect, tuple)
    assert connect[0:3] == (5, 1, 0)
    assert connect[3] in expected_type
    assert connect[5] == 443
    assert capture["payload"] == b"ping"
    assert tunneled == b"pong"
    assert response.startswith(b"HTTP/1.1 200")
    assert relay.dns_observations == (
        {"delegation": delegation, "destination_type": "hostname"},
    )
    serialized_observations = repr(relay.dns_observations)
    assert authority.split(":", 1)[0] not in serialized_observations
    assert relay.active_worker_count == 0


def test_cleanup_closes_active_tunnel_and_joins_workers() -> None:
    listener = socket.create_server(("127.0.0.1", 0))
    capture: dict[str, object] = {}
    accepted = threading.Event()

    def hold_upstream() -> None:
        connection, _ = listener.accept()
        with connection:
            capture["request"] = _recv_headers(connection)
            connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            accepted.set()
            while connection.recv(1024):
                pass
        listener.close()

    upstream_thread = threading.Thread(target=hold_upstream, daemon=True)
    upstream_thread.start()
    upstream_port = listener.getsockname()[1]
    relay = AuthenticatedProxyRelay(
        f"http://{_USERNAME}:{_ENCODED_PASSWORD}@127.0.0.1:{upstream_port}",
        worker_join_timeout=1.0,
    )
    relay.start()
    browser_host, browser_port = relay.browser_proxy_url.removeprefix("http://").split(":")
    browser = socket.create_connection((browser_host, int(browser_port)), timeout=2)
    browser.settimeout(2)
    browser.sendall(b"CONNECT example.test:443 HTTP/1.1\r\nHost: example.test:443\r\n\r\n")
    assert _recv_headers(browser).startswith(b"HTTP/1.1 200")
    assert accepted.wait(1)

    relay.close()
    relay.close()

    assert not relay.is_running
    assert relay.active_worker_count == 0
    assert browser.recv(1) == b""
    browser.close()
    upstream_thread.join(2)
    assert not upstream_thread.is_alive()
    with pytest.raises(OSError):
        socket.create_connection((browser_host, int(browser_port)), timeout=0.2)


def test_upstream_failures_return_only_a_generic_browser_error() -> None:
    rejecting = socket.create_server(("127.0.0.1", 0))
    port = rejecting.getsockname()[1]
    rejected = threading.Event()

    def reject_connection() -> None:
        connection, _ = rejecting.accept()
        connection.close()
        rejecting.close()
        rejected.set()

    reject_thread = threading.Thread(target=reject_connection, daemon=True)
    reject_thread.start()
    upstream = f"http://{_USERNAME}:{_ENCODED_PASSWORD}@127.0.0.1:{port}"

    with AuthenticatedProxyRelay(upstream) as relay:
        host, relay_port = relay.browser_proxy_url.removeprefix("http://").split(":")
        browser = socket.create_connection((host, int(relay_port)), timeout=2)
        browser.sendall(b"CONNECT nowhere.invalid:443 HTTP/1.1\r\n\r\n")
        response = _recv_headers(browser)
        browser.close()

    assert rejected.wait(1)
    reject_thread.join(1)

    assert response == b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n"
    rendered = repr(relay)
    for secret in (_USERNAME, _PASSWORD, _ENCODED_PASSWORD, "127.0.0.1"):
        assert secret not in rendered
    assert relay.active_worker_count == 0
