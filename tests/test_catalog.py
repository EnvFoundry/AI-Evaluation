import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ai_eval.catalog import add_runs, list_runs, query
from ai_eval.engine import run


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        samples = [{"id": "a", "input": 0, "target": 1, "group": "g1", "weight": 9},
                   {"id": "b", "input": 1, "target": 1, "group": "g2", "weight": 1}]
        (self.root / "samples.jsonl").write_text("".join(json.dumps(row) + "\n" for row in samples), encoding="utf-8")
        (self.root / "benchmark.json").write_text(json.dumps({"schema_version": "1.0", "name": "weighted population",
            "revision": "1", "samples": "samples.jsonl", "protocol": {"trials": 2, "seed": 0},
            "metrics": [{"name": "accuracy", "scorer": "exact_match", "direction": "maximize"}]}), encoding="utf-8")
        self.run_path = self.root / "run"
        self.loaded = run(self.root / "benchmark.json", self.run_path, system={"name": "model", "revision": "1"},
                          target=lambda request: {"output": request["input"]})
        self.database = self.root / "catalog.sqlite"

    def test_partial_refresh_preserves_weighting_coverage_and_trial_rows(self):
        path = self.run_path / "results.jsonl"
        complete = path.read_bytes()
        rows = self.loaded["results"]
        partial = [row for row in rows if not (row["sample_id"] == "a" and row["trial"] == 1)]
        path.write_text("".join(json.dumps(row) + "\n" for row in partial), encoding="utf-8")
        add_runs(self.database, [self.run_path])
        page = list_runs(self.database)
        metric = page["items"][0]["metrics"][0]
        self.assertAlmostEqual(metric["mean"], .1)  # Not the trial-level mean 2/3.
        self.assertEqual(metric["coverage"]["complete_samples"], 1)
        self.assertEqual(metric["coverage"]["observed_trials"], 3)
        sql = "SELECT sample_id,scored_trials,complete FROM sample_metrics ORDER BY sample_id"
        self.assertEqual(query(self.database, sql)["items"], [
            {"sample_id": "a", "scored_trials": 1, "complete": 0},
            {"sample_id": "b", "scored_trials": 2, "complete": 1}])
        path.write_bytes(complete)
        add_runs(self.database, [self.run_path])
        add_runs(self.database, [self.run_path])
        self.assertEqual(query(self.database, "SELECT count(*) AS n FROM trials")["items"], [{"n": 4}])
        self.assertEqual(list_runs(self.database)["items"][0]["metrics"][0]["coverage"]["complete_samples"], 2)

    def test_filters_and_bound_parameters_preserve_numeric_values(self):
        add_runs(self.database, [self.run_path])
        self.assertEqual(list_runs(self.database, benchmark="weighted", system="MODEL", metric="accuracy")["total"], 1)
        self.assertEqual(list_runs(self.database, benchmark="unrelated")["total"], 0)
        first = query(self.database, "SELECT sample_id,trial,value FROM scores WHERE value >= ? ORDER BY sample_id,trial",
                      params=[1], limit=1)
        second = query(self.database, "SELECT sample_id,trial,value FROM scores WHERE value >= ? ORDER BY sample_id,trial",
                       params=[1], limit=1, offset=first["next_offset"])
        self.assertEqual(first["items"], [{"sample_id": "b", "trial": 0, "value": 1.0}])
        self.assertEqual(second["items"], [{"sample_id": "b", "trial": 1, "value": 1.0}])
        self.assertIsNone(second["next_offset"])

    def test_catalog_snapshot_is_atomic_and_rejects_reused_run_id_with_changed_manifest(self):
        add_runs(self.database, [self.run_path])
        manifest_path = self.run_path / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        changed = copy.deepcopy(manifest)
        changed["created_at"] = "changed"
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        second = self.root / "second"
        run(self.root / "benchmark.json", second, system={"name": "second", "revision": "1"},
            target=lambda request: {"output": 1})
        with self.assertRaisesRegex(ValueError, "different manifest"):
            add_runs(self.database, [second, self.run_path])
        self.assertEqual(query(self.database, "SELECT count(*) AS n FROM runs")["items"], [{"n": 1}])
        self.assertEqual(query(self.database, "SELECT count(*) AS n FROM scores")["items"], [{"n": 4}])
        self.assertEqual(query(self.database, "SELECT created_at FROM runs")["items"], [{"created_at": manifest["created_at"]}])

    def test_query_changes_no_rows_and_requires_clear_column_names(self):
        add_runs(self.database, [self.run_path])
        for sql in ("DELETE FROM trials", "SELECT 1; DELETE FROM trials", "SELECT x'0102' AS binary_value"):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                query(self.database, sql)
        self.assertEqual(query(self.database, "SELECT count(*) AS n FROM trials")["items"], [{"n": 4}])
        duplicate = query(self.database, "SELECT run_id,run_id FROM runs")
        self.assertEqual(len(duplicate["columns"]), 2)
        self.assertEqual(len(duplicate["items"][0]), 2)
        text = query(self.database, "SELECT printf('%.*c',5000,'a') AS long_text")
        self.assertEqual(len(text["items"][0]["long_text"]), 4000)
        self.assertEqual(text["truncated_cells"], [{"row": 0, "column": "long_text", "characters": 5000}])
        with self.assertRaisesRegex(ValueError, "limit"):
            list_runs(self.database, limit=101)

    def test_missing_catalog_is_not_created_by_read_operations(self):
        with self.assertRaises(sqlite3.OperationalError):
            list_runs(self.database)
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
