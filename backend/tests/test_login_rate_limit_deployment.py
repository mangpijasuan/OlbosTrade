"""
The login rate limiter only works if the deployment lets it see the caller.

api/rate_limit.py keys login attempts on request.client.host. That is the real
caller ONLY when uvicorn runs with --proxy-headers behind a proxy that writes
X-Forwarded-For itself. Without the flag every request carries the proxy's
address, all callers land in one bucket, and the limit inverts into a denial of
service: ten failed logins from anyone lock out everybody for five minutes.

That is not hypothetical — it is what shipped. The image CMD had no
--proxy-headers, and nothing in the test suite noticed, because the limiter's
own behaviour was correct in isolation. The bug lived entirely in the gap
between the code and the way it is launched.

So these tests assert the deployment invariant rather than the function:

  * the stack that runs this app passes --proxy-headers
  * the stacks that publish the backend port do NOT

The second half matters as much as the first. uvicorn 0.29 with
--forwarded-allow-ips=* takes the LEFTMOST X-Forwarded-For entry, which a
caller can forge — harmless when the only route in is a proxy that overwrites
the header, and a free pass around the rate limit when the port is reachable
directly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Stack files and whether their backend is reachable without passing a proxy.
COMPOSE_FILES = [
    "docker-compose.hetzner.yml",
    "docker-compose.yml",
    "docker-compose.prod.yml",
]


def service_block(compose_text: str, service: str) -> str:
    """
    The YAML block for one service, by indentation, WITH COMMENTS STRIPPED.

    Avoids a PyYAML import: it is not a declared dependency of this project,
    and a transitively-present package is a poor thing for a guard test to rest
    on.

    Stripping comments is not tidiness — without it this whole file was
    decorative. The `command:` in the Hetzner stack carries a long comment
    explaining why --proxy-headers is there and why it must not be copied
    elsewhere, so `"--proxy-headers" in block` matched the PROSE. Deleting the
    actual flag left every assertion green. Caught by mutation testing; the
    flag is only meaningful where Docker will read it.
    """
    lines = compose_text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if re.match(rf"^  {re.escape(service)}:\s*$", line):
            inside = True
            continue
        if inside:
            # A new top-level service (two-space indent, not deeper) ends it.
            if re.match(r"^  \S", line) and not line.startswith("    "):
                break
            if re.match(r"^\s*#", line):
                continue                      # comment line — never a directive
            out.append(re.sub(r"\s+#.*$", "", line))   # trailing comment
    if not inside:
        raise AssertionError(f"no `{service}` service found")
    return "\n".join(out)


def publishes_backend_port(block: str) -> bool:
    """A `ports:` mapping means something outside Docker can open a socket
    straight to uvicorn, bypassing any proxy."""
    return bool(re.search(r"^\s+-\s+\"?\d+:\d+", block, re.M))


def read(name: str) -> str:
    path = REPO / name
    assert path.exists(), f"{name} is missing — deployment invariant cannot be checked"
    return path.read_text()


class TestTheRunningStackCanSeeTheCaller:
    def test_hetzner_backend_runs_with_proxy_headers(self):
        block = service_block(read("docker-compose.hetzner.yml"), "backend")
        assert "--proxy-headers" in block, (
            "the Hetzner backend no longer passes --proxy-headers, so uvicorn "
            "ignores X-Forwarded-For and every caller shares one login "
            "rate-limit bucket: ten failed logins lock out everybody"
        )

    def test_hetzner_backend_actually_trusts_the_frontend(self):
        """--proxy-headers alone does nothing here, which is easy to miss.

        uvicorn defaults forwarded_allow_ips to "127.0.0.1". The frontend
        reaches the backend over the Docker network from a container address,
        never from loopback, so with --proxy-headers but no
        --forwarded-allow-ips uvicorn parses the header and then discards it as
        untrusted. The limiter falls straight back to one shared bucket, and
        the command still LOOKS correct.

        Caught in review: the guard above passes on that half-configured
        command, so deleting only this flag left the tests green and the
        limiter broken.
        """
        block = service_block(read("docker-compose.hetzner.yml"), "backend")
        assert "--forwarded-allow-ips" in block, (
            "the Hetzner backend passes --proxy-headers but no "
            "--forwarded-allow-ips, so uvicorn defaults to trusting 127.0.0.1 "
            "only, ignores the frontend's X-Forwarded-For, and every caller is "
            "back in one login rate-limit bucket"
        )

    def test_hetzner_backend_is_not_directly_reachable(self):
        """The whole reason --forwarded-allow-ips=* is safe there."""
        block = service_block(read("docker-compose.hetzner.yml"), "backend")
        assert not publishes_backend_port(block), (
            "the Hetzner backend now publishes a host port. With "
            "--forwarded-allow-ips=* a caller can reach uvicorn directly and "
            "forge X-Forwarded-For, which makes the login rate limit vacuous. "
            "Remove the port, or scope the trusted proxies."
        )

    def test_the_uvicorn_flags_it_overrides_are_not_lost(self):
        """`command:` replaces the image CMD wholesale, so the flags the
        Dockerfile set have to be repeated or they silently disappear."""
        block = service_block(read("docker-compose.hetzner.yml"), "backend")
        for flag in ("--workers", "--loop", "--access-log", "--host", "--port"):
            assert flag in block, (
                f"{flag} was dropped when `command:` overrode the image CMD — "
                f"compare against backend/Dockerfile"
            )


class TestStacksThatExposeTheBackendDoNotTrustTheHeader:
    @pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.prod.yml"])
    def test_a_published_backend_port_never_pairs_with_proxy_headers(self, name):
        block = service_block(read(name), "backend")
        if not publishes_backend_port(block):
            pytest.skip(f"{name} no longer publishes the backend port")
        assert "--proxy-headers" not in block, (
            f"{name} publishes the backend port AND passes --proxy-headers. A "
            f"caller can then connect directly and set X-Forwarded-For to a "
            f"fresh value per request, giving every attempt its own bucket and "
            f"removing the login rate limit entirely."
        )


class TestTheProxyDoesNotLetCallersWriteTheHeader:
    """The other half of the chain: the header uvicorn trusts must be written
    by the proxy, never forwarded from the caller."""

    def test_frontend_overwrites_x_forwarded_for(self):
        entrypoint = (REPO / "frontend" / "docker-entrypoint.sh").read_text()
        api_line = next(
            (l for l in entrypoint.splitlines() if "location /api" in l), None
        )
        assert api_line, "the /api proxy block is gone"
        assert "X-Forwarded-For \\$remote_addr" in api_line, (
            "the /api proxy no longer sets X-Forwarded-For from $remote_addr. "
            "If it appends instead ($proxy_add_x_forwarded_for), the caller's "
            "own header survives into the chain and uvicorn — which reads the "
            "leftmost entry under --forwarded-allow-ips=* — would trust it."
        )

    def test_real_ip_trust_is_opt_in(self):
        """Trusting a proxy for real-IP recovery must default to off: a default
        that trusts a broad range would let a direct caller forge the header."""
        entrypoint = (REPO / "frontend" / "docker-entrypoint.sh").read_text()
        assert "set_real_ip_from" in entrypoint, "real-IP support was removed"
        assert re.search(r'if \[ -n "\$TRUSTED_PROXY_CIDR" \]', entrypoint), (
            "set_real_ip_from is no longer gated on TRUSTED_PROXY_CIDR being "
            "set — it must default to trusting nobody"
        )


class TestTheBlockExtractorIgnoresProse:
    """This file was briefly decorative because the extractor kept comments and
    the Hetzner `command:` is heavily commented. Guard the guard."""

    SAMPLE = """
  backend:
    # a comment mentioning --proxy-headers and "8000:8000" in prose
    image: example
    command: uvicorn app.main:app --workers 1   # trailing comment
  other:
    image: nope
"""

    def test_comment_text_is_not_mistaken_for_configuration(self):
        block = service_block(self.SAMPLE, "backend")
        assert "--proxy-headers" not in block, "a comment was read as a directive"
        assert not publishes_backend_port(block), "a port in prose was read as published"

    def test_real_directives_survive(self):
        block = service_block(self.SAMPLE, "backend")
        assert "--workers 1" in block
        assert "image: example" in block

    def test_the_block_stops_at_the_next_service(self):
        assert "nope" not in service_block(self.SAMPLE, "backend")
