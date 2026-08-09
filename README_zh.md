# ResearchOps Toolkit

ResearchOps Toolkit 是面向 Codex、Claude Code、Gemini CLI 以及可选第三方模型 Worker 的模块化 **Research and Development 工作流插件**。它把渐进加载的 Skills、确定性 Runtime、任务相关的行为约束、证据/状态管理，以及项目级模型评估和路由组合在一起。

> 它的目标不是让一个 Agent 自动“写完一篇论文”，而是让问题、工作单元、产物、证据、模型分派、失败、成本、决策、风险和人工批准都有明确 owner，并能长期追溯。

v2.1 包含 13 个顶层 Skill、8 个 Behavior Pack、7 个内部组件、一个基于 SQLite 的 Model Intelligence 内核、原生 Hook Adapter，以及可裁剪的发布 Preset。

## 直接把这句话发给你的 Agent

> 拉取 `git@github.com:hungryDodo/researchops-toolkit.git` 并进入仓库；先运行 `python3 -m rops inspect /path/to/project`；再执行 `python3 -m rops bootstrap /path/to/project --title "My Project" --mode auto --upgrade` 并为目标 Harness 安装 `research-routed` Preset；最后运行 `python3 -m rops up --root /path/to/project --open` 检查接管后的项目状态和 Dashboard。

需要时可将 `codex` 换成 `claude`、`gemini`、`portable` 或 `all`。

## 快速开始

```bash
git clone git@github.com:hungryDodo/researchops-toolkit.git
cd researchops-toolkit

python3 -m rops inspect /path/to/project

python3 -m rops bootstrap /path/to/project \
  --title "My Project" \
  --mode auto \
  --upgrade

python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --preset research-routed \
  --with-agents \
  --with-behavior \
  --behavior-mode guide

python3 -m rops doctor --target codex --project /path/to/project
python3 -m rops up --root /path/to/project --open
```

在 Codex 中，项目级安装会保留 `.codex/hooks.json` 里已有的 Hook 组，并合并所选的 Behavior
处理器。Codex 对新增或变更 Hook 的正常人工信任确认不会被 ResearchOps 绕过。

用户项目根目录只增加一个隐藏目录：

```text
.researchops/
├── state/          项目设计、运行、证据、决策和 Dashboard 状态
├── governance/     项目规则、注册表和路由配置
├── intelligence/   权威 SQLite 数据库和生成的只读投影
├── runtime/        可重装的 Hook、Behavior Runtime 与本地 Runtime 副本
├── artifacts/      本地大文件和生成产物
├── cache/
└── logs/
```

v2 不再同时维护 `.research/` 和 `.researchops/` 两个并列目录；旧项目会迁移到这个单一根目录。

插件启用不等于项目从零开始。`rops inspect` 会在写入前先审阅仓库；非空项目默认采用 non-destructive adoption，不覆盖原文件，也不会默认在根目录增加政策文件。确定性扫描只提供事实和保守阶段推断，再由 Research Program Orchestrator 选择 light、standard 或 deep 接管深度并与用户确认。

## 最重要的架构区别

Research、Development 和 Routing **不是三个对等的业务域**：

- **Research-led R&D** 与 **Development-led R&D** 是两种用户可感知的工作流取向，目标函数和验收标准不同。
- **Model Intelligence / Routing** 是横切服务，可以给 Research、Development、Visual、Hardware 或外部自定义任务使用。
- Communication/Visual、Hardware、Hygiene 和 Skill-system maintenance 在产物、权限或风险边界确实不同，因此继续作为独立能力域。

```text
                         安装 Preset / 原生插件
                                  │
                ┌─────────────────┴─────────────────┐
                │                                   │
             顶层 Skills                        Behavior Runtime
 Research-led · Development-led · Visual      scope / evidence / risk / approval
 Hardware · Hygiene                              │
                └─────────────────┬─────────────────┘
                                  │
                         确定性 ROPS Runtime
 Model Gateway · Model Intelligence · Engineering Assurance · Evidence
                                  │
                     权威 `.researchops/` 状态
                                  │
 routing · dossier · dashboard · benchmark · audit 投影
                                  │
                         可选 Recall / Memory Adapter
```

## 为什么第一版就直接使用 SQLite

模型评价记录是关系型、随时间变化、持续增长的数据，需要按项目、工作单元、模型执行配置、endpoint、Judge、failure pattern 和 mitigation 查询。因此：

```text
.researchops/intelligence/state.sqlite
```

从第一条 Evaluation Event 开始就是权威事实库。JSONL 只用于导入、导出、审计和可复现实验交换，不会先维护一套 JSONL 事实源再迁移：

```bash
python3 -m rops intelligence --root /path/to/project export-jsonl \
  --out /tmp/evaluation-events.jsonl

python3 -m rops intelligence --root /path/to/project import-jsonl \
  /tmp/evaluation-events.jsonl
```

一个确定性的 Profile Engine 读取这些事件，并统一生成 Routing、Model Dossier、Dashboard、Benchmark 和 Audit 投影。路由画像与模型档案不再各自维护一套聚合逻辑。

## Model Intelligence 能力

Model Intelligence 可以脱离完整 Research 工作流单独安装，包含：

- live、shadow、anchor 三类规范化 Evaluation Event；
- 有限、可解释的任务条件化 Profile Slice，而不是高维笛卡尔积；
- 模型 × reasoning effort 联合 execution arm、effort-demand 匹配、硬性 effort 边界和可直接执行的 Codex 分派字段；
- 依据任务依赖选择 single / Lead-worker / centralized-fanout 拓扑，而不是为全能模型固化公司式岗位；
- 成功率后验、verified progress、质量、成本、延迟、人工修正与不确定性；
- 与模型能力分开的 endpoint health、有效期价格和身份观测；
- 新项目 warmup、soft transfer、zero-start 对照及负迁移自动拒绝；
- 聚合后的 failure pattern 和有 scope/revision/lifecycle 的 mitigation；
- 按任务族校准的 pairwise/LLM Judge；
- 闭源 API 的可观测行为漂移和 deployment epoch；
- Routing、Dossier、Dashboard、Benchmark、Audit 等只读投影；
- 带 episodic/semantic/procedural/preference 四层、去重、时效、替代关系、溯源、项目同步和可选外部 Adapter 的本地 Memory。

连接 probe 和 smoke 只更新 endpoint/identity，不会把“接口能调通”当作“模型能力很好”。

## 项目进度与路由可视化

`python3 -m rops up --root /path/to/project --open` 可以一键完成必要的接管/初始化、状态生成和 Dashboard 启动。现有论文/项目进度 Dashboard 增加了紧凑的 Intake、Memory 和 Model Intelligence 区域，只展示人真正关心的信息：

- 当前模型偏好和简短原因；
- 最近任务由谁完成、完成了什么；
- 已验证样本、成功趋势、成本与服务健康；
- 项目适应/warmup 进度；
- 行为漂移提醒；
- 必要时显示 active failure pattern 和 mitigation。

完整 posterior 参数、内部评分因子、策略细节和证据链保留在 Audit/Projection 中，不堆满主面板。

## 安装 Preset

Preset 是“安装与打包配方”，不是 Git bundle、Git submodule，也不是代码 owner 边界。

```bash
python3 -m rops presets
python3 -m rops presets routing-core --format json
```

| Preset | 用途 |
|---|---|
| `routing-core` | Model Gateway、评估、路由、漂移、Judge、warmup 和看板 |
| `development-core` | Development-led 技术调研、实现、调试、评审与发布 |
| `research-base` | 不强制启用动态多模型路由的 Research-led 工作流 |
| `research-routed` | `research-base` + `routing-core`，源码仓库默认 Preset |
| `communication-visual` | 学术表达和可选参考图分析输入 |
| `hardware` | 物理实验与硬件安全 |
| `hygiene` | archive-first 仓库/数据生命周期 |
| `platform-dev` | 维护 Skill、Hook、Manifest 与插件系统 |
| `full` | 所有能力 |

`rops bundles` 与 `--bundle` 继续作为兼容别名。

## 用户不用记住内部 operation code

用户只需自然语言描述目标，或显式调用稳定的顶层 Skill。`discover`、`design`、`implement`、`debug`、`validate`、`communicate` 等只是 Router、Evaluation 和 Benchmark Pack 使用的内部工作单元标签。

| Skill | 主要 owner |
|---|---|
| `research-program-orchestrator` | 生命周期、Gate、下一 owner、项目进度 |
| `research-discovery` | 可追溯调研、closest work、Related Work |
| `research-route-evaluator` | fatal flaw 与有限的可证伪路线 |
| `experimental-research` | 实验合同、执行、分析与证据 |
| `research-engineering` | 会影响研究 claim/测量的 research-led 代码 |
| `software-development` | development-led 调研、实现、调试、评审、发布 |
| `adaptive-agent-orchestration` | 有界委派、模型路由、独立验收 |
| `research-validation` | 复现、产物审计、论文 red-team |
| `research-writing` | 证据门控写作和 LaTeX 修订 |
| `research-communication` | 论文图、结果图和演示文稿 |
| `hardware-experiment-loop` | 拓扑、校准、租约、恢复 |
| `project-hygiene` | 归档、恢复、隔离、批准后 purge、worktree |
| `skill-system-engineering` | Skill/Pack 边界、触发、Hook、provenance、发布 |

## Research-led 与 Development-led R&D

两者共用：

```text
Frame → Investigate → Decide → Implement → Verify → Learn
```

Research-led 主要优化有效知识和 claim-to-evidence linkage，复杂、新奇或负结果路线也可能有科研价值；Development-led 主要优化可靠、可维护、可部署的交付物，并拒绝收益不足以覆盖工程复杂度的方法。共享的 `engineering-assurance` 负责任务合同、RED/baseline、diff 分析和风险适配验证；两个 Skill 再附加各自的验收规则。

## 参考图分析是可选能力

用户可以把参考图交给任意有视觉能力的外部模型，让它依据 `templates/visual-reference-analysis.md` 输出 `components/visual-contracts/visual-reference.schema.json`。ROPS 只消费结构化 Design Brief，不要求主 Harness 必须具备视觉能力，也不复制品牌或内容专属资产。

## 闭源 Provider 的“降智”或模型替换

Execution Arm 会记录 model family/revision、endpoint、量化或 reasoning 配置、adapter/tool schema、Harness/prompt revision、mitigation bundle 和本地 deployment epoch。若 Provider 不提供不可变 revision，系统无法从密码学意义上证明底层权重被替换；它只能监测格式/工具遵循、延迟、token 使用、anchor 结果、返回身份元数据等可观测行为是否持续漂移，并在确认后创建新的 epoch，避免新旧证据混在一起。

## Memory 边界

ROPS 必须自己维护权威状态。v2.1 的内置 Memory 支持 episodic、semantic、procedural、preference 四层，candidate/active/superseded/retired 生命周期，按来源去重与替代、有效期、关系、项目自动同步，以及带 provenance 的受限 Context Bundle。Harness memory、向量库或时间图仍是可选 Recall Adapter。检索结果不能直接修改路由画像、激活 mitigation、覆盖当前价格或批准高风险操作。

## 工具自身的 Evaluation 与 Baseline

```bash
python3 -m rops evaluate \
  --baseline-root /path/to/older/researchops \
  --out /tmp/researchops-product-benchmark
```

内置 Product Benchmark 会测试非破坏性接管、真实 HTTP Dashboard 快速启动、SQLite 权威状态，以及 Memory 的去重/替代/时效/隔离/溯源/同步。外部产品可通过标准报告 Adapter 接入，但功能表不能被当成“性能更好”的证据；更广泛的结论还需要同模型同任务的 paired Skill 实验和长期真实项目研究。

## 生成原生插件/Extension 发行物

```bash
python3 -m rops package \
  --out /tmp/researchops-release \
  --preset routing-core \
  --target codex

python3 -m rops package \
  --out /tmp/researchops-release \
  --preset full \
  --target portable
```

每个 ZIP 只包含所选 Skill、Component 和 Behavior Pack，并在包内重新生成默认 Preset、Catalog、原生 Manifest、Validation Report 和 SHA-256 完整性清单。

## 文档

| 文档 | 内容 |
|---|---|
| [文档索引](docs/README.md) | 推荐阅读路径 |
| [Getting started](docs/getting-started.md) | 审阅/接管、安装、一键 Dashboard、升级 |
| [Architecture and state](docs/architecture.md) | 横向层、纵向能力切片、权威状态 |
| [Model Intelligence](docs/model-intelligence.md) | event、聚合、projection、路由、漂移、warmup、Judge |
| [Research and Development](docs/research-and-development.md) | Research-led 与 Development-led 目标函数 |
| [Presets and distribution](docs/presets-and-distribution.md) | monorepo 组合与裁剪发布 |
| [Product landscape](docs/product-landscape.md) | 可观测性、Research Agent、Coding Agent 与 Memory 同类/相邻工具 |
| [Evaluation and baselines](docs/evaluation-and-baselines.md) | 工具回归、外部 Adapter、paired Skill、Routing 与用户研究 |
| [State and memory](docs/state-and-memory.md) | `.researchops/`、SQLite 权威、生命周期 Memory 与可选 Adapter |
| [Skills and progressive loading](docs/skills-and-bundles.md) | 顶层 owner、内部 mode、触发 |
| [Agents and model routing](docs/agents-and-model-routing.md) | Provider、Execution Arm、Dispatch 与评价 |
| [Safety and hygiene](docs/safety-and-hygiene.md) | Hook、审批、archive-first |
| [Migration to v2](docs/migration-v2.md) | 旧目录与 JSONL 迁移 |
| [Development and release](docs/development.md) | 测试、provenance、打包与贡献 |

直接修改本仓库的 Agent 应先阅读 [`AGENTS.md`](AGENTS.md)。

## 验证

```bash
python3 -m rops validate
python3 tests/smoke.py
python3 tests/intelligence_smoke.py
python3 tests/behavior_smoke.py
python3 tests/model_control_plane_smoke.py
python3 tests/model_effort_routing_smoke.py
python3 tests/adoption_memory_smoke.py
python3 -m rops evaluate --out /tmp/researchops-product-benchmark
python3 -m rops package --out /tmp/researchops-release --preset full --target portable
```

这些测试验证确定性结构和行为，但不保证未来所有模型/Provider/Harness 都能完美路由，也无法证明闭源服务是否真的更换隐藏权重，更不保证某个研究项目必然达到特定 venue。

## Provenance 与 License

ResearchOps Toolkit 使用 [MIT License](LICENSE)。外部项目和平台文档只用于设计分析，默认发行包不 vendor 第三方 Skill、Prompt、脚本、模板、手册或视觉资产。机器可读声明见 [`PROVENANCE.json`](PROVENANCE.json)。

## Research 评估路线

完整的研究问题、baseline、指标、消融与经验边界见 [`docs/research-agenda.md`](docs/research-agenda.md)。
