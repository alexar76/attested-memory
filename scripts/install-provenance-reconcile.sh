#!/bin/sh
# Install the supplied reconcile units on the standard Attested Memory Compose host.
set -eu

scripts=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
units=$scripts/systemd
hub=/opt/aicom/attested/attested-memory-hub
state=/var/lib/attested-provenance-reconcile
helper=/usr/local/libexec/attested-provenance-checkpoint.py
case "${1-}" in
    ''|--initialize) ;;
    *) echo "Usage: $0 [--initialize]" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [--initialize]" >&2
    exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root on the Attested Memory host." >&2
    exit 1
fi
if [ ! -f "$hub/docker-compose.yml" ]; then
    echo "The supplied service expects the Compose project at $hub." >&2
    exit 1
fi
command -v systemctl >/dev/null
command -v /usr/bin/python3 >/dev/null
if [ ! -f "$state/heads.json" ] && [ "${1-}" != --initialize ]; then
    echo "Restore the retained heads, or use --initialize to establish the first baseline." >&2
    exit 1
fi
install -d -m 0700 "$state"
install -d -m 0755 /usr/local/libexec
install -m 0644 "$scripts/provenance-checkpoint.py" "$helper"
if [ "${1-}" = --initialize ]; then
    (cd "$hub" && /usr/bin/python3 "$helper" "$state" --initialize)
fi
install -m 0644 "$units/attested-provenance-reconcile.service" /etc/systemd/system/
install -m 0644 "$units/attested-provenance-reconcile.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now attested-provenance-reconcile.timer
