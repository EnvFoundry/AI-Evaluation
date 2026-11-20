import { PythonCLI, flag, type CallOptions, type Json, type JsonObject, type ProcessOptions } from "./process.js";
export { ProcessError, PythonCLI } from "./process.js";
export type { CallOptions, Json, JsonObject, ProcessOptions } from "./process.js";

export interface SystemSpec { name: string; revision: string; config?: JsonObject }
export type Target = { predictions: string } | { command: string[] } | { plugin: string; config?: JsonObject };
export interface RunOptions { workers?: number; timeout?: number; resume?: boolean }
export interface AnalysisOptions {
  confidence?: number; resamples?: number; seed?: number; sliceBy?: string;
  missing?: "error" | "complete_cases"; jsonOutput?: string;
}
export interface StudyOptions extends AnalysisOptions { baseline?: number; resource?: string; htmlOutput?: string }
export interface Page<T = JsonObject> { items: T[]; offset: number; limit: number; next_offset: number | null; total?: number }
export interface RunInfo {
  path: string; run_id: string; benchmark_id: string; system_id: string;
  planned_trials: number; recorded_trials: number; status_counts: Record<string, number>;
}
export interface ExperimentResult {
  experiment_id: string; name: string; status: string; path: string; manifest_path: string;
  conditions: (Omit<RunInfo, "benchmark_id" | "system_id"> & { id: string })[];
  analyses: { id: string; kind: string; json_path: string; html_path: string }[];
  catalog_path?: string;
}

export interface ExperimentCondition {
  id: string; system: SystemSpec;
  target: { predictions: string } | { command: string[]; cwd?: string } | { plugin: string; config?: JsonObject };
}
interface ExperimentAnalysisBase {
  id: string; metric: string; conditions?: string[]; missing?: "error" | "complete_cases"; slice_by?: string;
}
interface ExperimentIntervalOptions { confidence?: number; resamples?: number; seed?: number }
export type ExperimentAnalysis =
  | (ExperimentAnalysisBase & ExperimentIntervalOptions & { kind: "study"; baseline?: string; resource?: string })
  | (ExperimentAnalysisBase & ExperimentIntervalOptions & { kind: "factorial"; factor_a?: string; factor_b?: string })
  | (ExperimentAnalysisBase & { kind: "benchmark" });
export interface ExperimentPlan {
  schema_version: "1.0"; name: string; benchmark: string; question?: string;
  conditions: ExperimentCondition[]; analyses: ExperimentAnalysis[];
  execution?: { workers?: number; timeout?: number };
}

function analysisFlags(args: string[], options: AnalysisOptions) {
  flag(args, "confidence", options.confidence); flag(args, "resamples", options.resamples);
  flag(args, "seed", options.seed); flag(args, "slice-by", options.sliceBy);
  flag(args, "missing", options.missing); flag(args, "json-output", options.jsonOutput);
}

/** Typed argv construction; execution and analysis stay in the Python package. */
export class EvaluationClient {
  readonly cli: PythonCLI;
  constructor(options: ProcessOptions = {}) { this.cli = new PythonCLI("ai_eval", options); }
  capabilities(call?: CallOptions) { return this.cli.json(["capabilities"], call); }
  guide(topic: string, call?: CallOptions) { return this.cli.json(["guide", topic], call); }
  benchmark(path: string, call?: CallOptions) { return this.cli.json(["benchmark", path], call); }

  run(benchmark: string, output: string, system: SystemSpec, target: Target, options: RunOptions = {}, call?: CallOptions) {
    const args = ["run", benchmark, "--output", output, "--system-name", system.name,
      "--system-revision", system.revision, "--system-config", JSON.stringify(system.config ?? {})];
    if ("predictions" in target) args.push("--predictions", target.predictions);
    else if ("command" in target) args.push("--command-json", JSON.stringify(target.command));
    else {
      args.push("--target-plugin", target.plugin);
      if (target.config !== undefined) args.push("--target-config", JSON.stringify(target.config));
    }
    flag(args, "workers", options.workers); flag(args, "timeout", options.timeout); flag(args, "resume", options.resume);
    return this.cli.json<RunInfo>(args, call);
  }

  summarize(run: string, metric: string, options: Omit<AnalysisOptions, "missing"> = {}, call?: CallOptions) {
    const args = ["summarize", run, "--metric", metric]; analysisFlags(args, options);
    return this.cli.json(args, call);
  }

  passAtK(run: string, metric: string, k: number, call?: CallOptions) {
    return this.cli.json(["pass-at-k", run, "--metric", metric, "--k", String(k)], call);
  }

  calibrateJudge(path: string, options: Pick<AnalysisOptions, "confidence" | "resamples" | "seed" | "jsonOutput">
      & { labels?: string[]; groupKey?: string } = {}, call?: CallOptions) {
    const args = ["calibrate-judge", path]; analysisFlags(args, options);
    if (options.labels !== undefined) flag(args, "labels", JSON.stringify(options.labels));
    flag(args, "group-key", options.groupKey);
    return this.cli.json(args, call);
  }

  compare(left: string, right: string, metric: string, options: AnalysisOptions = {}, call?: CallOptions) {
    const args = ["compare", left, right, "--metric", metric]; analysisFlags(args, options);
    return this.cli.json(args, call);
  }

  study(runs: string[], metric: string, options: StudyOptions = {}, call?: CallOptions) {
    const args = ["study", ...runs, "--metric", metric]; analysisFlags(args, options);
    flag(args, "baseline", options.baseline); flag(args, "resource", options.resource); flag(args, "html-output", options.htmlOutput);
    return this.cli.json(args, call);
  }

  factorial(runs: readonly [string, string, string, string], metric: string,
      options: AnalysisOptions & { factorA?: string; factorB?: string; htmlOutput?: string } = {}, call?: CallOptions) {
    const args = ["factorial", ...runs, "--metric", metric]; analysisFlags(args, options);
    flag(args, "factor-a", options.factorA); flag(args, "factor-b", options.factorB); flag(args, "html-output", options.htmlOutput);
    return this.cli.json(args, call);
  }

  analyzeBenchmark(runs: string[], metric: string,
      options: Pick<StudyOptions, "missing" | "sliceBy" | "jsonOutput" | "htmlOutput"> = {}, call?: CallOptions) {
    const args = ["analyze-benchmark", ...runs, "--metric", metric];
    flag(args, "missing", options.missing); flag(args, "slice-by", options.sliceBy);
    flag(args, "json-output", options.jsonOutput); flag(args, "html-output", options.htmlOutput);
    return this.cli.json(args, call);
  }

  analysis(source: string, options: { section?: string; offset?: number; limit?: number; search?: string } = {}, call?: CallOptions) {
    const args = ["analysis", source];
    flag(args, "section", options.section); flag(args, "offset", options.offset);
    flag(args, "limit", options.limit); flag(args, "search", options.search);
    return this.cli.json(args, call);
  }

  samples(run: string, options: { offset?: number; limit?: number; status?: "ok" | "target_error" | "score_error";
      sampleId?: string; sliceKey?: string; sliceValue?: string | number | boolean; includeOutput?: boolean } = {}, call?: CallOptions) {
    const args = ["samples", run];
    flag(args, "offset", options.offset); flag(args, "limit", options.limit); flag(args, "status", options.status);
    flag(args, "sample-id", options.sampleId); flag(args, "slice-key", options.sliceKey);
    if (options.sliceValue !== undefined) flag(args, "slice-value", JSON.stringify(options.sliceValue));
    flag(args, "include-output", options.includeOutput);
    return this.cli.json<Page>(args, call);
  }

  report(analysis: string, output: string, title?: string, call?: CallOptions) {
    const args = ["report", "--analysis", analysis, "--output", output]; flag(args, "title", title);
    return this.cli.json(args, call);
  }

  experiment(plan: string, output: string, options: { resume?: boolean; catalog?: string } = {}, call?: CallOptions) {
    const args = ["experiment", plan, "--output", output];
    flag(args, "resume", options.resume); flag(args, "catalog", options.catalog);
    return this.cli.json<ExperimentResult>(args, call);
  }

  catalogAdd(database: string, runs: string[], call?: CallOptions) {
    return this.cli.json(["catalog-add", database, ...runs], call);
  }

  catalogRuns(database: string, options: { benchmark?: string; system?: string; experiment?: string; metric?: string; offset?: number; limit?: number } = {}, call?: CallOptions) {
    const args = ["catalog-runs", database];
    for (const name of ["benchmark", "system", "experiment", "metric", "offset", "limit"] as const) flag(args, name, options[name]);
    return this.cli.json<Page>(args, call);
  }

  catalogQuery(database: string, sql: string, parameters: Json[] = [], options: { offset?: number; limit?: number } = {}, call?: CallOptions) {
    const args = ["catalog-query", database, "--sql", sql, "--params", JSON.stringify(parameters)];
    flag(args, "offset", options.offset); flag(args, "limit", options.limit);
    return this.cli.json<Page & { columns: string[]; truncated_cells: { row: number; column: string; characters: number }[] }>(args, call);
  }
}
