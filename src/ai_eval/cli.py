"""Command-line and small shared operations for evaluation hosts."""

from __future__ import annotations

import argparse
from collections import Counter
from importlib.metadata import entry_points
import json
from pathlib import Path
import sqlite3
import sys


NATIVE_SCORERS = ["exact_match", "numeric", "set_f1", "token_f1", "recall_at_k", "ndcg_at_k", "brier", "log_loss"]


def capabilities() -> dict:
    from . import __version__
    from .guidance import GUIDES
    return {"name": "AI Evaluation", "version": __version__, "schema_version": "1.0",
            "operations": ["benchmark", "run", "summarize", "compare", "study", "factorial", "analyze-benchmark",
                           "pass-at-k", "calibrate-judge", "samples", "analysis", "report", "guide", "import-gym", "import-inspect",
                           "experiment", "catalog-add", "catalog-runs", "catalog-query"],
            "targets": ["predictions-jsonl", "command-json", "entry-point"], "scorers": NATIVE_SCORERS,
            "imports": ["gym-export-v1", "inspect-json"],
            "plugins": {group: sorted(ep.name for ep in entry_points(group=group))
                        for group in ("ai_eval.scorers", "ai_eval.targets", "ai_eval.importers")},
            "analysis": "common-cohort system comparisons; resource frontiers; factorial effects; benchmark item analysis; group uncertainty",
            "guides": list(GUIDES),
            "execution": "local workers; external targets own their model or harness implementation"}


def benchmark_info(path: str | Path) -> dict:
    from .contracts import load_benchmark
    benchmark = load_benchmark(path)
    samples = benchmark["samples"]
    return {key: benchmark[key] for key in ("name", "revision", "metrics", "protocol")} | {
        "description": benchmark.get("description", ""), "samples": len(samples),
        "independent_groups": len({sample.get("group", sample["id"]) for sample in samples}),
        "slice_fields": sorted({key for sample in samples for key in sample.get("slices", {})})}


def run_info(path: str | Path) -> dict:
    from .contracts import load_run
    loaded = load_run(path)
    manifest, rows = loaded["manifest"], loaded["results"]
    return {"path": str(Path(path).resolve()), "run_id": manifest["run_id"],
            "benchmark_id": manifest["benchmark"]["id"], "system_id": manifest["system_id"],
            "planned_trials": manifest["planned_trials"], "recorded_trials": len(rows),
            "status_counts": dict(Counter(row["status"] for row in rows))}


def run_target(benchmark, output, *, system_name, system_revision, system_config=None,
               predictions=None, command=None, target_plugin=None, target_config=None,
               workers=1, resume=False, timeout=60.0):
    from .engine import run
    from .targets import CommandTarget, PredictionTarget, resolve_plugin
    if sum(value is not None for value in (predictions, command, target_plugin)) != 1:
        raise ValueError("choose exactly one of predictions, command or target_plugin")
    if system_config is not None and not isinstance(system_config, dict):
        raise ValueError("system config must be an object")
    if target_config is not None:
        if not isinstance(target_config, dict):
            raise ValueError("target config must be an object")
        if target_plugin is None:
            raise ValueError("target config requires a target plugin")
    if command is not None and (not isinstance(command, list) or not command or not command[0] or
                                not all(isinstance(arg, str) for arg in command)):
        raise ValueError("command must be an array of strings with a nonempty executable")
    if predictions is not None:
        target = PredictionTarget(predictions)
    elif command is not None:
        target = CommandTarget(command, timeout=timeout)
    else:
        target = resolve_plugin(target_plugin, target_config or {})
    system = {"name": system_name, "revision": system_revision, "config": system_config or {}}
    run(benchmark, output, system=system, target=target, workers=workers, resume=resume)
    return run_info(output)


def bounded_analysis(value: dict, *, limit: int = 20) -> dict:
    """Keep MCP responses small while retaining the number of omitted details."""
    def compact(item):
        if isinstance(item, list):
            return [compact(child) for child in item[:limit]]
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                if key == "samples" and isinstance(child, list):
                    result["sample_details"] = len(child)
                elif key in ("slices", "exclusions", "groups") and isinstance(child, list):
                    result[key + "_total"] = len(child)
                elif key in ("config", "system") and isinstance(child, dict):
                    # Full target configurations belong in the saved analysis.
                    result[key + "_available"] = True
                else:
                    result[key] = compact(child)
                    if isinstance(child, list):
                        result[key + "_total"] = len(child)
            return result
        return item

    result = compact(value)
    result.setdefault("sample_details", 0)
    result["available_sections"] = [key for key, child in value.items() if isinstance(child, (list, dict))]
    if isinstance(value.get("confusion"), dict):
        result["confusion"]["truncated"] = len(value["confusion"].get("labels", [])) > limit
    return result


def analysis_page(source, *, section="samples", offset=0, limit=20, search=None) -> dict:
    """Read one section of a saved analysis without loading every case into a host."""
    from .report import load_analysis
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("offset must be nonnegative and limit between 1 and 100")
    value = load_analysis(source)
    sections = ["summary"] + [key for key, rows in value.items() if isinstance(rows, (list, dict)) and key != "summary"]
    if section not in sections:
        raise ValueError(f"analysis section must be one of: {', '.join(sections)}")
    if search is not None and not isinstance(search, str):
        raise ValueError("search must be text")
    if section == "summary":
        return {"kind": value.get("kind", "analysis"), "section": section,
                "sections": sections, "summary": bounded_analysis(value)}
    rows = value[section]
    if isinstance(rows, dict):
        rows = [{"name": key, "value": row} for key, row in rows.items()]
    selected = [row for row in rows if not search or search.casefold() in json.dumps(row, ensure_ascii=False).casefold()]
    page = selected[offset:offset + limit]
    next_offset = offset + len(page)
    return {"kind": value.get("kind", "analysis"), "section": section, "sections": sections,
            "total": len(selected), "offset": offset, "limit": limit,
            "next_offset": next_offset if next_offset < len(selected) else None,
            "items": page}


def samples_page(path, *, offset=0, limit=20, status=None, sample_id=None,
                 slice_key=None, slice_value=None, include_output=False) -> dict:
    from .contracts import load_run
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("offset must be nonnegative and limit between 1 and 100")
    if status is not None and status not in ("ok", "target_error", "score_error"):
        raise ValueError("unknown result status")
    if slice_value is not None and type(slice_value) not in (str, int, float, bool):
        raise ValueError("slice value must be a JSON scalar")
    rows = load_run(path)["results"]
    selected = [row for row in rows if
                (status is None or row["status"] == status) and
                (sample_id is None or row["sample_id"] == sample_id) and
                (slice_key is None or slice_key in row.get("slices", {}) and
                 json.dumps(row["slices"][slice_key], allow_nan=False) == json.dumps(slice_value, allow_nan=False))]
    selected.sort(key=lambda row: (row["sample_id"], row["trial"]))
    page = []
    for row in selected[offset:offset + limit]:
        item = {key: row[key] for key in ("sample_id", "trial", "group", "slices", "weight", "status", "scores", "elapsed_seconds") if key in row}
        item["errors"] = {key: str(value)[:800] for key, value in row.get("errors", {}).items()}
        item["usage"] = row.get("usage", {})
        if include_output:
            payload = json.dumps(row.get("output"), ensure_ascii=False, allow_nan=False)
            item["output_preview"] = payload[:2000]
            item["output_truncated"] = len(payload) > 2000
        page.append(item)
    next_offset = offset + len(page)
    return {"total": len(selected), "offset": offset, "limit": limit,
            "next_offset": next_offset if next_offset < len(selected) else None, "items": page}


def _analysis_options(command, *, metric_required=True):
    command.add_argument("--metric", required=metric_required)
    command.add_argument("--confidence", type=float, default=0.95)
    command.add_argument("--resamples", type=int, default=2000)
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("--slice-by")
    command.add_argument("--json-output", type=Path)


def parser():
    from . import __version__
    result = argparse.ArgumentParser(prog="ai-eval", description="Construct, run and compare AI evaluations")
    result.add_argument("--version", action="version", version=__version__)
    sub = result.add_subparsers(dest="operation", required=True)
    sub.add_parser("capabilities", help="Discover operations, scorers and installed extensions")
    benchmark = sub.add_parser("benchmark", help="Inspect the benchmark contract and population")
    benchmark.add_argument("path", type=Path)
    experiment = sub.add_parser("experiment", help="Execute a declared set of conditions and analyses, with resumable runs")
    experiment.add_argument("plan", type=Path)
    experiment.add_argument("--output", type=Path, required=True)
    experiment.add_argument("--resume", action="store_true")
    experiment.add_argument("--catalog", type=Path, help="Index the experiment and recorded runs in SQLite")
    catalog_add = sub.add_parser("catalog-add", help="Insert or refresh native runs in a SQLite experiment catalog")
    catalog_add.add_argument("database", type=Path)
    catalog_add.add_argument("runs", nargs="+", type=Path)
    catalog_runs = sub.add_parser("catalog-runs", help="Find runs by benchmark, system, experiment and metric")
    catalog_runs.add_argument("database", type=Path)
    for name in ("benchmark", "system", "experiment", "metric"):
        catalog_runs.add_argument("--" + name)
    catalog_query = sub.add_parser("catalog-query", help="Read a page from a SQLite SELECT over experiments, samples or trials")
    catalog_query.add_argument("database", type=Path)
    catalog_query.add_argument("--sql", required=True)
    catalog_query.add_argument("--params", default="[]", help="Bound SQL parameters as a JSON array")
    for command in (catalog_runs, catalog_query):
        command.add_argument("--offset", type=int, default=0)
        command.add_argument("--limit", type=int, default=20)
    run = sub.add_parser("run", help="Evaluate predictions, a model/harness command or an installed target")
    run.add_argument("benchmark", type=Path)
    choice = run.add_mutually_exclusive_group(required=True)
    choice.add_argument("--predictions", type=Path)
    choice.add_argument("--command-json", help="Executable and arguments as a JSON array")
    choice.add_argument("--target-plugin", help="Installed ai_eval.targets entry-point name")
    run.add_argument("--target-config", help="Target factory configuration as JSON")
    run.add_argument("--system-name", required=True)
    run.add_argument("--system-revision", required=True)
    run.add_argument("--system-config", default="{}", help="Model/harness configuration as JSON")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--workers", type=int, default=1)
    run.add_argument("--timeout", type=float, default=60.0)
    run.add_argument("--resume", action="store_true")
    summary = sub.add_parser("summarize", help="Estimate a metric with group-aware uncertainty")
    summary.add_argument("run", type=Path)
    _analysis_options(summary)
    comparison = sub.add_parser("compare", help="Compare matched cases under the same protocol")
    comparison.add_argument("left", type=Path)
    comparison.add_argument("right", type=Path)
    comparison.add_argument("--missing", choices=("error", "complete_cases"), default="error")
    _analysis_options(comparison)
    study = sub.add_parser("study", help="Compare systems on one shared population and a resource-quality frontier")
    study.add_argument("runs", nargs="+", type=Path)
    study.add_argument("--baseline", type=int, default=0, help="Zero-based baseline index in the run list")
    study.add_argument("--resource", help="elapsed_seconds or usage.FIELD, measured per attempt")
    study.add_argument("--missing", choices=("error", "complete_cases"), default="error")
    study.add_argument("--html-output", type=Path)
    _analysis_options(study)
    factorial = sub.add_parser("factorial", help="Estimate component effects and interaction from four matched conditions")
    factorial.add_argument("runs", nargs=4, type=Path, metavar="RUN", help="Conditions in 00, 10, 01, 11 order")
    factorial.add_argument("--factor-a", default="A")
    factorial.add_argument("--factor-b", default="B")
    factorial.add_argument("--missing", choices=("error", "complete_cases"), default="error")
    factorial.add_argument("--html-output", type=Path)
    _analysis_options(factorial)
    development = sub.add_parser("analyze-benchmark", help="Study item variation and group-excluded discrimination across systems")
    development.add_argument("runs", nargs="+", type=Path)
    development.add_argument("--metric", required=True)
    development.add_argument("--missing", choices=("error", "complete_cases"), default="error")
    development.add_argument("--slice-by")
    development.add_argument("--json-output", type=Path)
    development.add_argument("--html-output", type=Path)
    passk = sub.add_parser("pass-at-k", help="Estimate success within k attempts for binary outcomes")
    passk.add_argument("run", type=Path)
    passk.add_argument("--metric", required=True)
    passk.add_argument("--k", required=True, type=int)
    calibrate = sub.add_parser("calibrate-judge", help="Compare categorical judge labels with reference judgments")
    calibrate.add_argument("path", type=Path)
    calibrate.add_argument("--labels", help="Ordered categorical labels as a JSON array")
    calibrate.add_argument("--group-key", default="group")
    calibrate.add_argument("--confidence", type=float, default=0.95)
    calibrate.add_argument("--resamples", type=int, default=2000)
    calibrate.add_argument("--seed", type=int, default=0)
    calibrate.add_argument("--json-output", type=Path)
    sample = sub.add_parser("samples", help="Read a bounded page of recorded trials")
    sample.add_argument("run", type=Path)
    sample.add_argument("--offset", type=int, default=0)
    sample.add_argument("--limit", type=int, default=20)
    sample.add_argument("--status", choices=("ok", "target_error", "score_error"))
    sample.add_argument("--sample-id")
    sample.add_argument("--slice-key")
    sample.add_argument("--slice-value", help="JSON scalar value")
    sample.add_argument("--include-output", action="store_true")
    analysis = sub.add_parser("analysis", help="Read a filtered page of a saved analysis")
    analysis.add_argument("source", type=Path)
    analysis.add_argument("--section", default="samples")
    analysis.add_argument("--offset", type=int, default=0)
    analysis.add_argument("--limit", type=int, default=20)
    analysis.add_argument("--search")
    guide = sub.add_parser("guide", help="Read concise guidance for the current research task")
    guide.add_argument("topic", nargs="?", default="experimental-design")
    report = sub.add_parser("report", help="Write a self-contained interactive HTML analysis")
    report.add_argument("run", nargs="?", type=Path)
    report.add_argument("--analysis", type=Path, help="Render an already computed analysis JSON")
    report.add_argument("--against", type=Path, help="Right-hand candidate run; run is the left baseline")
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--title")
    report.add_argument("--missing", choices=("error", "complete_cases"), default="error")
    _analysis_options(report, metric_required=False)
    gym = sub.add_parser("import-gym", help="Import Gym export-v1 observed outcomes")
    gym.add_argument("source", type=Path)
    gym.add_argument("--output", type=Path, required=True)
    gym.add_argument("--system-name", required=True)
    gym.add_argument("--system-revision", required=True)
    gym.add_argument("--benchmark-name", required=True)
    gym.add_argument("--revision", default="1")
    inspect = sub.add_parser("import-inspect", help="Import explicit sample scores from an Inspect JSON log")
    inspect.add_argument("source", type=Path)
    inspect.add_argument("--output", type=Path, required=True)
    inspect.add_argument("--scorer", required=True)
    inspect.add_argument("--value-key")
    inspect.add_argument("--direction", choices=("maximize", "minimize"), default="maximize")
    connect = sub.add_parser("connect", help="Write MCP configuration for this installed interpreter")
    connect.add_argument("--root", type=Path, default=Path.cwd())
    connect.add_argument("--output", type=Path, required=True)
    serve = sub.add_parser("serve", help="Start the MCP stdio service")
    serve.add_argument("--root", type=Path, default=Path.cwd())
    return result


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def main(argv=None):
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.operation == "capabilities":
            value = capabilities()
        elif args.operation == "benchmark":
            value = benchmark_info(args.path)
        elif args.operation == "experiment":
            from .experiments import run_experiment
            value = run_experiment(args.plan, args.output, resume=args.resume, catalog=args.catalog)
        elif args.operation == "catalog-add":
            from .catalog import add_runs
            value = add_runs(args.database, args.runs)
        elif args.operation == "catalog-runs":
            from .catalog import list_runs
            value = list_runs(args.database, benchmark=args.benchmark, system=args.system,
                              experiment=args.experiment, metric=args.metric, offset=args.offset, limit=args.limit)
        elif args.operation == "catalog-query":
            from .catalog import query
            value = query(args.database, args.sql, params=json.loads(args.params), offset=args.offset, limit=args.limit)
        elif args.operation == "run":
            value = run_target(args.benchmark, args.output, system_name=args.system_name,
                               system_revision=args.system_revision, system_config=json.loads(args.system_config),
                               predictions=args.predictions,
                               command=json.loads(args.command_json) if args.command_json else None,
                               target_plugin=args.target_plugin,
                               target_config=json.loads(args.target_config) if args.target_config is not None else None,
                               workers=args.workers, resume=args.resume, timeout=args.timeout)
        elif args.operation == "report" and args.analysis is not None:
            if args.run is not None or args.against is not None or args.metric is not None:
                raise ValueError("--analysis renders saved results; omit run, --against and --metric")
            from .report import load_analysis, write_report
            value = write_report(load_analysis(args.analysis), args.output, title=args.title)
        elif args.operation in ("summarize", "compare", "report"):
            from .analysis import compare, summarize
            if args.operation == "report" and (args.run is None or args.metric is None):
                raise ValueError("report requires a run and --metric, or --analysis")
            options = {key: getattr(args, key) for key in ("confidence", "resamples", "seed", "slice_by")}
            if args.operation == "compare":
                value = compare(args.left, args.right, args.metric, missing=args.missing, **options)
            elif args.operation == "report" and args.against is not None:
                value = compare(args.run, args.against, args.metric, missing=args.missing, **options)
            else:
                value = summarize(args.run, args.metric, **options)
            if args.json_output is not None:
                _write_json(args.json_output, value)
            if args.operation == "report":
                from .report import write_report
                value = write_report(value, args.output, title=args.title)
        elif args.operation in ("study", "factorial", "analyze-benchmark"):
            if args.operation == "analyze-benchmark":
                from .benchmarks import analyze_benchmark
                value = analyze_benchmark(args.runs, args.metric, missing=args.missing, slice_by=args.slice_by)
            else:
                options = {key: getattr(args, key) for key in ("confidence", "resamples", "seed", "slice_by", "missing")}
                if args.operation == "study":
                    from .studies import compare_systems
                    value = compare_systems(args.runs, args.metric, baseline=args.baseline, resource=args.resource, **options)
                else:
                    from .factorial import factorial
                    value = factorial(*args.runs, args.metric, factor_a=args.factor_a, factor_b=args.factor_b, **options)
            if args.json_output is not None:
                _write_json(args.json_output, value)
            if args.html_output is not None:
                from .report import write_report
                report = write_report(value, args.html_output)
                value = dict(value, report=report)
        elif args.operation == "analysis":
            value = analysis_page(args.source, section=args.section, offset=args.offset, limit=args.limit, search=args.search)
        elif args.operation == "guide":
            from .guidance import get_guide
            value = get_guide(args.topic)
        elif args.operation == "pass-at-k":
            from .analysis import pass_at_k
            value = pass_at_k(args.run, args.metric, args.k)
        elif args.operation == "calibrate-judge":
            from .judgments import calibrate
            value = calibrate(args.path, labels=json.loads(args.labels) if args.labels is not None else None,
                              group_key=args.group_key, confidence=args.confidence,
                              resamples=args.resamples, seed=args.seed)
            if args.json_output is not None:
                _write_json(args.json_output, value)
        elif args.operation == "samples":
            value = samples_page(args.run, offset=args.offset, limit=args.limit, status=args.status,
                                 sample_id=args.sample_id, slice_key=args.slice_key,
                                 slice_value=json.loads(args.slice_value) if args.slice_value is not None else None,
                                 include_output=args.include_output)
        elif args.operation == "import-gym":
            from .importers import import_gym
            import_gym(args.source, args.output, system={"name": args.system_name, "revision": args.system_revision},
                       benchmark_name=args.benchmark_name, revision=args.revision)
            value = run_info(args.output)
        elif args.operation == "import-inspect":
            from .importers import import_inspect
            import_inspect(args.source, args.output, scorer=args.scorer, value_key=args.value_key,
                           direction=args.direction)
            value = run_info(args.output)
        elif args.operation == "connect":
            from importlib.util import find_spec
            if find_spec("mcp") is None:
                raise ValueError('Install MCP support with python -m pip install ".[mcp]"')
            root = args.root.resolve(strict=True)
            if not root.is_dir():
                raise ValueError("MCP root must be a directory")
            configuration = {"mcpServers": {"ai-evaluation": {
                "command": sys.executable, "args": ["-m", "ai_eval", "serve", "--root", str(root)]}}}
            _write_json(args.output, configuration)
            value = {"path": str(args.output.resolve()), "root": str(root)}
        elif args.operation == "serve":
            from .mcp_server import create_server
            create_server(args.root).run(transport="stdio")
            return 0
        else:
            raise ValueError("unknown operation")
        print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
