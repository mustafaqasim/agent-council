# Agent Council

Use the right AI model for each part of a task, without leaving your chat.

Agent Council helps Codex and Claude Code decide when to:

- Do the work in the main chat.
- Send routine work to a cheaper model.
- Send harder work to a stronger model.
- Add an independent review when the work is risky.

![Agent Council routes each coding subtask to an appropriate model based on complexity, risk, and cost](assets/agent-council.png)

## Why use it

Using one model for everything creates waste.

A premium model can spend expensive tokens on simple checks. A cheaper model can get stuck on a hard problem and burn tokens on retries. Switching models by hand fixes this, but it breaks your flow.

Agent Council handles that choice inside the chat. You keep one conversation. The main agent keeps control of the task and brings in another model only when it is useful.

It works for coding, research, analysis, strategy, business planning, documents, and reviews.

## How it works

For each request, Agent Council picks one path:

- **Work directly:** The task is small or delegation would add more overhead than value.
- **Delegate a subtask:** A suitable model handles a clear piece of work. The main chat keeps the context and final answer.
- **Add safeguards:** Risky work gets stronger routing, separate review, and evidence checks.

You see which model is assigned and why before delegated work starts.

Agent Council does not read your remaining quota or predict the exact cost. It routes from the work it can see: difficulty, risk, and likely delegation overhead.

## Model routing examples

In Codex, routine work can go to Luna, implementation to Terra, review to Sol, and the hardest decisions to Astra.

In Claude Code, routine work can go to Haiku 4.5, implementation to Sonnet 5, difficult review to Opus 5.5, and the hardest decisions to Fable 5.1. Opus 5.5 replaces Opus 5 as the qualified operational model.

The available models still depend on your account and host.

## Example

A search for Microsoft Surface deals started in a **Sol High** chat. Agent Council sent price research and device-fit checks to **Terra Medium** workers. Sol stayed focused on the final recommendation.

<img width="574" height="1280" alt="Agent Council delegates Surface deal research from Sol High to Terra Medium workers" src="https://github.com/user-attachments/assets/f09275ea-31a5-4be1-b1ef-ad0081e06f6b" />

When delegation would not help, Agent Council keeps the work in the main chat.

<img width="1092" height="366" alt="Agent Council chooses direct execution for a small task" src="https://github.com/user-attachments/assets/36512129-e21a-482d-aa2a-73b4a1ba0352" />

## Safeguards for risky work

Most requests do not need a formal Council case. Higher-risk work does.

- **R1:** A narrow automation repair with a known cause.
- **R2:** An unexpected failure, uncertain design, or material design decision.
- **R3:** An architecture implementation, shared contract, safety boundary, lifecycle or acceptance change, repeated unresolved failure, or model qualification problem.

Read-only architecture review and routine checks do not become R3 just because they mention architecture or risk.

For a governed case, Agent Council records the route, model identity, and evidence. It will not mark the case complete when a required test or independent review is missing.

## Install

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

Start a new task after installation so the plugin can load.

Do not install the repository root as a personal plugin. The marketplace installs the package under `plugins/agent-council`.

## Update

### Codex

```sh
codex plugin marketplace upgrade agent-council
codex plugin add agent-council@agent-council
```

### Claude Code

```sh
claude plugin marketplace update agent-council
claude plugin update agent-council@agent-council
```

Agent Council can check the public Codex marketplace once a day. It only shows an update prompt. It never installs an update by itself.

Use these messages in a Codex task:

```text
agent-council update now
agent-council update-check on
agent-council update-check off
agent-council update status
agent-council update cleanup
```

`update now` checks the marketplace version on `main` and gives you the two Codex commands to run. GitHub Releases are not used for this check.

`update-check off` stops automatic marketplace requests. Manual checks still work. `update cleanup` removes only updater settings and check state. It does not remove the plugin or Council cases.

An update takes effect in a new task. Claude Code users update through the Claude plugin manager.

## Activation

Agent Council works alongside your other skills. Those skills still do their normal jobs. Agent Council decides whether another model should handle part of the work and whether extra review is needed.

- **Claude Code:** Packaged hooks run the routing check after you trust them.
- **Local Codex:** Enabled plugins can load packaged hooks after you review and trust them. Start a new task after installation.
- **Codex fallback:** Add the [routing directive](plugins/agent-council/codex/routing-directive.md) to `AGENTS.md` when hooks are unavailable.
- **Cloud and web sessions:** Hooks do not run there. Use the `AGENTS.md` directive.

In Claude Code, `/agent-council` always requests a routing check.

For a local, read-only activation report:

```sh
python3 plugins/agent-council/scripts/Diagnose-AgentCouncil.py
```

The report checks the package, runtime, hooks, fallback directive, and updater support. It cannot prove that a host trusted a hook or that an agent followed the routing policy unless the host provides that evidence.

## Limits

- The local engine does not call model providers. The main chat uses the native Codex or Claude Code tools.
- Agent Council checks model identity reported by the host or provider. It cannot independently prove which infrastructure ran the model.
- It does not guarantee that every model in the registry is available on your account.
- It does not run live model benchmarks or promise a specific saving.
- Compound Engineering is optional. Agent Council works without it.

## Safety boundary

Case records require `--project-root` and `--case-root` to point to a directory you control. The engine keeps its files inside that boundary and refuses a different root or a symlinked path.

This protects against accidental writes by the current user. It is not a sandbox against a malicious process running as the same user.

The engine rejects common secret-shaped values before writing a record. This is a pattern check, not a guarantee. Do not put secrets in command arguments or evidence fields.

## For maintainers

Compare direct and Council-assisted runs with the local paired benchmark:

```sh
python3 plugins/agent-council/scripts/Invoke-AgentCouncilBenchmark.py --help
python3 plugins/agent-council/scripts/Test-AgentCouncilBenchmark.py
```

The benchmark records complete pairs, including elapsed time, retries, quality results, observed usage, and missing metrics. It does not call models or upload data.

Run the plugin checks from the plugin directory:

```sh
cd plugins/agent-council
python3 scripts/Test-AgentCouncilPlugin.py
python3 scripts/Test-AgentCouncilUpdates.py
python3 scripts/Test-AgentCouncilActivation.py
python3 scripts/Test-ClaudeQualificationHarness.py
python3 scripts/Test-RoutingPolicyPacketD.py
python3 scripts/Test-AgentCouncilBenchmark.py
for group in schema lifecycle stages routes provider authoring security dispatch-contracts; do
  python3 scripts/core/agent-council/0.2.0/Test-AgentCouncilContracts.py --group "$group"
done
```

See [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [MIGRATION.md](MIGRATION.md).
