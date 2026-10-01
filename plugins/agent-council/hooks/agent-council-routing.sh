#!/usr/bin/env bash
# Agent Council activation hook.
# Injects the routing directive so the outer agent runs the Council
# applicability check BEFORE it selects a domain skill. Agent Council is a
# layer that composes above other skills (lab-building, planning,
# brainstorming, etc.), never an alternative to choose instead of them.
# The agent-council skill remains the single source of truth for the rules.

set -euo pipefail
event="${1:-UserPromptSubmit}"

if [ "$event" = "SessionStart" ]; then
  msg="Agent Council is active this session as a cost-aware routing and governance layer. It composes ABOVE other skills (lab-building, planning, brainstorming, code review, etc.), it is not an alternative to choose instead of them. Apply its routing check before substantive work. The agent-council skill holds the full rules."
else
  msg="Agent Council routing layer is active. Before substantive work (engineering, research, analysis, planning, strategy, business, or document tasks), INCLUDING when a domain skill such as lab-building, brainstorming, or planning will do the actual work, first run the Agent Council applicability check and show a one-line 'Council check:' outcome: direct execution, lightweight cost-aware tier routing, or a governed case. Agent Council composes above other skills; it is not an alternative you pick instead of them (e.g. a complex lab-build decision is still Council's routing call even though ACPL builds the lab). Skip the check only for trivial, conversational, or single-step requests. Full routing rules and evidence requirements are in the agent-council skill."
fi

python3 - "$event" "$msg" "${BASH_SOURCE[0]%/*}/../scripts/AgentCouncilTrace.py" <<'PY'
import json, os, shlex, sys
event, msg = sys.argv[1], sys.argv[2]
if os.environ.get("AGENT_COUNCIL_TRACE") == "1":
    command = shlex.join(["python3", "-B", sys.argv[3], "decision"])
    msg += ('\nLocal decision tracing is explicitly enabled. Once after the actual routing decision, '
            'run the command below with the JSON below on stdin, replacing outcome with '
            'direct_execution, lightweight_routing, governed_r1, governed_r2, governed_r3, skipped, or blocked. '
            'Use only these metadata fields; never include task content, prompts, responses, paths, or secrets. '
            'This optional agent-reported observation is not a durable Council receipt or proof of compliance. '
            'If execution is unavailable or fails, continue the authorized task without retrying.\n'
            'Decision trace command: ' + command + '\n'
            'Decision trace JSON: {"activation_source":"host_instruction","outcome":"direct_execution"}')
print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": msg}}))
PY
# Trace failure must never hide or replace the activation output above.
if [ "${AGENT_COUNCIL_TRACE:-}" = "1" ]; then
  python3 -B "${BASH_SOURCE[0]%/*}/../scripts/AgentCouncilTrace.py" hook --event "$event" >/dev/null 2>&1 || true
fi
exit 0
