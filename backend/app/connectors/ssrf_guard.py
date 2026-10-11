"""Block connector targets that resolve to loopback, link-local, or metadata addresses."""

import ipaddress
import socket
from urllib.parse import urlsplit

from app.config import Settings
from app.errors import HubError

BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
    "metadata",
}


def _ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, settings: Settings) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _ip_allowed(ip.ipv4_mapped, settings)
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if str(ip) == "169.254.169.254":
        return False
    if ip.is_loopback:
        return settings.egress_allow_loopback
    if ip.is_private:
        return settings.egress_allow_private
    return True


def validate_destination(url: str, settings: Settings) -> tuple[str, int, list[str]]:
    """Return host, port, and the resolved addresses that passed policy."""

    parts = urlsplit(url)
    if parts.username or parts.password:
        raise HubError("SSRF_BLOCKED", "Credentials in the connector URL are not allowed", 422)
    if parts.scheme == "https":
        pass
    elif parts.scheme == "http" and settings.allow_insecure_http:
        pass
    else:
        raise HubError("SSRF_BLOCKED", "Connector URL scheme is not allowed", 422)
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host in BLOCKED_HOSTS or host.endswith(".localhost"):
        raise HubError("SSRF_BLOCKED", "Connector host is not allowed", 422)
    hosts = settings.csv(settings.egress_allowed_hosts)
    networks = [ipaddress.ip_network(value, strict=False) for value in settings.csv(settings.egress_allowed_cidrs)]
    host_approved = host in hosts
    if hosts and not host_approved and not networks:
        raise HubError("SSRF_BLOCKED", "Connector host is outside approved egress destinations", 422)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in settings.port_list:
        raise HubError("SSRF_BLOCKED", "Connector port is not allowed", 422)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_allowed(literal, settings):
            raise HubError("SSRF_BLOCKED", "Destination address is not allowed", 422)
        if (hosts or networks) and not host_approved and not any(literal in n for n in networks):
            raise HubError("SSRF_BLOCKED", "Destination is outside approved egress destinations", 422)
        return host, port, [str(literal)]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HubError("CONNECTOR_DNS", "Connector host could not be resolved", 422) from exc
    addresses: list[str] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not _ip_allowed(ip, settings):
            raise HubError("SSRF_BLOCKED", "Destination address is not allowed", 422)
        if (hosts or networks) and not host_approved and not any(ip in n for n in networks):
            raise HubError("SSRF_BLOCKED", "Destination is outside approved egress destinations", 422)
        addresses.append(str(ip))
    if not addresses:
        raise HubError("CONNECTOR_DNS", "Connector host could not be resolved", 422)
    return host, port, addresses


def assert_same_origin(original: str, redirected: str) -> None:
    left = urlsplit(original)
    right = urlsplit(redirected)
    if (left.scheme, (left.hostname or "").lower(), left.port) != (
        right.scheme,
        (right.hostname or "").lower(),
        right.port,
    ):
        raise HubError("SSRF_BLOCKED", "Redirect to another origin is not allowed", 422)
