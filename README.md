# Agent Council

Keep one coding chat moving without manually playing model dispatcher.

Some parts of a task need a stronger model: an unfamiliar failure, an architecture choice, or a change to a shared contract. Other parts do not: gathering evidence, making a narrow edit, or checking a known result. Switching models by hand is easy to get wrong. You can keep a premium model on routine work, spend several attempts on a hard problem before escalating, then forget to scale back down once the difficult part is over.

Agent Council is an attempt to remove that friction. It gives the outer coding agent a way to classify a piece of work, choose an appropriate model tier, delegate a bounded subtask, and retain evidence for the result. The goal is not to replace your main chat. It is to let that chat use the right help at the right time.

The local engine uses only the Python standard library.

## When it helps

Use Agent Council when a task changes shape as you work through it: a simple repair turns into an uncertain diagnosis, a retry reveals a deeper design problem, or an implementation needs an independent check before it can be accepted.

It is not a quota meter or a cost forecaster. It does not inspect your account usage. It helps the agent make and record better routing decisions, so you do not have to manage every model handoff yourself.

## How routing works

The outer agent assigns a route to work that needs Council governance:

- **R1**: a bounded fix with a known cause and narrow impact.
- **R2**: an unexpected failure or uncertain composition.
- **R3**: architecture, shared contracts, safety boundaries, or repeated unresolved failures.

The plugin does not run models itself. It gives the outer agent a model-routing and evidence protocol. The local engine records the plan, checks local record consistency, validates evidence links, and blocks closure when required gates are missing or stale.

## Install

**Codex:**

```sh
codex plugin marketplace add mustafaqasim/agent-council --ref main
codex plugin add agent-council@agent-council
```

**Claude Code:**

```sh
claude plugin marketplace add mustafaqasim/agent-council --ref main
claude plugin add agent-council@agent-council
```

Start a new task after installation so the skill loads.

## What it does not do

- It does not launch or call models.
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
for group in schema lifecycle stages routes provider authoring security dispatch-contracts; do
  python3 scripts/core/agent-council/0.2.0/Test-AgentCouncilContracts.py --group "$group"
done
```

See [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [MIGRATION.md](MIGRATION.md).
