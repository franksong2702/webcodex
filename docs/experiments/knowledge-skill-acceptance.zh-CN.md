# 项目知识与 Skill 验收

[English](knowledge-skill-acceptance.md)

本协议覆盖 [Issue #1159](https://github.com/yyjeqhc/webcodex/issues/1159)
中的 T01/T02 子范围，在现有 [Agent Loop 采集器](agent-loop-baseline.md)上增加显式选择的样例。
生产工具 API、权限、检索算法和 Memory 不变；默认案例及原有严格通过规则不变。
公开材料只保留合成事实和脱敏结论，原始回答、捕获和操作状态保留在私有目录。
[历史结果报告](knowledge-skill-acceptance-results.zh-CN.md)保留首次尝试、获准补采、测量失败和人工干预。

## 证据差距

| 原有证据 | 已证明 | 尚未证明 | 本轮补充 |
| --- | --- | --- | --- |
| [效率基线](agent-efficiency-upgrade.zh-CN.md)，九对、18 个真实样本 | 冻结 Host 策略任务的正确性合格观察 | 知识/Skill 采用、生产提速或成功率 | 六个独立资源场景，不重新计入原有 18 个样本 |
| 已合并的 [#1160](https://github.com/yyjeqhc/webcodex/pull/1160)、[#1162](https://github.com/yyjeqhc/webcodex/pull/1162)、[#1165](https://github.com/yyjeqhc/webcodex/pull/1165) | 已有增量刷新和采集基础 | 模型实际发现并读取当前项目资源 | 复用基础，观察实际调用 |
| Provider 单测与隔离 MCP/WS smoke | scope、精确 Project binding、越界、变更/删除来源排除、Provider 移除 | Host 工具选择和答案质量 | 独立核验事实、引用和资源链路 |
| 六场景脚本化验收器集成 | 真实 Server/Runner/Provider、捕获结构、受控更新和陈旧读取负例 | 真实模型样本 | 用户辅助的 ChatGPT Web 会话及身份捕获 |

## 冻结样例与独立答案依据

提示保存在 [`agent_loop_cases.json`](../../scripts/agent_loop_cases.json)，
独立答案依据和确定性 Git fixture 由
[`agent_knowledge_fixture.py`](../../scripts/agent_knowledge_fixture.py)维护。
Runner 只暴露样例 checkout，评测代码和答案依据位于其允许根目录之外。
每个样本独立创建 Project、索引缓存、Project Skill、Runner、捕获标记和提示指纹。
近似名称文件含不同事实，知识 Provider cwd 必须精确等于该 fixture 根目录。

| 显式案例 ID | 工具选择口径 | 必需观察 |
| --- | --- | --- |
| `knowledge_identifier` | 自由选择 | 正确的标识符实现和来源行范围，另记 Plugin 采用情况 |
| `knowledge_procedure` | 自由选择 | 当前审计顺序、标记及批量事实，另记 Skill 采用情况 |
| `knowledge_paraphrase` | 要求项目知识资源，不指定函数 | 账簿事实及足够的 hash 绑定摘录 |
| `knowledge_source_update` | 要求项目知识资源 | 首次读取、协调器修改来源、当前事实和来源 hash |
| `knowledge_skill_read` | 要求项目 Skill | 正文及引用资源；接受加载或发现后读取等合法路径 |
| `knowledge_skill_update` | 继续核验所选 Skill | 首次读取、定义变更、新 definition revision 和当前资源事实 |

每个场景使用一次全新的 ChatGPT Web 会话。搜索摘录包含全部所需事实时可作为实际读取，
不要求冗余读取或最优工具序列。两个自由场景可以通过普通文件工具答对，
但不能据此证明 Plugin/Skill 采用；四个定向场景仅使用普通文件时，资源链路判失败。
bootstrap-only 和 driver 自报成功均不能证明通过。
最终 JSON 必须恰好含 `facts`（所要求的 `key=value` 字符串）及
`sources`（项目相对路径和包含两端的行范围）。错误格式或错误事实应如实判为答案失败。
Host 提示明确要求在最终 JSON 之前单独报告 canonical Session ID。
早期已保存提示要求将 ID 与最终 JSON 一同回报，对两者是否分开存在歧义；
保留这些提示的原始答案及冻结规则判断，并在报告中将提示歧义与事实正确性分别说明。
Host 协议进一步明确现有 recorder 契约：在 Project/资源发现前只 bootstrap 一次，保留精确 Session，
相关 MCP 调用通过 `_wc.record` 记录，包括没有业务 `session_id` 参数的调用。
记录元数据不能作为额外业务选择器加入已绑定资源调用。
检查点暂停与确认通过同一个 ChatGPT 对话传递，不通过 UI 卡片或 Session 消息等待操作人员。
v3 将暂停限定为两个更新场景。早期 v2 公共前缀可能造成不必要暂停，须保留原始回复，
并单独记录操作人员的澄清，不将其描述为模型自主完成。
这些说明不指定知识/Skill 工具名或检索顺序。
私有 `ready.json` 记录协议版本与完整提示的 SHA-256。
已获授权的补采保留首轮尝试和结果文件，使用独立输出，并固定自身源码与配置身份。
知识验收器将 Session 控制消息的精确授权目标与文件系统工作分别绑定，
仍核对捕获中的 Window/principal 及返回的 Session 身份；消息不能作为来源读取证据。
通用 Project 绑定与缺失 Window 的拒绝规则保持不变。

两个更新场景在完整首次读取后暂停。协调器独立核对精确 Workflow Session 中的读取，
再修改唯一允许的来源文件，之后模型在原会话继续。
Skill 更新修改定义本身，而非仅修改附属资源。
合法的旧 hash/revision 拒绝作为失败调用保留，不误判为采集缺失。
检查点反馈属于人工干预，须单独报告；它不能替代必需资源的实际读取，也不能证明无辅助恢复。
报告还需描述模型是否识别旧引用失效以及如何恢复；脚本主动触发的陈旧读取仅证明运行时守卫。

## 执行与人工配合

从干净、已提交且包含新 manifest 的源码构建对齐的 dogfood Server/Runner。
仓库之外准备仅所有者可访问的状态目录和 `model.json`：

```json
{
  "host": "chatgpt_web",
  "displayed_model": "实际页面显示名称",
  "displayed_reasoning": "实际页面显示档位",
  "internal_model_id": null,
  "tool_exposure": "专用 WebCodex 连接、冻结源码 manifest",
  "instructions": "新会话、使用样例提供的提示"
}
```

记录实际显示配置，不推测内部模型 ID。driver 对私有记录计算摘要，核对二进制版本、
源码和二进制 hash；结果只保留摘要和有界构建元数据。
人工声明或其摘要均不能独立证明远程实际模型身份。严格验收要求所有样本配置和构建身份一致。
可选布尔配置 `mcp_apps_enabled` 固定 Server 已有的展示设置，默认 `true`。
文本与资源验收可选 `false`，关闭 App 工具和卡片元数据，不改变知识/Skill API、权限或证据门槛。
须将它记录为不同工具暴露配置，不当作可比较的重试。采集前关闭旧测试卡片，避免后台轮询
进入同一 Server 捕获却没有 Workflow Session/Window 身份。这类调用仍阻止严格验收，不增加 UI 豁免。

```sh
python3 scripts/agent_loop_benchmark.py \
  --repo . --base-revision '<完整已提交源码 SHA>' \
  --experiment tool_selection --samples 1 \
  --case-id knowledge_identifier --case-id knowledge_procedure \
  --case-id knowledge_paraphrase --case-id knowledge_source_update \
  --case-id knowledge_skill_read --case-id knowledge_skill_update \
  --driver 'python3 /absolute/checkout/scripts/agent_knowledge_host.py drive --state-dir /private/knowledge-run --bin-dir /absolute/dogfood --model-config /private/knowledge-run/model.json' \
  --output /private/knowledge-run/result.json --strict
```

driver 同时只运行一个隔离的 loopback Server/Runner。
私有 `samples/<sample-id>/ready.json` 标明 Project、路径和精确源码，
`prompt.txt` 是应粘贴到新网页会话的任务。
顺序样本间仅复用本任务专属连接 URL 和认证数据库。
操作人员预先配置的私有 `connection.json` 可在现有 `owner` PAT 之外指定 `username`。
driver 会将样例 Runner 注册到该精确账号，保持 Project 可见性；默认仍为 `knowledge-owner`。
有效授权须由操作人员独立配置；driver 不续期过期授权、不导入 token hash，也不修改原生恢复记录。
复用已有保护记录的 tunnel，须通过受支持的恢复流程沿用原 URL、认证头和日志；
新的评测状态目录不构成绕过旧记录的授权。
通过专用测试 tunnel 和测试凭据，沿用正常
[MCP 连接流程](../MCP.zh-CN.md)及
[原生 tunnel client](../../crates/webcodex-openai-tunnel/README.md)。
Secure MCP Tunnel 在本地使用专属 owner 的有 scope 限制的 PAT 转发至 loopback `/mcp`，
完整本地 authorization header 只放在 owner-only 文件中。
ChatGPT 选择 Tunnel 和 No authentication，不把 bootstrap 凭据粘贴到 ChatGPT。
也可使用 `drive --public-url https://test.example` 配置明确的 HTTPS OAuth origin，
正常 client 配置仍需操作人员完成。driver 不自动登录、创建连接、操作浏览器或执行模型。

所有相关工具调用必须记录到本样例 bootstrap 返回的精确 canonical Workflow Session。
禁止按时间猜测最新 Session。更新场景模型暂停后执行：

```sh
python3 scripts/agent_knowledge_host.py checkpoint \
  --sample-dir /private/knowledge-run/samples/<sample-id> \
  --session '<canonical Session ID>' --trace-id '<已观察到的成功来源读取>'
```

等待 `ready.json` 中私有 coordination 目录出现 `advanced.json` 后，再通知模型继续。
出现 `coordination-failed` 则停止并诊断。禁止手工修改 fixture，也不要悄悄重跑失败样本。
完成时把真实最终 JSON 保存为私有文件，再执行：

```sh
python3 scripts/agent_knowledge_host.py submit \
  --sample-dir /private/knowledge-run/samples/<sample-id> \
  --session '<canonical Session ID>' --answer-file /private/final-answer.json
```

若 Host 只显示错误而没有最终答案，将操作人员的原始观察保存为私有 UTF-8 文本，
用 `--host-failure-file /private/failure.txt` 替代 `--answer-file`。
该路径单独标记操作人员观察，并提交 `answer=null`，不会补造模型 JSON。
Host 未显示 Session 时，从本次尝试的 bootstrap 捕获取得精确 Session。
本地工具成功不能证明 Host 收到或显示了响应，也不能直接归因为模型失败；
捕获或身份不完整仍为 `partial`。

driver 关闭专属服务、保留有界私有捕获后返回候选回执，由父采集器独立判断。
沿用每个 driver 30 分钟进程组限制，须在 29 分钟内提交。
人工中断不能算合格测量。仅关闭本任务拥有的进程，保留已有实验环境。

需要在当前样本结束后保存结果并停止后续采集时，使用 `stop-after-current`，提供
`--state-dir`、`--base-revision`、`--model-config` 和有界 `--reason`。
私有停止请求绑定精确源码和配置，不中断活动样本；后续 driver 在启动 Server、Runner 或模型
会话前返回 `unsupported`。这些未执行案例不计为模型尝试。等待父进程保存原始结果后，
用相同身份执行 `resume-collection` 归档停止请求，再开始独立续采。
不得覆盖此前输出；不同协议版本须分别记录身份和结果。

## 核验与限制

[`agent_knowledge_evidence.py`](../../scripts/agent_knowledge_evidence.py)
复用有界压缩捕获完整性、canonical audit 身份、trace 覆盖及 fixture/Session/Project 核验。
必须观察到实际返回的来源正文、范围、当前 hash/revision、事实引用、精确文件清单和协调器更新顺序。
不允许的修改、错误 Project、缺少捕获、陈旧来源及伪造回执均不能通过。
缺失或歧义证据为 `partial`，已观察到的验收失败为 `fail`，不支持的 adapter 保持 `unsupported`。
原有 strict 失败仍为失败。证据完整、可归因的模型失败是有效测量，但 `--strict` 仍返回非零。

部分 Plugin 参数解析拒绝发生在 Session 记录和 Provider 执行之前。仅当审计中的 Window/principal
精确匹配、原始参数和错误捕获完整、错误为已知校验拒绝、无 Session 关联且没有运行时阶段时，
知识验收器才单独计数。它不算 canonical Session 调用，也不提供来源证据。
未知、其他范围、损坏或包含运行时阶段的捕获仍不完整；通用 trace coverage 保持不变。

native Plugin 捕获会脱敏 opaque binding 和嵌套参数。因此核验结合实际 Project-bound describe、
返回来源 hash、精确 Session 和协调器固定的唯一 Provider，不声称能还原或独立比较已脱敏 binding。
部分 Skill 调用缺少效率遥测，仍用实际 canonical audit operation 和捕获结果证明读取，缺少指标保持未知。
原始捕获和回答始终私有；公开采集器完整结果前仍必须另做脱敏检查。

本地检查命令：

```sh
python3 -B -m unittest scripts.tests.test_agent_loop_benchmark scripts.tests.test_agent_loop_report scripts.tests.test_agent_efficiency_benchmark scripts.tests.test_agent_temporal_evidence scripts.tests.test_agent_knowledge_fixture scripts.tests.test_agent_knowledge_evidence scripts.tests.test_agent_knowledge_benchmark
python3 -B -m unittest discover -s plugins/project-knowledge -p 'test_*.py'
python3 -B scripts/e2e_project_knowledge_ws.py --bin-dir /absolute/dogfood
python3 -B scripts/e2e_agent_knowledge_ws.py --bin-dir /absolute/dogfood --source-revision '<运行时源码 SHA>'
```

最后一条命令主动提供脚本化答案，并明确报告 `model_samples: 0`。
真实报告分别列出六次尝试的事实正确性、资源采用、采集完整性、来源/配置身份及恢复行为。
不可观察的 token、缓存命中、模型轮次和时间保持未知；六个单次样本不用于推断生产成功率或提速。
下一项最小优化应基于实际证据在 #1159 归因，检索调优和 Memory 扩张不属于本协议。
