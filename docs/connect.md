# Connect a harness or research workspace

The Python API, command line and MCP server call the same runner, scorers and analysis functions. Model clients and agent harnesses remain responsible for generation and tool execution; AI Evaluation supplies experiment identity, trial records, scoring and comparisons.

## Install and discover

From a checkout:

```bash
python -m pip install -e ".[mcp]"
ai-eval capabilities
ai-eval benchmark examples/retrieval/benchmark.json
```

Core execution and reports use the Python standard library. The `mcp` extra adds the optional MCP SDK. `capabilities` reports installed versions, native operations and discovered entry-point names. It does not connect to a model provider.

## Planned experiments and TypeScript

`ai-eval experiment PLAN --output DIRECTORY --catalog catalog.sqlite` executes named conditions and existing analyses from one plan. Add `--resume` to reuse recorded outcomes. Catalog operations add existing runs, list conditions with filters, and query samples/trials through parameterized read queries. See [experiment plans](experiments.md) for the schema and runnable example.

The [TypeScript SDK](../sdk/typescript/README.md) provides typed methods for these operations and the original analysis interface. It runs the installed Python package with an argument array; environment selection, cancellation and process errors remain visible to the harness.

## Predictions and command targets

Prediction JSONL supplies recorded outputs, keyed by sample ID and optionally trial:

```json
{"sample_id":"q0","output":["doc-0","context-0"],"usage":{"input_tokens":120,"output_tokens":14}}
```

Without `trial`, the output is reused for every scheduled trial. This is useful for importing deterministic predictions; repeating an identical recorded answer does not create independent generation attempts. With `trial`, numbering starts at zero.

```bash
ai-eval run examples/retrieval/benchmark.json \
  --predictions examples/retrieval/baseline.jsonl \
  --system-name baseline --system-revision 1 \
  --system-config '{"retrieval":{"k":2}}' \
  --output runs/baseline

ai-eval summarize runs/baseline --metric recall --slice-by variant \
  --json-output reports/baseline.json
```

For a live model, tool-using agent, retriever or simulator, use the command target. `--command-json` is an executable and argument array, without shell interpretation:

```bash
ai-eval run examples/numeric/benchmark.json \
  --command-json '["python","examples/numeric/solver.py"]' \
  --system-name physical-parameter-solver --system-revision 1 \
  --workers 4 --timeout 30 --output runs/physics
```

Each trial starts one process. It receives one UTF-8 JSON request on stdin:

```json
{"sample_id":"lens-a","input":{"quantity":"focal_length","x":[2,3,4,5,6],"y":[8,7,6,5,4],"x_unit":"1/m","y_unit":"1/m"},"trial":0,"seed":17,"metadata":{}}
```

The process writes one JSON response to stdout and sends runtime messages to stderr:

```json
{"output":0.1,"usage":{"observations":5},"metadata":{"method":"centered-least-squares","quantity":"focal_length"}}
```

The request omits the reference answer. `input` may contain text, structured observations or artifact references. Pass the trial seed to the generation policy when supported, and record the model snapshot, sampling settings, harness revision and tool configuration in `--system-config`. The command inherits the caller's working directory and environment; use absolute script paths when a host launches from another directory. The timeout applies to each command invocation. Native Python targets own their own external-operation deadlines.

`--resume` preserves every complete recorded outcome, including failures, and schedules only unrecorded trials. It requires a matching benchmark, system and target contract. Use a new output directory for a changed experiment.

## Compare and inspect

```bash
ai-eval run examples/retrieval/benchmark.json \
  --predictions examples/retrieval/candidate.jsonl \
  --system-name candidate --system-revision 1 \
  --system-config '{"retrieval":{"k":2}}' --output runs/candidate

ai-eval compare runs/baseline runs/candidate --metric recall \
  --slice-by variant --resamples 2000 --seed 17 \
  --json-output reports/comparison.json

ai-eval samples runs/candidate --limit 20 --offset 0 \
  --slice-key variant --slice-value '"paraphrase"' --include-output

ai-eval report runs/baseline --against runs/candidate \
  --metric recall --slice-by variant --output reports/comparison.html
```

The paired difference is candidate minus baseline. `improvement` also accounts for a metric whose direction is `minimize`. The default comparison requires every planned trial to be scored in both runs. `--missing complete_cases` explicitly excludes incomplete samples and records their IDs and coverage; it changes the population being estimated.

The HTML file includes the complete analysis JSON, sortable sample rows, a text filter, pagination and a JSON download. It opens without a server or network connection. Report rendering does not recalculate scores or uncertainty. `--json-output` and report output paths create new files.

Use `ai-eval pass-at-k RUN --metric success --k 4` for completed binary success trials from a common sampling policy. The estimator and its assumptions are described in [contracts](contracts.md).

## Research studies

Compare several systems on one shared sample cohort, including a measured resource per attempt:

```bash
ai-eval study runs/base runs/expanded runs/reranked runs/combined \
  --metric recall --baseline 0 --resource usage.token_comparisons \
  --slice-by variant --json-output reports/study.json --html-output reports/study.html

ai-eval factorial runs/base runs/expanded runs/reranked runs/combined \
  --metric recall --factor-a query-expansion --factor-b phrase-reranking \
  --json-output reports/effects.json --html-output reports/effects.html

ai-eval analyze-benchmark runs/base runs/expanded runs/reranked runs/combined \
  --metric recall --slice-by variant --json-output reports/items.json

ai-eval analysis reports/effects.json --section summary
ai-eval analysis reports/items.json --section samples --search paraphrase --limit 10
ai-eval report --analysis reports/items.json --output reports/items.html
```

The factorial run order is `00, 10, 01, 11`. Study intervals and baseline contrasts use the same retained cohort and paired groups. Resource means describe attempts, not total experiment cost. The plotted Pareto frontier uses observed means; uncertainty remains visible alongside it. Benchmark analysis describes the chosen reference panel and excludes a sample's entire independent group from its item-rest correlation.

`analysis --section summary` returns a compact overview. Other sections page arrays or object entries, such as `systems`, `conditions`, `effects`, `samples`, `slices` and `exclusions`. Object entries use `name` and `value`; available sections are included in each reply. Search matches the recorded JSON text. Reports render saved analyses without rerunning a target or changing the estimates.

Run `python examples/research_study.py` for a complete authored retrieval experiment. The installed package also supplies task guidance through `ai-eval guide experimental-design`, `system-comparison`, `factorial-experiments` and `benchmark-development`.

## MCP

Generate configuration using the interpreter with MCP support installed:

```bash
ai-eval connect --root "$PWD" --output ai-evaluation.mcp.json
```

The resulting `mcpServers.ai-evaluation` entry launches the absolute Python executable with `-m ai_eval serve --root <absolute workspace>`. Copy that entry into your host's MCP server configuration. Hosts that configure servers through a UI can use the same command and arguments. The generated file is configuration; loading it is the host's responsibility.

The stdio server resolves data and result paths relative to `--root`, independently of the host's working directory. Commands passed to `eval_run` are explicit executable/argument arrays; their script paths follow the command's working-directory behavior described above.

| Tool | Purpose |
|---|---|
| `eval_capabilities` | Discover operations, installed extensions and response limits. |
| `eval_benchmark` | Read benchmark identity, protocol, metric definitions and population size. |
| `eval_experiment` | Execute or resume named conditions and analyses from a plan. |
| `eval_catalog_add` | Store existing runs in the local catalog. |
| `eval_catalog_runs` | Browse conditions, metrics and coverage through bounded pages. |
| `eval_catalog_query` | Read selected SQL columns/rows with parameters and a page limit. |
| `eval_run` | Execute predictions, a command or an installed target and return run identity and outcome counts. |
| `eval_summarize` | Return a metric estimate, group interval, coverage and slice overview. |
| `eval_compare` | Return a paired comparison with explicit missing-data treatment. |
| `eval_study` | Compare multiple systems on one cohort, with baseline contrasts and optional resource frontier. |
| `eval_factorial` | Estimate main effects, simple effects and interaction from four crossed conditions. |
| `eval_analyze_benchmark` | Describe item variation, saturation and group-excluded discrimination across a system panel. |
| `eval_import` | Import Gym export-v1 or Inspect JSON observations into the run contract. |
| `eval_samples` | Read filtered, paginated trial records. |
| `eval_analysis` | Read a compact overview or selected rows from a saved analysis. |
| `eval_report` | Write offline interactive HTML from saved analysis, a run summary or a paired comparison. |
| `eval_pass_at_k` | Estimate success within k attempts from complete binary trials. |
| `eval_calibrate_judge` | Compare categorical judge labels with reference judgments and inspect agreement. |

MCP analysis replies return primary estimates and coverage. Samples, slices, groups and exclusions appear as counts; full system configurations remain in the saved analysis. Other lists retain up to 20 entries with total counts. Supply `output` on analysis tools to save complete JSON. Use `eval_analysis(source=..., section="summary")` for an overview or another named section for selected details. Both `eval_analysis` and `eval_samples` default to 20 rows and accept up to 100. Trial output previews stop at 2,000 characters; full outputs remain in `results.jsonl`.

The server exposes six Markdown resources under `evaluation://guides/`: `experimental-design`, `system-comparison`, `factorial-experiments`, `benchmark-development`, `experiment-plans` and `experiment-catalog`. These work from an installed wheel as well as a checkout. Prompts connect a question to the tools; discovery lists their current names and arguments:

| Prompt | Arguments | Use |
|---|---|---|
| `design_study` | `question`, `systems`, `population` | Specify and execute a scientific comparison. |
| `develop_benchmark` | `capability`, `population`, `reference_systems` | Construct or revise a measurement using item behavior. |
| `interpret_results` | `question`, `analysis` | Explain a recorded analysis and its relevant observations. |
| `plan_experiment` | `question`, `benchmark`, `conditions` | Prepare and execute named conditions and analyses. |
| `find_experiments` | `question`, `catalog` | Retrieve the runs and observations relevant to a research question. |

Judge calibration uses JSONL records such as `{"id":"case-1","group":"source-1","reference":"pass","judge":"fail"}`. Run `ai-eval calibrate-judge judgments.jsonl --labels '["pass","fail"]' --json-output reports/calibration.json`, or use `eval_calibrate_judge` with `source` and optional `output`. It reports label agreement, a group-bootstrap interval, Cohen's kappa and a confusion matrix. Reference judgments are a chosen comparison standard; agreement does not establish correctness. MCP returns up to 20 matrix labels and per-class records with explicit truncation counts. Saved JSON retains all labels and records.

A useful harness sequence is `eval_benchmark` → `eval_run` → the analysis suited to the question. Use selected sample records to explain a difference, and `eval_report(analysis="reports/study.json", output="reports/study.html")` to share the result.

## Import observed experiments

```bash
ai-eval import-gym gym-export.jsonl --output runs/gym \
  --system-name tool-agent --system-revision experiment-1 \
  --benchmark-name gym-study --revision 1

ai-eval import-inspect inspect-log.json --output runs/inspect \
  --scorer latency --direction minimize
```

Inspect accepts version-2 JSON logs. Select a numeric component of a structured score with `--value-key`. Convert binary `.eval` files using Inspect before importing. Original source data and provenance remain with the imported run; aggregate-only tables do not supply sample observations. See [scoring and import semantics](scoring.md) for field mappings and comparison requirements.

## Python and extensions

```python
from ai_eval.analysis import compare
from ai_eval.engine import run
from ai_eval.targets import PredictionTarget

run("benchmark.json", "runs/system-a",
    system={"name": "system-a", "revision": "1", "config": {}},
    target=PredictionTarget("predictions.jsonl"), workers=4)
result = compare("runs/system-a", "runs/system-b", "accuracy")
```

A Python target is a callable accepting the same request and returning the same response as the command protocol. Existing framework integrations can produce predictions, implement that callable, or export sample observations for an importer. Installed extensions use the `ai_eval.scorers`, `ai_eval.targets` and `ai_eval.importers` entry-point groups; `capabilities` lists the names actually installed. Scorer selection is part of the benchmark contract.

To expose a target factory from an installed package, register its import location in that package's `pyproject.toml`:

```toml
[project.entry-points."ai_eval.targets"]
my-harness = "my_package.evaluation:create_target"
```

`create_target(config)` receives the target configuration dictionary and returns the request callable. Select it with:

```bash
ai-eval run benchmark.json --target-plugin my-harness \
  --target-config '{"endpoint":"local","batch_size":8}' \
  --system-name research-agent --system-revision experiment-1 \
  --output runs/research-agent
```

MCP uses `target_plugin` and `target_config` on `eval_run`. Choose exactly one of predictions, command or plugin. Factory configuration belongs to the target execution identity; the system description should also identify the scientific condition, including externally managed model and harness state. Plugin targets are Python callables and own their external-operation deadlines.

For experiment design and complete executable examples, use [workflows](workflows.md). For the complete record and analysis contract, use [contracts](contracts.md).
