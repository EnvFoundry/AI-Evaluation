import asyncio
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from ai_eval.report import write_report


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture(root):
    samples = [{"id": f"s{i}", "input": {"value": i}, "target": i,
                "group": f"g{i // 2}", "slices": {"domain": "even" if i % 2 == 0 else "odd"}}
               for i in range(4)]
    (root / "samples.jsonl").write_text("".join(json.dumps(row) + "\n" for row in samples), encoding="utf-8")
    write_json(root / "benchmark.json", {"schema_version": "1.0", "name": "interface-study", "revision": "1",
        "samples": "samples.jsonl", "metrics": [{"name": "accuracy", "scorer": "exact_match", "direction": "maximize"}],
        "protocol": {"trials": 2, "seed": 17}})
    for name in ("baseline", "candidate"):
        rows = [{"sample_id": f"s{i}", "output": i if name == "candidate" or i % 2 == 0 else -1,
                 "usage": {"calls": 2 if name == "candidate" else 1}} for i in range(4)]
        (root / f"{name}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    write_json(root / "inspect.json", {"version": 2, "eval": {"task": "latency-study", "model": "recorded-model",
        "config": {"epochs": 1}}, "samples": [{"id": "a", "epoch": 1, "input": "x", "target": "y",
        "scores": {"latency": {"value": 0.25}}}]})
    judgments = [{"id": f"j{i}", "group": f"g{i // 2}", "reference": "pass" if i < 2 else "fail",
                  "judge": "pass" if i % 2 == 0 else "fail"} for i in range(4)]
    (root / "judgments.jsonl").write_text("".join(json.dumps(row) + "\n" for row in judgments), encoding="utf-8")


def plugin_environment(root):
    """Expose an installed-distribution fixture to real entry-point discovery."""
    package = root / "plugin-site"
    package.mkdir()
    (package / "interface_target.py").write_text(
        'def create(config):\n'
        '    offset = config.get("offset", 0)\n'
        '    def target(request):\n'
        '        return {"output": request["input"]["value"] + offset}\n'
        '    return target\n', encoding="utf-8")
    metadata = package / "interface_target-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: interface-target\nVersion: 1.0\n", encoding="utf-8")
    (metadata / "entry_points.txt").write_text(
        "[ai_eval.targets]\nai_eval_interface_echo = interface_target:create\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package) + (os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else "")
    return environment


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "outside-project"
        self.work.mkdir()
        fixture(self.root)

    def cli(self, *args, success=True, env=None):
        result = subprocess.run([sys.executable, "-m", "ai_eval", *map(str, args)], cwd=self.work,
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        return json.loads(result.stderr)

    def run_fixture(self, name, *extra):
        return self.cli("run", self.root / "benchmark.json", "--predictions", self.root / f"{name}.jsonl",
                        "--system-name", name, "--system-revision", "1", "--output", self.root / name, *extra)

    def test_cli_run_pair_compare_report_and_resume_from_another_directory(self):
        capabilities = self.cli("capabilities")
        self.assertIn("recall_at_k", capabilities["scorers"])
        benchmark = self.cli("benchmark", self.root / "benchmark.json")
        self.assertEqual(benchmark["samples"], 4)
        self.assertEqual(benchmark["independent_groups"], 2)
        baseline = self.run_fixture("baseline", "--workers", 2)
        self.run_fixture("candidate")
        before = (self.root / "baseline/results.jsonl").read_bytes()
        self.assertEqual(self.run_fixture("baseline", "--resume")["run_id"], baseline["run_id"])
        self.assertEqual((self.root / "baseline/results.jsonl").read_bytes(), before)
        self.assertEqual(baseline["status_counts"], {"ok": 8})
        summary = self.cli("summarize", self.root / "baseline", "--metric", "accuracy", "--resamples", 100,
                           "--slice-by", "domain")
        self.assertEqual(summary["mean"], 0.5)
        self.assertEqual(len(summary["slices"]), 2)
        comparison_path = self.root / "comparison.json"
        comparison = self.cli("compare", self.root / "baseline", self.root / "candidate", "--metric", "accuracy",
                              "--resamples", 100, "--json-output", comparison_path)
        self.assertEqual(comparison["delta"], 0.5)
        self.assertEqual(comparison["interval"]["independent_groups"], 2)
        self.assertEqual(json.loads(comparison_path.read_text()), comparison)
        report = self.cli("report", self.root / "baseline", "--against", self.root / "candidate", "--metric", "accuracy",
                          "--resamples", 100, "--output", self.root / "report.html")
        document = Path(report["path"]).read_text()
        embedded = re.search(r'<script id="analysis" type="application/json">(.*?)</script>', document, re.S)[1]
        self.assertEqual(json.loads(embedded), comparison)
        self.assertGreater(report["bytes"], 5000)

    def test_command_adapter_and_paginated_trial_details(self):
        solver = self.root / "solver.py"
        solver.write_text('import json,sys\nr=json.load(sys.stdin)\nassert "target" not in r\n'
                          'print(json.dumps({"output":r["input"]["value"],"usage":{"calls":1}}))\n', encoding="utf-8")
        run = self.cli("run", self.root / "benchmark.json", "--command-json", json.dumps([sys.executable, str(solver)]),
                       "--system-name", "echo", "--system-revision", "1", "--output", self.root / "command")
        self.assertEqual(run["status_counts"], {"ok": 8})
        page = self.cli("samples", self.root / "command", "--limit", 2, "--slice-key", "domain",
                        "--slice-value", '"odd"', "--include-output")
        self.assertEqual(page["total"], 4)
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual([row["sample_id"] for row in page["items"]], ["s1", "s1"])
        self.assertEqual(page["items"][0]["output_preview"], "1")
        self.assertFalse(page["items"][0]["output_truncated"])
        passk = self.cli("pass-at-k", self.root / "command", "--metric", "accuracy", "--k", 2)
        self.assertEqual(passk["estimate"], 1)

    def test_import_preserves_explicit_metric_direction(self):
        result = self.cli("import-inspect", self.root / "inspect.json", "--output", self.root / "imported",
                          "--scorer", "latency", "--direction", "minimize")
        self.assertEqual(result["recorded_trials"], 1)
        summary = self.cli("summarize", self.root / "imported", "--metric", "latency", "--resamples", 20)
        self.assertEqual(summary["direction"], "minimize")
        self.assertEqual(summary["mean"], 0.25)

    def test_installed_target_factory_config_reaches_cli_and_resume_identity(self):
        environment = plugin_environment(self.root)
        discovered = self.cli("capabilities", env=environment)
        self.assertIn("ai_eval_interface_echo", discovered["plugins"]["ai_eval.targets"])
        arguments = ("run", self.root / "benchmark.json", "--target-plugin", "ai_eval_interface_echo",
                     "--system-name", "plugin", "--system-revision", "1", "--output", self.root / "plugin")
        result = self.cli(*arguments, "--target-config", '{"offset":1}', env=environment)
        self.assertEqual(result["recorded_trials"], 8)
        summary = self.cli("summarize", self.root / "plugin", "--metric", "accuracy", "--resamples", 20)
        self.assertEqual(summary["mean"], 0)
        error = self.cli(*arguments, "--target-config", '{"offset":0}', "--resume", success=False, env=environment)
        self.assertIn("error", error)

    def test_judge_calibration_uses_recorded_reference_labels(self):
        destination = self.root / "calibration.json"
        result = self.cli("calibrate-judge", self.root / "judgments.jsonl", "--labels", '["pass","fail"]',
                          "--resamples", 100, "--json-output", destination)
        self.assertEqual(result["agreement"], 0.5)
        self.assertEqual(result["kappa"], 0)
        self.assertEqual(result["confusion"]["rows"], [[1, 1], [1, 1]])
        self.assertEqual(json.loads(destination.read_text()), result)

    def test_cli_reports_contract_failure_as_json(self):
        self.run_fixture("baseline")
        error = self.cli("samples", self.root / "baseline", "--limit", 101, success=False)
        self.assertIn("limit", error["error"])
        error = self.cli("run", self.root / "benchmark.json", "--command-json", '["python"]',
                         "--system-name", "bad", "--system-revision", "1", "--system-config", '[]',
                         "--output", self.root / "bad", success=False)
        self.assertIn("config", error["error"])

    def test_research_commands_share_saved_results_and_selective_reading(self):
        self.run_fixture("baseline")
        self.run_fixture("candidate")
        for name in ("with-b", "with-ab"):
            self.cli("run", self.root / "benchmark.json", "--predictions", self.root / "candidate.jsonl",
                     "--system-name", name, "--system-revision", "1", "--output", self.root / name)
        runs = [self.root / name for name in ("baseline", "candidate", "with-b", "with-ab")]
        study = self.cli("study", *runs, "--metric", "accuracy", "--resource", "usage.calls",
                         "--resamples", 30, "--slice-by", "domain", "--json-output", self.root / "study.json",
                         "--html-output", self.root / "study.html")
        self.assertEqual([system["mean"] for system in study["systems"]], [.5, 1, 1, 1])
        self.assertEqual([system["resource_mean"] for system in study["systems"]], [1, 2, 2, 2])
        self.assertEqual(study["pareto_frontier"], [0, 1, 2, 3])
        effects = self.cli("factorial", *runs, "--metric", "accuracy", "--factor-a", "retrieval",
                           "--factor-b", "memory", "--resamples", 30, "--json-output", self.root / "effects.json")
        self.assertEqual(effects["effects"]["interaction"]["estimate"], -.5)
        overview = self.cli("analysis", self.root / "effects.json", "--section", "summary")
        self.assertNotIn("samples", overview["summary"])
        self.assertEqual(overview["summary"]["sample_details"], 4)
        selected = self.cli("analysis", self.root / "effects.json", "--section", "effects", "--search", "interaction")
        self.assertEqual(selected["items"][0]["value"]["estimate"], -.5)
        first = self.cli("analysis", self.root / "study.json", "--limit", 2)
        second = self.cli("analysis", self.root / "study.json", "--offset", first["next_offset"], "--limit", 2)
        self.assertIsNone(second["next_offset"])
        self.assertEqual([row["sample_id"] for row in first["items"] + second["items"]], ["s0", "s1", "s2", "s3"])
        items = self.cli("analyze-benchmark", *runs, "--metric", "accuracy", "--json-output", self.root / "items.json")
        self.assertEqual(items["summary"]["ceiling_samples"], 2)
        report = self.cli("report", "--analysis", self.root / "items.json", "--output", self.root / "items.html")
        document = Path(report["path"]).read_text(encoding="utf-8")
        embedded = re.search(r'<script id="analysis" type="application/json">(.*?)</script>', document, re.S)[1]
        self.assertEqual(json.loads(embedded), items)
        guide = self.cli("guide", "factorial-experiments")
        self.assertIn("difference of differences", guide["content"])
        error = self.cli("analysis", self.root / "study.json", "--section", "absent", success=False)
        self.assertIn("section", error["error"])


class ReportTests(unittest.TestCase):
    def test_report_retains_exact_json_and_literal_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unicode.html"
            text = '</script><img src=x onerror="alert(1)"> & __TITLE__ __DATA__ 中文\u2028'
            analysis = {"metric": text, "mean": 1, "samples": [{"sample_id": text, "mean": 1}]}
            write_report(analysis, path, title="__DATA__ <research>")
            document = path.read_text(encoding="utf-8")
            embedded = re.search(r'<script id="analysis" type="application/json">(.*?)</script>', document, re.S)[1]
            self.assertEqual(json.loads(embedded), analysis)
            self.assertNotIn("<img", document)
            self.assertIn("<title>__DATA__ &lt;research&gt;</title>", document)
            with self.assertRaises(FileExistsError):
                write_report(analysis, path)


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional MCP SDK is not installed")
class MCPTests(unittest.TestCase):
    def test_real_stdio_session_uses_workspace_and_shared_analysis(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            environment = plugin_environment(root)
            outside = root / "outside-project"
            outside.mkdir()
            config_path = root / "mcp.json"
            configured = subprocess.run([sys.executable, "-m", "ai_eval", "connect", "--root", str(root),
                                         "--output", str(config_path)], cwd=outside, capture_output=True,
                                        text=True, encoding="utf-8", timeout=30)
            self.assertEqual(configured.returncode, 0, configured.stderr)
            configuration = json.loads(config_path.read_text())["mcpServers"]["ai-evaluation"]
            self.assertTrue(Path(configuration["command"]).is_absolute())
            many_labels = [{"id": f"label-{i:02}", "reference": f"class-{i:02}", "judge": f"class-{i:02}"} for i in range(28)]
            (root / "many-labels.jsonl").write_text("".join(json.dumps(row) + "\n" for row in many_labels), encoding="utf-8")

            async def exercise():
                parameters = StdioServerParameters(command=configuration["command"], args=configuration["args"],
                                                   cwd=outside, env=environment)
                async with stdio_client(parameters) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        names = {tool.name for tool in (await session.list_tools()).tools}
                        self.assertEqual(names, {"eval_capabilities", "eval_benchmark", "eval_run", "eval_summarize", "eval_compare",
                                                 "eval_import", "eval_samples", "eval_report", "eval_pass_at_k", "eval_calibrate_judge",
                                                 "eval_study", "eval_factorial", "eval_analyze_benchmark", "eval_analysis",
                                                 "eval_experiment", "eval_catalog_add", "eval_catalog_runs", "eval_catalog_query"})

                        resources = {str(resource.uri) for resource in (await session.list_resources()).resources}
                        self.assertEqual(resources, {f"evaluation://guides/{topic}" for topic in (
                            "experimental-design", "system-comparison", "factorial-experiments", "benchmark-development",
                            "experiment-plans", "experiment-catalog")})
                        guide = await session.read_resource("evaluation://guides/factorial-experiments")
                        self.assertIn("difference of differences", guide.contents[0].text)
                        prompts = {prompt.name for prompt in (await session.list_prompts()).prompts}
                        self.assertEqual(prompts, {"design_study", "develop_benchmark", "interpret_results", "plan_experiment", "find_experiments"})
                        prompt = await session.get_prompt("interpret_results", arguments={
                            "question": "Does retrieval help?", "analysis": "study.json"})
                        self.assertIn("Does retrieval help?", prompt.messages[0].content.text)

                        async def call(name, **arguments):
                            result = await session.call_tool(name, arguments)
                            self.assertFalse(result.isError, result.content)
                            return result.structuredContent or json.loads(result.content[0].text)

                        discovery = await call("eval_capabilities")
                        self.assertEqual(discovery["workspace"], str(root.resolve()))
                        self.assertIn("ai_eval_interface_echo", discovery["plugins"]["ai_eval.targets"])
                        self.assertEqual((await call("eval_benchmark", benchmark="benchmark.json"))["samples"], 4)
                        for name in ("baseline", "candidate"):
                            result = await call("eval_run", benchmark="benchmark.json", output=name, system_name=name,
                                                system_revision="1", predictions=f"{name}.jsonl")
                            self.assertEqual(result["recorded_trials"], 8)
                        plugin = await call("eval_run", benchmark="benchmark.json", output="plugin", system_name="plugin",
                                            system_revision="1", target_plugin="ai_eval_interface_echo", target_config={"offset": 0})
                        self.assertEqual(plugin["status_counts"], {"ok": 8})
                        self.assertEqual((await call("eval_summarize", run="plugin", metric="accuracy", resamples=20))["mean"], 1)
                        summary = await call("eval_summarize", run="baseline", metric="accuracy", resamples=100,
                                             output="summary.json")
                        self.assertEqual(summary["mean"], 0.5)
                        self.assertEqual(summary["sample_details"], 4)
                        self.assertNotIn("samples", summary)
                        self.assertEqual(len(json.loads((root / "summary.json").read_text())["samples"]), 4)
                        comparison = await call("eval_compare", left="baseline", right="candidate", metric="accuracy", resamples=100)
                        self.assertEqual(comparison["delta"], 0.5)
                        await call("eval_run", benchmark="benchmark.json", output="combined", system_name="combined",
                                   system_revision="1", predictions="candidate.jsonl")
                        study = await call("eval_study", runs=["baseline", "candidate", "combined"], metric="accuracy",
                                           resource="usage.calls", resamples=30, output="study.json")
                        self.assertEqual([item["mean"] for item in study["systems"]], [.5, 1, 1])
                        self.assertNotIn("samples", study)
                        effects = await call("eval_factorial", run_00="baseline", run_10="candidate", run_01="plugin",
                                             run_11="combined", metric="accuracy", resamples=30, output="effects.json")
                        self.assertEqual(effects["effects"]["interaction"]["estimate"], -.5)
                        items = await call("eval_analyze_benchmark", runs=["baseline", "candidate", "plugin"],
                                           metric="accuracy", output="items.json")
                        self.assertEqual(items["summary"]["ceiling_samples"], 2)
                        overview = await call("eval_analysis", source="effects.json", section="summary")
                        self.assertEqual(overview["summary"]["effects"]["interaction"]["estimate"], -.5)
                        analysis_page = await call("eval_analysis", source="items.json", search="s1", limit=1)
                        self.assertEqual(analysis_page["items"][0]["sample_id"], "s1")
                        report = await call("eval_report", analysis="study.json", output="reports/study.html")
                        self.assertTrue(Path(report["path"]).is_file())
                        page = await call("eval_samples", run="candidate", limit=3)
                        self.assertEqual(len(page["items"]), 3)
                        self.assertEqual(page["next_offset"], 3)
                        self.assertEqual((await call("eval_pass_at_k", run="candidate", metric="accuracy", k=2))["estimate"], 1)
                        report = await call("eval_report", run="baseline", against="candidate", metric="accuracy",
                                            output="reports/paired.html", resamples=100)
                        self.assertTrue(Path(report["path"]).is_file())
                        imported = await call("eval_import", source="inspect.json", output="imported", source_format="inspect",
                                              scorer="latency", direction="minimize")
                        self.assertEqual(imported["recorded_trials"], 1)
                        calibration = await call("eval_calibrate_judge", source="judgments.jsonl", labels=["pass", "fail"],
                                                 resamples=100, output="calibration.json")
                        self.assertEqual(calibration["agreement"], 0.5)
                        self.assertEqual(calibration["kappa"], 0)
                        self.assertNotIn("samples", calibration)
                        self.assertTrue((root / "calibration.json").is_file())
                        bounded = await call("eval_calibrate_judge", source="many-labels.jsonl", resamples=20,
                                             output="complete-calibration.json")
                        self.assertEqual(len(bounded["confusion"]["labels"]), 20)
                        self.assertEqual(bounded["confusion"]["labels_total"], 28)
                        self.assertTrue(bounded["confusion"]["truncated"])
                        self.assertTrue(all(len(row) == 20 for row in bounded["confusion"]["rows"]))
                        self.assertEqual(len(json.loads((root / "complete-calibration.json").read_text())["confusion"]["labels"]), 28)
                        plan = {"schema_version": "1.0", "name": "MCP study", "benchmark": "benchmark.json",
                            "conditions": [{"id": name, "system": {"name": name, "revision": "1"},
                                            "target": {"predictions": f"{name}.jsonl"}}
                                           for name in ("baseline", "candidate")],
                            "analyses": [{"id": "systems", "kind": "study", "metric": "accuracy", "resamples": 20}]}
                        write_json(root / "plan.json", plan)
                        experiment = await call("eval_experiment", plan="plan.json", output="planned", catalog="catalog.sqlite")
                        self.assertEqual(experiment["status"], "complete")
                        catalog = await call("eval_catalog_runs", catalog="catalog.sqlite", experiment=experiment["experiment_id"], limit=1)
                        self.assertEqual(catalog["total"], 2)
                        self.assertEqual(catalog["next_offset"], 1)
                        added = await call("eval_catalog_add", catalog="catalog.sqlite", runs=["candidate"])
                        self.assertEqual(added["runs"][0]["recorded_trials"], 8)
                        selected = await call("eval_catalog_query", catalog="catalog.sqlite",
                                              sql="SELECT count(*) AS trials FROM trials")
                        self.assertEqual(selected["items"], [{"trials": 24}])
                        error = await session.call_tool("eval_samples", {"run": "candidate", "limit": 101})
                        self.assertTrue(error.isError)
                        error = await session.call_tool("eval_benchmark", {"benchmark": "../benchmark.json"})
                        self.assertTrue(error.isError)

            asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
