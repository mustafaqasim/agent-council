#!/usr/bin/env python3
"""Check route-local policy disclosure without dispatching or creating cases."""
from pathlib import Path
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "agent-council"


class ProgressiveDisclosure(unittest.TestCase):
    def test_entry_is_bounded_and_preserves_routing(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertLessEqual(len(text.encode()), 6500, "entry must reduce the old 13038-byte payload by at least half")
        for boundary in (
            "council_reentry: denied", "Diagnosis authorizes diagnosis only",
            "Explicit invocation guarantees the applicability check",
            "user scope, authority, and reentry; qualifying risk; then economics",
            "Council check: direct execution", "Council check: lightweight routing",
            "Council check: governed case", "asserted automation repair",
            "unexpected ordinary failure", "uncertain composition", "material design decision",
            "architecture implementation", "shared-contract", "lifecycle authority",
            "safety-boundary", "acceptance-gate", "repeated unresolved failure",
            "unqualified capability composition", "Council qualification failure",
            "Read-only architecture assessment", "expected refusals",
            "known-cause, reversible ordinary local repair", "Reassess only when material evidence changes",
            "domain skill", "optional", "missing or unreadable",
        ):
            self.assertIn(boundary, text)

    def test_routes_load_only_their_own_instructions(self):
        text = (SKILL / "SKILL.md").read_text()
        self.assertIn("Direct: read no Council reference", text)
        self.assertIn("Lightweight: read only references/lightweight-routing.yaml", text)
        self.assertIn("Governed: read references/governed-workflow.yaml", text)
        self.assertIn("block the affected work", text)
        self.assertNotIn("references/model-adapters.yaml", text)
        self.assertNotIn("references/forward-tests.yaml", text)
        self.assertNotIn("Invoke-AgentCouncil.py", text)
        for path in re.findall(r"references/[a-z-]+\.yaml", text):
            self.assertTrue((SKILL / path).is_file(), path)

    def test_lightweight_is_self_contained(self):
        text = (SKILL / "references/lightweight-routing.yaml").read_text()
        self.assertNotRegex(text, r"references/[a-z-]+\.yaml")
        registry = re.search(r"(\.\./[./a-z0-9-]+/agent-model-registry\.v2\.yaml)", text)
        self.assertIsNotNone(registry, "lightweight must locate the actual registry")
        self.assertTrue((SKILL / "references" / registry.group(1)).resolve().is_file())
        for boundary in (
            "worker_intelligence", "technical_tactical_intelligence",
            "operational_intelligence", "ultimate_intelligence", "smallest useful fanout",
            "minimal", "medium", "same-tier fallback", "next higher qualified tier",
            "Council: <model>/<effort>", "compact conversational receipt",
            "Do not create a durable lightweight log", "actual observed model and effort",
            "versioned registry", "native", "user model or effort preference",
        ):
            self.assertIn(boundary, text)

    def test_governed_retains_gates_and_conditional_support(self):
        text = (SKILL / "references/governed-workflow.yaml").read_text()
        for boundary in (
            "references/model-adapters.yaml", "references/review-lenses.yaml",
            "references/forward-tests.yaml", "references/project-profiles.yaml",
            "references/compound-engineering.yaml", "implementation author cannot review",
            "two fresh", "candidate bytes", "structural_only", "Invoke-AgentCouncil.py",
            "integration evidence across the affected consumers", "fault evidence",
            "hold only the dependent Council gate", "missing or unreadable",
        ):
            self.assertIn(boundary, text)
        for path in re.findall(r"references/[a-z-]+\.yaml", text):
            self.assertTrue((SKILL / path).is_file(), path)
        self.assertTrue((SKILL / "../../scripts/core/agent-council/0.2.0/Invoke-AgentCouncil.py").resolve().is_file())

    def test_fallback_points_to_policy_instead_of_copying_it(self):
        text = (ROOT / "codex/routing-directive.md").read_text()
        self.assertLess(len(text.encode()), 1200)
        self.assertIn("agent-council", text)
        self.assertIn("Council check:", text)
        self.assertNotIn("worker_intelligence", text)
        self.assertNotIn("R3", text)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProgressiveDisclosure))
    print(json.dumps({"result": "passed" if result.wasSuccessful() else "failed", "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}))
    raise SystemExit(not result.wasSuccessful())
