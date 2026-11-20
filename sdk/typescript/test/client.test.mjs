import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { EvaluationClient } from "../dist/index.js";
import { retrievalExperiment } from "../examples/retrieval-experiment.mjs";

test("Execute, resume, query and page a real Python research experiment", async () => {
  const root = await mkdtemp(join(tmpdir(), "eval sdk "));
  try {
    const output = join(root, "experiment");
    const options = { python: process.env.PYTHON ?? "python" };
    const result = await retrievalExperiment(output, options);
    assert.equal(result.experiment.status, "complete");
    assert.equal(result.runs.total, 2);
    const means = result.runs.items.map(row => row.metrics[0].mean).sort((a, b) => a - b);
    assert.deepEqual(means, [1 / 3, 11 / 12]);
    const client = new EvaluationClient(options);
    const resumed = await client.experiment(join(output, "plan.json"), join(output, "experiment"), {
      resume: true, catalog: join(output, "research.sqlite"),
    });
    assert.deepEqual(resumed.conditions.map(item => item.run_id), result.experiment.conditions.map(item => item.run_id));
    const query = await client.catalogQuery(join(output, "research.sqlite"),
      "SELECT system_revision, recorded_trials FROM runs WHERE system_revision = ?", ["candidate"]);
    assert.deepEqual(query.columns, ["system_revision", "recorded_trials"]);
    assert.deepEqual(query.items, [{ system_revision: "candidate", recorded_trials: 6 }]);
    const page = await client.samples(resumed.conditions[0].path, { limit: 2 });
    assert.equal(page.items.length, 2);
    assert.equal(page.next_offset, 2);
    const details = await client.analysis(result.experiment.analyses[0].json_path, { section: "samples", limit: 2 });
    assert.equal(details.items.length, 2);
  } finally { await rm(root, { recursive: true, force: true }); }
});
