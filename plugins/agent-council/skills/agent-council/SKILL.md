---
name: agent-council
description: Use for substantive work that may benefit from cost-aware sub-agent routing, including engineering, research, analysis, strategy, business planning, document creation, and review. Route bounded work to an appropriate model tier, while opening a governed Council case only for qualifying risk. Skip trivial requests that need no delegation.
---

# Agent Council

Use the Council as the cost-aware routing and governance layer. The outer agent remains the execution harness. This skill decides whether direct execution or delegation is more efficient, selects qualified model tiers for bounded work, and adds formal evidence gates only when risk warrants them.

Preserve the user's authority boundary. Diagnosis does not authorize implementation. Planning does not authorize mutation. A Council decision does not grant destructive, publication, credential, third-party, or production authority.

## Check and route

First perform a cheap, read-only applicability check before substantive work, including debugging, implementation, refactoring, planning, architecture, integration, code review, research, analysis, strategy, business planning, document creation, or editorial review. If the active task carries `council_reentry: denied`, do not invoke Agent Council or open a nested case; return evidence to the existing Council case.

Explicit invocation guarantees the applicability check, not delegation or automatic case creation.

Choose one observable outcome and show it before substantive work:

- `Council check: direct execution; delegation overhead exceeds the likely benefit.` for trivial, single-step, conversational, or tightly coupled work that the outer agent should handle itself.
- `Council check: lightweight routing; delegating <brief task shape>.` when one or more bounded subtasks can be completed more economically, independently, or effectively by another model tier.
- `Council check: governed case <R1|R2|R3>; <qualifying risk>.` when a qualifying activation class requires formal evidence gates.

Lightweight routing creates no Council case or receipts. Use it when substantive work contains bounded research, evidence gathering, drafting, analysis, implementation, verification, independent review, or parallel workstreams. Do not delegate merely to demonstrate routing. The expected quality, latency, and token savings must outweigh coordination overhead.

Treat clearly separable substantive work as a lightweight-routing opportunity by default. For example, developing a consulting offer from existing research should delegate bounded research or drafting while the outer agent retains synthesis. Use direct execution only when the work is trivial, inseparable, explicitly kept local by the user, or no available qualified tier would provide a net benefit.

For each lightweight subtask, choose the lowest qualified tier that can complete it reliably:

- `worker_intelligence`: extraction, inventory, source gathering, formatting, and deterministic checks.
- `technical_tactical_intelligence`: bounded implementation, structured analysis, synthesis, and drafting.
- `operational_intelligence`: cross-stream integration, difficult review, and coordination.
- `ultimate_intelligence`: ambiguous architecture, difficult diagnosis, high-impact judgment, and final disposition when a lower tier is likely to retry or fail.

Keep the outer agent responsible for decomposition, user dialogue, synthesis, and final delivery. Escalate when returned evidence shows the assigned tier is insufficient. Downshift again after the difficult step is resolved.

If the preferred lightweight tier is unavailable, use an active same-tier fallback first. If none exists, use the next higher qualified tier only when the likely benefit still exceeds its cost; otherwise report the limitation and continue by direct execution. Never substitute a lower tier that is unlikely to complete the task reliably.

## Govern risk

Open a full Council case only when an existing qualifying activation class applies: an asserted automation repair, unexpected failure, repeated failure without new evidence, architecture or shared-contract change, unqualified capability composition, safety-boundary change, or acceptance-gate change. Do not open a full Council case for read-only status, formatting-only changes, expected refusals, healthy routine operations, routine refactors with bounded impact, or deterministic checks using already-qualified components.

When no qualifying activation class applies, use direct execution or lightweight routing without a Council case or Council receipts. Reconsider formal governance only when material new evidence changes risk.

Classify the route:

- R1: bounded repair with an established cause and narrow impact.
- R2: uncertain composition, unexpected failure, or material design decision.
- R3: architecture, shared contract, lifecycle authority, safety boundary, repeated unresolved failure, or Council qualification.

## Delegate visibly

- `ultimate_intelligence`: routing, architecture, difficult diagnosis, and final disposition.
- `operational_intelligence`: coordination, integration ownership, and independent review.
- `technical_tactical_intelligence`: bounded implementation and technical verification.
- `worker_intelligence`: mechanical evidence gathering and deterministic checks.

Resolve model names through the versioned registry. Never treat a prompt claiming a model name as proof of selection. Use clean contexts for independent review. The implementation author cannot review their own work.

Before each lightweight or governed delegation, show one concise user-facing notice containing the assigned model, effort, cost class, task, and one-sentence reason. Use this form:

`Council: <model>/<effort> (<premium|standard|economical>) assigned <task> because <brief reason>.`

After the worker returns, report its disposition and the evidence it produced. Do not reveal private chain-of-thought, internal deliberation, or lengthy routing mechanics.

For model dispatch or availability, read [model adapters](references/model-adapters.yaml). For review, read [review lenses](references/review-lenses.yaml). For qualification or behavioral validation, read [forward tests](references/forward-tests.yaml).

## Work with project methods

Read [project profiles](references/project-profiles.yaml) when a repository supplies `.agent-council/profile.yaml` or when a packaged profile applies. The outer agent selects and interprets one explicit profile. The local runtime pins the packaged default profile hash only. It does not dynamically load, merge, inherit, or semantically enforce repository profiles. Hold the affected route if profile selection or inheritance is unsupported or ambiguous.

Native standalone workflow is primary. Read [Compound Engineering integration](references/compound-engineering.yaml) only when that plugin is available and its method fits the work. It is an optional interoperability path, never an activation prerequisite or a dependency for normal Council operation. The Council decides who performs work and what evidence is required. When used, Compound Engineering can define how planning, debugging, implementation, review, and shipping are performed. Do not duplicate a completed Compound Engineering gate when its receipt satisfies the Council evidence contract.

## Enforce

Use the local engine at `../../scripts/core/agent-council/0.2.0/Invoke-AgentCouncil.py` for immutable case authoring and structural validation. Store project cases under `.agent/council/<case_id>/` unless the project profile provides another confined path.

The engine never launches models and never grants operational authority. The outer agent performs native delegation. The engine records the plan, validates model and context identity, checks evidence linkage, prevents self-review, and refuses closure when required gates are missing, failed, stale, or bound to different candidate bytes.

Local receipts provide `structural_only` assurance. Provider execution and real-world acceptance remain responsibilities of the outer agent task and its observed tool results.

If a required Council model tier is unavailable, record the limitation and hold only the dependent Council gate. If Compound Engineering is unavailable, continue with an equivalent native standalone method and record that no Compound Engineering receipt exists. Do not silently substitute a lower tier or invent a receipt.
