from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_attested_developer_portal_publishes_mcp_endpoint() -> None:
    html = (ROOT / "saas-landing/developers.html").read_text()

    assert "https://hub.attestedmemory.net/mcp" in html
    assert 'id="mcp"' in html
    assert "market_search" in html
    assert "market_invoke" in html
    assert "copy-btn" in html


def test_hub_terminal_publishes_its_own_origin_mcp_endpoint() -> None:
    html = (ROOT / "aimarket-hub/terminal-home.html").read_text()

    assert "`${HUB}/mcp`" in html
    assert 'id="mcp-copy"' in html
    assert 'href="/mcp"' in html


def test_attested_nav_rewrite_preserves_mcp_and_is_idempotent(tmp_path: Path) -> None:
    script = tmp_path / "rewrite_terminal_nav.py"
    terminal = tmp_path / "terminal-home.html"
    shutil.copy(ROOT / "attested/attested-memory-hub/hub/rewrite_terminal_nav.py", script)
    shutil.copy(ROOT / "aimarket-hub/terminal-home.html", terminal)

    subprocess.run([sys.executable, str(script)], check=True)
    first = terminal.read_text()
    subprocess.run([sys.executable, str(script)], check=True)

    assert terminal.read_text() == first
    assert '<a href="/mcp">MCP</a>' in first
    assert 'href="https://attestedmemory.net/developers"' in first
    # The nav is Attested's own pages. The page body may link GitHub now that Attested Memory is
    # published there (the shared terminal template carries the Pay-on-Verified disclaimer link).
    nav = first[first.index('<div class="nav-links">'):first.index('<span data-i18n="nav_live">')]
    assert "github.com" not in nav


def test_independent_portal_publishes_mcp_endpoint() -> None:
    html = (ROOT / "independent/landing/public/index.html").read_text()
    javascript = (ROOT / "independent/landing/public/portal.js").read_text()
    endpoint = "https://independentai.network/hub/mcp"

    assert endpoint in html
    assert endpoint in javascript
    assert 'href="#agents">MCP</a>' in html
