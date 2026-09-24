# Security Policy

## Scope

Agent Council is a local structural governance tool. It does not contact model providers, deploy infrastructure, or authenticate users. On trusted local Codex installations, its optional update checker contacts only the fixed public Agent Council marketplace URL on GitHub.

## Boundaries

- Mutable commands require a declared project boundary and reject case paths outside it.
- A stable per-case lock serializes local writers.
- Symlinked paths inside a mutable case are refused before a command writes.
- Secret-shaped keys and common token patterns are rejected recursively before a record is persisted.
- Automatic installation is unavailable. Hook prompts and legacy preferences cannot authorize installation.
- The updater checks only the fixed public marketplace and gives the user a fixed host-managed CLI command. It does not invoke the installer or rewrite plugin cache files.
- Automatic update checks can be disabled locally. Status is read-only, and cleanup is confined to known updater-owned settings and state files.
- A downloaded update is used only by a later task. The active task keeps its loaded plugin version.

The daily check reveals the user's public IP address and request metadata to GitHub in the same way as other HTTPS requests to GitHub. No project content, prompts, case records, or credentials are included in the request.

These controls reduce accidental exposure and local corruption. They are not a complete sandbox, malware defense, secret scanner, provider-attestation mechanism, or guarantee that GitHub is reachable.

## Reporting a vulnerability

Until a public security contact is published, do not create a public issue containing a vulnerability or a secret. Contact the repository owner privately through GitHub and include a minimal reproduction with secrets removed.

## Supported environment

Version 0.8.0 has local structural checks on macOS with Python 3 and Codex. Native provider execution and Windows filesystem-lock behaviour are not yet qualified for a public support claim.
