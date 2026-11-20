import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { EvaluationClient } from "../dist/index.js";

export async function retrievalExperiment(output, options = {}) {
  await mkdir(output, { recursive: false });
  const repository = fileURLToPath(new URL("../../../", import.meta.url));
  const client = new EvaluationClient(options);
  const plan = {
    schema_version: "1.0", name: "authored-retrieval-comparison",
    question: "How do the two authored retrieval prediction sets differ on the same queries?",
    benchmark: join(repository, "examples/retrieval/benchmark.json"),
    conditions: ["baseline", "candidate"].map(id => ({ id,
      system: { name: "authored-retriever", revision: id },
      target: { predictions: join(repository, `examples/retrieval/${id}.jsonl`) },
    })),
    analyses: [{ id: "recall", kind: "study", metric: "recall", baseline: "baseline", resamples: 200 }],
  };
  const planFile = join(output, "plan.json");
  const catalog = join(output, "research.sqlite");
  await writeFile(planFile, JSON.stringify(plan, null, 2));
  const experiment = await client.experiment(planFile, join(output, "experiment"), { catalog });
  const runs = await client.catalogRuns(catalog, { metric: "recall", limit: 10 });
  const analysis = await client.analysis(experiment.analyses[0].json_path, { section: "summary" });
  return { output, experiment, runs, analysis };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const parent = process.argv[2] ? null : await mkdtemp(join(tmpdir(), "ai-eval-typescript-"));
  const output = process.argv[2] ? resolve(process.argv[2]) : join(parent, "study");
  const result = await retrievalExperiment(output, { python: process.env.PYTHON ?? "python" });
  console.log(JSON.stringify({ output, experiment: result.experiment, runs: result.runs }, null, 2));
}
