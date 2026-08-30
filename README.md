# Video Production Toolkit

一个面向中文口播与教程类知识视频的 Codex 插件。它把脚本、真实配音时序、视觉方案、分镜、素材生产、时间线装配、结构校验和审阅拆成可恢复、可审批、可追踪的工作流。

当前版本：`0.3.0`

### 0.3.0 重点

- 通过确定性 Python 校验器把完整任务合同投影为不超过 8 KiB 的 compact task packet。
- 生产以同章节连续 4–6 镜为常规批次，每批使用干净子代理上下文。
- 全片真实配音时序、关键词和场景时序冻结后才允许生产。
- 时长、A/V、黑帧、cue 顺序和 JSON 由批量脚本检查，模型只接收紧凑失败摘要。

## 主要能力

- 从主题、脚本、配音或 A-roll 开始规划知识视频
- 支持用户上传配音，或在明确批准后使用 ChatCut TTS
- 把已批准的语义节拍绑定到真实配音时间锚点，而不是依赖估算时长
- 在进入分镜和生产前校验时序；修复任务只能处理明确列出的有限问题
- 通过 Style Pack、Layout Pack 和 Scene Contract 固化视觉决策
- 为视觉媒体生成与检查创建隔离、限界且可验证的任务上下文
- 协调器只接收元数据和紧凑审阅交接，不读取图片或其他媒体载荷
- 将批准后的素材装配到可编辑时间线
- 校验路径、时长、空隙、重叠、安全区、素材血缘和审批状态
- 生成轻量审阅包，并把修改意见映射回版本化输入
- 使用不可变产物、事件日志和任务状态支持中断恢复与局部重建

## 工作流

`video-director` 每次只路由一个已就绪任务，不直接生成或处理媒体：

```text
项目初始化
  → 旁白规划
  → 视觉方向预览与批准
  → 配音来源批准与真实配音时长
  → 语义节拍冻结并绑定时间锚点
  → 时序校验与有限修复
  → 分镜与场景时序合同批准
  → 代表性片段批准
  → 完整素材生产
  → 可编辑时间线装配
  → 结构校验
  → 审阅包
```

关键创意决策会持久化为审批产物。缺少审批、时间血缘不一致、输入过期、合同不匹配或项目状态无法重放时，协调器会停止，而不是猜测后继续。

### 0.2.0 重点

- 新增 `semantic-beats`、`timed-semantic-beats`、场景时序合同和时序校验合同
- 生产任务必须引用已批准、可验证的真实配音时间血缘
- 时序问题以有限摘要进入修复任务，修复结果必须重新通过权威校验
- 视觉任务使用封闭的媒体上下文，限定作用域、输入、产物路径和审阅预览
- 恢复项目时会重新验证视觉隔离与时序权威性，失效结果不能继续流入生产
- 插件清单包含发布指纹，用于发现分发包与运行时副本漂移

## 内置 Skills

| Skill | 职责 |
| --- | --- |
| `video-director` | 读取紧凑项目状态，每次路由一个合法任务 |
| `video-project-manager` | 初始化或恢复项目，管理事件、版本与失效传播 |
| `narration-planner` | 规划旁白、语义节拍和证据需求 |
| `voiceover-producer` | 准备上传配音或已批准的 ChatCut TTS，并发布真实时长 |
| `visual-system-designer` | 定义 Style Pack、Layout Pack 和低成本方向预览 |
| `storyboard-director` | 生成视觉编排与不可变 Scene Contract |
| `scene-producer` | 按同章节 4–6 镜的精确合同批次生产场景或视觉素材 |
| `motion-director` | 选择动效预览，并委派已批准的可编辑动效生产 |
| `timeline-assembler` | 装配配音、字幕、素材与动效，不重新设计 |
| `structural-validator` | 执行客观结构校验，不做主观审美判断 |
| `video-review-packager` | 生成紧凑审阅材料并路由反馈 |

## 安装

需要 Python 3.9+ 和支持个人插件目录的 Codex Desktop。ChatCut、HyperFrames、Remotion 与 VideoShotCraft 都是按任务选用的可选适配器。

克隆仓库：

```bash
git clone https://github.com/Fantasy421/video-production-toolkit.git
cd video-production-toolkit
```

先校验插件包：

```bash
python3 scripts/validate_package.py
```

注册到个人插件目录。开发时推荐 `link`，仓库更新后不需要重复复制：

```bash
python3 scripts/install_personal_plugin.py --source "$PWD" --mode link
```

然后重启 Codex，在 Plugins Directory 中安装并启用 `video-production-toolkit`。

如果希望插件副本不依赖仓库当前位置，使用 `copy`：

```bash
python3 scripts/install_personal_plugin.py --source "$PWD" --mode copy
```

如果同 ID 插件已经存在，可显式替换；旧版本会先保存到可恢复的备份目录：

```bash
python3 scripts/install_personal_plugin.py \
  --source "$PWD" \
  --mode link \
  --replace
```

## 快速开始

初始化一个项目：

```bash
python3 scripts/init_project.py ./projects/demo \
  --project-id demo \
  --workflow knowledge-video
```

随后在 Codex 中描述你的输入和目标，例如：

```text
用 Video Production Toolkit 把这份中文口播稿做成一条可编辑的知识视频。
先规划旁白和视觉方向，每个审批点都等我确认再继续。
```

插件会根据项目阶段选择下一项合法任务。它不会绕过视觉方向、配音来源、时间节拍、分镜或代表性片段等审批门。提供脚本或音频时，建议同时说明目标平台、画幅、期望时长、是否保留 A-roll，以及允许使用哪些可选适配器。

## 可选适配器

仓库包含 ChatCut、HyperFrames、Remotion 和 VideoShotCraft 的适配器声明。它们只会在对应 Skill 已安装、能力匹配且任务合同明确允许时被选择：

- ChatCut：配音、字幕、可编辑时间线和 Motion Graphics
- HyperFrames：视觉方向与 H5 动效预览
- Remotion：程序化视频与渲染流程
- VideoShotCraft：基于镜头配方的产品视频生产

缺失的可选适配器不会被未声明的工具静默替代。

## 项目结构

```text
.codex-plugin/   插件清单
agents/          Codex 展示信息
skills/          各工作流入口
scripts/         安装、初始化、校验与运行时工具
references/      Schema 与工作流策略
registries/      适配器、样式、布局和配方注册表
assets/          项目与审阅包模板
previews/        样式和布局预览
tests/           单元测试与端到端恢复场景
docs/            迁移与发布记录
```

## 开发与验证

校验分发包：

```bash
python3 scripts/validate_package.py
```

运行测试：

```bash
python3 -m unittest discover -s tests
```

检查本机插件发现、适配器和恢复流程：

```bash
python3 scripts/verify_installation.py --help
```

## 设计原则

- 一次只推进一个任务，避免协调器扇出失控
- 创意决策由用户批准，执行 Skill 不得自行改写
- 媒体生成与检查使用封闭隔离上下文，协调器只处理元数据
- 真实配音时序是分镜、字幕和生产的权威时间来源
- 产物不可变，变更通过新版本和事件传播
- 验证失败时默认停止，不把未知状态当作成功
- 只重建受失效输入影响的场景，保留已批准且仍有效的工作

## 状态

该项目目前面向个人 Codex 插件工作流，接口和 Schema 仍可能随实际视频生产反馈演进。
