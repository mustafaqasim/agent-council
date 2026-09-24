# Migration

## Version 0.7.1

The Claude Code operational tier now binds to Opus 5.5 (`claude-opus-5-5`) instead of Opus 5. Registry and binding hashes are recomputed. Governed cases opened on an earlier version keep their pinned registry. No other routing change.

## Version 0.7.0

Version 0.7.0 adds a bounded daily update check for trusted local Codex installations. Notification is the default. Automatic installation remains off until the user sends the exact `agent-council auto-update on` instruction and the preference is stored in the plugin data directory.

Updates are installed through the fixed public Agent Council marketplace and apply only to a new task. Claude Code keeps its existing manual plugin-manager update path. Existing routing and case records require no migration.

## Version 0.6.0

Version 0.6.0 adds automatic activation on Claude Code through packaged session and prompt hooks, so the routing check runs before the agent selects a domain skill. Agent Council now behaves as a layer above other skills rather than a peer option that a stronger domain skill could bypass.

At the time of the v0.6.0 release, Codex activation used the `AGENTS.md` routing directive. Version 0.7.0 adds packaged hooks for trusted local Codex installations. Cloud and web sessions still use the directive; see `plugins/agent-council/codex/routing-directive.md`. The `agent-council` skill remains the single source of truth for the routing rules in every case.

Restart or start a new session after updating so the hooks load.

## Version 0.5.0

Version 0.5.0 broadens automatic selection from engineering-only governance to cost-aware routing for substantive engineering, research, analysis, strategy, business, document, and review work.

Lightweight routing does not create a Council case. Existing R1, R2, and R3 cases retain their formal evidence and closure requirements.

Install or update Agent Council through the public GitHub marketplace commands in the README. Start a new task afterward so the updated skill catalog loads.

## Version 0.2.0

Version 0.2.0 establishes the public `agent-council.*` schema namespace and neutral runtime file names.

Cases created by incompatible legacy package versions are intentionally not mutable with this package. Their pinned files, event hashes, and receipts remain authoritative only under the package that created them. Create a new case instead of rewriting historical evidence.
