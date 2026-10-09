"""Behaviour of scripts/update_saas_env.sh against a shared .env.attested-saas.

The Deal/Meter/Prove deploy keeps its tokens and KEY_DERIVATION_SECRETs in the
same file as the SaaS gateway. Every test runs the real script in a temp dir;
all values are fakes.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[1] / "scripts" / "update_saas_env.sh"

HUB_MM_KEY = "mm" + "1" * 62
HUB_TEAM_SECRET = "team" + "2" * 60
INPUTS = {
    "PUBLIC_SAAS_URL": "https://memory.example.test",
    "PAYMENT_RECIPIENT": "0x" + "ab" * 20,
    "KOVA_URL": "https://kova.example.test",
    "KOVA_API_KEY": "kova-caller-key",
    "HUB_NETWORK": "attested-memory-hub_default",
}

# The keys the gateway owns, in the order the old whole-file heredoc wrote them.
GATEWAY_KEYS = [
    "AIFACTORY_PROD",
    "SAAS_POSTGRES_USER",
    "SAAS_POSTGRES_PASSWORD",
    "SAAS_POSTGRES_DB",
    "SAAS_GATEWAY_API_KEY",
    "SAAS_EDGE_TOKEN",
    "SAAS_KEY_DERIVATION_SECRET",
    "SAAS_RECONCILE_SECONDS",
    "SAAS_KEY_REVEAL_HOURS",
    "KOVA_URL",
    "KOVA_API_KEY",
    "SAAS_PAYMENT_RECIPIENT",
    "SAAS_TEAM_AUTH_SECRET",
    "SAAS_PUBLIC_ORIGIN",
    "MEMORY_MARKET_URL",
    "MEMORY_MARKET_API_KEY",
    "ATTESTED_HUB_NETWORK",
]
MINTED = [
    "SAAS_POSTGRES_PASSWORD",
    "SAAS_GATEWAY_API_KEY",
    "SAAS_EDGE_TOKEN",
    "SAAS_KEY_DERIVATION_SECRET",
]

# What attested/deploy/deploy_attested_saas.sh keeps in the same file.
TRIO_LINES = [
    "# attested-saas trio",
    *(
        f"{service}_{name}={service.lower()}-{name.lower()}-" + "9" * 24
        for service in ("DEAL", "METER", "PROVE")
        for name in ("ADMIN_TOKEN", "SERVICE_TOKEN", "KEY_DERIVATION_SECRET")
    ),
    *(
        f"ATTESTED_{service}_PUBLISHER_TOKEN={service.lower()}-publisher-" + "8" * 24
        for service in ("DEAL", "METER", "PROVE")
    ),
    "AIMARKET_CAPABILITY_TOKEN=capability-" + "7" * 24,
    "DEAL_TRUTH_URL=http://truth-layer:8811",
    "AIMARKET_HUB_URL=http://hub:9083",
    "EXPERT_PUBLIC_ORIGIN=https://expert.example.test",
    # Would run if the file were sourced, as the old deploy did.
    "DEAL_ARBITER_KEYS=k1:ab,k2:cd $(touch pwned) ; x",
]


def key_of(line: str) -> str:
    return line.split("=", 1)[0] if "=" in line and not line.startswith("#") else ""


def parse(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        if key_of(line):
            key, value = line.split("=", 1)
            env[key] = value
    return env


def run(tmp_path: Path, env_file: Path, hub_env: str | None = None, **inputs: str | None):
    hub = tmp_path / "hub.env"
    hub.write_text(
        hub_env
        if hub_env is not None
        else f"MEMORY_MARKET_API_KEY={HUB_MM_KEY}\nSAAS_TEAM_AUTH_SECRET={HUB_TEAM_SECRET}\n"
    )
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "ATTESTED_HUB_ENV": str(hub)}
    for name, value in {**INPUTS, **inputs}.items():
        if value is not None:
            env[name] = value
    return subprocess.run(
        ["bash", str(HELPER), str(env_file)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_foreign_keys_and_existing_gateway_secrets_survive(tmp_path: Path) -> None:
    kept = {name: f"{name.lower()}-" + "5" * 40 for name in MINTED}
    seed = [
        *TRIO_LINES[:6],
        *(f"{name}={value}" for name, value in kept.items()),
        "KOVA_API_KEY=kova-file-key",
        *TRIO_LINES[6:],
    ]
    env_file = tmp_path / ".env.attested-saas"
    # No trailing newline: the trio's last line must not be glued to ours.
    env_file.write_text("\n".join(seed))

    result = run(tmp_path, env_file)

    assert result.returncode == 0, result.stderr
    after = env_file.read_text().splitlines()
    foreign_before = [line for line in seed if key_of(line) not in GATEWAY_KEYS]
    foreign_after = [line for line in after if key_of(line) not in GATEWAY_KEYS]
    assert foreign_after == foreign_before
    values = parse(env_file.read_text())
    for name, value in kept.items():
        assert values[name] == value
    # The file's KOVA key outranks the caller's, as it did when the file was sourced.
    assert values["KOVA_API_KEY"] == "kova-file-key"
    assert "generated" not in result.stdout
    assert not (tmp_path / "pwned").exists()


def test_gateway_keys_come_from_inputs_and_the_hub(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.attested-saas"
    kova_key = r"kova\n\\literal"  # awk -v would have expanded these

    result = run(tmp_path, env_file, KOVA_API_KEY=kova_key)

    assert result.returncode == 0, result.stderr
    text = env_file.read_text()
    assert [key_of(line) for line in text.splitlines()] == GATEWAY_KEYS
    values = parse(text)
    assert values["KOVA_API_KEY"] == kova_key
    assert values["KOVA_URL"] == INPUTS["KOVA_URL"]
    assert values["SAAS_PAYMENT_RECIPIENT"] == INPUTS["PAYMENT_RECIPIENT"]
    assert values["SAAS_PUBLIC_ORIGIN"] == INPUTS["PUBLIC_SAAS_URL"]
    assert values["ATTESTED_HUB_NETWORK"] == INPUTS["HUB_NETWORK"]
    assert values["MEMORY_MARKET_API_KEY"] == HUB_MM_KEY
    assert values["SAAS_TEAM_AUTH_SECRET"] == HUB_TEAM_SECRET
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env.attested-saas", "hub.env"]


def test_placeholders_are_minted_and_no_value_is_printed(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.attested-saas"
    env_file.write_text(
        "SAAS_GATEWAY_API_KEY=replace-with-openssl-rand-hex-32\n"
        "SAAS_EDGE_TOKEN=change-me\n"
        "SAAS_POSTGRES_PASSWORD=dev-secret\n"
        + "\n".join(TRIO_LINES)
        + "\n"
    )

    result = run(tmp_path, env_file)

    assert result.returncode == 0, result.stderr
    values = parse(env_file.read_text())
    minted = [values[name] for name in MINTED]
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in minted)
    assert len(set(minted)) == len(minted)
    for name in MINTED:
        assert f"generated {name}" in result.stdout
    output = result.stdout + result.stderr
    for secret in [*minted, HUB_MM_KEY, HUB_TEAM_SECRET, INPUTS["KOVA_API_KEY"]]:
        assert secret not in output
    for line in TRIO_LINES:
        assert line in env_file.read_text().splitlines()


def test_repeated_key_keeps_the_last_value_once(tmp_path: Path) -> None:
    # deploy_attested_saas.sh appends a fresh line rather than replacing a weak one.
    env_file = tmp_path / ".env.attested-saas"
    env_file.write_text(
        "SAAS_POSTGRES_PASSWORD=dev-secret\n"
        "DEAL_ADMIN_TOKEN=deal-admin\n"
        "SAAS_POSTGRES_PASSWORD=" + "4" * 48 + "\n"
    )

    result = run(tmp_path, env_file)

    assert result.returncode == 0, result.stderr
    lines = env_file.read_text().splitlines()
    assert [line for line in lines if line.startswith("SAAS_POSTGRES_PASSWORD=")] == [
        "SAAS_POSTGRES_PASSWORD=" + "4" * 48
    ]
    assert "DEAL_ADMIN_TOKEN=deal-admin" in lines


def test_rerun_changes_nothing(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.attested-saas"
    env_file.write_text("\n".join(TRIO_LINES) + "\n")
    assert run(tmp_path, env_file).returncode == 0
    first = env_file.read_bytes()

    result = run(tmp_path, env_file)

    assert result.returncode == 0, result.stderr
    assert env_file.read_bytes() == first
    assert "generated" not in result.stdout


@pytest.mark.parametrize(
    ("hub_env", "inputs", "named"),
    [
        (None, {"PAYMENT_RECIPIENT": None}, "PAYMENT_RECIPIENT"),
        (None, {"KOVA_API_KEY": ""}, "KOVA_API_KEY"),
        (f"SAAS_TEAM_AUTH_SECRET={HUB_TEAM_SECRET}\n", {}, "MEMORY_MARKET_API_KEY"),
        (f"MEMORY_MARKET_API_KEY={HUB_MM_KEY}\n", {}, "SAAS_TEAM_AUTH_SECRET"),
    ],
)
def test_missing_input_leaves_the_file_untouched(
    tmp_path: Path, hub_env: str | None, inputs: dict[str, str | None], named: str
) -> None:
    env_file = tmp_path / ".env.attested-saas"
    env_file.write_text("\n".join(TRIO_LINES) + "\n")
    before = env_file.read_bytes()

    result = run(tmp_path, env_file, hub_env=hub_env, **inputs)

    assert result.returncode != 0
    assert named in result.stderr
    assert HUB_MM_KEY not in result.stderr and HUB_TEAM_SECRET not in result.stderr
    assert env_file.read_bytes() == before
