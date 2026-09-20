# Agent Council

Agent Council is a reusable governance skill for AI-assisted engineering work. It helps Codex and Claude Code decide when a task needs a stronger model, an independent review, or a simple worker check.

Use it when a task is risky, unclear, repeated, or changes a shared design. Leave routine work alone.

## What it does

The Council puts a small decision process around complex work:

1. Classify the work as a bounded repair, an uncertain problem, or a high-impact change.
2. Assign the right model tier for planning, implementation, review, and mechanical checks.
3. Keep a local record of the decision, the evidence, and the final outcome.
4. Prevent a case from being marked complete when required evidence or independent review is missing.

The plugin is model-provider neutral. It uses four roles, not fixed model names:

- ultimate intelligence: hard diagnosis, architecture, final decision
- operational intelligence: integration and independent review
- technical tactical intelligence: bounded implementation and verification
- worker intelligence: routine checks and evidence collection

Your Codex or Claude Code agent performs the actual delegation through its native tools. Agent Council does not contact model providers or spend money by itself.

## Install

These commands use the GitHub repository. You need access to it if it is private. Start a new Codex or Claude Code task after installing so the skill is available in the new task.

### Codex

```sh
codex plugin marketplace add mustafaqasim/agent-council --ref main
codex plugin add agent-council@agent-council
```

### Claude Code

```sh
claude plugin marketplace add mustafaqasim/agent-council
claude plugin install agent-council@agent-council
```

### Install from a local checkout

Use this only when testing or contributing to the plugin:

```sh
codex plugin marketplace add /path/to/agent-council
codex plugin add agent-council@agent-council
```

For Claude Code, add the same local repository path as a marketplace, then install `agent-council@agent-council`.

## Update

### Codex

Refresh the marketplace, then install the plugin again. Restart or begin a new task after the update.

```sh
codex plugin marketplace upgrade agent-council
codex plugin add agent-council@agent-council
```

### Claude Code

```sh
claude plugin update agent-council@agent-council
```

Claude Code reports when a restart is required. Do it before expecting the new skill files to apply.

## Use it

State the work normally, then ask for Council governance. For example:

```text
Use Agent Council to diagnose why this deployment fails after restart.
```

```text
Use Agent Council to plan and implement this shared authentication change.
```

```text
Use Agent Council to review this release candidate before it is shipped.
```

For simple tasks, do not invoke the Council. A request such as "rename this variable" or "show the current status" should stay direct.

When the Council is active, the host agent should briefly state which model tier it is assigning and why. It should then report the evidence and result, not private reasoning.

## Safety and limits

- Council cases are kept inside the project path you specify. The local engine refuses writes outside that boundary and refuses symlinked case paths.
- It rejects common secret-shaped values before writing case records. This is a guardrail, not a guarantee. Never put passwords, tokens, or private keys in commands or evidence.
- It records structural evidence locally. It cannot prove a provider ran a particular model beyond the host agent's observed tool results.
- Compound Engineering is optional. If installed, it can provide the delivery workflow while Agent Council controls routing and evidence gates.

## For contributors

Run the checks from the repository root:

```sh
python3 plugins/agent-council/scripts/Test-AgentCouncilPlugin.py
for group in schema lifecycle stages routes provider authoring security dispatch-contracts; do
  python3 plugins/agent-council/scripts/core/agent-council/0.2.0/Test-AgentCouncilContracts.py --group "$group"
done
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules, [SECURITY.md](SECURITY.md) for reporting security issues, and [MIGRATION.md](MIGRATION.md) for compatibility notes.
