# Migration

## Version 0.9.0

The installable package now includes portable identity metadata, its own README and MIT license, and matching host manifests. The repository root remains a marketplace. Existing host hooks retain both SessionStart and UserPromptSubmit, Codex PLUGIN_ROOT precedence, Claude fallback, and quoted paths. Anthropic directory compatibility of the dual-host wrapper remains pending; Claude Code strict validation does not establish directory acceptance.

The skill keeps scope, reentry, risk precedence, exclusions, and route selection in the entry point. Lightweight and governed instructions load from separate references. New governed cases pin both references. Historical cases and native qualification receipts are not rewritten, and the legacy six-file candidate digest keeps its original meaning.

Current release evidence uses the versioned behavioral inventory, including activation, traces, manifests, policy, native evals, and validation helpers. The new v3 registry starts with every binding as a candidate. New cases cannot fall back to v2; historical pinned v2 cases remain readable. For each v3 Claude binding, prepare two fresh runs with `ClaudeQualificationHarness.py prepare --binding-id <exact-binding-id>`, score the native transcripts, and validate the pair. Each binding also needs an exact packaged Agent probe. Claude requires provider-attested model identity and matching native effort evidence.

Codex also supports an approved lower-assurance path: `CodexQualificationHarness.py score --host-selected` checks retained parent and child exports against the local native session store. Two passing fresh runs, a validated pair, and a third independent native probe can support promotion as `identity_assurance: host_selected`. Promotion replays dispatch linkage and scoring from the frozen artifacts. This establishes structural consistency of explicit host selection, not provider-resolved identity or host authenticity. Ordinary `client_configuration` receipts remain ineligible for promotion. The implementation alone qualifies no binding; all current candidates still need fresh native evidence.

Qualification of only the default effort does not authorize other efforts. Promotion can qualify one binding without waiting for the other provider, but its proof must cover every live qualified binding in that registry snapshot. An existing qualified binding cannot enter a new promotion archive without prior-proof lineage. Any change to inventoried bytes invalidates earlier candidate-bound evidence.

Tracing remains disabled by default. Native eval release runs require verified promotion and use a frozen package copy with publication disabled. Do not promote 0.9.0 from offline checks or historical receipts alone. Directory submissions, publication, installation, and fresh paid native runs are separate actions.

Existing governed cases retain their pinned registry, including after `cycle-start`. To adopt the installed registry, run `python3 plugins/agent-council/scripts/Migrate-AgentCouncilCase.py --source-case-root <old-case> --case-root <new-case> --project-root <project> --case-id <new-id>`. This creates a separate successor, preserves the historical case, and records its identity in `migration-provenance.json`. It retains the route and engineering input hashes but carries no approvals, dispatches, or evidence. Supply `--candidate-json` when the engineering inputs have also changed. Fresh capability observations and all applicable qualification and closure gates remain required.

## Version 0.8.2

Version 0.8.2 promotes Claude Opus 5.5 to the Claude Code operational tier after two clean, blind native qualification runs passed GFT01 through GFT12 on identical candidate bytes. Claude Opus 5 is revoked as the superseded operational binding.

Claude Code Agent aliases are no longer treated as proof of a versioned model ID. Ordinary delegation must observe the exact provider model identity. Native qualification uses fresh interactive sessions with an exact full model ID, safe mode, restricted workspace access, distinct session IDs, and no answer key in the evaluator workspace.

Existing governed cases retain their pinned registry. Start a new case to use a newly installed binding.

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
