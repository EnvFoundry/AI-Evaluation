# AI Evaluation

**设计基准、测量 AI 系统，研究哪些改变真正影响了系统行为。**

[English](README.md) · [实验计划](docs/experiments.md) · [研究工作流](docs/workflows.md) · [研究方法](docs/research.md) · [接入 Harness](docs/connect.md)

AI Evaluation 是面向模型、检索系统、智能体和科学研究流程的独立研究环境。它将研究问题、任务总体、完整的系统描述、执行协议与观测结果联系起来。研究者与 Agent 使用同一套 Python、CLI 和 MCP 操作。

核心问题很具体：在相同案例上，哪个系统表现更好？改进需要多少资源？两个组件各自有效，还是组合后才有效？哪些案例能够区分系统，哪些已经无法提供足够的分辨力？

## 运行一项研究

需要 Python 3.11 或更新版本。核心与报告仅依赖标准库。

```bash
git clone https://github.com/EnvFoundry/AI-Evaluation.git
cd AI-Evaluation
python -m pip install -e .
python examples/experiment_plan.py --output runs/planned-study
```

示例执行一份声明式实验计划：在人工构造的 18 条查询、6 个主题组上运行四种词法检索算法，交叉改变查询扩展与短语重排，记录工作量，生成系统比较、析因和案例分析及离线报告，并将实验存入 SQLite。再次运行计划时可以沿用已有结果。

| 查询扩展 | 短语重排 | Recall@1 | 平均词元比较次数 |
| --- | --- | ---: | ---: |
| 关闭 | 关闭 | 1/3 | 13⅓ |
| 开启 | 关闭 | 1/3 | 26⅔ |
| 关闭 | 开启 | 2/3 | 20⅔ |
| 开启 | 开启 | 1 | 56 |

查询扩展单独使用时没有提高召回率；开启短语重排后，它又带来了 `1/3` 的提升。析因分析揭示这个交互作用。系统比较给出观测到的质量与工作量前沿，基准分析指出参考系统全部答对的六个案例。这些结果解释的是示例构造的检索机制，不代表模型表现或对自然语言的泛化能力。

打开 `runs/planned-study/experiment/analyses/systems.html`、`effects.html` 和 `items.html`。同一目录保留计划、语料、目标程序、运行观测、分析 JSON 和 `catalog.sqlite`。

```sh
ai-eval experiment runs/planned-study/plan.json --output runs/planned-study/experiment --catalog runs/planned-study/catalog.sqlite --resume
ai-eval catalog-query runs/planned-study/catalog.sqlite --sql "SELECT system_revision,mean,recorded_trials FROM run_metrics WHERE metric='recall' ORDER BY system_revision"
```

计划明确每个系统条件、目标、执行设置与分析。目录保存样本、试次和指标定义，均值先在样本内部聚合。不同任务总体上的结果仍然属于不同实验；SQL 查询不会自动赋予它们可比性。[实验计划与目录](docs/experiments.md)解释具体语义，[研究工作流](docs/workflows.md)提供直接操作、预测回放与物理参数求解示例。

## 从观测走向研究决策

| 研究问题 | 操作 | 方法 |
| --- | --- | --- |
| 如何重复整项研究并查找结果？ | `experiment` 与目录操作 | 声明实验条件、恢复执行、保存分析和按需查询 |
| 在给定资源预算下应选择哪个系统？ | `study` | 统一分析总体、相对基线的配对差值、按独立组计算的区间和观测资源前沿 |
| 两项改动如何共同作用？ | `factorial` | 四种条件、主效应、条件效应和差分之差交互作用 |
| 这些基准案例对我们的系统有多大分辨力？ | `analyze-benchmark` | 参考系统面板上的案例得分、离散程度、地板/天花板和案例与其余任务得分的关联 |

执行支持 Python 函数、JSON 命令目标、已记录预测和目标插件。原生评分包括精确匹配、数值容差、集合/词元 F1、检索指标与概率评分；评分插件可以扩展测量。并发本地执行保留案例与试次记录，支持中断后继续。

分析还包括单系统汇总、双系统配对比较、切片、二元 `pass@k` 和分类评判校准。重复尝试归属于各自案例，相关案例归属于独立组，缺失测量保留覆盖率信息。HTML 报告直接呈现已保存的分析。

参见[析因实验](docs/factorial-experiments.md)、[基准开发](docs/benchmark-development.md)和[研究方法](docs/research.md)，理解结果的含义。[数据契约](docs/contracts.md)与[评分说明](docs/scoring.md)定义具体语义，[设计](docs/design.md)解释系统边界，[生态指南](docs/ecosystem.md)介绍可选的外部执行器和数据格式。

## 与模型和 Agent 一起工作

```bash
python -m pip install -e '.[mcp]'
ai-eval capabilities
ai-eval connect --root /absolute/path/to/studies --output mcp.json
```

目标可以封装本地模型、云 API、检索流程、模拟器或完整 Agent Harness。它接收任务输入与试次种子；参考答案留在评分侧。模型服务与供应商配置沿用目标自身的运行环境。

MCP 提供同一套执行与分析操作，以及方法资源、研究提示词和分页观测。Agent 可以从问题和少量记录入手，再读取能够推进判断的细节。[连接指南](docs/connect.md)说明配置、插件入口与 Python 接口；[评测 Skill](skills/ai-evaluation/SKILL.md)提供按任务组织的指导。

[TypeScript SDK](sdk/typescript/README.md)让 Node Harness 通过类型化方法执行实验、读取分析和查询目录。Python 执行研究操作，SQL 保存实验关系，SDK 管理进程通信。环境保持独立可用。

## 开发

贡献应带来有用的测量、研究方法、可运行接入或更清楚的实验。从 [AGENTS.md](AGENTS.md) 和[贡献说明](CONTRIBUTING.md)开始。当前引擎执行并分析本地运行；领域模拟器、模型服务和分布式调度可以沿用各自的运行方式。

MIT 许可证。
