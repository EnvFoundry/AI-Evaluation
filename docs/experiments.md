# Experiments and the local catalog

An experiment plan names the conditions to run and the comparisons that answer a research question. One command executes those conditions, retains their observations, calculates the declared analyses and writes portable reports. Its targets and analyses are the same implementations used by individual `run`, `study`, `factorial` and `analyze-benchmark` operations.

```sh
python examples/experiment_plan.py --output runs/planned-study
```

This example executes four lexical retrievers over an authored corpus, resumes the experiment without issuing completed attempts again, and queries the results through SQLite. It writes `plan.json`, the benchmark and target implementation, `experiment/conditions/`, `experiment/analyses/` and `catalog.sqlite`. The observed interaction is the same `1/3` recall improvement explained by the original retrieval example; it describes that constructed mechanism.

## Declare conditions and comparisons

A minimal two-condition plan looks like this:

```json
{
  "schema_version": "1.0",
  "name": "retrieval-revision-study",
  "question": "Does the revised retriever improve recall at the same query budget?",
  "benchmark": "cases/benchmark.json",
  "execution": {"workers": 2, "timeout": 60},
  "conditions": [
    {
      "id": "baseline",
      "system": {"name": "retriever", "revision": "baseline", "config": {"budget": 4}},
      "target": {"predictions": "baseline.jsonl"}
    },
    {
      "id": "candidate",
      "system": {"name": "retriever", "revision": "candidate", "config": {"budget": 4}},
      "target": {"predictions": "candidate.jsonl"}
    }
  ],
  "analyses": [
    {
      "id": "systems",
      "kind": "study",
      "metric": "recall",
      "baseline": "baseline",
      "resource": "usage.calls",
      "resamples": 2000,
      "seed": 17
    }
  ]
}
```

```sh
ai-eval experiment plan.json --output runs/retrieval-study --catalog runs/catalog.sqlite
ai-eval experiment plan.json --output runs/retrieval-study --catalog runs/catalog.sqlite --resume
```

Paths in the plan resolve relative to the plan file. Each condition has one target:

| Target | Declaration |
| --- | --- |
| Recorded predictions | `{"predictions": "candidate.jsonl"}` |
| Executable model or harness | `{"command": ["python", "target.py", "--mode", "candidate"], "cwd": "."}` |
| Installed target factory | `{"plugin": "research_model", "config": {"checkpoint": "model-v2"}}` |

Command targets run in the declared working directory, which also defaults to the plan directory. They consume the existing JSON request protocol. The execution timeout applies to each command call; plugin targets own their external deadlines. Python executable names depend on the host; the generated example records the actual interpreter path.

Condition IDs and analysis IDs are lowercase filename identifiers. System name, revision and full configuration describe the scientific condition, independently of its short filename. Model versions, harness settings, inference budgets and retrieval settings belong in this configuration. Benchmark analysis requires distinct system descriptions.

All analyses name a metric declared in the benchmark. `conditions` selects an ordered subset; omitting it selects all conditions in plan order.

| Kind | Additional fields | Result |
| --- | --- | --- |
| `study` | `baseline` condition ID, optional `resource` | Common-cohort comparison and optional observed quality/resource frontier |
| `factorial` | Exactly four conditions in **00, 10, 01, 11** order; optional `factor_a`, `factor_b` | Main and conditional effects, plus full difference-of-differences interaction |
| `benchmark` | At least two distinct systems | Case variation, saturation and group-excluded item–rest association |

All three accept `missing` (`error` by default or `complete_cases`) and `slice_by`. Study and factorial additionally accept `confidence`, `resamples` and `seed`. Their statistical interpretation is unchanged by orchestration; see [research methods](research.md).

Conditions execute in declared order, with the configured worker count within each condition. Shared-service drift or carry-over state calls for a separately designed randomized or counterbalanced experiment. A saved list of conditions does not itself randomize the intervention.

## Resume and inspect

`experiment.json` retains the resolved plan, condition/run links, progress and analysis paths. Each condition is an ordinary native run. A completed run remains readable by all existing operations; a report can be reconstructed from its saved analysis JSON.

Resume requires the same resolved plan and native execution contracts. It preserves completed observations, including recorded target/scoring failures, and issues attempts that have no complete durable record. Missing later conditions run normally. Analyses and reports are recomputed from the resulting observations. A changed condition or changed measurement gets a new output directory.

The command returns the experiment identity, concise per-condition progress and file paths. MCP limits long condition/analysis lists in this reply; the complete `manifest_path` can be read through `eval_analysis`, and catalog pages retrieve selected runs.

```python
from ai_eval.experiments import run_experiment

result = run_experiment("plan.json", "runs/retrieval-study", catalog="runs/catalog.sqlite")
resumed = run_experiment("plan.json", "runs/retrieval-study", resume=True)
```

## Find previous experiments

The SQLite catalog is a local index of recorded runs. It can accumulate unrelated research programs without collapsing their scores onto a common scale.

```sh
ai-eval catalog-add runs/catalog.sqlite runs/baseline runs/candidate
ai-eval catalog-runs runs/catalog.sqlite --benchmark retrieval --metric recall --limit 10
ai-eval catalog-runs runs/catalog.sqlite --system retriever --offset 10 --limit 10
```

`catalog-add` inserts or refreshes a snapshot atomically. Reimporting the same run does not duplicate trials. A run that was partial can be refreshed after more observations complete. Its original files remain authoritative; the catalog changes only when explicitly refreshed or updated by an experiment invocation. `--experiment ID` selects conditions belonging to one indexed experiment.

Each returned metric mean uses the analysis core's weighted average of **per-sample observed-trial means**. Coverage accompanies the number: planned, recorded and scored trials, complete samples and independent groups. A sample with more attempts receives no extra population weight. These run summaries are discovery information; use `study` or `compare` on the referenced runs for a matched cohort and uncertainty.

## Work directly in SQL

| Table/view | Unit and content |
| --- | --- |
| `experiments`, `experiment_runs` | Resolved plans, progress and named condition/run relationships |
| `runs` | One native run, benchmark/system identities and full manifest/configuration JSON |
| `metrics`, `run_metrics` | One run/metric definition, sample-weighted mean and coverage JSON |
| `samples` | One run/sample, independent group, weight, slices and planned attempts |
| `trials` | One run/sample/trial, status, resource observations and full result JSON |
| `scores` | One trial/metric; unavailable measurements remain SQL `NULL` |
| `sample_metrics` | Per-sample observed-trial mean, observed/scored trial counts and completeness |

```sh
ai-eval catalog-query runs/catalog.sqlite --sql "SELECT benchmark_name,system_name,system_revision,metric,mean,recorded_trials,planned_trials FROM run_metrics ORDER BY benchmark_name,system_name,system_revision" --limit 20
```

Use bound parameters for changing selections:

```python
from ai_eval.catalog import query

page = query(
    "runs/catalog.sqlite",
    "SELECT sample_id,mean,scored_trials,complete FROM sample_metrics "
    "WHERE run_id=? AND metric=? ORDER BY sample_id",
    params=[run_id, "recall"], limit=20,
)
```

SQL replies include columns, rows and `next_offset`, with up to 100 rows per page. Order the query explicitly when paging. Text cells longer than 4,000 characters return a preview and a `truncated_cells` entry; use SQLite `json_extract` or `substr` to request the relevant part. Queries are read-only and run for up to five seconds. The database can also be opened with an ordinary SQLite client for longer local analysis.

A SQL average over trial rows estimates a different quantity from the sample-weighted research analyses. Combining run means across benchmark revisions likewise changes the population. Keep those distinctions explicit in any custom query.

MCP exposes `eval_experiment`, `eval_catalog_add`, `eval_catalog_runs` and `eval_catalog_query`. The `experiment-plans` and `experiment-catalog` guide resources, and the `plan_experiment` and `find_experiments` prompts, provide task-specific starting points.
