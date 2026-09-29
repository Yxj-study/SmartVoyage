import hashlib
import json
import unittest
from pathlib import Path

from SmartVoyage.evaluation.runner import load_cases
from SmartVoyage.memory.policy import SUPPORTED_PREFERENCE_KEYS


DATA_ROOT = Path(__file__).parents[1] / "evaluation" / "data"


def _queries(cases):
    values = set()
    for case in cases:
        if case.query.strip():
            values.add(case.query.strip())
        values.update(turn.query.strip() for turn in case.turns if turn.query.strip())
    return values


class EvaluationDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dev = load_cases(DATA_ROOT / "dev")
        cls.test = load_cases(DATA_ROOT / "test")

    def test_split_counts_and_ids_are_fixed(self):
        self.assertEqual(len(self.dev), 60)
        self.assertEqual(len(self.test), 160)
        ids = [case.id for case in [*self.dev, *self.test]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_test_queries_do_not_duplicate_development_queries(self):
        overlap = _queries(self.dev) & _queries(self.test)
        self.assertEqual(overlap, set())

    def test_task_and_boundary_coverage(self):
        combined = [*self.dev, *self.test]
        for task in {"weather", "ticket", "attraction", "order"}:
            self.assertTrue(any(task in case.expected_tasks for case in combined))
            self.assertTrue(any(task not in case.expected_tasks for case in combined))
        all_tags = {tag for case in combined for tag in case.tags}
        for required in {
            "multi-intent",
            "clarification",
            "confirmation",
            "error",
            "cross-user",
        }:
            self.assertIn(required, all_tags)

    def test_every_memory_key_has_write_and_override_cases(self):
        memory_cases = [*load_cases(DATA_ROOT / "dev" / "memory.jsonl"),
                        *load_cases(DATA_ROOT / "test" / "memory.jsonl")]
        for key in SUPPORTED_PREFERENCE_KEYS:
            tagged = [case for case in memory_cases if f"memory-key:{key}" in case.tags]
            self.assertTrue(any("memory-write" in case.tags for case in tagged), key)
            self.assertTrue(any("current-override" in case.tags for case in tagged), key)

    def test_frozen_test_manifest_matches_raw_files(self):
        manifest_path = DATA_ROOT / "test" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIs(manifest["frozen"], True)
        self.assertEqual(manifest["case_count"], 160)
        for name, expected in manifest["files"].items():
            path = DATA_ROOT / "test" / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, expected["sha256"], name)
            self.assertEqual(len(load_cases(path)), expected["case_count"], name)


if __name__ == "__main__":
    unittest.main()
