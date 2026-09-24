"""Public-web policy shared by the controller, native scraper and egress proxy."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

MAX_URL = 2048
FIXTURE_ENV = "RAPP_DOCK_TEST_FIXTURE"
FIXTURE_PORT = 8765
FIXTURE_MAX_SECONDS = 1800
_TEST_NAMESPACE = re.compile(r"rapp-dock-t[a-h]\Z")
_FIXTURE_NETWORKS = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home")
_METADATA_HOSTS = frozenset(("metadata.packet.net", "metadata.platformequinix.com"))
_METADATA_ADDRESSES = frozenset(("168.63.129.16", "100.100.100.200"))
_CREDENTIAL_QUERY_KEYS = frozenset((
    "access_token", "api_key", "apikey", "auth", "authorization", "awsaccesskeyid",
    "bearer_token", "client_secret", "googleaccessid", "id_token", "jwt", "key",
    "oauth_token", "password", "passwd", "pwd", "sas_token", "secret", "sig",
    "signature", "token", "x_amz_credential", "x_amz_security_token", "x_amz_signature",
    "x_goog_credential", "x_goog_signature",
))
_TRANSITION_NETS = tuple(
    ipaddress.ip_network(value)
    for value in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16")
)


class URLNotAllowed(ValueError):
    def __init__(self, detail: str = "Only public HTTP(S) destinations on ports 80/443 are allowed."):
        super().__init__(detail)


@dataclass(frozen=True)
class FixtureScope:
    namespace: str
    origin: str
    address: str
    expires_at: int


def fixture_scope(*, namespace: str | None = None, environment=None, now=None) -> FixtureScope | None:
    environment = os.environ if environment is None else environment
    encoded = environment.get(FIXTURE_ENV, "")
    if not encoded:
        return None
    active_namespace = environment.get("RAPP_DOCK_NAMESPACE", "")
    if not _TEST_NAMESPACE.fullmatch(active_namespace) or namespace not in (None, active_namespace):
        raise URLNotAllowed("The exact-origin fixture is available only in its matching test namespace.")
    try:
        if len(encoded) > 1024:
            raise ValueError()
        value = json.loads(encoded)
        if not isinstance(value, dict) or set(value) != {"namespace", "origin", "address", "expires_at"}:
            raise ValueError()
        if value["namespace"] != active_namespace:
            raise ValueError()
        address = ipaddress.IPv4Address(value["address"])
        if value["address"] != str(address) or not any(address in network for network in _FIXTURE_NETWORKS):
            raise ValueError()
        if value["origin"] != f"http://{address}:{FIXTURE_PORT}":
            raise ValueError()
        clock = time.time() if now is None else now
        if type(value["expires_at"]) is not int or not clock < value["expires_at"] <= clock + FIXTURE_MAX_SECONDS:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise URLNotAllowed("The exact-origin test fixture scope is invalid or expired.") from None
    return FixtureScope(**value)


@dataclass(frozen=True)
class Target:
    url: str
    host: str
    port: int
    addresses: tuple[tuple[int, str], ...]
    fixture: FixtureScope | None = None


def public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if str(address) in _METADATA_ADDRESSES:
        return False
    if not address.is_global or any(
        (address.is_private, address.is_loopback, address.is_link_local,
         address.is_multicast, address.is_reserved, address.is_unspecified)
    ):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.is_site_local or address.ipv4_mapped or any(address in network for network in _TRANSITION_NETS):
            return False
    return True


def public_url(url: str, *, resolve: bool = True, resolver=None, namespace: str | None = None) -> Target:
    scope = fixture_scope(namespace=namespace)
    if not isinstance(url, str) or not url or len(url) > MAX_URL:
        raise URLNotAllowed()
    if "\\" in url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise URLNotAllowed()
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https") or not parsed.netloc or parsed.username is not None:
            raise URLNotAllowed()
        if "%" in parsed.netloc or "@" in parsed.netloc or parsed.password is not None:
            raise URLNotAllowed()
        query_fields = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=128)
        if any(key.lower().replace("-", "_") in _CREDENTIAL_QUERY_KEYS for key, _ in query_fields):
            raise URLNotAllowed()
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
        if not host or len(host) > 253:
            raise URLNotAllowed()
        if scope:
            if scheme != "http" or parsed.netloc != f"{scope.address}:{FIXTURE_PORT}" or host != scope.address:
                raise URLNotAllowed()
        else:
            if port != (443 if scheme == "https" else 80):
                raise URLNotAllowed()
            if host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or host in _METADATA_HOSTS:
                raise URLNotAllowed()
            try:
                literal = ipaddress.ip_address(host)
            except ValueError:
                if "." not in host or not all(_LABEL.fullmatch(label) for label in host.split(".")):
                    raise URLNotAllowed()
            else:
                if not public_address(str(literal)):
                    raise URLNotAllowed()
    except (UnicodeError, ValueError):
        raise URLNotAllowed() from None

    authority = f"[{host}]" if ":" in host else host
    if scope:
        authority += f":{FIXTURE_PORT}"
    normalized = urlunsplit(
        (scheme, authority, quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
         quote(parsed.query, safe="/?%:@!$&'()*+,;=-._~"), "")
    )
    addresses: list[tuple[int, str]] = []
    if resolve:
        try:
            rows = (resolver or socket.getaddrinfo)(host, port, type=socket.SOCK_STREAM)
        except (OSError, UnicodeError):
            raise URLNotAllowed("The destination does not resolve exclusively to public addresses.") from None
        for family, _kind, _protocol, _canonical, address in rows:
            value = address[0]
            if scope:
                valid = family == socket.AF_INET and value == scope.address
            else:
                valid = family in (socket.AF_INET, socket.AF_INET6) and public_address(value)
            if not valid:
                raise URLNotAllowed("The destination does not resolve exclusively to public addresses.")
            pair = (family, value)
            if pair not in addresses:
                addresses.append(pair)
        if not addresses:
            raise URLNotAllowed("The destination has no public address.")
    return Target(normalized, host, port, tuple(addresses), scope)


def connect_public(target: Target, *, timeout: float = 10, socket_factory=None):
    """Connect to an already-validated literal address, never resolving it again."""
    if target.fixture and fixture_scope(namespace=target.fixture.namespace) != target.fixture:
        raise URLNotAllowed("The exact-origin test fixture scope is no longer active.")
    factory = socket_factory or socket.socket
    for family, address in target.addresses:
        connection = factory(family, socket.SOCK_STREAM)
        try:
            connection.settimeout(timeout)
            connection.connect((address, target.port))
            return connection
        except OSError:
            connection.close()
    raise OSError("Public destination connection failed.")
