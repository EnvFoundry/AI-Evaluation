# Evaluation contracts

Schema version is `1.0`; package version is `0.3.0`. Python package: `ai_eval`; CLI: `ai-eval`.

## Benchmark

A JSON specification references UTF-8 JSONL samples relative to its directory:

```json
{
  "schema_version": "1.0",
  "name": "retrieval-study",
  "revision": "1",
  "description": "Compare retrieval on independent topics.",
  "samples": "samples.jsonl",
  "metrics": [{"name": "recall", "scorer": "recall_at_k", "direction": "maximize", "params": {"k": 5}}],
  "protocol": {"trials": 1, "seed": 17},
  "metadata": {}
}
```

Each sample has `id`, `input`, `target`, optional `group` (defaults to its ID), `slices` (scalar labels), positive finite `weight` (defaults to 1), and `metadata`. Inputs/targets retain JSON structure; modality artifacts can be referenced there. Group identifies the independent unit for statistical resampling, such as source document, task family, scene or experimental specimen. Trial numbering starts at zero. Metrics have unique names and a declared optimization direction. Benchmark identity follows the specification and sample content independently of the directory containing them.

`load_benchmark(path)` returns the specification, loaded `samples` and benchmark identity. `system_id(system)` identifies a system description containing `name`, `revision`, optional `kind`, and `config`. Model, harness, retrieval and generation configurations belong in that description.

## Execute

`run(benchmark_path, output, *, system, target, workers=1, resume=False)` calls `target(request)` for each sample/trial. A request contains `sample_id`, `input`, `trial`, `seed` and sample `metadata`; the target answer is supplied only to the scorer. Target response: `{"output": <JSON>, "usage": {}, "metadata": {}}`. A supplied target is responsible for its own external operation deadlines. The command adapter enforces a per-call deadline.

A run directory contains `manifest.json` and `results.jsonl`. The manifest records `schema_version`, `run_id`, `benchmark` (identity, `name`, `revision`, `protocol`, `metrics`), `system`, `system_id`, `planned_trials`, sample descriptors (`id`, `group`, `slices`, `weight`), and engine/runtime metadata. Each result records:

```json
{
  "schema_version": "1.0",
  "benchmark_id": "<id>",
  "system_id": "<id>",
  "sample_id": "topic-1",
  "group": "source-1",
  "slices": {"domain": "science"},
  "weight": 1,
  "trial": 0,
  "seed": 17,
  "status": "ok",
  "output": ["doc-1", "doc-3"],
  "scores": {"recall": 0.5},
  "errors": {},
  "elapsed_seconds": 0.02,
  "usage": {},
  "metadata": {}
}
```

Statuses: `ok`, `target_error`, `score_error`. Unavailable metric values are null. Target errors appear under `errors.target`; scorer errors under their metric names. Recorded outcomes are retained on resume, including failures. Resuming requires the same benchmark, system and execution contract; interrupted tasks without a complete durable record are issued again. A new experiment gets a new output directory.

`load_run(path)` returns `{"manifest": <dict>, "results": <list>}`. It validates benchmark/system IDs, unique `(sample_id, trial)` keys, declared metrics, finite values and membership in the manifest's sample/trial population. It can load a partial run; analysis reports coverage.

## Scoring

`ai_eval.metrics.score(metric_spec, output, target) -> float`. Native scorers: `exact_match`, `numeric`, `set_f1`, `token_f1`, `recall_at_k`, `ndcg_at_k`, `brier`, `log_loss`. `numeric` yields tolerance-based accuracy. Predictions and references are structured according to each scorer's guide. Installed scorer functions register in `ai_eval.scorers`; there is no universal score across unrelated metrics.

## Analysis

`summarize(run_path, metric, *, confidence=0.95, resamples=2000, seed=0, slice_by=None)` reports the weighted mean of per-sample means, sample/trial coverage, status counts, resource observations and optional slice results. For a partially scored sample its observed-trial mean is conditional on those trials completing; coverage remains explicit. Confidence intervals use percentile bootstrap of independent groups, keeping samples and attempts in each group together. A single independent group has no estimable interval.

`compare(left_path, right_path, metric, *, confidence=0.95, resamples=2000, seed=0, missing="error", slice_by=None)` reports right minus left on paired sample means. Native runs must share the same benchmark/protocol/metric contract. Default missing policy requires every planned trial scored for both runs. `missing="complete_cases"` retains only samples with complete scores for both systems and reports every exclusion. Bootstrap resamples paired independent groups. Direction-adjusted improvement is reported separately from raw score difference.

`pass_at_k(run_path, metric, k)` uses the unbiased estimator `1 - C(n-c,k)/C(n,k)` per sample for binary completed trials, requires all scheduled trials scored and `n >= k`, and averages with sample weights. It measures success among k attempts, not single-attempt accuracy or repeated-run reliability.

`compare_systems(run_paths, metric, *, baseline=0, resource=None, confidence=0.95, resamples=2000, seed=0, missing="error", slice_by=None)` in `ai_eval.studies` compares two or more unique runs on one common cohort. Baseline is the zero-based run index. Every retained sample has all planned scores in all runs and, when requested, every resource observation. `resource` is `elapsed_seconds` or `usage.FIELD`, with consistent units across runs. Scores and resources are means per attempt within each sample, then weighted across samples. Results include systems, paired baseline contrasts, pointwise intervals, coverage, exclusions, slices and the Pareto frontier of observed quality/resource means. Frontier ties remain included; frontier membership is descriptive.

`factorial(run_00, run_10, run_01, run_11, metric, *, factor_a="A", factor_b="B", confidence=0.95, resamples=2000, seed=0, missing="error", slice_by=None)` in `ai_eval.factorial` estimates two main effects, four simple effects and the full difference-of-differences interaction. All contrasts use the same complete cohort and paired groups. Results include named conditions, effects, their coefficients and raw and direction-adjusted intervals. [Factorial experiments](factorial-experiments.md) defines the conventions and interpretation.

`analyze_benchmark(run_paths, metric, *, missing="error", slice_by=None)` in `ai_eval.benchmarks` describes item behavior across at least two distinct systems on one shared cohort. Per-item results include panel means, ranges, population standard deviations, and item-rest Pearson correlation excluding the entire focal independent group. Correlation needs at least three systems and nonconstant item/rest scores. Optional metric `bounds: [lower, upper]` specifies finite endpoints for saturation. Native accuracy, F1, recall and nDCG supply known `[0,1]` bounds; observed zeros and ones alone do not establish the support of an unknown metric. Facility is the success fraction for binary outcomes on a maximizing `[0,1]` scale. Results include panel, samples, groups, slices, exclusions and reasons for undefined correlations. These are descriptive panel statistics. See [benchmark development](benchmark-development.md).

`report` writes JSON-backed HTML for summaries, comparisons, studies, factorial effects and benchmark profiles. It includes tables, relevant plots, sample filtering and the complete analysis for download. `report --analysis FILE` renders saved JSON; `analysis FILE --section summary` returns a compact overview, while other sections provide filtered pages.

## Interchange

Native prediction JSONL uses `sample_id`, optional `trial` (absence reuses that output for each trial), `output`, optional `usage` and `metadata`. Missing requested predictions are target errors.

Result importers produce the same run directory contract, retaining source format/revision, source identity and original metadata. Gym imports use export-v1 rows and preserve unscored statuses, task/data identity and rollout metadata. Inspect imports use JSON logs and explicit scorer/value selection. Aggregate-only result tables do not become invented sample observations. Imported populations must be aligned explicitly before paired comparisons.

Python, CLI and MCP share these functions. Installed targets and importers use `ai_eval.targets` and `ai_eval.importers` entry points. MCP returns bounded summaries and paginated samples; result payloads stay in files.

## Experiment plans and result catalog

[Experiments](experiments.md) defines plan schema `1.0`, condition execution/resume and SQLite tables/views. Plans and catalogs retain the existing run and analysis formats; SQL browsing does not change their pairing or weighting semantics.
