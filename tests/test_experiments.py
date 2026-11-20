import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_eval.catalog import list_runs, query
from ai_eval.experiments import load_plan, run_experiment
from ai_eval.engine import run as native_run


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def plan_fixture(root):
    samples = [{"id": f"s{i}", "input": i, "target": 1, "group": f"g{i}",
                "slices": {"topic": "even" if i % 2 == 0 else "odd"}} for i in range(4)]
    (root / "samples.jsonl").write_text("".join(json.dumps(row) + "\n" for row in samples), encoding="utf-8")
    write_json(root / "benchmark.json", {"schema_version": "1.0", "name": "component-study", "revision": "1",
        "samples": "samples.jsonl", "metrics": [{"name": "accuracy", "scorer": "exact_match", "direction": "maximize"}],
        "protocol": {"trials": 2, "seed": 17}})
    conditions = []
    for name, values, cost in (("base", [0, 0, 0, 1], 1), ("a", [0, 0, 0, 1], 2),
                               ("b", [0, 0, 1, 1], 3), ("ab", [1, 1, 1, 1], 4)):
        (root / f"{name}.jsonl").write_text("".join(json.dumps({"sample_id": f"s{i}", "output": value,
            "usage": {"calls": cost}}) + "\n" for i, value in enumerate(values)), encoding="utf-8")
        conditions.append({"id": name, "system": {"name": "retrieval", "revision": name,
                           "config": {"condition": name}}, "target": {"predictions": f"{name}.jsonl"}})
    plan = {"schema_version": "1.0", "name": "component intervention", "question": "Does A depend on B?",
            "benchmark": "benchmark.json", "conditions": conditions,
            "analyses": [{"id": "systems", "kind": "study", "metric": "accuracy", "resource": "usage.calls", "resamples": 30},
                         {"id": "effects", "kind": "factorial", "metric": "accuracy", "resamples": 30},
                         {"id": "items", "kind": "benchmark", "metric": "accuracy"}]}
    write_json(root / "plan.json", plan)
    return plan


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plan = plan_fixture(self.root)
        self.source = self.root / "plan.json"
        self.output = self.root / "experiment"
        self.catalog = self.root / "experiments.sqlite"

    def test_conditions_analyses_reports_and_catalog_share_actual_native_runs(self):
        result = run_experiment(self.source, self.output, catalog=self.catalog)
        self.assertEqual(result["status"], "complete")
        self.assertEqual([condition["recorded_trials"] for condition in result["conditions"]], [8] * 4)
        systems = json.loads((self.output / "analyses/systems.json").read_text())
        self.assertEqual([row["mean"] for row in systems["systems"]], [.25, .25, .5, 1])
        self.assertEqual([row["resource_mean"] for row in systems["systems"]], [1, 2, 3, 4])
        effects = json.loads((self.output / "analyses/effects.json").read_text())
        self.assertEqual(effects["effects"]["interaction"]["estimate"], .5)
        self.assertTrue(all(Path(item["html_path"]).stat().st_size > 5000 for item in result["analyses"]))
        runs = list_runs(self.catalog, experiment=result["experiment_id"], metric="accuracy")
        self.assertEqual(runs["total"], 4)
        table = query(self.catalog, "SELECT status,count(*) AS n FROM trials GROUP BY status")
        self.assertEqual(table["items"], [{"status": "ok", "n": 32}])
        self.assertEqual(query(self.catalog, "SELECT status FROM experiments")["items"], [{"status": "complete"}])

    def test_resume_keeps_run_ids_and_recorded_bytes(self):
        first = run_experiment(self.source, self.output, catalog=self.catalog)
        recorded = [(Path(item["path"]) / "results.jsonl").read_bytes() for item in first["conditions"]]
        second = run_experiment(self.source, self.output, resume=True, catalog=self.catalog)
        self.assertEqual(first, second)
        self.assertEqual(recorded, [(Path(item["path"]) / "results.jsonl").read_bytes() for item in second["conditions"]])
        self.assertEqual(query(self.catalog, "SELECT count(*) AS n FROM trials")["items"], [{"n": 32}])
        with self.assertRaisesRegex(ValueError, "must be empty"):
            run_experiment(self.source, self.output)

    def test_interrupted_condition_resumes_missing_attempts_and_later_conditions(self):
        calls = 0
        class InterruptedTarget:
            def __init__(self, target):
                self.target, self.calls = target, 0
                self.identity = target.identity
            def __call__(self, request):
                self.calls += 1
                if self.calls == 2:
                    raise KeyboardInterrupt("worker interrupted")
                return self.target(request)
        def interrupt_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                kwargs["target"] = InterruptedTarget(kwargs["target"])
            return native_run(*args, **kwargs)
        with patch("ai_eval.experiments.run", side_effect=interrupt_second), self.assertRaises(KeyboardInterrupt):
            run_experiment(self.source, self.output, catalog=self.catalog)
        base = self.output / "conditions/base/results.jsonl"
        before = base.read_bytes()
        interrupted = (self.output / "conditions/a/results.jsonl").read_bytes()
        self.assertEqual(len(interrupted.splitlines()), 1)
        result = run_experiment(self.source, self.output, resume=True, catalog=self.catalog)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(before, base.read_bytes())
        self.assertTrue((self.output / "conditions/a/results.jsonl").read_bytes().startswith(interrupted))

    def test_changed_plan_and_changed_predictions_do_not_replace_recorded_outcomes(self):
        result = run_experiment(self.source, self.output)
        before = (self.output / "conditions/base/results.jsonl").read_bytes()
        changed = copy.deepcopy(self.plan)
        changed["conditions"][0]["system"]["config"]["new"] = True
        write_json(self.source, changed)
        with self.assertRaisesRegex(ValueError, "same resolved plan"):
            run_experiment(self.source, self.output, resume=True)
        write_json(self.source, self.plan)
        (self.root / "base.jsonl").write_text('{"sample_id":"s0","output":1}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "same benchmark, system and execution"):
            run_experiment(self.source, self.output, resume=True)
        self.assertEqual(before, (self.output / "conditions/base/results.jsonl").read_bytes())
        self.assertEqual(result["conditions"][0]["recorded_trials"], 8)

    def test_invalid_analysis_is_rejected_before_starting_conditions(self):
        self.plan["analyses"][0]["baseline"] = "missing"
        write_json(self.source, self.plan)
        with self.assertRaisesRegex(ValueError, "baseline"):
            run_experiment(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.plan["analyses"][0].pop("baseline")
        self.plan["conditions"][0]["id"] = "../outside"
        write_json(self.source, self.plan)
        with self.assertRaisesRegex(ValueError, "identifier"):
            load_plan(self.source)

    def test_command_paths_are_plan_relative_from_a_different_working_directory(self):
        (self.root / "solver.py").write_text('import json,sys\nr=json.load(sys.stdin)\n'
            'assert "target" not in r\nprint(json.dumps({"output":1,"usage":{"calls":1}}))\n', encoding="utf-8")
        self.plan["conditions"][3]["target"] = {"command": [sys.executable, "solver.py"]}
        write_json(self.source, self.plan)
        outside = self.root / "outside"
        outside.mkdir()
        completed = subprocess.run([sys.executable, "-m", "ai_eval", "experiment", str(self.source),
            "--output", str(self.output), "--catalog", str(self.catalog)], cwd=outside,
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["conditions"][3]["status_counts"], {"ok": 8})
        page = subprocess.run([sys.executable, "-m", "ai_eval", "catalog-query", str(self.catalog),
            "--sql", "SELECT system_revision,mean FROM run_metrics ORDER BY system_revision", "--limit", "2"],
            cwd=outside, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(page.returncode, 0, page.stderr)
        self.assertEqual(json.loads(page.stdout)["next_offset"], 2)


if __name__ == "__main__":
    unittest.main()
