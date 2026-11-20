# AI Evaluation

**Design benchmarks, measure AI systems, and study what changes their behavior.**

[中文](README.zh-CN.md) · [Experiment plans](docs/experiments.md) · [Workflows](docs/workflows.md) · [Research methods](docs/research.md) · [Connect a harness](docs/connect.md)

AI Evaluation is a standalone research environment for models, retrieval systems, agents and scientific workflows. It connects a research question to a task population, a complete system description, an execution protocol and observed outcomes. Researchers and agents use the same Python, CLI and MCP operations.

The central questions are practical: Which system performs better on the same cases? What does the improvement cost? Do two components help independently or only together? Which cases distinguish the systems, and which have stopped providing useful resolution?

## Run a research study

Python 3.11 or newer. The core and reports use the standard library.

```bash
git clone https://github.com/EnvFoundry/AI-Evaluation.git
cd AI-Evaluation
python -m pip install -e .
python examples/experiment_plan.py --output runs/planned-study
```

The example executes a declarative experiment plan: four lexical retrievers on an authored corpus of 18 queries in six topic groups, crossing query expansion with phrase reranking. It records work, writes system/factorial/item analyses and offline reports, and stores the experiment in a local SQLite catalog. Re-running the plan resumes recorded conditions.

| Query expansion | Phrase reranking | Recall@1 | Mean token comparisons |
| --- | --- | ---: | ---: |
| Off | Off | 1/3 | 13⅓ |
| On | Off | 1/3 | 26⅔ |
| Off | On | 2/3 | 20⅔ |
| On | On | 1 | 56 |

Expansion contributes no recall on its own, but adds `1/3` when phrase reranking is active. The factorial analysis exposes that interaction. The system study identifies the observed quality–work frontier; benchmark analysis identifies six cases that every reference system solves. These results explain the constructed retrieval mechanism. They are not measurements of model performance or natural-language generalization.

Open `runs/planned-study/experiment/analyses/systems.html`, `effects.html` and `items.html`. The directory also contains the experiment plan, corpus, target program, run observations, analysis JSON and `catalog.sqlite`.

```sh
ai-eval experiment runs/planned-study/plan.json --output runs/planned-study/experiment --catalog runs/planned-study/catalog.sqlite --resume
ai-eval catalog-query runs/planned-study/catalog.sqlite --sql "SELECT system_revision,mean,recorded_trials FROM run_metrics WHERE metric='recall' ORDER BY system_revision"
```

A plan names every system condition, target, execution setting and analysis. The catalog preserves individual samples, trials and metric definitions; its means first average within each sample. Querying the catalog does not turn runs on different populations into a paired comparison. [Experiment plans and catalog](docs/experiments.md) defines these semantics. [Workflows](docs/workflows.md) covers direct operations, prediction replay and a physical-parameter solver.

## From observations to research decisions

| Question | Operation | Method |
| --- | --- | --- |
| How do we repeat a whole study and find its recorded results? | `experiment`, catalog operations | Declarative conditions, resumable runs, stored analyses and paginated SQL-backed discovery |
| Which system should we use at a given resource budget? | `study` | One common cohort, paired differences against a baseline, group intervals and an observed resource frontier |
| How do two interventions combine? | `factorial` | Four conditions, main and conditional effects, and a difference-in-differences interaction |
| How informative are these benchmark cases for our systems? | `analyze-benchmark` | Item facility, dispersion, floor/ceiling and item–rest association across a reference panel |

Execution accepts Python callables, JSON command targets, recorded predictions and installed target plugins. Native scoring covers exact match, numerical tolerance, set/token F1, retrieval metrics and probability scores; scorer plugins extend the measurement. Local workers retain sample/trial observations for continuation after interruption.

Analysis also includes single-system summaries, paired comparisons, slices, binary `pass@k` and categorical judge calibration. Repeated trials remain within their sample, related cases remain within their independent group, and incomplete measurements retain their coverage. HTML reports render the saved analysis without a separate scoring path.

Read [factorial experiments](docs/factorial-experiments.md), [benchmark development](docs/benchmark-development.md) and [research methods](docs/research.md) for interpretation. [Contracts](docs/contracts.md) and [scoring](docs/scoring.md) define exact data and measurement semantics. [Design](docs/design.md) explains the system boundary; [ecosystem](docs/ecosystem.md) covers optional external runners and data formats.

## Work with models and agents

```bash
python -m pip install -e '.[mcp]'
ai-eval capabilities
ai-eval connect --root /absolute/path/to/studies --output mcp.json
```

A target can wrap a local model, hosted API, retrieval pipeline, simulator or complete agent harness. It receives task inputs and a trial seed; reference answers remain with scoring. Serving and provider configuration belong to the target's runtime.

MCP offers the same execution and analysis operations, method resources, research prompts and paginated observations. Agents can begin with a question and a small set of records, then request the details needed to resolve it. The [connection guide](docs/connect.md) describes configuration, plugin entry points and Python interfaces; the [evaluation skill](skills/ai-evaluation/SKILL.md) provides task-specific guidance.

The [TypeScript SDK](sdk/typescript/README.md) gives Node harnesses typed access to experiment execution, analysis and catalog queries. Python carries out the research operations; SQL preserves the experimental relationships; the SDK manages the subprocess exchange. Each environment can run independently.

## Develop

Contributions should enable a useful measurement, research method, working integration or clearer experiment. Start with [AGENTS.md](AGENTS.md) and [contributing](CONTRIBUTING.md). The current engine executes and analyzes local runs; domain simulators, model serving and distributed scheduling can remain in their existing runtimes.

MIT license.
