# Agent Council activation on Codex

On Claude Code this plugin activates automatically through packaged hooks
(`hooks/hooks.json`). Codex has no equivalent plugin-auto-hook that a cloud or
web install can rely on, so use the universal fallback below. Both paths point
back to the `agent-council` skill, which stays the single source of truth for
the routing rules and evidence requirements.

## Universal fallback (recommended): AGENTS.md directive

Add this to your project `AGENTS.md` (or global `~/.codex/AGENTS.md`). It is
persistent context Codex loads on every task, so it works everywhere including
cloud sessions:

```
Agent Council routing: before substantive work — engineering, research,
analysis, planning, strategy, business, or document tasks, INCLUDING when a
domain skill (lab-building, brainstorming, planning, code review) will do the
actual work — first run the Agent Council applicability check and state a
one-line "Council check:" outcome: direct execution, lightweight cost-aware
tier routing, or a governed case. Agent Council composes above other skills; it
is not an alternative you pick instead of them. Skip only for trivial or
conversational requests. Full rules are in the agent-council skill.
```

## Optional (local, trusted installs): Codex SessionStart hook

For a local Codex install you can add a `SessionStart` hook that injects the
same directive. Add to `~/.codex/hooks.json` (or the `[[hooks.SessionStart]]`
form in `config.toml`), pointing at the installed script:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": ".*",
        "hooks": [
          { "type": "command", "command": "bash '<PLUGIN_PATH>/hooks/agent-council-routing.sh' SessionStart" }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": ".*",
        "hooks": [
          { "type": "command", "command": "bash '<PLUGIN_PATH>/hooks/agent-council-routing.sh' UserPromptSubmit" }
        ]
      }
    ]
  }
}
```

Replace `<PLUGIN_PATH>` with the installed plugin directory. Hook scripts run
only in a local, trusted environment; a cloud or web session cannot execute
them, so the AGENTS.md directive is the reliable path there.
