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


# ── The domain half of the same problem ──────────────────────────────────────
#
# The port drift (`:8081` in the audit doc against `8080:3000` in compose) had a
# twin waiting: the Caddy site block and the README's "open this URL" line live
# in different files with nothing tying them together. Rename one and the other
# sends an operator to a host that answers nothing — during an incident, which
# is the only time anyone reads a deploy guide.

CADDY_SNIPPET = REPO / "deploy" / "hetzner" / "Caddyfile.snippet"
DEPLOY_README = REPO / "deploy" / "hetzner" / "README.md"


def caddy_site_domain() -> str:
    """The hostname Caddy actually serves, from its site block.

    On parsing: the snippet's header comment names the domain in prose, so a
    loose scan would match the explanation instead of the directive.

    What prevents that is the ANCHORED regex — the whole line must be
    `<domain> {` — not the comment stripping. Mutation testing: delete the
    site block, keep the comment, disable the stripping, and this still
    returns "" correctly.

    Worth stating plainly because I claimed the opposite here, and twice
    before in this file's sibling guards, each time writing the justification
    before testing it. The stripping stays as defence in depth against a
    future comment that is itself a bare `something.tld {` line; it is not
    what is holding today. Loosening the regex is what would break this.
    """
    lines = [l for l in CADDY_SNIPPET.read_text().splitlines()
             if not l.lstrip().startswith("#")]
    for line in lines:
        m = re.match(r"^\s*([A-Za-z0-9.-]+\.[A-Za-z]{2,})\s*\{\s*$", line)
        if m:
            return m.group(1)
    return ""


def test_the_caddy_site_block_was_found():
    """Guards the guard: an empty domain makes the comparison vacuous."""
    assert caddy_site_domain(), (
        "no site block parsed out of Caddyfile.snippet. Either the snippet "
        "changed shape or it no longer declares a site — the comparison below "
        "would otherwise pass against nothing."
    )


#: Hosts the README may legitimately reference that Caddy does not serve.
EXTERNAL_HOSTS = {"github.com"}


def readme_https_hosts() -> set[str]:
    """Every host the README tells an operator to reach over HTTPS."""
    return {
        h for h in re.findall(r"https://([A-Za-z0-9.-]+)", DEPLOY_README.read_text())
        if h not in EXTERNAL_HOSTS
    }


def test_the_deploy_readme_names_the_domain_caddy_serves():
    domain = caddy_site_domain()
    assert domain in readme_https_hosts(), (
        f"Caddyfile.snippet serves {domain!r} but no https:// URL in "
        f"deploy/hetzner/README.md points there. The README is what an "
        f"operator follows; if it names a different host they will curl "
        f"something that does not answer and conclude the deploy failed when "
        f"it did not."
    )


def test_every_https_url_in_the_readme_points_at_that_domain():
    r"""Not just "the domain appears somewhere".

    The first version asserted `domain in readme`, which passes while the
    actual `Open https://...` line names a different host — the domain still
    occurs in the architecture diagram and the DNS row. That is the same
    "appears anywhere" weakness as the bare \b(\d{4,5})\b scan two tests up,
    and it would have missed precisely the drift this guard exists for.
    Raised in review on PR #66.

    Checking every URL rather than one specific line also survives rewording:
    a guard pinned to exact prose fails on an edit that changed nothing real.
    """
    domain = caddy_site_domain()
    wrong = readme_https_hosts() - {domain}
    assert not wrong, (
        f"deploy/hetzner/README.md sends operators to {sorted(wrong)} over "
        f"HTTPS, but Caddy only serves {domain!r}. Those URLs answer nothing. "
        f"If one of them is a genuine external link, add it to EXTERNAL_HOSTS."
    )


def test_no_placeholder_domain_survives_the_rename():
    """A half-finished rename is worse than either state on its own."""
    stale = []
    for path in (REPO / "deploy" / "hetzner").rglob("*"):
        if not path.is_file() or path.suffix in {".sql", ".png"}:
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if "yourdomain" in line:
                stale.append(f"{path.relative_to(REPO)}:{n}")
    assert not stale, (
        f"placeholder domains still present after the rename: {stale}. Mixed "
        f"real and placeholder hostnames in one deploy guide is the worst of "
        f"both — a reader cannot tell which lines they are meant to edit."
    )
