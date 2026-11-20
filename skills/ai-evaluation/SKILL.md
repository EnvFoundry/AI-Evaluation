---
name: ai-evaluation
description: Design and execute AI evaluation experiments, compare systems and resource use, measure component interactions, develop benchmarks, calibrate judges and query recorded experiments. Use for models, retrieval, agents, harnesses and scientific predictions.
---

# AI Evaluation

State the research question and the decision it should inform. Identify the changed system condition, target population, observable outcome and independent unit. Include model, harness, prompts, retrieval, tools and generation settings when they affect the experiment.

Run `ai-eval capabilities`; from a source checkout, `python server.py capabilities` also works. Use Python, CLI or MCP operations over the same implementation. Read installed guidance with `ai-eval guide TOPIC` or `evaluation://guides/TOPIC`.

| Question | Guide | Operation |
| --- | --- | --- |
| What population and outcome address the question? | `experimental-design` | `benchmark`, `run`, `summarize` |
| Which system improves quality at a given resource use? | `system-comparison` | `study` / `eval_study` |
| How do two component changes combine? | `factorial-experiments` | `factorial` / `eval_factorial` |
| Which cases distinguish a reference panel? | `benchmark-development` | `analyze-benchmark` / `eval_analyze_benchmark` |
| How do we execute and continue the whole experiment? | `experiment-plans` | `experiment` / `eval_experiment` |
| Which recorded runs answer this question? | `experiment-catalog` | `catalog-runs`, `catalog-query` |

For a repeatable experiment, write a plan containing the actual benchmark, named conditions, targets, configurations and analyses. Execute it into a new output directory and use `--resume` for continuation. Use `--catalog` to retain searchable results. Installed guides work when the host copies this Skill separately. For source-level details, explicitly locate the [AI Evaluation checkout](https://github.com/EnvFoundry/AI-Evaluation); `docs/experiments.md` defines plans/catalogs and `docs/workflows.md` covers individual operations. Document and SDK paths below refer to that checkout.

For matched comparisons, keep benchmark, scoring and protocol compatible. Average repeated trials within samples and retain related cases within independent groups. Multi-system and factorial analyses use one common complete cohort; state coverage when it differs from the planned population. In factorial work, supply conditions in `00,10,01,11` order and interpret simple effects alongside the interaction.

Save full analyses. Begin with `analysis --section summary` or `eval_analysis(section="summary")`, then request only the systems, slices or samples needed to resolve the question. Use original trials to explain unexpected behavior. SQL helps find runs and select observations; a pooled trial average is not the weighted sample estimate. Use the existing analyses for paired uncertainty. Keep metric direction, resource units and comparison population explicit.

Read `docs/judges.md` for judge calibration, `docs/contracts.md` and `docs/scoring.md` for measurement extensions, and `docs/connect.md` or `sdk/typescript/README.md` for harness access.

Example request: “Run these four crossed retriever and prompt configurations on the same cases, measure quality and token use, then explain whether either change helps only in combination.” Return the plan and result paths, measured effects, coverage, resource observations and concrete cases; distinguish the observed result from a proposed cause.
