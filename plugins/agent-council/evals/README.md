# Native plugin evals

This package contains 16 native cases covering the 18 boundaries required for the routing release. Cases use JSON-compatible YAML so the structural validator needs only Python's standard library. Every grader is deterministic: response regexes grade stated decisions, and native `tool_used` or `tool_order` events grade invocation and ordering. A model saying it used a tool is never invocation evidence.

Run these commands from the repository root. The validator also checks that the installed native CLI exposes the required flags.

```sh
python3 plugins/agent-council/scripts/Test-NativePluginEvals.py
python3 plugins/agent-council/scripts/NativePluginEvals.py validate
```

For an inexpensive iteration, select one exact case, run once, and omit the baseline. The wrapper rejects case globs and unknown cases. No paid model graders run.

```sh
python3 plugins/agent-council/scripts/NativePluginEvals.py iterate --case trivial-negative
claude plugin eval ./plugins/agent-council --case trivial-negative --runs 1 --ablation none --threshold 1.0 --model claude-opus-5-5 --no-scaffold --trust-plugin --output-dir ./plugins/agent-council/evals/results/manual-iteration --no-publish
```

After candidate freeze, the release check runs the full suite three times with and without the plugin, at threshold 1.0. Passing structural tests or a single iteration does not qualify a release.

For subscriptions with five-hour session limits, use a resumable release campaign. Initialize once after public promotion verifies all eight bindings, then run `step` once per native invocation. The 48 slots are fixed before the first run: each of the 16 exact cases in three indexed rounds. Pause between steps when a quota window ends. A started slot is never retried in place, including after a crash or quota error. Start a new campaign if any slot fails. `verify` accepts only all 48 complete, sealed slots, both arms, every with-plugin grader and score passing at 1.0, unchanged package/proof/suite/model/CLI, and total cost at or below $20.

```sh
python3 plugins/agent-council/scripts/NativePluginEvals.py release-campaign init --campaign plugins/agent-council/evals/results/campaign-001
python3 plugins/agent-council/scripts/NativePluginEvals.py release-campaign step --campaign plugins/agent-council/evals/results/campaign-001
python3 plugins/agent-council/scripts/NativePluginEvals.py release-campaign verify --campaign plugins/agent-council/evals/results/campaign-001
```

Repeat `step` until it reports all 48 slots complete. Each step runs one exact case with one with/without pair, `--runs 1`, threshold 1.0, exact model `claude-opus-5-5`, local trusted plugin, no scaffold, no publication, and the remaining budget passed to the native CLI. The CLI checks cost before each arm launches, so an in-flight arm can exceed that budget. $20 is the campaign acceptance cap, not a strict spend ceiling. An observed overrun invalidates the campaign and prevents the next step.

The campaign uses `--keep-temp` and copies both original native trace files into each ignored slot result before sealing all output hashes. Verification requires the exact model in the native init and actual assistant response, successful terminal usage and matching arm cost, unique session, trace, and provider response identities across all 96 arms, and native starts and response timestamps ordered after preparation and campaign creation. Provider message IDs are required; request IDs are also checked when present. Repeated streaming chunks may share an identity within one arm. Copied or replayed output, missing traces, aliases, and synthetic error responses cannot qualify. Native temporary directories and retained traces contain private prompts and responses; they must remain local. The older monolithic `release` mode remains available.

```sh
python3 plugins/agent-council/scripts/NativePluginEvals.py release
```

Add `--print-command` to a wrapper invocation to inspect it without launching a model run. The wrapper always disables publication and rejects changed or duplicate flags that weaken the selected run mode. Release mode cannot select one case, lower the threshold or run count, omit ablation, change the model, or raise the spending ceiling. Probe mode retains its zero-cost ceiling. Output paths must remain inside the local package without symlink components. `--trust-plugin` is appropriate here only because these are authored local cases and a local fixture. It does not authorize scaffold scripts or gated mutation tools.

Use the wrapper for release evidence. For v3 full release, it first requires verified promotion of all eight default bindings, then runs the CLI from a private verified package copy and records that exact command, behavioral identity, proof hash, eval-suite digest, and timestamp. Partial promotion does not satisfy the full release gate. After execution it checks the copied package again and records the exit code and output hashes. A direct CLI run has no promotion gate or wrapper receipt and cannot qualify this release. Inspect the native aggregate results, both arms, case coverage, model identity, and thresholds before claiming qualification.

Each v3 Claude binding needs two fresh blind native runs. Use `ClaudeQualificationHarness.py prepare --binding-id <exact-binding-id>` for each run, `score` on each native transcript, and `validate-pair` on the two receipts. Each binding also needs an observed packaged Agent task whose resolved model and effort match that binding. Claude requires provider-attested model identity and matching native effort evidence. Preserve the candidate unchanged across all runs. Promote only after every required binding and probe passes, then run the ordinary-routing release eval. Historical v1/v2 receipts remain readable but do not qualify v3.

New qualifications use the versioned role protocol resolved from the frozen registry binding. Every role must pass universal safety assertions. Worker, technical, operational, and ultimate bindings also receive objective tasks for their covered roles. Higher tiers prove cumulative lower-role coverage before they can replace a lower tier. Callers cannot choose an easier role, omit a safety case, reuse historical GFT results, or mix protocol versions in a pair. Every applicable assertion must pass independently in both fresh runs; no average can offset a failed safety assertion. The independent native probe remains required.

Controller obligations remain outside bounded-worker qualification. `verification.yaml` maps GFT08 to dispatch-contract tests and the domain-skill coexistence and CE-absence native cases; those native cases do not qualify installed Compound Engineering or full receipt reuse. GFT09 maps to the routine deterministic routing test and the trivial-negative and diagnosis-only native cases, which cover related invocation and authority boundaries. GFT12 maps to the packaged-default-profile isolation test; the native suite has no conflicting-project-profile fixture, so this boundary has structural coverage only. Removing these obligations from worker qualification does not turn those limits into native proof.

Role promotion preserves that exact protocol binding and each case outcome. The public proof contains only allowlisted identifiers, hashes, assurance fields, and derived outcomes. Private prompts, responses, rationales, local paths, transcripts, and loader logs remain local. Export public evidence only through the promotion exporter, then independently verify its closure without the private source evidence. The public proof establishes structural consistency and the recorded outcomes; it does not authenticate the provider or host.

Claude private promotion replays bounded response scoring and observed model/effort identity. It does not replay workspace preparation or the clean-context collector: `claude_workspace_preparation_replayed` and `claude_clean_context_replayed` remain false. Public proof never replays the native harness and always reports `native_harness_scoring_replayed: false` and `provider_authenticity_verified: false`; role public proof also reports `full_context_blindness_verified: false`. These are evidence limits, including when every recorded case outcome passes.

The public behavioral inventory excludes the three historical Opus native run and qualification receipts, which contain session identifiers. Their originals remain in source and history. Public assembly copies the verified inventory and sanitized proof closure, not an unfiltered source checkout.

Codex has a separate approved path with lower assurance. Prepare a frozen workspace with `CodexQualificationHarness.py prepare --binding-id <exact-binding-id> --output <new-workspace>`, then dispatch the exact prepared prompt and arguments through native collaboration. The selected binding determines the role suite and the manifest pins its protocol. For each binding, retain parent and child exports from two fresh completed runs. Score each with `score --host-selected`, supplying the workspace, binding ID, run ID, and both transcript paths. The collector checks each export against its corresponding local Codex session-store rollout. Validate the two receipts with `validate-pair`, supplying both parent and child exports in receipt order. A third independent completed native dispatch, scored against its own prepared workspace, supplies the probe.

Passing Codex host-selected receipts and pairs use `identity_assurance: host_selected` and may support promotion. Archive their preparations, prompts, receipts, parent and child exports, and probe release binding in local promotion evidence. Promotion reconstructs the candidate and replays native dispatch linkage, scoring, pair validation, and the independent probe. Legacy `client_configuration` receipts remain ineligible. Both paths retain `evidence_assurance: structural_only` and `provider_authenticity_verified: false`; local session records and hashes do not authenticate the provider or host. Fresh Codex tasks retain platform and user instructions, so the harness does not claim complete context blindness or a tool sandbox. Adding this path does not establish native qualification of any current binding.

For each Claude Agent probe, freeze the release binding before launch. Load this exact local plugin candidate with debug logging enabled in a fresh session, then preserve the parent transcript, its session-named child transcript, and `~/.claude/debug/<parent-session-id>.txt` unchanged. The verifier requires a namespaced packaged Agent call, exact resolved model and child effort, and ordered loader lines proving this checkout overrode the installed plugin. Run it against the frozen files:

```sh
python3 plugins/agent-council/scripts/ClaudeAgentProbe.py --binding-id BINDING_ID --release-binding FROZEN_RELEASE.json --parent PARENT_SESSION.jsonl --child PARENT_SESSION/subagents/agent-AGENT_ID.jsonl --debug-log PARENT_SESSION.txt
```

Keep the debug log as `probe_files.loader_debug_log` in promotion evidence. Promotion reparses the frozen log; a screenshot, installed-plugin listing, or agent self-report does not substitute. The log is local structural provenance, not cryptographic proof of loaded bytes. Desktop Agent probes and clean CLI blind qualifications remain separate evidence paths.

The native loader can be checked without model spending:

```sh
python3 plugins/agent-council/scripts/NativePluginEvals.py probe
claude plugin eval ./plugins/agent-council --runs 1 --ablation none --max-cost-usd 0 --model claude-opus-5-5 --no-scaffold --trust-plugin --output-dir ./plugins/agent-council/evals/results/manual-probe --no-publish
```

The zero-cost probe intentionally exits 2 with a partial cost-ceiling result. It checks case parsing and plugin resolution, not child execution, skill invocation, or behavioral success.

Coverage is recorded in each case's tags and enforced by the validator. The ordinary-failure case expects R2; the supplied identity-mismatch qualification scenario expects R3. Reentry denial and the delegated lightweight prompt cover the no-nested-Council boundary. The lightweight case requires an actual native Agent event from the packaged worker or technical agent, plus a `council_reentry: denied` instruction in its observed input. This establishes the dispatch boundary, not an independently visible trace of every nested worker action.

Tier-unavailability, fallback, and identity-mismatch cases explicitly supply hypothetical or recorded state and forbid real dispatch. Their assertions test policy disposition, not live provider identity or availability. Existing provider qualification tests remain necessary. Governed cases stop at the initial route and evidence decision; they do not claim case closure or end-to-end engine qualification. Regex graders constrain output and cannot establish semantic correctness beyond their matched assertions.

The coexistence case loads this package and a tiny `fixture-domain` plugin held inside that case directory. Native eval isolation rejects fixture plugins elsewhere in the suite. Both skill calls and their order must appear in tool events, and the final answer must contain the domain method marker and completion fraction. The fixture is not an installed dependency. The CE-absence case loads only Council, forbids CE skill calls, and requires native-method and absent-receipt disclosure.

In with/without runs, the native CLI normally treats implicit `tool_used: Skill` graders as plugin-fired indicators outside the comparative score. This suite explicitly sets `arm: both`, keeping actual invocation assertions in the score. A without-plugin baseline can therefore fail invocation assertions; that is an expected baseline limitation, not evidence that the with-plugin run failed.

Results, reports, temporary JSON responses, and transcripts are private local outputs under ignored `evals/results/` or `evals/local/`. All eval JSON is ignored except the fixture manifest. Do not commit those outputs or upload them. Native failure sandboxes may be retained by the CLI outside the repository; they are diagnostic output, not distributable fixtures.
