# AI Evaluation for TypeScript harnesses

The Node client runs evaluations and complete experiment plans through the Python engine. Scoring, sampling and statistical analysis have one implementation. This independent package has no runtime npm dependencies.

From the repository root:

```sh
python -m pip install -e .
cd sdk/typescript
npm ci
npm run build
node examples/retrieval-experiment.mjs
```

The example evaluates two authored retrieval prediction sets, creates a paired study and offline report, and records both runs in SQLite. The fixture demonstrates the research workflow; it does not measure a live model. The output directory contains the plan, runs, analysis, HTML and catalog.

```ts
import { EvaluationClient, type ExperimentPlan } from "@envfoundry/ai-evaluation";

const evaluation = new EvaluationClient({ python: "/path/to/venv/bin/python", cwd: "/research" });
const result = await evaluation.experiment("plans/retrieval.json", "runs/retrieval", {
  catalog: "research.sqlite",
});
const runs = await evaluation.catalogRuns("research.sqlite", { metric: "recall", limit: 10 });
const detail = await evaluation.analysis(result.analyses[0]!.json_path, { section: "samples", limit: 5 });
```

`ExperimentPlan` describes the JSON plan accepted by [the experiment operation](../../docs/experiments.md). Targets accept prediction files, command argument arrays or installed Python plugins. Target/model configuration stays in the plan and Python environment.

| Method | Use |
| --- | --- |
| `run`, `benchmark`, `capabilities` | Execute a target and inspect its measurement protocol |
| `summarize`, `compare`, `study` | Population estimates, paired differences and resource comparisons |
| `factorial`, `analyzeBenchmark` | Component interactions and item behavior |
| `samples`, `analysis`, `report` | Selected observations, saved analysis pages and offline HTML |
| `experiment` | Execute or resume named conditions and their analyses |
| `catalogAdd`, `catalogRuns`, `catalogQuery` | Persist and query research history |

`factorial` accepts runs in `00, 10, 01, 11` order. A study uses one common fully scored population. Catalog queries retrieve recorded facts; formal comparisons still use the analysis operations and their common-population semantics. SQL parameters are passed as a JSON array, separate from the statement.

Paths resolve from `cwd`. `python` names an executable, not a shell command. Calls accept an optional final `{ signal, timeoutMs, maxOutputBytes }`; the command deadline defaults to five minutes and output to 16 MiB. `RunOptions.timeout` and plan `execution.timeout` are Python target deadlines in **seconds**. Larger analyses can be saved with `jsonOutput` and read through `analysis` pages. `ProcessError` retains `exitCode`, `stderr` and `stdout` when Python exits unsuccessfully.

`npm test` executes the Python experiment, resumes it and queries its results. `npm pack` builds a package containing ESM JavaScript and declarations; install that tarball in a Node harness. The SDK is supplied in this repository. Node 20 or newer is required. Module/declaration conventions follow the [TypeScript documentation](https://www.typescriptlang.org/docs/handbook/modules/reference.html); process behavior follows [Node](https://nodejs.org/api/child_process.html).
