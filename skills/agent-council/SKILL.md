---
name: agent-council
description: Govern complex Codex engineering work with risk-based model-tier delegation, independent review, evidence gates, and project-specific profiles. Use for defects, repairs, architecture changes, shared-contract changes, repeated failures, uncertain implementation, or high-consequence acceptance decisions. Excludes routine proven operations and simple read-only explanations.
---

# Agent Council

Use the Council as the outer governance layer. Codex remains the agent harness. This skill classifies risk, selects qualified model tiers, delegates bounded work, and verifies evidence before completion.

Preserve the user's authority boundary. Diagnosis does not authorize implementation. Planning does not authorize mutation. A Council decision does not grant destructive, publication, credential, third-party, or production authority.

## Activate

Open a Council case when work includes an asserted automation repair, unexpected failure, repeated failure without new evidence, architecture or shared-contract change, unqualified capability composition, safety-boundary change, or acceptance-gate change. Do not open a full Council case for read-only status, formatting-only changes, expected refusals, healthy routine operations, or deterministic checks using already-qualified components.

Classify the route:

- R1: bounded repair with an established cause and narrow impact.
- R2: uncertain composition, unexpected failure, or material design decision.
- R3: architecture, shared contract, lifecycle authority, safety boundary, repeated unresolved failure, or Council qualification.

## Delegate

- `ultimate_intelligence`: routing, architecture, difficult diagnosis, and final disposition.
- `operational_intelligence`: coordination, integration ownership, and independent review.
- `technical_tactical_intelligence`: bounded implementation and technical verification.
- `worker_intelligence`: mechanical evidence gathering and deterministic checks.

Resolve model names through the versioned registry. Never treat a prompt claiming a model name as proof of selection. Use clean contexts for independent review. The implementation author cannot review their own work.

Before each delegation, show one concise user-facing notice containing the assigned model, effort, cost class, task, and one-sentence reason. Use this form:

`Council: <model>/<effort> (<premium|standard|economical>) assigned <task> because <brief reason>.`

After the worker returns, report its disposition and the evidence it produced. Do not reveal private chain-of-thought, internal deliberation, or lengthy routing mechanics.

For model dispatch or availability, read [model adapters](references/model-adapters.yaml). For review, read [review lenses](references/review-lenses.yaml). For qualification or behavioral validation, read [forward tests](references/forward-tests.yaml).

## Work with project methods

Read [project profiles](references/project-profiles.yaml) when a repository supplies `.agent-council/profile.yaml` or when a packaged profile applies. A profile may raise a route or add gates, but cannot weaken the core independence, provenance, or evidence rules.

Read [Compound Engineering integration](references/compound-engineering.yaml) when that plugin is available. The Council decides who performs work and what evidence is required. Compound Engineering defines how planning, debugging, implementation, review, and shipping are performed. Do not duplicate a completed Compound Engineering gate when its receipt satisfies the Council evidence contract.

## Enforce

Use the local engine at `../../scripts/core/agent-council/0.2.0/Invoke-CyberRangeAgentCouncil.py` for immutable case authoring and structural validation. Store project cases under `.agent/council/<case_id>/` unless the project profile provides another confined path.

The engine never launches models and never grants operational authority. Codex performs native delegation. The engine records the plan, validates model and context identity, checks evidence linkage, prevents self-review, and refuses closure when required gates are missing, failed, stale, or bound to different candidate bytes.

Local receipts provide `structural_only` assurance. Provider execution and real-world acceptance remain responsibilities of the outer Codex task and its observed tool results.

If the required model tier or Compound Engineering skill is unavailable, record the limitation and hold only the dependent gate. Do not silently substitute a lower tier or invent a receipt.
