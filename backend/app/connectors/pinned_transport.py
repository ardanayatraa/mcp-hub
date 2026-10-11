"""Connect only to validated IPs while retaining the hostname for HTTP and TLS."""

import httpx
from httpcore._backends.auto import AutoBackend

from app.errors import HubError


class PinnedBackend(AutoBackend):
    def __init__(self, host: str, port: int, addresses: list[str]):
        self.host, self.port, self.addresses = host, port, addresses

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        name = host.decode() if isinstance(host, bytes) else host
        if name.lower().rstrip(".") != self.host or port != self.port:
            raise HubError("SSRF_BLOCKED", "Connection escaped the validated destination", 422)
        # The hostname is never resolved here: the underlying backend gets a literal IP.
        # httpcore still owns TLS start_tls(server_hostname=the original hostname).
        return await super().connect_tcp(self.addresses[0], port, timeout, local_address, socket_options)


def pinned_transport(host: str, port: int, addresses: list[str], verify: bool):
    transport = httpx.AsyncHTTPTransport(verify=verify, trust_env=False, retries=0)
    transport._pool._network_backend = PinnedBackend(host, port, addresses)
    return transport
