# Production PostgreSQL profile

Production starts PostgreSQL 16 and refuses to boot a Hub/service when a required
store has no PostgreSQL DSN. The stores use separate environment variables and
independent `psycopg` pools; they may point at one PostgreSQL database or separate
databases.

SQLite remains available only when `AIFACTORY_PROD` is unset, for development and
tests. Existing files can be copied with `scripts/migrate_sqlite_to_postgres.py`.
Back up with `scripts/backup_postgres.sh`; restore into a disposable database by setting
`VERIFY_DATABASE_URL` and run `scripts/restore_verify_postgres.sh` before replacing the
primary. Run the backup once for every distinct service DSN if the stores are split across
databases. The restore verifier compares the resolved PostgreSQL server and database—not
only the DSN text—and refuses to clean the production database through an alias.

The bundled Hub is pinned to an upstream commit and its production PostgreSQL changes are
stored in `patches/aimarket-hub-production.patch`. `bootstrap-upstreams.sh` applies that
patch only to a clean checkout, and `scripts/check.sh` fails if the checked-out runtime does
not contain it. This makes clean-clone and GitHub satellite builds reproduce the audited
runtime instead of depending on ignored local files.

Production startup also rejects SQLite DSNs, weak operator/internal/publisher secrets,
disabled response or PQ signatures, relaxed supply security, simulated ZK/TEE modes and
payment verification stubs. Local provider publishing is allowed only with an explicit
service-host allowlist.

The three bundled providers are listed in `AIMARKET_SUPPLY_OPERATOR_PUBLISHERS` and
authenticate with separate publisher credentials. This explicit first-party trust policy
bypasses only the external collateral requirement for those exact IDs; every unlisted
community publisher still needs verified stake.

Memory Market requests that name an actor must send the API bearer token plus a
cryptographic actor identity: `X-Actor-ID` must be
`did:actor:<sha256(raw-ed25519-public-key)>`, `X-Actor-Public-Key` is the base64url
raw Ed25519 public key, and `X-Actor-Signature` is a base64url Ed25519 signature over
the exact actor ID. A shared actor secret and arbitrary string actor IDs are rejected
in production. Generate a key with `scripts/generate_actor_identity.py`.

## Publisher credentials of the bundled products

Six services publish into this Hub, each with its own secret keyed by publisher id:
the three providers (`memory-market`, `truth-layer`, `provenance-ledger`) and the Attested
trio (`attested-deal`, `attested-meter`, `attested-prove`).

- **The Hub mints them.** `scripts/ensure_env.sh` writes `MEMORY_MARKET_PUBLISHER_TOKEN`,
  `TRUTH_LAYER_PUBLISHER_TOKEN`, `PROVENANCE_PUBLISHER_TOKEN` and
  `ATTESTED_{DEAL,METER,PROVE}_PUBLISHER_TOKEN` into this directory's `.env` whenever one is
  missing or weak. `docker-compose.yml` joins all six into the Hub's
  `AIMARKET_PUBLISHER_TOKENS` (`id:secret,…`) — that value, not the `.env`, is what the
  running Hub checks.
- **The providers cannot drift**: compose hands them the same `.env` values.
- **The trio could, and now keeps itself in step.** Deal, Meter and Prove are a separate
  compose project (`attested-saas`) with their own env file, `/opt/aicom/.env.attested-saas`.
  Three things keep it matching the Hub, none of them manual:
  - `attested-publisher-reconcile.timer` (installed by the trio deploy) runs
    `attested/deploy/reconcile_publishers.sh` every 10 minutes: it reads what the RUNNING
    Hub checks, rewrites a drifted key in the trio's env file (one line, nothing else) and
    recreates only that container, then confirms the Hub accepted it;
  - the Hub deploy (`scripts/deploy_attested_memory.sh`) runs the same reconcile right after
    it recreates the Hub, so a re-minted token reaches the trio in seconds, not minutes;
  - the trio deploy follows the running Hub too, and shares a lock with the reconcile.
  Each product also keeps publishing on its own: a refused or partial publish is retried
  after 1, 5, 15, 30 minutes and then hourly, and a complete one is refreshed every 6 hours
  (`AIMarket.keep_registered` in the shared `core.py`), so a Hub that was down at startup no
  longer leaves a listing frozen. Drilled on 2026-09-24: a deliberately broken Deal token was
  back in step, and Deal re-published, 15 seconds after the reconcile ran.
- **A new `.env` is new tokens.** Moving this directory, or starting from a copy without the
  trio's keys, makes `ensure_env.sh` mint fresh ones. The Hub starts with them and is fine;
  the trio keeps presenting the old ones until its next deploy.
- **What a drift looks like:** at trio startup `POST /ai-market/v2/supply/register` answers
  `403 token does not authenticate` — one log line per service. Health stays green and the
  Hub keeps serving the last listing it accepted, so nothing else notices. That is how Deal
  and Prove ran from 2026-09-11 (the directory moved on 2026-09-08) until 2026-09-24.
- **Rotating one:** change it in `.env` and recreate the Hub (`docker compose up -d hub` —
  a plain `docker restart` keeps the environment the container was created with). That is
  all: the reconcile carries it to the trio within 10 minutes (immediately when the Hub was
  recreated by its deploy script). Until the Hub is recreated, the reconcile reports "a hub
  recreate is pending" and keeps the trio on what the Hub is actually running.
- **Watching it:** `journalctl -u attested-publisher-reconcile` on the host; by hand,
  `ATTESTED_HOST=attested ./attested/deploy/reconcile_publishers.sh --dry-run`.
- **Checking:** `ATTESTED_HOST=attested ./attested/deploy/check_hub_publishers.sh` (credentials
  by hash prefix, refusals since start, last accepted publish); add `--probe` to ask the Hub
  directly without writing anything.
- **The pre-move directory** `/opt/aicom/attested-memory-hub` still holds retired tokens and
  an old payment address. Nothing reads it; never copy a value out of it.

