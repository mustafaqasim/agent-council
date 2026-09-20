# Security Policy

## Scope

Agent Council is a local structural governance tool. It does not contact model providers, deploy infrastructure, or authenticate users.

## Boundaries

- Mutable commands require a declared project boundary and reject case paths outside it.
- A stable per-case lock serializes local writers.
- Symlinked paths inside a mutable case are refused before a command writes.
- Secret-shaped keys and common token patterns are rejected recursively before a record is persisted.

These controls reduce accidental exposure and local corruption. They are not a complete sandbox, malware defense, secret scanner, or provider-attestation mechanism.

## Reporting a vulnerability

Until a public security contact is published, do not create a public issue containing a vulnerability or a secret. Contact the repository owner privately through GitHub and include a minimal reproduction with secrets removed.

## Supported environment

The current candidate has local structural checks on macOS with Python 3 and Codex. Native provider execution and Windows filesystem-lock behaviour are not yet qualified for a public support claim.
