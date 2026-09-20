# Agent Council

Agent Council is a Codex plugin for governing complex engineering work. It maps work to model tiers, records the planned delegation, requires independent review where the route demands it, and keeps local evidence linked to the exact candidate under review.

It is independent of any lab, customer environment, network, or other plugin. The local runtime uses only the Python standard library.

## What it does

- Classifies bounded repairs, uncertain compositions, and shared-contract changes as routes R1 through R3.
- Records model-tier plans and visible delegation notices.
- Requires evidence, independent review, and final disposition according to the selected route.
- Refuses unsafe or incomplete local case transitions rather than silently downgrading assurance.

## What it does not do

- It does not launch models, verify a provider's execution, or grant production or acceptance authority.
- It does not dynamically benchmark available models or promise that every account can use every model in its registry.
- Project profiles are interpreted by the outer agent. The runtime only pins the packaged default profile for traceability.
- Compound Engineering is optional. Native Codex operation remains available when it is absent.

## Install from GitHub

After this repository is published, add its marketplace and install the plugin:

```sh
codex plugin marketplace add mustafaqasim/agent-council --ref main
codex plugin add agent-council@agent-council
```

Start a new Codex task after installation so the new skill is loaded.

## Local safety model

Mutable commands require both `--project-root` and `--case-root`. The runtime resolves the case inside the declared project boundary, pins that boundary in case state, and refuses later mutations through a different root or a symlinked case path.

This is an accidental-write guard for the current user, not a sandbox against a malicious same-user process. Store cases in a project directory you control. The runtime rejects common secret-shaped keys and values before it writes a record, but that is known-pattern rejection, not a guarantee that evidence contains no secrets. Do not pass secrets as command-line arguments or evidence.

## Development

Run the focused plugin check and the contract groups from the plugin directory:

```sh
cd plugins/agent-council
python3 scripts/Test-AgentCouncilPlugin.py
for group in schema lifecycle stages routes provider authoring security dispatch-contracts; do
  python3 scripts/core/agent-council/0.2.0/Test-AgentCouncilContracts.py --group "$group"
done
```

See [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [MIGRATION.md](MIGRATION.md).
