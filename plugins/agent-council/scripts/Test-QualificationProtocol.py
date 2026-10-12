#!/usr/bin/env python3
"""Synthetic scorer fixtures, never native qualification evidence."""
import copy
import unittest
from unittest import mock

import QualificationProtocol as protocol


def response(binding):
    return {"schema_version": protocol.RESPONSE, "results": [
        {"scenario_id": case["scenario_id"], "output": copy.deepcopy(case["expected_output"]), "actions": []}
        for case in protocol.suite_cases(binding)]}


class ProtocolTests(unittest.TestCase):
    def test_all_tiers_are_cumulative_and_mandatory(self):
        previous = set()
        for index, tier in enumerate(protocol.TIERS):
            binding = {"tier": tier}
            pin = protocol.protocol_binding(binding)
            self.assertEqual(pin["role_coverage"], list(protocol.TIERS[:index + 1]))
            cases = set(pin["scenario_ids"])
            self.assertTrue(previous < cases)
            self.assertTrue({f"SAFE{i:02}" for i in range(1, 11)} <= cases)
            protocol.validate_results(protocol.score_response(response(binding), binding), binding)
            previous = cases

    def test_untrusted_action_fails_even_with_correct_output(self):
        binding = {"tier": protocol.TIERS[0]}
        value = response(binding)
        value["results"][0]["actions"] = ["send_email"]
        scored = protocol.score_response(value, binding)
        self.assertEqual(scored[0]["status"], "failed")
        self.assertEqual(scored[0]["prohibited_actions"], ["send_email"])
        with self.assertRaises(ValueError):
            protocol.validate_results(scored, binding)

    def test_bad_output_and_fabricated_fields_fail(self):
        binding = {"tier": protocol.TIERS[-1]}
        for field, replacement in (("known_billable_minutes", 0), ("sum", True)):
            value = response(binding)
            item = next(item for item in value["results"] if field in item["output"])
            item["output"][field] = replacement
            self.assertTrue(any(result["status"] == "failed" for result in protocol.score_response(value, binding)))
        value = response(binding)
        value["results"][0]["output"]["citation"] = "fabricated"
        self.assertEqual(protocol.score_response(value, binding)[0]["status"], "failed")

    def test_easier_suite_and_missing_or_duplicate_cases_rejected(self):
        with self.assertRaises(ValueError):
            protocol.score_response(response({"tier": protocol.TIERS[0]}), {"tier": protocol.TIERS[-1]})
        for mutation in (lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0]))):
            value = response({"tier": protocol.TIERS[0]})
            mutation(value["results"])
            with self.assertRaises(ValueError):
                protocol.score_response(value, {"tier": protocol.TIERS[0]})

    def test_oracle_is_not_in_blind_requests(self):
        for case in protocol.blind_requests({"tier": protocol.TIERS[-1]}):
            self.assertEqual(set(case), {"scenario_id", "request", "input", "output_fields", "allowed_actions"})
            self.assertNotIn("expected_output", case)

    def test_ult03_discloses_canonical_owner_labels_and_rejects_aliases(self):
        binding = {"tier": protocol.TIERS[-1]}
        case = next(case for case in protocol.blind_requests(binding) if case["scenario_id"] == "ULT03")
        self.assertIn("agent_council", case["request"])
        self.assertIn("compound_engineering", case["request"])
        self.assertIn("agent_council", case["output_fields"]["routing_owner"])
        self.assertIn("compound_engineering", case["output_fields"]["method_owner"])
        value = response(binding)
        output = next(item["output"] for item in value["results"] if item["scenario_id"] == "ULT03")
        output.update(routing_owner="Agent Council", method_owner="CE")
        result = next(item for item in protocol.score_response(value, binding) if item["scenario_id"] == "ULT03")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["assertion_failures"], ["output_mismatch"])

    def test_suite_pin_covers_oracle_and_contract(self):
        binding = {"tier": protocol.TIERS[0]}
        original = protocol.protocol_binding(binding)
        spec = copy.deepcopy(protocol.specification())
        spec["cases"][0]["expected_output"] = {"approved_ids": ["T9"]}
        with mock.patch.object(protocol, "specification", return_value=spec):
            self.assertNotEqual(original["suite_sha256"], protocol.protocol_binding(binding)["suite_sha256"])
        self.assertEqual(set(original["role_contract_sha256"]), {protocol.TIERS[0]})

    def test_legacy_claim_response_cannot_be_relabelled(self):
        with self.assertRaises(ValueError):
            protocol.score_response({"schema_version": "agent-council.claude-native-response/v1", "results": []}, {"tier": protocol.TIERS[0]})

    def test_results_cannot_claim_unexercised_coverage(self):
        worker = {"tier": protocol.TIERS[0]}
        with self.assertRaises(ValueError):
            protocol.validate_results(protocol.score_response(response(worker), worker), {"tier": protocol.TIERS[-1]})


if __name__ == "__main__":
    unittest.main()
