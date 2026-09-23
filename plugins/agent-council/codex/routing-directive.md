# Agent Council activation on Codex

On trusted local Codex and Claude Code installations, this plugin can activate
through packaged hooks (`hooks/hooks.json`). Codex skips plugin hooks until the
user reviews and trusts the current hook definition. Cloud and web sessions
cannot execute local hook scripts, so use the universal fallback below. Both
paths point back to the `agent-council` skill, which stays the single source of
truth for routing rules and evidence requirements.

## Universal fallback (recommended): AGENTS.md directive

Add this to your project `AGENTS.md` (or global `~/.codex/AGENTS.md`). It is
persistent context Codex loads on every task, so it works everywhere including
cloud sessions:

```
Agent Council routing: before substantive work, including engineering, research,
analysis, planning, strategy, business, or document tasks, INCLUDING when a
domain skill (lab-building, brainstorming, planning, code review) will do the
actual work, first run the Agent Council applicability check and state a
one-line "Council check:" outcome: direct execution, lightweight cost-aware
tier routing, or a governed case. Agent Council composes above other skills; it
is not an alternative you pick instead of them. Skip only for trivial or
conversational requests. Full rules are in the agent-council skill.
```

## Packaged hooks on local Codex

Agent Council ships `SessionStart` and `UserPromptSubmit` hooks. Once the user
trusts them, Codex loads them with the plugin. `SessionStart` injects the routing
directive and performs the bounded daily update check. `UserPromptSubmit`
reinforces routing and handles the exact update preference commands documented
in the README.

The update installer is Codex-only. It requires explicit one-time instruction
or a successfully stored `auto-update on` preference, updates only the fixed
`agent-council@agent-council` selector, and takes effect in a new task. Hook
failures never block routing.
