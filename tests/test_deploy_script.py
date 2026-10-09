import re
from pathlib import Path


def _deploy_script() -> str:
    return (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "deploy_attested_memory.sh"
    ).read_text()


def test_deploy_reloads_persisted_wallet_before_compose() -> None:
    script = _deploy_script()

    reload_line = (
        'PAYMENT_RECIPIENT="$(sed -n '
        "'s/^PAYMENT_RECIPIENT=//p' .env | head -n 1)\""
    )
    reload_at = script.index(reload_line)

    assert script.index("path.chmod(0o600)") < reload_at
    assert reload_at < script.index("./bootstrap-upstreams.sh")
    assert "export PAYMENT_RECIPIENT" in script[reload_at:]
    assert "persisted PAYMENT_RECIPIENT must be" in script[reload_at:]


def test_deploy_updates_shared_saas_env_in_place() -> None:
    # The Deal/Meter/Prove project keeps its tokens and key-derivation secrets in
    # the same file; truncating it orphans every key the trio ever issued.
    # tests/test_update_saas_env.py covers what the helper does to the file.
    script = _deploy_script()

    assert not re.search(r'>\s*"?\$\{?SAAS_ENV', script)
    assert not re.search(r'(source|\.)\s+"?\$\{?SAAS_ENV', script)
    update_at = script.index('update_saas_env.sh "$SAAS_ENV"')
    unset_at = script.index("unset KOVA_URL KOVA_API_KEY")
    compose_at = script.index('docker compose --env-file "$SAAS_ENV"')
    assert update_at < unset_at < compose_at
