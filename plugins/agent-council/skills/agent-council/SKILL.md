---
name: agent-council
description: "Run before any non-trivial engineering, debugging, implementation, research, analysis, planning, architecture, review, strategy, business planning, or document creation task. Choose direct work, qualified delegation, or risk gates. Skip trivial requests and council_reentry: denied."
---

purpose: "Outer agent executes; Council chooses direct work, delegation, or risk gates."
authority:
  - "Preserve user scope and authority first. council_reentry: denied is absolute: do not invoke Council, select a route, create a case, or delegate as Council; return only requested evidence to the owning case."
  - "Diagnosis authorizes diagnosis only: read-only inspection and a recommended repair. Planning authorizes planning only. Neither authorizes implementation or mutation. Council grants no destructive, publication, credential, third-party, production, or withheld authority."
check:
  - "Before substantive engineering, debugging, implementation, planning, review, research, analysis, strategy, business, or document work, perform a cheap read-only applicability check. Explicit invocation guarantees the applicability check, not delegation or automatic case creation."
  - "Apply this fixed precedence: user scope, authority, and reentry; qualifying risk; then economics. A risk trigger overrides task size, simplicity, and delegation savings. Select the highest applicable risk route."
profile_check:
  - "After authority and reentry checks, before final route selection, check for repository .agent-council/profile.yaml or an explicitly selected packaged profile. If present, read references/project-profiles.yaml and the selected profile; apply its route floors even when the built-in rules would choose direct or lightweight. Profiles may raise risk floors or add gates, never lower them or expand authority."
  - "Hold the affected route for missing or unreadable selected profiles, unknown relevant semantics, or ambiguous selection. With neither profile present, skip this reference until governed case initialization; do not load unrelated governed references."
risk:
  R1: "An asserted automation repair with an established cause and narrow impact, unless a higher trigger applies."
  R2: "An unexpected ordinary failure, uncertain composition, or material design decision, unless a higher trigger applies. An ordinary failure is a failed expected behavior in the work, not a model, tier, binding, or qualification failure."
  R3: "An architecture implementation or shared-contract/shared-interface change, lifecycle authority, safety-boundary change, acceptance-gate change, repeated unresolved failure without material new evidence, unqualified capability composition, or Council qualification failure. A qualification failure concerns whether a model, binding, capability, or evidence gate is qualified, not an ordinary product failure."
  exclusions:
    - "Read-only architecture assessment, status, diagnosis, formatting, expected refusals, healthy routine operations, bounded refactors, and deterministic checks with qualified components are not governed merely by mentioning architecture, failure, or repair. Implementing architecture changes is R3."
    - "A known-cause, reversible ordinary local repair without automation, lifecycle, updater, authority, shared-contract, safety, acceptance, or repeated-failure impact is direct or lightweight. Cause, reversibility, and size never defeat a qualifying trigger. Automation repair is R1 unless higher risk applies; other listed impacts require their governed route."
  reassess: "Reassess only when evidence changes scope, authority, cause, contract, safety, acceptance, qualification, or repetition, not for narration, elapsed time, or preferences that do not alter qualification."
economics:
  - "Without qualifying risk, choose lightweight only when bounded delegation has net benefit in quality, latency, or reliability after coordination cost. Do not delegate to demonstrate routing or claim unobserved savings."
  - "Treat separable substantive work as lightweight by default. When asked for independent assessment, including developing a consulting offer from existing research, delegate one bounded assessment if qualified; retain synthesis and delivery. Use direct execution only for authority, availability, or coordination cost."
outcomes:
  instruction: "Show the selected outcome before substantive work."
  direct: "Council check: direct execution; delegation overhead exceeds the likely benefit. After the conditional profile check, read no more Council references; execute within scope, say no delegation occurred, and create no case or durable receipt."
  lightweight: "Council check: lightweight routing; delegating <brief task shape>. After the conditional profile check, read only references/lightweight-routing.yaml; create no case or receipts."
  governed: "Council check: governed case <R1|R2|R3>; <qualifying risk>."
disclosure:
  - "Direct: after the conditional profile check, read no further Council reference; execute within scope, say no delegation occurred, create no case or receipt."
  - "Lightweight: after the conditional profile check, read only references/lightweight-routing.yaml before delegation; create no case or durable receipt."
  - "Governed: read references/governed-workflow.yaml before case work, then its named supporting references only when their stated condition applies."
  - "If a required reference is missing or unreadable, block the affected work, report its path, and continue only independent authorized work. Never invent rules or silently downgrade."
selection_boundary:
  - "Use v3 bindings for new selections; existing cases stay pinned, including v2. Use qualified default effort unless a compatible preference applies. Unsupported effort is null and omitted natively. Candidates are unavailable until qualified. Direct needs no catalog."
  lightweight: "Lightweight routing creates no Council case or receipts."
composition:
  - "Council composes above the applicable domain skill; it does not replace that skill. Council governs who works and the evidence required; the domain skill supplies the method within existing authority."
  - "Native standalone execution is primary. Compound Engineering is optional, never an activation prerequisite or a dependency for normal Council operation. Use its integration instructions only on the governed route when available and relevant; otherwise use the native or domain method."
