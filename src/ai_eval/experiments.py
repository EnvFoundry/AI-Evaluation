"""Execute declared conditions and analyses through the native evaluation core."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import uuid

from .analysis import _settings
from .contracts import _number, _object, _parse, _text, canonical_json, load_benchmark, load_run, system_id
from .engine import _RunLease, _atomic_json, run
from .studies import _resource_field


def _fields(value, required: set[str], optional: set[str], label: str) -> dict:
    _object(value, label)
    missing, extra = required - value.keys(), value.keys() - required - optional
    if missing or extra:
        raise ValueError(f"{label}: missing={sorted(missing)}, unknown={sorted(extra)}")
    return value


def _id(value, label: str) -> str:
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) or value in reserved:
        raise ValueError(f"{label} must be a lowercase filename identifier of 1–64 characters")
    return value


def load_plan(source: str | Path) -> dict:
    """Read and resolve a plan; file paths and command working directories are plan-relative."""
    path = Path(source).resolve(strict=True)
    plan = _parse(path.read_text(encoding="utf-8"), str(path))
    _fields(plan, {"schema_version", "name", "benchmark", "conditions", "analyses"},
            {"question", "execution"}, "experiment plan")
    if plan["schema_version"] != "1.0":
        raise ValueError("experiment plan schema_version must be '1.0'")
    _text(plan["name"], "name")
    if not isinstance(plan.get("question", ""), str):
        raise ValueError("question must be text")
    plan.setdefault("question", "")
    plan["benchmark"] = str((path.parent / _text(plan["benchmark"], "benchmark")).resolve(strict=True))
    benchmark = load_benchmark(plan["benchmark"])
    metric_names = {metric["name"] for metric in benchmark["metrics"]}
    execution = plan.setdefault("execution", {})
    _fields(execution, set(), {"workers", "timeout"}, "execution")
    execution.setdefault("workers", 1)
    execution.setdefault("timeout", 60.0)
    if type(execution["workers"]) is not int or execution["workers"] < 1:
        raise ValueError("execution.workers must be a positive integer")
    _number(execution["timeout"], "execution.timeout", positive=True)
    if not isinstance(plan["conditions"], list) or not plan["conditions"]:
        raise ValueError("conditions must be a nonempty array")
    names = []
    for condition in plan["conditions"]:
        _fields(condition, {"id", "system", "target"}, set(), "condition")
        name = _id(condition["id"], "condition.id")
        if name in names:
            raise ValueError(f"duplicate condition ID: {name}")
        names.append(name)
        system_id(condition["system"])
        target = condition["target"]
        _fields(target, set(), {"predictions", "command", "plugin", "config", "cwd"}, "target")
        if sum(key in target for key in ("predictions", "command", "plugin")) != 1:
            raise ValueError("target must specify exactly one of predictions, command or plugin")
        if "predictions" in target:
            if set(target) != {"predictions"}:
                raise ValueError("a prediction target only accepts predictions")
            target["predictions"] = str((path.parent / _text(target["predictions"], "predictions")).resolve(strict=True))
        elif "command" in target:
            if "config" in target:
                raise ValueError("target.config belongs to a plugin target")
            command = target["command"]
            if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command) or not command[0]:
                raise ValueError("target.command must be a nonempty argv array")
            cwd = (path.parent / _text(target.get("cwd", "."), "target.cwd")).resolve(strict=True)
            if not cwd.is_dir():
                raise ValueError("target.cwd must be a directory")
            target["cwd"] = str(cwd)
        else:
            _text(target["plugin"], "target.plugin")
            if "cwd" in target:
                raise ValueError("target.cwd belongs to a command target")
            _object(target.setdefault("config", {}), "target.config")
    if not isinstance(plan["analyses"], list) or not plan["analyses"]:
        raise ValueError("analyses must be a nonempty array")
    analysis_names = set()
    for analysis in plan["analyses"]:
        kind = analysis.get("kind") if isinstance(analysis, dict) else None
        optional = {"conditions", "missing", "slice_by"}
        if kind in ("study", "factorial"):
            optional |= {"confidence", "resamples", "seed"}
        if kind == "study":
            optional |= {"baseline", "resource"}
        if kind == "factorial":
            optional |= {"factor_a", "factor_b"}
        if kind not in ("study", "factorial", "benchmark"):
            raise ValueError("analysis.kind must be study, factorial or benchmark")
        _fields(analysis, {"id", "kind", "metric"}, optional, "analysis")
        name = _id(analysis["id"], "analysis.id")
        if name in analysis_names:
            raise ValueError(f"duplicate analysis ID: {name}")
        analysis_names.add(name)
        _text(analysis["metric"], "analysis.metric")
        if analysis["metric"] not in metric_names:
            raise ValueError(f"unknown analysis metric: {analysis['metric']}")
        selected = analysis.setdefault("conditions", list(names))
        if (not isinstance(selected, list) or not all(isinstance(item, str) for item in selected)
                or len(selected) != len(set(selected)) or not set(selected).issubset(names)):
            raise ValueError("analysis.conditions must be distinct declared condition IDs")
        if (kind == "factorial" and len(selected) != 4) or len(selected) < 2:
            raise ValueError("factorial needs four conditions in 00,10,01,11 order; other analyses need at least two")
        if analysis.setdefault("missing", "error") not in ("error", "complete_cases"):
            raise ValueError("analysis.missing must be error or complete_cases")
        if analysis.get("slice_by") is not None:
            _text(analysis["slice_by"], "analysis.slice_by")
        if kind in ("study", "factorial"):
            analysis.setdefault("confidence", .95)
            analysis.setdefault("resamples", 2000)
            analysis.setdefault("seed", 0)
            _settings(analysis["confidence"], analysis["resamples"], analysis["seed"])
        selected_systems = [system_id(next(condition["system"] for condition in plan["conditions"] if condition["id"] == name))
                            for name in selected]
        if kind == "benchmark" and len(selected_systems) != len(set(selected_systems)):
            raise ValueError("benchmark analysis needs distinct system descriptions")
        if kind == "study":
            if analysis.setdefault("baseline", selected[0]) not in selected:
                raise ValueError("analysis.baseline must name one of its conditions")
            _resource_field(analysis.get("resource"))
        elif kind == "factorial":
            _text(analysis.setdefault("factor_a", "A"), "factor_a")
            _text(analysis.setdefault("factor_b", "B"), "factor_b")
    return plan


def _target(description: dict, timeout: float):
    from .targets import CommandTarget, PredictionTarget, resolve_plugin
    if "predictions" in description:
        return PredictionTarget(description["predictions"])
    if "command" in description:
        return CommandTarget(description["command"], timeout=timeout, cwd=description["cwd"])
    return resolve_plugin(description["plugin"], description["config"])


def _condition_info(name: str, path: Path) -> dict:
    loaded = load_run(path)
    manifest, rows = loaded["manifest"], loaded["results"]
    return {"id": name, "run_id": manifest["run_id"], "path": str(path),
            "planned_trials": manifest["planned_trials"], "recorded_trials": len(rows),
            "status_counts": dict(Counter(row["status"] for row in rows))}


def _analyze(description: dict, paths: dict[str, Path]) -> dict:
    selected = [paths[name] for name in description["conditions"]]
    metric = description["metric"]
    common = {key: description[key] for key in ("confidence", "resamples", "seed", "missing", "slice_by") if key in description}
    if description["kind"] == "study":
        from .studies import compare_systems
        return compare_systems(selected, metric, baseline=description["conditions"].index(description["baseline"]),
                               resource=description.get("resource"), **common)
    if description["kind"] == "factorial":
        from .factorial import factorial
        return factorial(*selected, metric, factor_a=description["factor_a"], factor_b=description["factor_b"], **common)
    from .benchmarks import analyze_benchmark
    return analyze_benchmark(selected, metric, **common)


def _save_report(value: dict, destination: Path) -> None:
    from .report import write_report
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    write_report(value, temporary)
    temporary.replace(destination)


def run_experiment(source: str | Path, output: str | Path, *, resume: bool = False,
                   catalog: str | Path | None = None) -> dict:
    """Execute each condition, then the declared analyses; resume retains recorded attempts."""
    if type(resume) is not bool:
        raise ValueError("resume must be boolean")
    plan = load_plan(source)
    destination = Path(output).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "experiment.json"
    with _RunLease(destination):
        if resume:
            if not manifest_path.is_file():
                raise ValueError("experiment resume requires an existing experiment.json")
            manifest = _parse(manifest_path.read_text(encoding="utf-8"), str(manifest_path))
            if manifest.get("plan") != plan:
                raise ValueError("experiment resume requires the same resolved plan")
        else:
            if any(path.name != ".run.lock" for path in destination.iterdir()):
                raise ValueError("new experiment output must be empty; use resume for an existing experiment")
            manifest = {"schema_version": "1.0", "kind": "experiment", "experiment_id": uuid.uuid4().hex,
                        "name": plan["name"], "question": plan["question"], "path": str(destination),
                        "created_at": datetime.now(timezone.utc).isoformat(), "plan": plan,
                        "conditions": [], "analyses": []}
        manifest.update(status="running", path=str(destination))
        manifest.pop("error", None)
        manifest.pop("completed_at", None)
        manifest.pop("catalog_error", None)
        _atomic_json(manifest_path, manifest)
        paths = {condition["id"]: destination / "conditions" / condition["id"] for condition in plan["conditions"]}

        def index_completed():
            if catalog is not None:
                from .catalog import add_runs
                add_runs(catalog, [condition["path"] for condition in manifest["conditions"]], experiment=manifest)

        try:
            for condition in plan["conditions"]:
                name, path = condition["id"], paths[condition["id"]]
                run(plan["benchmark"], path, system=condition["system"],
                    target=_target(condition["target"], plan["execution"]["timeout"]),
                    workers=plan["execution"]["workers"], resume=(path / "manifest.json").exists())
                record = _condition_info(name, path)
                manifest["conditions"] = [item for item in manifest["conditions"] if item["id"] != name] + [record]
                _atomic_json(manifest_path, manifest)
                index_completed()
            for description in plan["analyses"]:
                value = _analyze(description, paths)
                analysis_path = destination / "analyses" / (description["id"] + ".json")
                analysis_path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_json(analysis_path, value)
                report_path = analysis_path.with_suffix(".html")
                _save_report(value, report_path)
                record = {"id": description["id"], "kind": description["kind"],
                          "json_path": str(analysis_path), "html_path": str(report_path)}
                manifest["analyses"] = [item for item in manifest["analyses"] if item["id"] != record["id"]] + [record]
                _atomic_json(manifest_path, manifest)
            manifest["status"] = "complete"
            manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_json(manifest_path, manifest)
            index_completed()
        except BaseException as exc:
            manifest["status"] = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "incomplete"
            manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
            _atomic_json(manifest_path, manifest)
            try:
                index_completed()
            except Exception as catalog_error:
                # A secondary indexing failure must not hide the interrupted operation.
                manifest["catalog_error"] = str(catalog_error)
                _atomic_json(manifest_path, manifest)
            raise
    result = {key: manifest[key] for key in ("experiment_id", "name", "status", "path", "conditions", "analyses")}
    result["manifest_path"] = str(manifest_path)
    if catalog is not None:
        result["catalog_path"] = str(Path(catalog).resolve())
    return result
