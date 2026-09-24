"""Narrow authenticated native Scrapling MCP, running only inside its image."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urljoin

from scrapling.core.ai import ResponseModel, ScraplingMCPServer, _translate_response
from scrapling.fetchers import AsyncDynamicSession, FetcherSession

from policy_client import checked_target
from url_policy import URLNotAllowed

MAX_CONTENT = 2 * 1024 * 1024
PROXY = "http://egress:8081"


class DockResponse(ResponseModel):
    requested_url: str
    redirects: list[str] = []
    fetch_mode: str
    browser_version: str | None = None


def browser_endpoint():
    address = ipaddress.ip_address(socket.gethostbyname("browser"))
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
        raise ValueError("app-not-ready: the private native browser endpoint is unavailable")
    return f"http://{address}:9222"


def translated(page, requested: str, redirects: list[str], mode: str) -> DockResponse:
    result = _translate_response(page, "markdown", None, True)
    content = "\n\n".join(result.content)
    if len(content.encode("utf-8")) > MAX_CONTENT:
        raise ValueError("output-invalid: extracted content exceeds the size limit")
    final = checked_target(result.url).url
    return DockResponse(
        status=result.status, content=result.content, url=final,
        requested_url=requested, redirects=redirects, fetch_mode=mode,
    )


class DockScrapling(ScraplingMCPServer):
    async def make_request(self, url: str) -> DockResponse:
        """Extract one public HTTP(S) page; fixed GET, safe redirects and egress."""
        try:
            target = checked_target(url).url
            requested, redirects = target, []
            async with FetcherSession() as session:
                for index in range(6):
                    checked_target(target)
                    page = await session.get(
                        target, proxy=PROXY, timeout=25, retries=0,
                        follow_redirects=False, verify=True,
                        stealthy_headers=False, http3=False,
                    )
                    if (page.headers.get("x-rapp-dock-policy") or page.headers.get("X-Rapp-Dock-Policy")) == "url-not-allowed":
                        raise URLNotAllowed("The egress policy refused the connection.")
                    if page.status not in (301, 302, 303, 307, 308):
                        return translated(page, requested, redirects, "http")
                    location = page.headers.get("location") or page.headers.get("Location")
                    if not location or index == 5:
                        raise URLNotAllowed("Redirect chain is missing a target or exceeds five hops.")
                    target = checked_target(urljoin(target, location)).url
                    redirects.append(target)
        except URLNotAllowed as error:
            raise ValueError("url-not-allowed: " + str(error)) from None
        raise ValueError("output-invalid: no response")

    async def fetch(self, url: str) -> DockResponse:
        """Extract one public page with Chromium; no custom browser capabilities."""
        blocked: list[str] = []
        redirects: list[str] = []
        try:
            requested = checked_target(url).url

            async def route_request(route):
                try:
                    if route.request.method not in ("GET", "HEAD"):
                        raise URLNotAllowed("Only read-only browser requests are allowed.")
                    target = await asyncio.to_thread(checked_target, route.request.url)
                    if route.request.is_navigation_request():
                        redirects.append(target.url)
                        if len(redirects) > 8:
                            raise URLNotAllowed("Browser navigation limit exceeded.")
                    await route.fallback()
                except URLNotAllowed:
                    blocked.append("url-not-allowed")
                    await route.abort("blockedbyclient")
                except (ValueError, OSError):
                    blocked.append("app-not-ready")
                    await route.abort("blockedbyclient")

            async def setup(page):
                async def block_socket(route):
                    blocked.append("url-not-allowed")
                    await route.close()

                try:
                    await page.context.route("**/*", route_request)
                    # Native resource filters install page routes, which precede context routes.
                    await page.route("**/*", route_request)
                    await page.context.route_web_socket("**/*", block_socket)
                except Exception:
                    blocked.append("url-not-allowed")
                    await page.close()
                    raise

            async with AsyncDynamicSession(
                headless=True, proxy=PROXY, cdp_url=browser_endpoint(), max_pages=1, timeout=30000,
                google_search=False, disable_resources=True, block_ads=True,
                page_setup=setup, network_idle=False,
                extra_flags=[
                    "--proxy-bypass-list=<-loopback>", "--disable-quic",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                ],
                additional_args={
                    "service_workers": "block", "accept_downloads": False,
                    "ignore_https_errors": False,
                    "proxy": {"server": PROXY, "bypass": "<-loopback>"},
                },
            ) as session:
                page = await session.fetch(requested)
                version = session.browser.version
            if blocked:
                if "url-not-allowed" in blocked:
                    raise URLNotAllowed("A browser request targeted a prohibited destination.")
                raise ValueError("app-not-ready: public-web policy checks did not complete")
            result = translated(page, requested, redirects[1:], "browser")
            result.browser_version = version
            return result
        except URLNotAllowed as error:
            raise ValueError("url-not-allowed: " + str(error)) from None
        except Exception:
            if blocked:
                code = "url-not-allowed" if "url-not-allowed" in blocked else "app-not-ready"
                raise ValueError(code + ": browser request refused") from None
            raise

    def _build_server(self, host, port):
        server = super()._build_server(host, port)
        for name in (
            "open_session", "open_request_session", "close_session", "list_sessions",
            "bulk_get", "bulk_fetch", "stealthy_fetch", "bulk_stealthy_fetch",
            "session_fetch", "session_make_request", "screenshot",
        ):
            server.remove_tool(name)
        return server


if __name__ == "__main__":
    if not os.environ.get("SCRAPLING_MCP_AUTH_TOKEN"):
        raise SystemExit("A private MCP token is required.")
    DockScrapling().serve(
        True, "0.0.0.0", 8000, allowed_hosts=("scrapling:8000",),
        allow_unauthenticated=False,
    )
