r"""
Docs name the port the Hetzner stack actually publishes.

ARCHITECTURE_AUDIT.md recorded the production server as `46.224.0.213:8081`.
The compose file has published `8080:3000` since it was first committed, and the
running server publishes 8080 — so that line was wrong the day it was written,
not merely stale.

It was not harmless. During the 2026-09-17 outage the operator's bookmark
pointed at :8081, so the app looked dead from the browser even once it was
serving; and the wrong port sent the investigation toward "the server's config
has diverged from the repo", which was backwards — the document had diverged
from both.

Worse, no doc named the RIGHT port at all. `grep -rn 8080 --include=*.md` came
back empty. Someone deploying without a domain had nowhere to look but the
compose file's inline comment.

So this asserts a direction, not a value: every literal `IP:port` in the docs
must use a port the Hetzner compose file publishes. Restating "8080" in a test
would only agree with itself; parsing both sides means changing the compose
port makes the docs fail until they follow.

Scope is deliberately narrow — only PUBLIC-IP-literal references. localhost and
127.0.0.1 appear throughout README.md and DEPLOY_V3.md for local development
and for curling the backend from inside its own container; those ports are not
published to the host and must not be dragged into this.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "docker-compose.hetzner.yml"

#: A dotted-quad followed by :port, in any markdown file.
IP_PORT = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})\b")

PRIVATE_PREFIXES = ("127.", "0.", "10.", "192.168.", "172.16.", "172.17.", "255.")


def published_host_ports() -> set[int]:
    """Host ports the Hetzner stack publishes, from `ports:` entries.

    Comments are stripped: the `ports:` block carries an explanatory comment
    naming the URL, and this repo has already shipped one guard that matched
    its own prose instead of the setting.
    """
    lines = [
        l for l in COMPOSE.read_text().splitlines()
        if not l.lstrip().startswith("#")
    ]
    ports: set[int] = set()
    for line in lines:
        m = re.match(r'^\s*-\s*"?(\d{2,5}):(\d{2,5})"?\s*$', line)
        if m:
            ports.add(int(m.group(1)))
    return ports


def markdown_files() -> list[Path]:
    return [
        p for p in REPO.rglob("*.md")
        if "node_modules" not in p.parts and ".git" not in p.parts
    ]


def documented_ip_ports() -> list[tuple[Path, int, int, str]]:
    """(file, line_no, port, the line) for each public-IP:port in the docs."""
    found = []
    for path in markdown_files():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for ip, port in IP_PORT.findall(line):
                if ip.startswith(PRIVATE_PREFIXES):
                    continue
                found.append((path, n, int(port), line.strip()))
    return found


def test_the_compose_ports_were_actually_parsed():
    """Guards the guard: an empty set makes every membership check below fail
    loudly rather than pass vacuously — but an empty set of DOC references
    would make them pass, so both sides are checked."""
    ports = published_host_ports()
    assert ports, (
        "no published host ports parsed from docker-compose.hetzner.yml. Either "
        "the stack stopped publishing any port, or the `ports:` shape changed "
        "and this test can no longer see it."
    )


def test_every_documented_ip_port_is_one_the_stack_publishes():
    published = published_host_ports()
    wrong = [
        (str(p.relative_to(REPO)), n, port, line)
        for p, n, port, line in documented_ip_ports()
        if port not in published
    ]
    assert not wrong, (
        "these docs name a port the Hetzner stack does not publish "
        f"(published: {sorted(published)}):\n"
        + "\n".join(f"  {f}:{n} → :{port}\n      {line}" for f, n, port, line in wrong)
        + "\n\nA wrong port here reads as a dead app. On 2026-09-17 it sent an "
          "outage investigation toward the server's config when the document "
          "was what had drifted."
    )


def test_the_direct_access_port_is_documented_somewhere():
    """The original gap: :8081 was wrong AND nothing named the right one."""
    published = published_host_ports()
    readme = (REPO / "deploy" / "hetzner" / "README.md").read_text()
    # `:8080`, not a bare 8080. A loose \b(\d{4,5})\b scan is satisfied by the
    # number appearing anywhere at all — including inside a quoted
    # `ports: ["8080:3000"]` example — which is the difference between "the
    # README tells an operator the URL" and "the digits occur in this file".
    # Mutation-testing caught exactly that: gutting the URL prose left this
    # passing.
    named = {int(m) for m in re.findall(r":(\d{4,5})\b", readme)}
    assert published & named, (
        f"deploy/hetzner/README.md names none of the published host ports "
        f"{sorted(published)}. An operator deploying without a domain has "
        f"nowhere to find the direct URL but a comment inside the compose file "
        f"— which is how :8081 survived in the audit doc unchallenged."
    )
