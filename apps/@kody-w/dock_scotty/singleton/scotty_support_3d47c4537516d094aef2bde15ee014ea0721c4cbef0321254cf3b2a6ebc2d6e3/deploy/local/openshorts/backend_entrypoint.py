"""Bind native API/MCP only to this project's private interface, never its AI link."""

import ipaddress
import os
import socket


def private_address():
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo("openshorts-native", 8000, socket.AF_INET, socket.SOCK_STREAM)
    }
    if len(addresses) != 1:
        raise RuntimeError("OpenShorts private interface is not uniquely resolvable")
    address = addresses.pop()
    value = ipaddress.ip_address(address)
    if not value.is_private or value.is_loopback or value.is_unspecified:
        raise RuntimeError("OpenShorts private interface is invalid")
    return address


if __name__ == "__main__":
    os.execv("/opt/venv/bin/uvicorn", [
        "uvicorn", "app:app", "--host", private_address(), "--port", "8000",
        "--timeout-graceful-shutdown", "15",
    ])
