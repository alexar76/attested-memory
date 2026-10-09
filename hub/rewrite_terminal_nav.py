#!/usr/bin/env python3
"""Rewrite AIMarket factory nav links for the Attested Memory Hub landing."""
from __future__ import annotations

import re
from pathlib import Path

PATH = Path(__file__).resolve().with_name("terminal-home.html")
if not PATH.is_file():
    PATH = Path("/app/terminal-home.html")

# Only reuse i18n keys that already exist in hub-ui-i18n.json (nav_devs, nav_live).
# Unknown data-i18n keys render as NAV_* placeholders in the UI.
FIXED = """    <div class="nav-links">
      <a href="/mcp">MCP</a>
      <a href="https://attestedmemory.net/memory">Memory</a>
      <a href="https://attestedmemory.net/teams">Teams</a>
      <a href="https://attestedmemory.net/market">Market</a>
      <a href="https://attestedmemory.net/docs">Guide</a>
      <a href="https://attestedmemory.net/developers" data-i18n="nav_devs">Developers</a>
      <a href="https://attestedmemory.net/billing">Billing</a>
      <a href="https://attestedmemory.net/">SaaS</a>
      <a class="nav-live" href="/"><span class="pip"></span> <span data-i18n="nav_live">Live</span></a>"""

NAV_BLOCK = re.compile(
    r'    <div class="nav-links">\n.*?'
    r'      <a class="nav-live" href="/">'
    r'<span class="pip"></span> <span data-i18n="nav_live">Live</span></a>',
    re.DOTALL,
)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if FIXED in text:
        print(f"already patched: {PATH}")
        return
    patched, count = NAV_BLOCK.subn(FIXED, text, count=1)
    if count != 1:
        raise SystemExit(f"nav block not found in {PATH}")
    PATH.write_text(patched, encoding="utf-8")
    print(f"patched factory nav in {PATH}")


if __name__ == "__main__":
    main()
