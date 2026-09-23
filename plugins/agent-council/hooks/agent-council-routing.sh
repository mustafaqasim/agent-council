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

python3 - "$event" "$msg" <<'PY'
import json, sys
event, msg = sys.argv[1], sys.argv[2]
print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": msg}}))
PY
exit 0
