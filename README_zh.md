# ResearchOps Toolkit

ResearchOps Toolkit 是一套面向 Codex、Claude Code、Gemini CLI 与可选第三方模型的**证据驱动研究工作流**。它把调研、路线筛选、实验、独立验证、写作、审稿、可视化和项目清理组织为可审计、可恢复、可渐进加载的研究闭环。

> 目标不是让 Agent 自动“写出一篇论文”，而是让研究过程中的问题、假设、证据、失败、决策、风险和人工审批都有明确归属。

当前发行版提供 **12 个顶层 Skill、2 个内部组件、跨框架安装器、Sub-Agent/多模型路由、Capability Proposal、安全清理与全屏研究看板**。

## 一句话快速开始

如果你不想读任何文档，只想立刻开始，把这句话丢给你的 Agent 即可：

> 克隆 git@github.com:hungryDodo/researchops-toolkit.git，进入目录后依次执行 `python3 -m rops install --target codex --scope project --project . --mode link --with-agents`、`python3 -m rops bootstrap . --title "我的研究项目"`、`python3 -m rops doctor --target codex --project .`。

## 快速开始

推荐在目标项目中使用项目级安装，并默认启用 `research-core` bundle：

```bash
git clone git@github.com:hungryDodo/researchops-toolkit.git
cd researchops-toolkit

python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --with-agents

python3 -m rops bootstrap /path/to/project \
  --title "My Research Project" \
  --upgrade

python3 -m rops doctor \
  --target codex \
  --project /path/to/project
```

启动研究看板：

```bash
python3 -m rops dashboard serve \
  --root /path/to/project \
  --port 8765
```

默认不会安装硬件、清理和 Skill 开发等低频/高风险能力。需要时再安装对应 bundle：

```bash
python3 -m rops bundles
python3 -m rops install --target codex --scope project --project . --bundle hardware
python3 -m rops install --target codex --scope project --project . --bundle hygiene
python3 -m rops install --target codex --scope project --project . --bundle platform-dev
```

完整安装、跨框架用法和升级方式见 [快速开始](docs/getting-started.md)。

## 文档导航

| 文档 | 适用场景 |
|---|---|
| [Docs 索引](docs/README.md) | 人类或 Agent 第一次进入仓库时的最短阅读路径 |
| [快速开始](docs/getting-started.md) | 安装、初始化、看板、升级与多设备部署 |
| [架构与状态模型](docs/architecture.md) | 目录、控制面、执行面、`.research/` 权威状态 |
| [研究工作流](docs/workflows.md) | 阶段、Gate、证据状态、Capability Proposal 与交接 |
| [Skills 与 Bundles](docs/skills-and-bundles.md) | 12 个 Skill、渐进加载、触发和颗粒度原则 |
| [Sub-Agent 与模型路由](docs/agents-and-model-routing.md) | 任务拆分、弱模型/第三方模型、独立验收与模型画像 |
| [安全、归档与清理](docs/safety-and-hygiene.md) | 硬件、Archive-first、两阶段删除、worktree 和隐私 |
| [开发与发布](docs/development.md) | 新 Skill、跨 Harness 适配、测试、来源和发布检查 |

仓库根目录的 [`AGENTS.md`](AGENTS.md) 为直接进入本仓库的编程 Agent 提供最小阅读和修改约束。

## 体系结构

```text
researchops-toolkit/
├── skills/                 # 12 个可渐进加载的顶层 Skill
├── components/             # evidence-ledger、dashboard；不参与语义触发
├── rops/                   # 统一跨平台 CLI 及其内部模块
├── config/                 # 框架路径、bundles、触发、proposal 与产物合同
├── catalog/                # 面向人类和 Agent 的生成式 Skill 目录
├── tests/                  # 触发 fixture 与端到端 smoke test
├── templates/              # 单一的项目 Agent 策略模板
├── release/                # 发布验证报告与内部文件哈希清单
└── docs/                   # 稳定的用户与维护文档
```

目标项目初始化后，`.research/` 是研究状态的唯一权威来源；终端滚屏、聊天摘要和临时 Markdown 不能替代已登记的设计、运行、证据和决策。

## 12 个顶层 Skill

| Skill | 主要职责 |
|---|---|
| `research-program-orchestrator` | 生命周期、阶段 Gate、下一步、证据/看板和能力建议 |
| `research-discovery` | Survey、closest work、Related Work 与可信语料综合 |
| `research-route-evaluator` | Idea 致命缺陷、资源匹配、Top 1–3 路线与最小验证 |
| `experimental-research` | 软件实验设计、执行、分析和可复现实证 |
| `hardware-experiment-loop` | 硬件拓扑、安全、校准、租约与恢复 |
| `research-engineering` | 影响研究结论的代码变更：SPEC → RED → GREEN → Gauntlet |
| `adaptive-agent-orchestration` | Sub-Agent 拆分、模型路由、独立验收和模型画像 |
| `research-validation` | 独立复现、artifact audit 和论文 red-team review |
| `research-writing` | 证据门控写作、LaTeX 修订、反馈 ledger 与视觉编译检查 |
| `research-communication` | 学术插图、结果图和研究型 PPT |
| `project-hygiene` | Archive-first、数据/日志、worktree、临时测试与两阶段 purge |
| `skill-system-engineering` | Skill 创建/合并/拆分、触发、安全、来源和跨 Harness 适配 |

完整目录和 startup context 估算见 [`catalog/README.md`](catalog/README.md)。

## 高风险能力：先建议，再决定是否加载

为了兼顾“防误触”和“避免忘记功能”，Orchestrator 只在关键阶段或即将发生高风险动作时运行轻量 Capability Advisor，并生成 proposal：

```text
轻量发现 → Proposal → 用户批准加载 Specialist → Specialist 自己的操作审批
```

Proposal 只说明为什么可能需要某个能力、上下文/成本和所需批准；它**不会读取完整高风险 Skill、不会运行工具，也不等于硬件写入、第三方发送或永久删除的操作批准**。`dismissed`、`snoozed` 和 `completed` 状态会持久化，避免反复打扰。

## 设计参考与致谢

本项目认真阅读并拆解了以下开源项目、规范和平台文档。我们学习的是它们解决问题的方式、Skill/Harness 组织、验证边界和工作流思想；**本发行包没有复制、修改或 vendor 这些项目的 Skill、Prompt、脚本、模板、Handbook 或前端资源**。所有实现均为针对 ResearchOps Toolkit 需求重新编写的 clean-room implementation。详细机器可读声明见 [`PROVENANCE.json`](PROVENANCE.json)。

| 项目 / 文档 | 对本项目的主要启发 |
|---|---|
| [Orchestra Research AI-research-SKILLs](https://github.com/Orchestra-Research/AI-research-SKILLs) | 模块化研究能力、AutoResearch 风格执行与按需工具箱 |
| [OpenJudge](https://github.com/agentscope-ai/OpenJudge) | 独立 evaluator、弱点分析、持续评测与验收分离 |
| [ARS-Codex](https://github.com/Imbad0202/academic-research-skills-codex) | 端到端学术工作流、跨模型审阅和平台适配边界 |
| [phd-skills](https://github.com/fcakyon/phd-skills) | 实验设计、复现、研究诚信和论文核验 |
| [CCFA-Skills](https://github.com/mikubaka88/CCFA-Skills) | owner 边界、正/负触发、共享 references 和 artifact contract |
| [old-coder](https://github.com/AmazingAng/old-coder) | SPEC、observed RED、minimum GREEN、Gauntlet 与 fresh evidence |
| [revise-paper](https://github.com/CISLab-HKUST/revise-paper) | LaTeX 源码与 PDF 双权威、反馈驱动修订和视觉检查 |
| [ResearchStudio-Idea](https://github.com/microsoft/ResearchStudio/tree/main/ResearchStudio-Idea) | 磁盘状态、幂等 next action、novelty axes 和干净上下文 worker |
| [Supervisor-Skills](https://github.com/HKUSTDial/Supervisor-Skills) | Guide/Skill 分层、fatal-flaw idea gate、证据门控写作、范式感知审稿 |
| [Anthropic Skills](https://github.com/anthropics/skills) 与 [frontend-design](https://github.com/anthropics/skills/tree/main/skills/frontend-design) | 自包含 Skill、渐进披露、可访问性和产物自审 |
| [Google Skills](https://github.com/google/skills) | 选择性安装、评测飞轮、机器/人类双报告 |
| [Ponytail](https://github.com/DietrichGebert/ponytail) | 最小充分改动、依赖预算和真实可执行检查 |
| [distill-design](https://github.com/ake77-code/distill-design) | 仅借鉴“紧凑、可复用视觉合同”；URL/品牌蒸馏不属于本项目正常路径 |
| [Agent Skills specification](https://agentskills.io/) | Skill 目录结构、description discovery 与渐进加载模型 |
| [OpenAI Codex](https://developers.openai.com/codex/)、[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)、[Gemini CLI](https://geminicli.com/docs/) | 原生 Agent/Skill 配置、权限和跨 Harness 兼容约定 |
| [LiteLLM](https://docs.litellm.ai/) 与 [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | 可选模型网关、provider 统一、handoff、trace 和 human-in-the-loop 参考 |

如后续选择 vendor 第三方 Skill，必须固定 commit、单独记录许可证、运行安全审计并更新 provenance；默认发行包不包含第三方实现。

## 验证与可信边界

```bash
python3 -m rops validate
python3 -m rops validate --smoke
python3 -m rops package --out /tmp/researchops-toolkit-release
```

这些检查验证结构、触发 fixture 覆盖、安装、工具行为、归档恢复、安全边界和内部文件哈希；它们不等价于所有模型/Harness 版本上的真实触发准确率，也不保证某个研究方向必然达到顶会水平。

## License

ResearchOps Toolkit 采用 [MIT License](LICENSE)。外部参考项目仍受各自许可证约束。
