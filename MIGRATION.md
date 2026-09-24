# Migration

## Version 0.8.2

Version 0.8.2 promotes Claude Opus 5.5 to the Claude Code operational tier after two clean, blind native qualification runs passed GFT01 through GFT12 on identical candidate bytes. Claude Opus 5 is revoked as the superseded operational binding.

Claude Code Agent aliases are no longer treated as proof of a versioned model ID. Ordinary delegation must observe the exact provider model identity. Native qualification uses fresh interactive sessions with an exact full model ID, safe mode, restricted workspace access, distinct session IDs, and no answer key in the evaluator workspace.

Existing governed cases retain their pinned registry. Open a new cycle before using the new binding.

## Version 0.8.1

Version 0.8.1 corrects the premature v0.7.1 substitution of Opus 5.5 for the qualified Claude Code operational binding. `claude-opus-5` remains the qualified operational route. Opus 5.5 (`claude-opus-5-5`) is catalogued separately as a candidate and cannot satisfy a qualified dispatch gate until two fresh native qualification runs record the observed Claude Code identity on identical candidate bytes.

The v0.7.1 entry remains historical. Governed cases retain their pinned registry state, including the registry that was active when each case opened.

## Version 0.8.0

Version 0.8.0 makes interrupted Council case writes recoverable, fixes plugin-root portability, adds a read-only activation diagnostic, clarifies risk-first routing, and adds a local paired benchmark harness.

Automatic installation has been removed. Daily checks remain notification-only. `agent-council update now` performs a fresh check and returns the two host-managed commands that refresh the marketplace and install the current plugin release. Existing `auto_update: true` preferences no longer authorize installation. Use `agent-council update-check off` to stop automatic network checks, `agent-council update status` to inspect local state, and `agent-council update cleanup` to remove updater-owned settings and check state. Cleanup preserves plugin files and Council cases.

Cases without a pending transaction journal remain readable. A v0.8.0 runtime recovers its own valid pending transaction before a mutation or through `recover-case`. It refuses malformed, conflicting, or path-escaping journals without rewriting evidence. Do not use an older runtime against a case that contains a v0.8.0 pending transaction. Older interrupted cases with unexplained orphan evidence require diagnosis; the runtime does not guess their intended state.

Routing remains risk-first. A small, known-cause automation repair remains R1 when the `bounded_automation_repair` activation class applies. Ordinary local repairs with no qualifying activation class may still run directly or through lightweight routing.

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
