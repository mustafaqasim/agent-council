#!/usr/bin/env python3
"""Standard-library bootstrap runner for Agent Council v2 contract qualification."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


_CONTRACTS = Path(__file__).with_name("Test-CyberRangeAgentCouncilContracts.py")
_SPEC = importlib.util.spec_from_file_location("agent_council_contracts", _CONTRACTS)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("Could not load v2 Council contract tests.")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
run = _MODULE.run
GROUPS = _MODULE.GROUPS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    test = sub.add_parser("test")
    test.add_argument("--group", choices=GROUPS, required=True)
    args = parser.parse_args(argv)
    result = run(args.group)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
