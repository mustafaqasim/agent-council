---
name: agent-council
description: Use for substantive work that may benefit from cost-aware sub-agent routing, including engineering, research, analysis, strategy, business planning, document creation, and review. Route bounded work to an appropriate model tier, while opening a governed Council case only for qualifying risk. Skip trivial requests that need no delegation.
---

# Agent Council

Use the Council as the cost-aware routing and governance layer. The outer agent remains the execution harness. This skill decides whether direct execution or delegation is more efficient, selects qualified model tiers for bounded work, and adds formal evidence gates only when risk warrants them.

Preserve the user's scope and authority boundary before evaluating risk or economics. `council_reentry: denied` is absolute: do not invoke Agent Council, select a route, create a case, or delegate as Council. Return only the requested evidence to the owning Council case. Diagnosis authorizes diagnosis only, including read-only inspection and a recommended repair. Planning authorizes planning only. Neither authorizes implementation or mutation. A Council decision does not grant destructive, publication, credential, third-party, production, or any authority the user withheld.

## Check and route

First perform a cheap, read-only applicability check before substantive work, including debugging, implementation, refactoring, planning, architecture, integration, code review, research, analysis, strategy, business planning, document creation, or editorial review. Apply this fixed precedence: user scope, authority, and reentry; qualifying risk; then economics. A risk trigger overrides task size, apparent simplicity, and delegation savings. When more than one risk trigger applies, select the highest applicable route.

Explicit invocation guarantees the applicability check, not delegation or automatic case creation.

Choose one observable outcome and show it before substantive work:

- `Council check: direct execution; delegation overhead exceeds the likely benefit.` for trivial, conversational, tightly coupled, or known-cause reversible ordinary local work with no qualifying trigger that the outer agent should handle itself.
- `Council check: lightweight routing; delegating <brief task shape>.` when one or more bounded subtasks have an observable net benefit in quality, latency, or reliable completion after coordination cost.
- `Council check: governed case <R1|R2|R3>; <qualifying risk>.` when a qualifying activation class requires formal evidence gates.

Lightweight routing creates no Council case or receipts. Use it when substantive work contains bounded research, evidence gathering, drafting, analysis, implementation, verification, independent review, or parallel workstreams. Do not delegate merely to demonstrate routing. Choose it only when the observable net benefit in quality, latency, or reliable completion exceeds coordination cost. Do not claim token or monetary savings that were not observed.

Treat clearly separable substantive work as a lightweight-routing opportunity by default. For example, developing a consulting offer from existing research should delegate bounded research or drafting while the outer agent retains synthesis. Use direct execution only when the work is trivial, inseparable, explicitly kept local by the user, or no available qualified tier would provide a net benefit.

For each lightweight subtask, choose the lowest qualified tier that can complete it reliably:

- `worker_intelligence`: extraction, inventory, source gathering, formatting, and deterministic checks.
- `technical_tactical_intelligence`: bounded implementation, structured analysis, synthesis, and drafting.
- `operational_intelligence`: cross-stream integration, difficult review, and coordination.
- `ultimate_intelligence`: ambiguous architecture, difficult diagnosis, high-impact judgment, and final disposition when a lower tier is likely to retry or fail.

Keep the outer agent responsible for decomposition, user dialogue, synthesis, and final delivery. For lightweight work, use `minimal` or `low` effort for mechanical and clearly bounded tasks, `medium` for bounded implementation, structured analysis, or drafting, and `high` only when the bounded task itself needs difficult technical judgment. Do not fan out merely because work is separable: fan out only independent tasks whose aggregate observable benefit exceeds coordination cost. Start with the smallest useful fanout. Escalate one tier or effort step only when returned evidence shows the assigned tier is insufficient, the task expands materially, or an in-scope risk trigger appears. Downshift again after the difficult step is resolved.

If the preferred lightweight tier is unavailable, use an active same-tier fallback first. If none exists, use the next higher qualified tier only when the likely benefit still exceeds its cost; otherwise report the limitation and continue by direct execution. Never substitute a lower tier that is unlikely to complete the task reliably.

## Govern risk

Open a full Council case only when an existing qualifying activation class applies. Test the facts, not a label such as "repair" or "architecture":

- R1 is an asserted automation repair with an established cause and narrow impact, unless a higher trigger applies.
- R2 is an unexpected ordinary failure, uncertain composition, or material design decision, unless a higher trigger applies. An ordinary failure is a failed expected behavior in the work, not a model, tier, binding, or qualification failure.
- R3 is an architecture implementation or shared-contract change, lifecycle authority, safety-boundary change, acceptance-gate change, repeated unresolved failure without material new evidence, unqualified capability composition, or Council qualification failure. A qualification failure concerns whether a model, binding, capability, or evidence gate is qualified, and is not merely an ordinary product failure.

For an R3 shared-contract or shared-interface change, require integration evidence across the affected consumers as well as fault evidence. Unit evidence for one component does not satisfy that boundary.

Read-only architecture assessment, status, diagnosis, formatting-only changes, expected refusals, healthy routine operations, routine refactors with bounded impact, and deterministic checks using already-qualified components are not governed just because they mention architecture, failure, or a repair. Implementing an architecture change is R3. A known-cause, reversible ordinary local repair with no automation, lifecycle, updater, authority, shared-contract, safety, acceptance, or repeated-failure impact is direct or lightweight. Known cause, reversibility, and line count do not defeat a qualifying trigger: an asserted automation repair is R1 unless a higher route applies, and lifecycle, updater, authority, shared-contract, safety, acceptance, or qualification triggers take their applicable governed route.

When repeated unresolved failure activates R3, restart diagnosis by separating the observed symptom from the hypothesized cause. Do not repeat the same repair action without materially new evidence. When routine deterministic work is excluded from a governed case, record the ordinary-operation exclusion where the workflow requires it and preserve the user's existing authorization boundary.

When no qualifying activation class applies, use direct execution or lightweight routing without a Council case or Council receipts. Reconsider formal governance only when material new evidence changes risk. Reassess only when material evidence changes scope, authority, the cause, affected contract, safety, acceptance, qualification, or repeated-failure facts. Do not reassess for unchanged task narration, elapsed time, or a preference that does not alter qualification.

Classify the route:

- R1: bounded asserted automation repair with an established cause and narrow impact.
- R2: uncertain composition, unexpected ordinary failure, or material design decision.
- R3: architecture implementation, shared contract, lifecycle authority, safety boundary, acceptance gate, repeated unresolved failure, unqualified capability composition, or Council qualification failure.

## Delegate visibly

- `ultimate_intelligence`: routing, architecture, difficult diagnosis, and final disposition.
- `operational_intelligence`: coordination, integration ownership, and independent review.
- `technical_tactical_intelligence`: bounded implementation and technical verification.
- `worker_intelligence`: mechanical evidence gathering and deterministic checks.

Resolve model names through the versioned registry. Select a qualified active binding that meets the route and task, honoring an explicit user model or effort preference when it is compatible with that binding, the route, and native tool support. If a preference is incompatible or unavailable, keep the required qualification floor, state the limitation, and choose the qualified binding under the fallback rule. Never treat a prompt claiming a model name as proof of selection. Use clean contexts for independent review. The implementation author cannot review their own work.

Reject self-review and keep closure held until the named independent review gate is satisfied. Changing candidate bytes starts a new candidate cycle, invalidates stale evidence, and requires fresh review plus both fresh native qualification runs before promotion or closure.

Before each lightweight or governed delegation, show one concise user-facing notice containing the assigned model, effort, cost class, task, and one-sentence reason. Use this form:

`Council: <model>/<effort> (<premium|standard|economical>) assigned <task> because <brief reason>.`

After the worker returns, report its disposition and the evidence it produced. For direct or lightweight work, finish with one compact conversational receipt: actual observed model and effort for each delegation, outcome, evidence, and limitations. If there was no delegation, say so plainly. Keep this receipt in the active conversation only. Do not create a durable lightweight log, receipt, case, dispatch plan, or invented savings. Do not reveal private chain-of-thought, internal deliberation, or lengthy routing mechanics.

For model dispatch or availability, read [model adapters](references/model-adapters.yaml). For review, read [review lenses](references/review-lenses.yaml). For qualification or behavioral validation, read [forward tests](references/forward-tests.yaml).

## Work with project methods

Read [project profiles](references/project-profiles.yaml) when a repository supplies `.agent-council/profile.yaml` or when a packaged profile applies. The outer agent selects and interprets one explicit profile. The local runtime pins the packaged default profile hash only. It does not dynamically load, merge, inherit, or semantically enforce repository profiles. Hold the affected route if profile selection or inheritance is unsupported or ambiguous.

When no repository profile is present, use the packaged default profile. Do not inherit unrelated project rules, and do not change external-action authority through profile selection or fallback.

Native standalone workflow is primary. Read [Compound Engineering integration](references/compound-engineering.yaml) only when that plugin is available and its method fits the work. It is an optional interoperability path, never an activation prerequisite or a dependency for normal Council operation. The Council decides who performs work and what evidence is required. When used, Compound Engineering can define how planning, debugging, implementation, review, and shipping are performed. Do not duplicate a completed Compound Engineering gate when its receipt satisfies the Council evidence contract.

## Enforce

Use the local engine at `../../scripts/core/agent-council/0.2.0/Invoke-AgentCouncil.py` for immutable case authoring and structural validation. Store project cases under `.agent/council/<case_id>/` unless the project profile provides another confined path.

The engine never launches models and never grants operational authority. The outer agent performs native delegation. The engine records the plan, validates model and context identity, checks evidence linkage, prevents self-review, and refuses closure when required gates are missing, failed, stale, or bound to different candidate bytes.

Local receipts provide `structural_only` assurance. Provider execution and real-world acceptance remain responsibilities of the outer agent task and its observed tool results.

If a required Council model tier is unavailable, record the limitation and hold only the dependent Council gate. If Compound Engineering is unavailable, continue with an equivalent native standalone method and record that no Compound Engineering receipt exists. Do not silently substitute a lower tier or invent a receipt.
