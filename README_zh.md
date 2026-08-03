# ResearchOps Toolkit

ResearchOps Toolkit 是一套面向 Codex、Claude Code、Gemini CLI 与可选第三方模型 worker 的**证据驱动科研工作流与 Agent 行为工具包**。它把研究调研、路线筛选、实验、独立验证、论文写作、可视化、Sub-Agent 协作和项目清理组织为可审计、可恢复、可渐进加载的闭环。

项目由两套互补系统构成：

- **Skills System**：按需加载，负责“这项工作具体怎么做、产物是什么、由谁验收”。
- **Behavior Runtime**：通过 Harness 生命周期 Hook 横切任务，负责“执行时必须遵循哪些行为、何时提醒，以及如何通过结构化输入检查、非执行式命令规范化、声明式风险策略和可选语义复核处理高风险动作”。

> 目标不是让 Agent 自动“写出一篇论文”，而是让问题、假设、证据、失败、决策、风险、权限和人工审批都有明确归属。

当前发行版提供 **12 个顶层 Skill、7 个 Behavior Pack、1 个通用行为内核、3 个内部组件、三类 Harness 适配器、Sub-Agent/多模型路由、Capability Proposal、安全清理与研究看板**。

## 快速开始

建议先初始化目标项目，再安装项目级 Skills、原生 Agent 和 Behavior Runtime：

```bash
git clone git@github.com:hungryDodo/researchops-toolkit.git
cd researchops-toolkit

python3 -m rops bootstrap /path/to/project \
  --title "My Research Project" \
  --upgrade

python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --bundle research-core \
  --with-agents \
  --with-behavior \
  --behavior-mode guide

python3 -m rops doctor \
  --target codex \
  --project /path/to/project
```

检查 Behavior Runtime：

```bash
python3 -m rops behavior --root /path/to/project status
python3 -m rops behavior --root /path/to/project classify \
  --text "Refactor this parser and add regression tests"
```

启动研究看板：

```bash
python3 -m rops dashboard serve \
  --root /path/to/project \
  --port 8765
```

完整安装、Hook 信任提示、模式选择与多框架说明见 [快速开始](docs/getting-started.md)。

也可以从公开仓库安装分发层：Gemini CLI 会自动发现根目录的 Skills 与 `hooks/hooks.json`；Claude Code 可使用仓库中的 marketplace。Codex 当前推荐继续使用上面的项目级 `rops install` 路径，因为它能明确生成项目 Hook、Skill 和 Agent 配置，并避开不同版本本地 marketplace 对仓库根插件路径支持不一致的问题。

## 第三方模型与 Model Control Plane

第三方模型接入不是新的常驻顶层 Skill，而是 `adaptive-agent-orchestration` 的低频 onboarding 模式，配合非 Skill 的 `model-control-plane` 组件。Agent 可以根据用户给出的 provider 和目标模型查阅当前官方文档、生成不含秘密的接入计划、准备 probe/smoke；用户只需在本机环境变量或 `~/.config/rops/secrets.env` 中填写 Key，再让 Agent 继续验证和注册。

```bash
python3 -m rops models recipes
python3 -m rops models --root /path/to/project onboard \
  --provider anthropic --model <verified-model-id> \
  --capability review --risk-ceiling low \
  --agent independent_reviewer

python3 -m rops models secret-template --provider anthropic --write
# 用户在 Harness 外本地填写 Key，然后：
python3 -m rops models doctor --provider anthropic
python3 -m rops models --root /path/to/project probe \
  --plan <onboarding-plan.json> --enroll
```

Key 不得写入聊天、仓库、Skill、`.research/` 或命令行参数。连通性 probe 和 smoke 不会训练模型画像；只有经过确定性验收或独立 verifier 的真实任务结果才会更新档案。反复出现的弱点会生成模型专属提示词 proposal，必须由人批准后才会自动注入后续派发。详见 [Sub-Agent 与模型路由](docs/agents-and-model-routing.md)。

## 两个控制面，四层结构

```text
Plugin / Extension                         分发 Skills、Hooks 与元数据
          │
          ▼
Behavior Runtime + Harness Hooks           生命周期拦截、任务分类、提示与分层风险评估
          │
          ├── Universal Kernel             所有任务的范围、证据、状态、权限和审批原则
          └── Task Behavior Packs          编码、研究、写作、硬件、清理、委派等横切策略
          │
          ▼
Progressive Skills                         具体流程、脚本、references、产物合同与验收
          │
          ▼
Platform permissions / sandbox             最终工具权限和安全边界
```

**MCP 不承担强制行为控制。** MCP 适合外部工具和共享状态，但模型可以选择不调用某个 MCP 工具；必须执行的横切策略应放在 Hook、middleware、权限和紧凑常驻策略中。

### Behavior Runtime 模式

| 模式 | 行为 |
|---|---|
| `off` | 不注入、不记录、不决策 |
| `observe` | 仅进行元数据级分类和审计 |
| `guide` | 默认；注入紧凑任务策略并提出 Proposal，不阻断普通工作 |
| `enforce` | 在 `guide` 基础上，对静态或语义层识别出的高/严重风险执行 fail-closed，并要求内容绑定的一次性批准（不可批准类别除外） |

`enforce` 不是平台 sandbox 的替代品。Hook 只处理它实际覆盖到的生命周期事件，最终权限仍由 Codex、Claude Code、Gemini CLI 或外层 Harness 管理。

## 行为内核与 Behavior Packs

通用内核适用于所有任务：

- 保持请求范围，不顺手重写无关部分；
- 区分已观测证据、推断、Proposal 和未验证结论；
- 将关键决策与证据写入 `.research/`，不依赖聊天记忆；
- 高后果动作先提 Proposal，再进入专家流程和操作审批；
- 使用最小权限、最窄写范围和最小充分上下文。

任务特定 Pack 包括：

| Pack | 作用 |
|---|---|
| `coding-minimal-change` | Ponytail 风格的最小充分改动、复用优先和依赖克制 |
| `coding-evidence` | old-coder 风格的行为合同、RED/GREEN、风险校准验证和 fresh evidence |
| `research-integrity` | 假设、协议、负结果、来源状态与 Claim–Evidence 分离 |
| `writing-claim-discipline` | 让学术措辞与现有证据强度一致 |
| `hardware-safety` | 拓扑、供电、校准、租约、恢复与物理确认 |
| `hygiene-archive-first` | 先盘点和可恢复归档，再独立批准永久清除 |
| `delegation-quality` | 有边界的委派、资源隔离、独立验收和模型画像 |

这些 Pack 不是用户路由的顶层 Skill，也不会与 12 个 Skill 竞争触发；它们由 Hook 根据任务和活跃 Skill 选择性注入。

## 仓库结构

```text
researchops-toolkit/
├── behavior/               # 通用内核、7 个 Behavior Pack、分类/风险 runtime 与 eval
├── hooks/                  # 共享 Hook 可执行文件与平台专用生命周期清单
├── .codex-plugin/          # Codex 插件分发元数据
├── .claude-plugin/         # Claude Code 插件与 marketplace 元数据
├── gemini-extension.json   # Gemini CLI 扩展元数据
├── skills/                 # 12 个可渐进加载的顶层 Skill
├── components/             # evidence-ledger、dashboard、model-control-plane；不参与语义触发
├── rops/                    # 统一跨平台 CLI 与项目/行为/质量/发布模块
├── config/                 # 框架路径、bundles、触发、proposal 与产物合同
├── catalog/                # 生成式 Skill 目录
├── tests/                  # Trigger fixture、Behavior eval 与端到端 smoke test
├── templates/              # 项目级常驻 Agent 策略模板
├── release/                # 发布验证与内部文件哈希
└── docs/                   # 稳定的用户和维护文档
```

初始化后的目标项目以 `.research/` 为研究权威状态，以 `.researchops/` 保存可替换的 Behavior Runtime 副本和 Hook 入口。

## 文档导航

| 文档 | 适用场景 |
|---|---|
| [Docs 索引](docs/README.md) | 人类或 Agent 第一次进入仓库的最短阅读路径 |
| [快速开始](docs/getting-started.md) | 安装、初始化、Hook 信任、模式和多设备部署 |
| [架构与状态模型](docs/architecture.md) | 两个控制面、四层结构、目录和权威状态 |
| [Behavior Runtime](docs/behavior-runtime.md) | Pack、Hook、模式、批准、隐私和适配边界 |
| [研究工作流](docs/workflows.md) | 阶段、Gate、证据状态、Capability Proposal 与交接 |
| [Skills 与 Bundles](docs/skills-and-bundles.md) | 12 个 Skill、渐进加载、触发和颗粒度 |
| [Sub-Agent 与模型路由](docs/agents-and-model-routing.md) | 弱模型、第三方模型、独立验收和模型画像 |
| [安全、归档与清理](docs/safety-and-hygiene.md) | 硬件、Archive-first、两阶段删除、worktree 和隐私 |
| [开发与发布](docs/development.md) | 新 Skill、Behavior Pack、Harness 适配、测试和发布 |

根目录 [`AGENTS.md`](AGENTS.md) 为直接进入本仓库的编程 Agent 提供最短阅读顺序和修改约束。

## 12 个顶层 Skill

| Skill | 主要职责 |
|---|---|
| `research-program-orchestrator` | 生命周期、阶段 Gate、下一步、证据/看板和能力建议 |
| `research-discovery` | Survey、closest work、Related Work 与可信语料综合 |
| `research-route-evaluator` | Idea 致命缺陷、资源匹配、Top 1–3 路线与最小验证 |
| `experimental-research` | 软件实验设计、执行、分析和可复现实证 |
| `hardware-experiment-loop` | 硬件拓扑、安全、校准、租约与恢复 |
| `research-engineering` | 影响研究结论的代码变更：SPEC → RED → GREEN → Gauntlet |
| `adaptive-agent-orchestration` | 第三方模型接入、Sub-Agent 拆分、模型路由、独立验收和模型画像 |
| `research-validation` | 独立复现、artifact audit 和论文 red-team review |
| `research-writing` | 证据门控写作、LaTeX 修订、反馈 ledger 与视觉检查 |
| `research-communication` | 学术插图、结果图和研究型 PPT |
| `project-hygiene` | Archive-first、数据/日志、worktree、临时测试与两阶段 purge |
| `skill-system-engineering` | Skill/Pack 创建、合并、触发、安全、来源和 Harness 适配 |

## 分层风险护栏与批准

Behavior Runtime 不再把正则表达式当作主要安全机制。暴露给 Hook 的工具调用依次经过：

1. **结构化工具输入检查**：区分真实命令、文件路径、补丁正文和普通文档内容；
2. **非执行式 Shell 解析与规范化**：识别可执行文件路径、`sudo/env/busybox/timeout` 等包装器、长/短/分离选项、嵌套 `sh -c`、`xargs` 和 `find -exec`，但绝不执行 alias、变量或任意命令替换；
3. **声明式风险类别策略**：覆盖递归删除、直接覆写与设备写入、递归权限修改、Git 强推/历史重写、特权容器、文件系统管理、持久化、数据外发与隧道、远程代码执行、资源耗尽、系统电源、硬件写入和策略绕过；
4. **可选语义 Reviewer**：用于发现藏在通用解释器、动态代码或未知工具中的副作用。它只能增加或升级风险，不能清除静态命中。

不执行命令即可查看规范化和规则命中：

```bash
python3 -m rops behavior --root . analyze \
  --command 'sudo /bin/rm --recursive --force /data'
```

语义 Reviewer 必须由用户显式启用；启用后，原始工具输入会发送到用户指定的本地或已批准端点：

```bash
python3 -m rops behavior --root . semantic \
  --mode advisory \
  --scope uncertain \
  --command 'python3 /path/to/reviewer.py'
```

能力提醒与操作批准仍然分离：

```text
轻量发现 → Proposal → 用户批准加载 Specialist → Specialist 获取真正操作批准
```

`enforce` 模式下，可批准风险还需要短时、一次性的内容绑定批准。批准同时绑定风险类别、原始命令哈希、规范化命令哈希和精确规则集合，不能通过改写等价命令复用：

```bash
python3 -m rops behavior --root . approve \
  --kind hardware-write \
  --command 'nrfjprog --program app.hex --reset' \
  --reason 'topology and recovery plan reviewed' \
  --ttl 15
```

批准必须由 Harness 外的人类交互终端创建；Agent 自行修改批准账本、关闭运行时或调用批准命令会被识别为不可批准的 `policy-bypass`。这仍然是护栏而非完整命令沙箱，最终边界由平台权限、OS/容器隔离、仓库保护、硬件联锁和人工确认共同构成。

## 设计参考与致谢

本项目阅读并拆解了以下开源项目、规范和平台文档。我们学习的是解决问题的方式、Skill/Harness 组织、生命周期控制、验证边界和工作流思想；**本发行包没有复制、修改或 vendor 这些项目的 Skill、Prompt、脚本、Hook、模板、Handbook 或视觉资源**。实现均针对本项目重新编写。机器可读声明见 [`PROVENANCE.json`](PROVENANCE.json)。

| 项目 / 文档 | 主要启发 |
|---|---|
| Orchestra Research AI-research-SKILLs | 模块化研究能力和 AutoResearch 风格执行 |
| OpenJudge | 独立 evaluator、弱点分析与验收分离 |
| ARS-Codex、phd-skills、CCFA-Skills | 学术生命周期、研究诚信、owner/trigger/artifact contract |
| old-coder | SPEC、observed RED、minimum GREEN、Gauntlet、fresh evidence |
| Ponytail | 横切编码行为、最小充分改动、依赖预算和 Sub-Agent 传播 |
| revise-paper | LaTeX 源码与 PDF 双权威、反馈驱动修订 |
| ResearchStudio-Idea、Supervisor-Skills | 磁盘状态、干净上下文 worker、fatal-flaw gate、证据门控写作与范式感知审稿 |
| Anthropic Skills、Google Skills、Agent Skills 规范 | 自包含 Skill、渐进披露、选择性安装和评测飞轮 |
| Codex、Claude Code、Gemini CLI Hook/插件文档 | 生命周期事件、上下文注入、PreTool 决策、Sub-Agent 传播、信任与权限边界 |
| LangChain Agent Middleware | before/after agent/model、tool wrapping、guardrail 与执行状态拦截的分层思路 |
| distill-design | 仅保留“紧凑可复用视觉合同”的抽象，不采用 URL/品牌蒸馏 |
| LiteLLM、OpenAI Agents SDK | 可选 provider 统一、handoff、trace 和 human-in-the-loop |

外部项目仍受各自许可证约束；未来如 vendor 第三方实现，必须固定 commit、保留许可证、审计执行/网络行为并更新 provenance。

## 验证

```bash
python3 -m rops validate
python3 -m rops validate --smoke
python3 -m rops package --out /tmp/researchops-toolkit-release
```

这些检查覆盖 Skill 结构、Trigger fixture、Behavior Pack eval、134 条高风险/相邻安全对抗用例、Hook/扩展清单、父任务到 Sub-Agent 的策略传播、并发内容绑定一次性批准、可选语义复核、元数据日志、跨框架安装、模型路由、归档恢复、两阶段清除、worktree 保护和内部文件哈希。它们不等价于所有 Harness/模型版本上的真实语义触发准确率，也不保证某个研究方向必然达到顶会水平。

## License

ResearchOps Toolkit 采用 [MIT License](LICENSE)。
