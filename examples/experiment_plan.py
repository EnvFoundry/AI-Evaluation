"""Run the lexical retrieval study from a portable plan and query its SQLite catalog.

Usage: python examples/experiment_plan.py [--output runs/planned-study]
The example executes authored algorithms, resumes the same experiment, and
reads recorded sample/condition measurements through SQL. No model API is used.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import tempfile

from research_study import cli, write_benchmark


def example(directory: Path) -> dict:
    write_benchmark(directory / "cases")
    (directory / "target.py").write_text(Path(__file__).with_name("research_study.py").read_text(encoding="utf-8"), encoding="utf-8")
    conditions = []
    for name, expansion, phrases in (("base", False, False), ("expansion", True, False),
                                     ("phrases", False, True), ("combined", True, True)):
        conditions.append({"id": name, "system": {"name": "lexical-retriever", "revision": name,
            "config": {"query_expansion": expansion, "phrase_reranking": phrases}},
            "target": {"command": [sys.executable, "target.py", "--target", "--expansion", str(int(expansion)),
                                    "--phrases", str(int(phrases))]}})
    plan = {"schema_version": "1.0", "name": "retrieval-component-study",
        "question": "Does query expansion help independently of phrase reranking?",
        "benchmark": "cases/benchmark.json", "execution": {"workers": 2, "timeout": 20}, "conditions": conditions,
        "analyses": [
            {"id": "systems", "kind": "study", "metric": "recall", "resource": "usage.token_comparisons",
             "baseline": "base", "slice_by": "variant", "resamples": 200},
            {"id": "effects", "kind": "factorial", "metric": "recall", "factor_a": "query_expansion",
             "factor_b": "phrase_reranking", "slice_by": "variant", "resamples": 200},
            {"id": "items", "kind": "benchmark", "metric": "recall", "slice_by": "variant"},
        ]}
    plan_path = directory / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    output, catalog = directory / "experiment", directory / "catalog.sqlite"
    result = cli("experiment", plan_path, "--output", output, "--catalog", catalog)
    before = [(Path(condition["path"]) / "results.jsonl").read_bytes() for condition in result["conditions"]]
    resumed = cli("experiment", plan_path, "--output", output, "--catalog", catalog, "--resume")
    if resumed != result or before != [(Path(condition["path"]) / "results.jsonl").read_bytes() for condition in result["conditions"]]:
        raise AssertionError("resuming must preserve the recorded runs and observations")
    rows = cli("catalog-query", catalog, "--sql",
        "SELECT system_revision,mean,recorded_trials FROM run_metrics WHERE metric='recall' ORDER BY system_revision")
    expected = {"base": 1 / 3, "expansion": 1 / 3, "phrases": 2 / 3, "combined": 1}
    for row in rows["items"]:
        if not math.isclose(row["mean"], expected[row["system_revision"]], abs_tol=1e-12) or row["recorded_trials"] != 18:
            raise AssertionError("catalog result must match the executed retrieval mechanism")
    effects = json.loads((output / "analyses/effects.json").read_text(encoding="utf-8"))
    return {"origin": "authored corpus; executed lexical algorithms", "plan": str(plan_path),
            "experiment": result, "recorded_results": rows["items"],
            "interaction": effects["effects"]["interaction"]["estimate"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.output is None:
        with tempfile.TemporaryDirectory(prefix="ai-evaluation-plan-") as temporary:
            result = example(Path(temporary))
        result["artifacts"] = "temporary; pass --output to retain the plan, runs, reports and catalog"
    else:
        directory = arguments.output.resolve()
        directory.mkdir(parents=True, exist_ok=False)
        result = example(directory)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
