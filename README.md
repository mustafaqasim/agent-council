# Agent Council

Agent Council is a plugin that decides which AI model should do each piece of work in a task, checks that the work was actually done by the model it claimed to use, and refuses to mark a case complete if the evidence doesn't hold up.

You install it once. After that, when you open a task your agent will classify the risk, pick the right model tier, delegate the work, and verify the result before closing.

The local engine runs on Python standard library only. No extra dependencies.

## The problem it solves

Coding agents make decisions about which model to use and whether work is done, but they don't record those decisions or verify them. You end up with no audit trail, and no check that a cheaper model didn't quietly substitute for the one you expected.

Agent Council adds a governance layer on top: it classifies tasks by risk level, assigns each to a model tier matched to that risk, requires independent review where the risk warrants it, and keeps a local record of what was done and by whom.

## How it works

Every task gets a route:

- **R1**: a bounded fix with a known cause and narrow impact. One model tier, basic evidence.
- **R2**: uncertain composition or an unexpected failure. Requires a design decision and a higher model tier.
- **R3**: architecture, shared contracts, safety boundaries, or repeated failures. Requires ultimate-tier models and independent review.

The plugin does not run models itself. It records the plan, checks that the delegated model matches the registry, validates the evidence, and blocks closure when gates are missing or stale.

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
