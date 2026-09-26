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
claude plugin eval ./plugins/agent-council --case trivial-negative --runs 1 --ablation none --threshold 1.0 --model opus --no-scaffold --trust-plugin --output-dir ./plugins/agent-council/evals/results/manual-iteration --no-publish
```

After candidate freeze, the release check runs the full suite three times with and without the plugin, at threshold 1.0. Passing structural tests or a single iteration does not qualify a release.

```sh
python3 plugins/agent-council/scripts/NativePluginEvals.py release
claude plugin eval ./plugins/agent-council --runs 3 --ablation with-without --threshold 1.0 --concurrency 1 --model opus --no-scaffold --trust-plugin --output-dir ./plugins/agent-council/evals/results/manual-release --no-publish
```

Add `--print-command` to a wrapper invocation to inspect it without launching a model run. The wrapper always disables publication. `--trust-plugin` is appropriate here only because these are authored local cases and a local fixture. It does not authorize scaffold scripts or gated mutation tools.

The native loader can be checked without model spending:

```sh
python3 plugins/agent-council/scripts/NativePluginEvals.py probe
claude plugin eval ./plugins/agent-council --runs 1 --ablation none --max-cost-usd 0 --model opus --no-scaffold --trust-plugin --output-dir ./plugins/agent-council/evals/results/manual-probe --no-publish
```

The zero-cost probe intentionally exits 2 with a partial cost-ceiling result. It checks case parsing and plugin resolution, not child execution, skill invocation, or behavioral success.

Coverage is recorded in each case's tags and enforced by the validator. The ordinary-failure case expects R2; the supplied identity-mismatch qualification scenario expects R3. Reentry denial and the delegated lightweight prompt cover the no-nested-Council boundary. The lightweight case requires an actual native Agent event and a `council_reentry: denied` instruction in its observed input. This establishes the dispatch boundary, not an independently visible trace of every nested worker action.

Tier-unavailability, fallback, and identity-mismatch cases explicitly supply hypothetical or recorded state and forbid real dispatch. Their assertions test policy disposition, not live provider identity or availability. Existing provider qualification tests remain necessary. Governed cases stop at the initial route and evidence decision; they do not claim case closure or end-to-end engine qualification. Regex graders constrain output and cannot establish semantic correctness beyond their matched assertions.

The coexistence case loads this package and a tiny `fixture-domain` plugin held inside that case directory. Native eval isolation rejects fixture plugins elsewhere in the suite. Both skill calls and their order must appear in tool events, and the final answer must contain the domain method marker and completion fraction. The fixture is not an installed dependency. The CE-absence case loads only Council, forbids CE skill calls, and requires native-method and absent-receipt disclosure.

In with/without runs, the native CLI normally treats implicit `tool_used: Skill` graders as plugin-fired indicators outside the comparative score. This suite explicitly sets `arm: both`, keeping actual invocation assertions in the score. A without-plugin baseline can therefore fail invocation assertions; that is an expected baseline limitation, not evidence that the with-plugin run failed.

Results, reports, temporary JSON responses, and transcripts are private local outputs under ignored `evals/results/` or `evals/local/`. All eval JSON is ignored except the fixture manifest. Do not commit those outputs or upload them. Native failure sandboxes may be retained by the CLI outside the repository; they are diagnostic output, not distributable fixtures.
