---
name: agent-council
description: Use for substantive work that may benefit from cost-aware sub-agent routing, including engineering, research, analysis, strategy, business planning, document creation, and review. Route bounded work to an appropriate model tier, while opening a governed Council case only for qualifying risk. Skip trivial requests that need no delegation.
---

purpose: "The outer agent executes; Council selects direct work, useful delegation, or formal risk gates."
authority:
  - "Preserve user scope and authority first. council_reentry: denied is absolute: do not invoke Council, select a route, create a case, or delegate as Council; return only requested evidence to the owning case."
  - "Diagnosis authorizes diagnosis only: read-only inspection and a recommended repair. Planning authorizes planning only. Neither authorizes implementation or mutation. Council grants no destructive, publication, credential, third-party, production, or withheld authority."
check:
  - "Before substantive engineering, debugging, implementation, planning, review, research, analysis, strategy, business, or document work, perform a cheap read-only applicability check. Explicit invocation guarantees the applicability check, not delegation or automatic case creation."
  - "Apply this fixed precedence: user scope, authority, and reentry; qualifying risk; then economics. A risk trigger overrides task size, simplicity, and delegation savings. Select the highest applicable risk route."
risk:
  R1: "An asserted automation repair with an established cause and narrow impact, unless a higher trigger applies."
  R2: "An unexpected ordinary failure, uncertain composition, or material design decision, unless a higher trigger applies. An ordinary failure is a failed expected behavior in the work, not a model, tier, binding, or qualification failure."
  R3: "An architecture implementation or shared-contract/shared-interface change, lifecycle authority, safety-boundary change, acceptance-gate change, repeated unresolved failure without material new evidence, unqualified capability composition, or Council qualification failure. A qualification failure concerns whether a model, binding, capability, or evidence gate is qualified, not an ordinary product failure."
  exclusions:
    - "Read-only architecture assessment, status, diagnosis, formatting-only changes, expected refusals, healthy routine operations, bounded routine refactors, and deterministic checks with already-qualified components are not governed merely because they mention architecture, failure, or repair. Implementing an architecture change is R3."
    - "A known-cause, reversible ordinary local repair with no automation, lifecycle, updater, authority, shared-contract, safety, acceptance, or repeated-failure impact is direct or lightweight. Known cause, reversibility, and line count do not defeat a qualifying trigger. Automation repair is R1 unless higher risk applies; lifecycle, updater, authority, shared-contract, safety, acceptance, or qualification impacts require their applicable governed route."
  reassess: "Reassess only when material evidence changes scope, authority, cause, affected contract, safety, acceptance, qualification, or repeated-failure facts, never for unchanged narration, elapsed time, or a preference that does not alter qualification."
economics:
  - "Without qualifying risk, choose lightweight only when bounded delegation offers observable net benefit in quality, latency, or reliable completion after coordination cost. Do not delegate merely to demonstrate routing or claim unobserved savings."
  - "Treat clearly separable substantive work as a lightweight opportunity by default, including developing a consulting offer from existing research. Direct execution fits trivial, inseparable, explicitly local work, or work with no available qualified tier offering net benefit. The outer agent retains decomposition, user dialogue, synthesis, and delivery."
outcomes:
  instruction: "Show the selected outcome before substantive work."
  direct: "Council check: direct execution; delegation overhead exceeds the likely benefit."
  lightweight: "Council check: lightweight routing; delegating <brief task shape>."
  governed: "Council check: governed case <R1|R2|R3>; <qualifying risk>."
disclosure:
  - "Direct: read no Council reference. Execute within scope; say no delegation occurred. Create no Council case or durable receipt."
  - "Lightweight: read only references/lightweight-routing.yaml before delegation. Lightweight routing creates no Council case or receipts. The conversational summary is not a durable Council receipt."
  - "Governed: read references/governed-workflow.yaml before case work, then its named supporting references only when their stated condition applies."
  - "If a required route reference or supporting reference is missing or unreadable, block the affected work, report the missing path, and continue only independent authorized work. Never invent its rules or silently downgrade the route."
composition:
  - "Council composes above the applicable domain skill; it does not replace that skill. Council governs who works and the evidence required; the domain skill supplies the method within existing authority."
  - "Native standalone execution is primary. Compound Engineering is optional, never an activation prerequisite or a dependency for normal Council operation. Use its integration instructions only on the governed route when available and relevant; otherwise use the native or domain method."
