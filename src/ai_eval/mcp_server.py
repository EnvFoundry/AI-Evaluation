"""A small stdio tool surface over the installed Python implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal


def create_server(root: str | Path):
    """Create the optional MCP service with paths relative to one workspace."""
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise ImportError('Install MCP support with python -m pip install ".[mcp]"') from exc

    from .analysis import compare, pass_at_k, summarize
    from .benchmarks import analyze_benchmark
    from .catalog import add_runs, list_runs, query
    from .cli import analysis_page, _write_json, benchmark_info, bounded_analysis, capabilities, run_info, run_target, samples_page
    from .factorial import factorial
    from .experiments import run_experiment
    from .guidance import GUIDES, get_guide, plan_experiment, find_experiments
    from .importers import import_gym, import_inspect
    from .report import load_analysis, write_report
    from .studies import compare_systems

    workspace = Path(root).resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError("MCP root must be a directory")

    def path(value: str) -> Path:
        candidate = Path(value)
        if candidate.is_absolute():
            raise ValueError("Use a path relative to the evaluation workspace")
        resolved = (workspace / candidate).resolve()
        if not resolved.is_relative_to(workspace):
            raise ValueError("Path must resolve within the evaluation workspace")
        return resolved

    def analysis_result(value: dict, output: str | None) -> dict:
        result = bounded_analysis(value)
        if output is not None:
            destination = path(output)
            _write_json(destination, value)
            result["analysis_path"] = str(destination)
        return result

    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
    execute = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
    server = FastMCP("AI Evaluation", log_level="WARNING", instructions=(
        "Start with the research question, task population and the system conditions being compared. "
        "Paths are relative to the configured evaluation workspace. Run outputs are new directories; "
        "resume preserves recorded outcomes. System name, revision and configuration identify the experiment. "
        "Analyses omit sample arrays; provide output to save complete JSON, then use eval_analysis "
        "for selected details or eval_report for offline HTML. eval_samples reads original trials. "
        "Research guides are resources under evaluation://guides/. Use study for system comparisons, "
        "factorial for crossed component changes, and analyze_benchmark for item behavior across systems."
        " Use eval_experiment to execute a saved plan and its analyses; use the catalog to find prior runs "
        "before loading individual samples. Catalog summaries retain each benchmark's measurement scale."
    ))

    @server.tool(annotations=read)
    def eval_capabilities() -> dict:
        """Discover operations, native scorers, import formats and installed entry points."""
        return capabilities() | {"workspace": str(workspace), "sample_page_limit": 100,
                                 "analysis_detail_limit": 20,
                                 "resources": [f"evaluation://guides/{topic}" for topic in GUIDES],
                                 "prompts": ["design_study", "develop_benchmark", "interpret_results", "plan_experiment", "find_experiments"]}

    @server.tool(annotations=read)
    def eval_benchmark(benchmark: str) -> dict:
        """Inspect benchmark identity, protocol, metrics, groups and slice fields."""
        return benchmark_info(path(benchmark))

    @server.tool(annotations=execute)
    def eval_experiment(plan: str, output: str, resume: bool = False, catalog: str | None = None) -> dict:
        """Execute a JSON plan's conditions and analyses; optionally index its runs in SQLite."""
        return bounded_analysis(run_experiment(path(plan), path(output), resume=resume,
                                               catalog=path(catalog) if catalog is not None else None))

    @server.tool(annotations=write)
    def eval_catalog_add(catalog: str, runs: list[str]) -> dict:
        """Insert or refresh native runs, preserving samples, individual trials and metric definitions."""
        return add_runs(path(catalog), [path(run) for run in runs])

    @server.tool(annotations=read)
    def eval_catalog_runs(catalog: str, benchmark: str | None = None, system: str | None = None,
                          experiment: str | None = None, metric: str | None = None,
                          offset: int = 0, limit: int = 20) -> dict:
        """Find runs with per-run sample-weighted means and explicit coverage; at most 100 rows."""
        return list_runs(path(catalog), benchmark=benchmark, system=system, experiment=experiment,
                         metric=metric, offset=offset, limit=limit)

    @server.tool(annotations=read)
    def eval_catalog_query(catalog: str, sql: str, params: list | None = None,
                           offset: int = 0, limit: int = 20) -> dict:
        """Read a bounded SELECT page from runs, metrics, samples, sample_metrics, trials or scores."""
        return query(path(catalog), sql, params=params, offset=offset, limit=limit)

    @server.tool(annotations=execute)
    def eval_run(benchmark: str, output: str, system_name: str, system_revision: str,
                 predictions: str | None = None, command: list[str] | None = None,
                 target_plugin: str | None = None, target_config: dict | None = None,
                 system_config: dict | None = None, workers: int = 1,
                 resume: bool = False, timeout: float = 60.0) -> dict:
        """Run predictions, explicit command argv or an installed target plugin; choose one."""
        return run_target(path(benchmark), path(output), system_name=system_name,
                          system_revision=system_revision, system_config=system_config,
                          predictions=path(predictions) if predictions is not None else None,
                          command=command, target_plugin=target_plugin, target_config=target_config,
                          workers=workers, resume=resume, timeout=timeout)

    @server.tool(annotations=write)
    def eval_summarize(run: str, metric: str, confidence: float = 0.95,
                       resamples: int = 2000, seed: int = 0, slice_by: str | None = None,
                       output: str | None = None) -> dict:
        """Estimate sample means and group-bootstrap intervals; optionally save full JSON."""
        value = summarize(path(run), metric, confidence=confidence, resamples=resamples,
                          seed=seed, slice_by=slice_by)
        return analysis_result(value, output)

    @server.tool(annotations=write)
    def eval_compare(left: str, right: str, metric: str, confidence: float = 0.95,
                     resamples: int = 2000, seed: int = 0, missing: Literal["error", "complete_cases"] = "error",
                     slice_by: str | None = None, output: str | None = None) -> dict:
        """Estimate paired right-minus-left differences with explicit missing-data policy."""
        value = compare(path(left), path(right), metric, confidence=confidence,
                        resamples=resamples, seed=seed, missing=missing, slice_by=slice_by)
        return analysis_result(value, output)

    @server.tool(annotations=write)
    def eval_study(runs: list[str], metric: str, baseline: int = 0, resource: str | None = None,
                   confidence: float = 0.95, resamples: int = 2000, seed: int = 0,
                   missing: Literal["error", "complete_cases"] = "error",
                   slice_by: str | None = None, output: str | None = None) -> dict:
        """Compare systems on one cohort with baseline contrasts and an optional quality-resource frontier."""
        value = compare_systems([path(run) for run in runs], metric, baseline=baseline, resource=resource,
                                confidence=confidence, resamples=resamples, seed=seed,
                                missing=missing, slice_by=slice_by)
        return analysis_result(value, output)

    @server.tool(annotations=write)
    def eval_factorial(run_00: str, run_10: str, run_01: str, run_11: str, metric: str,
                       factor_a: str = "A", factor_b: str = "B", confidence: float = 0.95,
                       resamples: int = 2000, seed: int = 0,
                       missing: Literal["error", "complete_cases"] = "error",
                       slice_by: str | None = None, output: str | None = None) -> dict:
        """Estimate two component effects, their simple effects and full difference-of-differences interaction."""
        value = factorial(path(run_00), path(run_10), path(run_01), path(run_11), metric,
                          factor_a=factor_a, factor_b=factor_b, confidence=confidence,
                          resamples=resamples, seed=seed, missing=missing, slice_by=slice_by)
        return analysis_result(value, output)

    @server.tool(annotations=write)
    def eval_analyze_benchmark(runs: list[str], metric: str,
                               missing: Literal["error", "complete_cases"] = "error",
                               slice_by: str | None = None, output: str | None = None) -> dict:
        """Study item variation, saturation and whole-group-excluded discrimination across distinct systems."""
        value = analyze_benchmark([path(run) for run in runs], metric, missing=missing, slice_by=slice_by)
        return analysis_result(value, output)

    @server.tool(annotations=write)
    def eval_import(source: str, output: str, source_format: Literal["gym", "inspect"],
                    scorer: str | None = None, value_key: str | None = None,
                    direction: Literal["maximize", "minimize"] = "maximize",
                    system_name: str | None = None, system_revision: str | None = None,
                    benchmark_name: str | None = None, revision: str = "1") -> dict:
        """Import Gym export-v1 or Inspect JSON sample observations into a native run."""
        source_path, destination = path(source), path(output)
        if source_format == "gym":
            if not system_name or not system_revision or not benchmark_name:
                raise ValueError("Gym import requires system_name, system_revision and benchmark_name")
            import_gym(source_path, destination, system={"name": system_name, "revision": system_revision},
                       benchmark_name=benchmark_name, revision=revision)
        elif source_format == "inspect":
            if not scorer:
                raise ValueError("Inspect import requires an explicit scorer")
            import_inspect(source_path, destination, scorer=scorer, value_key=value_key, direction=direction)
        else:
            raise ValueError("source_format must be gym or inspect")
        return run_info(destination)

    @server.tool(annotations=read)
    def eval_samples(run: str, offset: int = 0, limit: int = 20,
                     status: Literal["ok", "target_error", "score_error"] | None = None,
                     sample_id: str | None = None, slice_key: str | None = None,
                     slice_value: str | int | float | bool | None = None,
                     include_output: bool = False) -> dict:
        """Read up to 100 trials with filters; optional output previews stop at 2000 characters."""
        return samples_page(path(run), offset=offset, limit=limit, status=status,
                            sample_id=sample_id, slice_key=slice_key, slice_value=slice_value,
                            include_output=include_output)

    @server.tool(annotations=read)
    def eval_analysis(source: str, section: str = "samples", offset: int = 0, limit: int = 20,
                      search: str | None = None) -> dict:
        """Read saved analysis: section='summary' for overview, or paged samples, systems, effects and other sections."""
        return analysis_page(path(source), section=section, offset=offset, limit=limit, search=search)

    @server.tool(annotations=write)
    def eval_report(output: str, run: str | None = None, metric: str | None = None, against: str | None = None,
                    confidence: float = 0.95, resamples: int = 2000, seed: int = 0,
                    missing: Literal["error", "complete_cases"] = "error",
                    slice_by: str | None = None, title: str | None = None,
                    analysis: str | None = None) -> dict:
        """Write offline interactive HTML from saved analysis, or calculate a run summary/paired comparison."""
        if analysis is not None:
            if run is not None or metric is not None or against is not None:
                raise ValueError("analysis renders saved results; omit run, metric and against")
            value = load_analysis(path(analysis))
        else:
            if run is None or metric is None:
                raise ValueError("provide analysis, or run and metric")
            options = {"confidence": confidence, "resamples": resamples, "seed": seed, "slice_by": slice_by}
            value = (compare(path(run), path(against), metric, missing=missing, **options) if against is not None
                     else summarize(path(run), metric, **options))
        return write_report(value, path(output), title=title)

    @server.tool(annotations=write)
    def eval_pass_at_k(run: str, metric: str, k: int, output: str | None = None) -> dict:
        """Estimate success within k attempts from complete binary outcomes; optionally save JSON."""
        return analysis_result(pass_at_k(path(run), metric, k), output)

    @server.tool(annotations=write)
    def eval_calibrate_judge(source: str, labels: list[str] | None = None, group_key: str = "group",
                             confidence: float = 0.95, resamples: int = 2000, seed: int = 0,
                             output: str | None = None) -> dict:
        """Compare categorical judge labels to reference judgments; references are not assumed truth."""
        from .judgments import calibrate
        value = calibrate(path(source), labels=labels, group_key=group_key,
                          confidence=confidence, resamples=resamples, seed=seed)
        return analysis_result(value, output)

    def guide_resource(topic):
        def read_guide() -> str:
            guide = get_guide(topic)
            return f"# {guide['title']}\n\n{guide['content']}\n"
        return read_guide

    for topic, (title, _) in GUIDES.items():
        server.resource(f"evaluation://guides/{topic}", name=topic, title=title,
                        description=title, mime_type="text/markdown")(guide_resource(topic))

    server.prompt()(plan_experiment)
    server.prompt()(find_experiments)

    @server.prompt()
    def design_study(question: str, systems: str, population: str) -> str:
        """Turn a research question into a runnable evaluation with a defined outcome and comparison."""
        context = json.dumps({"question": question, "systems": systems, "population": population}, ensure_ascii=False)
        return ("Design and, when the required inputs are available, run this evaluation: " + context + "\n"
                "Read evaluation://guides/experimental-design. Identify the outcome, independent group, "
                "changed conditions and resource budget. Discover existing benchmarks and targets. "
                "Use eval_study for matched systems or eval_factorial for two crossed factors. "
                "Keep only assumptions that affect the scientific comparison. Save the analysis and explain "
                "the measured effect, uncertainty and population in ordinary language.")

    @server.prompt()
    def develop_benchmark(capability: str, population: str, reference_systems: str) -> str:
        """Construct or revise a benchmark around observable capability and reference-panel behavior."""
        context = json.dumps({"capability": capability, "population": population,
                              "reference_systems": reference_systems}, ensure_ascii=False)
        return ("Develop the benchmark described here: " + context + "\n"
                "Read evaluation://guides/benchmark-development. Connect task choices and scoring to the "
                "capability and population. Use existing compatible runs with eval_analyze_benchmark, "
                "or prepare the missing runs. Explain item variation and saturation through concrete cases. "
                "Treat panel-dependent correlations as descriptive. Propose revisions that improve the "
                "intended measurement and assess them on additional systems or held-out groups.")

    @server.prompt()
    def interpret_results(question: str, analysis: str) -> str:
        """Explain a saved analysis in relation to the original research question."""
        context = json.dumps({"question": question, "analysis": analysis}, ensure_ascii=False)
        return ("Interpret this recorded analysis: " + context + "\n"
                "Use eval_analysis with section='summary', then relevant systems, effects, slices and samples. "
                "Distinguish raw differences from direction-adjusted improvements, pointwise uncertainty "
                "from selection among systems, and completed-case results from the planned population. "
                "For a factorial study, connect main and simple effects to the interaction. Explain the "
                "conclusion that the measurements support and a concrete next experiment if a mechanism "
                "remains unresolved. Use eval_report for a complete portable view.")

    return server
