# Agent Council

Use different AI models from one chat, without switching them by hand.

![Agent Council routes each coding subtask to an appropriate model based on complexity, risk, and cost](assets/agent-council.png)

Agent Council lets your main Codex or Claude Code chat hand a subtask to the model tier that fits the work:

- A fast, economical model for routine checks and evidence gathering.
- A technical model for a bounded implementation.
- A stronger model for difficult diagnosis, review, or architecture.
- A top-tier model for routing and final decisions.

In Codex, that can mean Luna for routine work, Terra for implementation, Sol for review, and Astra for the hardest decisions.

You stay in the same chat. The main agent decides when to work directly, when to delegate, which model tier fits each subtask, and when stronger governance is necessary.

This applies beyond coding. Research, analysis, strategy, business planning, document work, implementation, and review can all contain subtasks with very different levels of difficulty.

## Why this exists

Manually changing models creates two kinds of waste:

- Keep a premium model running and you spend expensive tokens on easy work.
- Keep a cheaper model on a hard problem and you can burn through retries before escalating anyway.

Then, once the hard part is over, you have to remember to switch back down. The repeated handoff breaks your flow and makes one task feel like several separate sessions.

Agent Council moves that routing decision into the chat. It can escalate when the work becomes harder, use a cheaper worker for routine steps, and downshift again when the difficult part is complete. When the work carries material risk, it can also require a separate reviewer and evidence before completion.

It does not read your remaining quota or predict cost. It routes from the task's complexity and risk.

## What happens during a task

Agent Council first chooses one of three paths:

- **Direct execution**: the request is too small or tightly coupled for delegation to save time or tokens.
- **Lightweight routing**: bounded research, drafting, implementation, analysis, or review is delegated to the lowest qualified model tier. No case files or governance ceremony are created.
- **Governed case**: a qualifying risk needs formal routing, independent review, and evidence gates.

You see the routing decision and each delegated model before work begins. A substantive consulting-offer task, for example, can send source inventory to a worker model, structured offer design to a technical model, and final integration or challenge review to a stronger model.

For governed work, the main chat classifies the current piece of work:

- **R1**: a bounded fix with a known cause and narrow impact.
- **R2**: an unexpected failure or uncertain composition.
- **R3**: architecture, shared contracts, safety boundaries, or repeated unresolved failures.

That route tells the chat which model tier and checks are required. Agent Council records the routing decision, checks returned model identity and evidence links, and refuses to close the case when required checks are missing or stale.

The local engine uses only the Python standard library.

## Install

**Codex:**

```sh
codex plugin marketplace add mustafaqasim/agent-council --ref main
codex plugin add agent-council@agent-council
```

**Claude Code:**

```sh
claude plugin marketplace add mustafaqasim/agent-council
claude plugin install agent-council@agent-council
```

Start a new task after installation so the skill loads.

To update from the public repository:

```sh
codex plugin marketplace upgrade agent-council
codex plugin add agent-council@agent-council
```

Do not install the repository root as a personal plugin. The public marketplace resolves the packaged plugin under `plugins/agent-council`.

## Update checks

On a trusted local Codex installation, Agent Council checks its public GitHub marketplace for a newer version at most once every 24 hours. The default is notification only. A newer version produces a clear prompt with the installed and available versions.

Use these exact messages in a Codex task:

```text
agent-council update now
agent-council auto-update on
agent-council auto-update off
```

`update now` installs the available version once. `auto-update on` explicitly opts in to installing future updates during the daily check. Automatic updates are off unless that setting is stored successfully. Settings and check state live in Codex's writable plugin data directory, not in the installed plugin cache.

An installed update applies to the next task. The active task continues using the version it loaded at startup. Update failures do not block Agent Council routing. Claude Code users continue to update through the Claude plugin manager; the automatic installer is Codex-only.

## Activation

Agent Council is a layer that sits above your other skills, not an alternative you pick instead of them. A domain skill (lab-building, planning, brainstorming, code review) still does the work; Agent Council decides which model tier should make the hard calls and whether governance is required.

- **Claude Code:** activation is automatic after its packaged hooks are trusted. The routing check runs before the agent selects a skill, so a strong domain skill no longer bypasses it.
- **Local Codex:** enabled plugins can load packaged lifecycle hooks after the user reviews and trusts them. Agent Council uses those hooks for activation and daily update checks. Restart or start a new task after installation so the hooks load.
- **Codex fallback:** add the routing directive to your `AGENTS.md` for persistent coverage, including environments where hook scripts are unavailable. See [codex/routing-directive.md](plugins/agent-council/codex/routing-directive.md).
- **Cloud and web sessions:** hooks do not run there. Use the `AGENTS.md` directive, which is persistent context loaded on every task.

You can always invoke it explicitly with `/agent-council` (Claude Code) to guarantee the check.

## What it does not do

- The local engine does not call model providers. The main chat delegates through the native Codex or Claude Code tools.
- Packaged hooks require a trusted local execution environment. Cloud and web sessions rely on the `AGENTS.md` directive and remain best-effort.
- It does not guarantee that a provider actually ran the model it claims. It verifies identity based on observed tool results, not provider assertions.
- It does not dynamically benchmark models or guarantee every model in the registry is available on your account.
- Compound Engineering is optional. The plugin works without it.

## Safety boundary

Case records require `--project-root` and `--case-root` to point to a directory you control. The engine resolves all paths inside that boundary and refuses mutations through a different root or a symlinked path.

This protects against accidental writes by the current user. It is not a sandbox against a malicious process running as the same user.

The engine rejects common secret-shaped values before writing a record. That is pattern-matching, not a guarantee. Do not pass secrets as command-line arguments or in evidence fields.

## Development

Run the plugin check and contract groups from the plugin directory:

```sh
cd plugins/agent-council
python3 scripts/Test-AgentCouncilPlugin.py
python3 scripts/Test-AgentCouncilUpdates.py
for group in schema lifecycle stages routes provider authoring security dispatch-contracts; do
  python3 scripts/core/agent-council/0.2.0/Test-AgentCouncilContracts.py --group "$group"
done
```

See [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [MIGRATION.md](MIGRATION.md).
