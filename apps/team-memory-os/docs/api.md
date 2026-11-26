# API guide

Team memory requests require `X-SaaS-Key`, actor proof headers and a `team_id`.
The Gateway checks membership, then issues a short-lived team assertion for
the Hub namespace.

## Team administration

- `POST /api/teams` with `{ "name": "Platform" }`;
- `POST /api/teams/{team_id}/members` with `actor_id` and `role`;
- `DELETE /api/teams/{team_id}/members/{actor_id}` to offboard a member.

## Memory

- `POST /api/team-memories` with `team_id`, `title`, `content`, `tags` and
  optional `source_refs`, `valid_from` and `valid_until`. The response carries
  `review_state: "pending"` until the Memory Market operator approves the submission;
- `GET /api/team-search?team_id=...&q=...`;
- `GET /api/team-memories/{memory_id}?team_id=...`.

Search and read accept timezone-aware RFC 3339 `valid_at` and `known_at`. Include
the parameters in the signed Market destination. Membership never replaces
cryptographic actor identity or operator approval.
