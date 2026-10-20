# Agent 效率配对证据

[English](agent-efficiency-upgrade.md)

本流程与已完成的 2026-10-17 Host 政策基准为
[Issue #1159](https://github.com/yyjeqhc/webcodex/issues/1159) 提供证据。基准包含九对、
18 个合格真实模型样本；它不证明生产环境存在低效，也不完成父 Issue 的四阶段范围。收集器复用
`agent_loop_benchmark` 的样本生命周期、夹具判定器和运行时门禁，以及
`agent_loop_report` 的比较逻辑。未使用可选效率身份字段的既有报告仍然可用。

知识/Skill 采用使用独立、显式选择的[验收协议](knowledge-skill-acceptance.zh-CN.md)。
新用例及获准的补采不替代或重复计入原有 18 个历史样本。

## 运行相同的三个任务

检出待测源码的精确 HEAD 提交。收集器从该提交读取用例清单，为每个样本创建新的
分离工作树，固定运行 `readonly_review`、`guarded_multi_file_edit` 和
`long_validation_handoff`。默认每个任务三对，共 18 个样本，依次交替 Direct →
Host Code Mode 与 Host Code Mode → Direct。配对次数限制为 1–10；每个驱动沿用
30 分钟的进程组超时限制。工作树、回执和注解位于同一个受控临时目录，成功、失败
或初始化异常时均清理。

长验证任务使用公开的验证选项，由 Server 控制同步等待到 Job 交接的时机，不要求
未公开的客户端计时提示。两臂须采用相同计时政策；仍须取得真实 pending Job，
在其实际完成前开展独立工作，并观察同一 Job 成功结束。历史提示、指纹及获准的
契约注记须保留：省略 `sync_wait_secs` 不证明早先明确要求的一秒等待已经通过。
清单变更会产生新的用例指纹，不能混入冻结的基准样本。

调用者须提供真实的在线 ChatGPT Host 驱动。它应为每个工作区建立新的 ChatGPT
任务或会话，提交用例提示，并保留该任务实际的 WebCodex 审计证据。Direct 直接
调用获准的 WebCodex 工具。Host Code Mode 通过 Host 的 JavaScript 编排相同工具，
遵守原有权限和 Job 生命周期；不能用 WebCodex 嵌套 `execute_*_code_mode` 代替 Host
通道。Job 后续操作使用外层 Job 工具。脚本化 MCP 驱动或模拟模型只能验证收集器，
不能充当真实模型证据。

开始前，在外部固定模型与配置记录，包括实际模型标识、Host 版本、推理设置、任务
指令、工具暴露、权限配置及相关 Server/Runner 构建身份。对稳定序列化后的记录计算
SHA-256，传入精确的小写 64 位十六进制摘要，并与实验证据一同保存安全的记录。
摘要与驱动声明都不能独立证明实际运行的模型。公开记录不能包含凭据、私密指令、
载荷或私密推理。驱动必须根据实际配置检查并填写声明，不能直接照抄期望值。

```sh
python3 scripts/agent_efficiency_benchmark.py \
  --repo . --base-revision "$(git rev-parse HEAD)" \
  --driver-command '/absolute/path/to/live-chatgpt-driver --pinned-config /private/config.json' \
  --model-config-digest '<固定模型和配置记录的 64 位 SHA-256 摘要>' \
  --pairs 3 --output /private/evidence/efficiency.json --strict
```

驱动接收既有 `WEBCODEX_BENCH_*` 环境契约：工作区、用例 ID、提示、variant、surface、
精确基准提交、用例指纹和回执路径。它应写入既有的有界结果回执，包括状态、选定的
审计数据库与工作流会话、正确性与验证结论，以及可选的修复注解。此外必须包含以下
精确的 `efficiency_attestation` 字段（以下为占位值）：

```json
{
  "efficiency_attestation": {
    "model_config_digest": "<固定的 64 位 SHA-256 摘要>",
    "base_revision": "<精确的 40 位提交>",
    "case_fingerprint": "<WEBCODEX_BENCH_CASE_FINGERPRINT>",
    "variant": "host_code_mode",
    "surface": "host_code_mode"
  }
}
```

Direct 使用 `variant=direct,surface=direct`。字段缺失、多余或不匹配都会使样本失败，
且不会回显意外的回执值。回执必须是普通文件，上限 64 KiB。不能写入私密模型文本、
原始工具参数或载荷。输出包含安全的聚合摘要，不包含原始回执或驱动标准输出与错误。

`--experimental-nested` 添加独立的 WebCodex 嵌套 Code Mode 比较组，并为其单独运行
新的 Direct 对照（三对时共 36 个样本）。嵌套 surface 来自固定用例定义，不替换或混合
默认 Host 结果。整个实验须保持相同的模型和配置摘要；配置发生变化时另开实验。

## 自由工具选型回归

第二阶段依赖已合并 [PR #1162](https://github.com/yyjeqhc/webcodex/pull/1162) 的通用运行时
证据验收工作，该工作已包含在 main 中。固定三任务、每任务三对的效率套件之外，默认 `tool_selection` 实验运行
四个有界只读场景：`selection_single_read`、`selection_batch_read`、
`selection_cross_tool_review` 和 `selection_compound_source_context`。新增场景要求模型
定位从文本匹配生成源码上下文读取的实现，依据当前源码及测试解释重叠合并、读取数量
限制、字节预算回退与零匹配行为，并注明出处。提示不指定工具或调用顺序。现有规范
复合工具为 `search_file_context`；分别搜索和读取同样允许，返回上下文充分时无需再次读取。

```sh
python3 scripts/agent_loop_benchmark.py \
  --experiment tool_selection --repo . --base-revision "$(git rev-parse HEAD)" \
  --driver '/absolute/path/to/live-chatgpt-selection-driver' \
  --samples 3 --output /private/evidence/selection.json --strict
```

运行前须将清单记录在精确待测提交中。上述选型实验为四用例 × 三次重复，不强制配对
通道；效率收集器仍为三任务 × 三对 × 两通道。修复测试与 Session 恢复选型场景仍需
显式选择。完整协议见[选型实验说明](agent-loop-baseline.md#free-tool-selection-experiment)。

四个场景均须保留实际最终答案，并对照待测源码或夹具值独立核验；仓库调查还需独立
核验 Git 状态。文件判定器只检查夹具适用性。调用者提供外部正确性结论：驱动声明
pass、规范调用数或最终夹具本身均不能证明答案正确。收集器没有自动语义答案验证器。
外部正确性缺失时保持 partial，不能严格通过；规范 Audit 元数据缺失同样不能严格通过，
不可用调用数保持 null。单次复合调用与分别搜索、读取均可满足选型运行时契约，但
调用准入检查不证明答案正确或工具选择最优。已有重叠、字节预算与零匹配运行时测试
以及模拟 Audit 回归夹具仅验证契约，不是真实模型行为。本文不声称新增场景已取得
在线测量结果或指引改进。

## 解读证据

严格模式拒绝缺失的用例、组、配对或通道样本，非 pass 状态，缺失或不匹配的身份声明，
失败的夹具判定器，未获证明的运行时与用例契约，以及源码、用例或正确性不可比较的
配对。它会重新计算验收结论，不信任存储的成功标志或样本计数。严格通过不要求所有
可选指标都有数据，也不证明 Host 单元分组或独立验证模型身份。

每个样本与合格配对报告总耗时、WebCodex 外层调用数、序列化工具结果字节数、修复
轮数、外层 `observe_jobs` 调用数与立即 observe 的调度元数据。缺失测量保持 null，
配对分布保留缺失与观测计数。收集器耗时包含 Host 驱动编排；外层调用不是模型轮数；
结果字节数不是完整网络流量；立即 observe 不证明多余 observe。差值是候选减 Direct，
p50/p95 为描述性的最近秩统计，不是置信区间或提速结论。

热点候选依次根据观测到的参数或工具选择修复、同类串行 Window 调用，以及失败已
交付后仍发生的显式 observe 排序。串行代理不能证明不必要的微调用。当前安全摘要不能
证明相同内容被重复读取，因此不会虚构重复读取结论。失败交付后的 observe 也须进一步检查必要性，
才能提出改进建议。调用次数低不能单独证明成功或效率。提出具体工具契约或指引
改进前，先检查真实候选证据，再在修改后的当前提交重复相同的三对实验，保持正确性
和运行时门禁。下文完成的基准不证明生产效率收益。单元夹具仅验证收集与拒绝行为。

一次真实 ChatGPT 尝试在 Server/Runner 对齐于 `d54e21b19d26` 时，向 `cargo_test`
传入 `_wc.compact_execution`。调用包校验在派发前返回 `-32602`，没有启动 Job；
该尝试保留为不完整样本。现在，不支持字段的错误会依据现有允许列表，列出目标工具
支持的 `_wc` 字段名，无字段时显示 `none`，不回显参数值。直接调用与网关回归均验证
拒绝发生在 Job 创建之前。此反馈修改通过 26 项聚焦运行时测试，但未部署到本次基准；真实模型恢复及效率影响仍未验收。

## Host 单调用与组合政策对照

网页仅经 `functions.exec` 暴露插件时，单元里只有一次 WebCodex 调用仍是 Host
调用，不能充当 Direct。原 Direct 对照继续标记未验收。新增独立模式
`--experiment host_cell_policy`；默认 `direct_vs_host` 保持兼容，不得与
`--experimental-nested` 混用。

新模式比较 `host_single_call` 与 `host_composition_allowed`，仍为三个任务、
各三对交替顺序，共18样本。两臂真实 `variant` 和 `surface` 均为 `host_code_mode`，
另设 policy 字段，经 `WEBCODEX_BENCH_HOST_CELL_POLICY` 传给 driver。
组合臂允许组合或并行，不强迫制造组合；是否实际组合须另看证据。
差值使用 `candidate_minus_baseline`，不冒称存在 Direct。

receipt 须包含闭合 `host_cell_attestation`：`policy`、
`source="caller_ui_attestation"`、`ui_evidence_sha256`、
`complete_tool_call_coverage=true`、`cells`。每个 cell 只含 `cell_id_sha256`
与 `tool_trace_ids_sha256`。单元及调用身份不得重复，所有被测 outer tool 调用
恰好覆盖一次；单调用臂每 cell 恰一调用，组合臂允许一个或多个。
私下保留可审查 UI 单元证据。哈希本身不独立证明执行或分组，报告明确记录 caller
声明及 `independently_verified=false`。Audit 只能证明规范调用，不能证明 Host
单元或模型轮数；不可由 Window、时间邻近或 Audit 顺序推断分组。重复同名同参数
同结果的调用无法唯一关联时保持 partial，不能按位置硬配。

新 strict 独立拒绝 Direct 混入、模式混用、缺样本、政策变化、缺 UI 证据、运行时
及 fixture 失败、身份或 case/source 不兼容；report 为 Host 政策提供明确相容规则，
不改写摘要伪装 Direct。未知 bytes、repair、模型轮数继续未知，合成测试不证明真实收益。

人工 bridge 在没有独立 UI 任务起止证据时明确写 `task_timing:null`。
字段缺省仍保留原自动 driver 的耗时回填；显式 null 则保持未知。人工复制、等待与
操作员复核时间不能当作模型任务耗时。Audit observed span 只是另一代理指标，不能
据此宣称整体加速。私有纯 JS 指纹助手正式采样前必须先通过单独真实 Host 只读 probe；
本地 JS 测试不能替代该证据。

## 已完成的 Host 政策基准：2026-10-17

Direct 暴露不可用，因此采用获准的替代实验，在真实 ChatGPT 任务中比较
`host_single_call` 与 `host_composition_allowed`：三任务 × 三对 × 两政策，
18 个样本、九对均独立通过未修改的运行时、任务和调用者证据门禁。Direct 仍未验收，
未运行嵌套 Code Mode。冻结夹具源码为
`29c906b8a624d315992f7a48d6f1a9a28593721d`，干净且对齐的 Server/Runner
源码为 `d54e21b19d26c3852cf4f9abd723e3e5f13353eb`。
调用者声明 ChatGPT UI 选项为 GPT-6、extreme 推理；后端模型身份未知，这不构成
独立的模型身份验证。

验收要求完整的规范 Audit 与夹具检查、外部任务正确性核验，以及覆盖每个实际外层
调用的唯一调用者 UI 映射。长验证样本还须证明真实 pending Job、在其权威记录的
实际结束前开展独立读取，并观察同一个 Job 以退出码 0 进入终态。驱动 pass 标记或
最终文件本身均不能满足这些门禁。Host 单元分组仍是调用者声明，
`independently_verified=false`。

旧版明确要求的一秒 `sync_wait_secs` 设置不可用，也未公开发布。首个长任务样本后，
用户明确批准使用 Server 默认十秒政策。原始提示、指纹、拒绝记录及批准注记均保留；
不声称一秒要求通过。十次退役无效尝试、两次未使用准备和两份已被替代且作废的证明
均保留并排除。精确样本工作区及原始材料清理前，已保留私有验证事实。

表内每格为 **单调用 / 允许组合**。调用数为规范 WebCodex 外层调用数，字节数为
序列化工具结果字节数，observe 为外层 `observe_jobs` 调用数。这些整数依次来自
合格配对的 `outer_calls.total`、`results.serialized_tool_result_bytes.total` 与
`efficiency.job_observe_calls` 的 `baseline` / `candidate` 值；配对从 1 编号。

| 任务 | 配对 | 调用数 | 结果字节数 | Job observe 数 | 声明的非空单元数 |
| --- | --- | --- | --- | --- | --- |
| `readonly_review` | 1 | 9 / 9 | 163,826 / 208,012 | 0 / 0 | 9 / 6 |
| `readonly_review` | 2 | 13 / 10 | 171,795 / 209,455 | 0 / 0 | 13 / 7 |
| `readonly_review` | 3 | 9 / 9 | 177,812 / 221,575 | 0 / 0 | 9 / 6 |
| `guarded_multi_file_edit` | 1 | 6 / 6 | 25,576 / 25,627 | 0 / 0 | 6 / 5 |
| `guarded_multi_file_edit` | 2 | 6 / 6 | 25,576 / 25,576 | 0 / 0 | 6 / 6 |
| `guarded_multi_file_edit` | 3 | 6 / 6 | 26,613 / 25,464 | 0 / 0 | 6 / 6 |
| `long_validation_handoff` | 1 | 10 / 8 | 91,903 / 84,197 | 2 / 2 | 10 / 8 |
| `long_validation_handoff` | 2 | 7 / 6 | 64,934 / 79,107 | 1 / 1 | 7 / 6 |
| `long_validation_handoff` | 3 | 6 / 6 | 81,267 / 78,373 | 1 / 1 | 6 / 6 |

每个样本的任务耗时和修复轮数均为 null。所有配对两臂的立即 observe 计数均为零，
这本身不证明调度最优。非空单元数由调用者声明，未经独立验证。调用者另报告只读配对 1 的组合臂、
只读配对 2 的单调用臂和长验证配对 2–3 的单调用臂各有一个空 Host 单元；
其余空单元计数未知。

每对内部的采集方式相同，但配对之间有变化。只读配对 1–2 使用 `original_v4`
回执指引；只读配对 3 及所有其余配对使用 `verbatim-recursion-reminder-v1`。
仅长验证配对 2–3 使用 `cargo-and-receipt-preflight-v2`；其余均为
`no_dispatch_guard`。这些采集变化不是产品收益。表格只支持逐对描述，不作汇总
因果、提速或 p95 结论。

助手源码的逐字指令遵循为 false。多文件编辑配对 3 单调用臂的 `review_changes`
单元中，未使用的 `read_files` 分支缺少字段；只读配对 3 单调用臂的 c09 单元改变了
实际执行的 `wcProject` 分支顺序。所有实际执行回执均已精确映射，但其余原始 Host
代码与完整源码语义等价性仍未验证。合格结果证明运行时与任务回执，不证明完整协议
源码合规，也不证明所有试次逐字使用了助手代码。独立的四用例自由选型实验在此没有
在线结果。上文支持 `_wc` 字段名的反馈修复未部署到本次基准，真实模型恢复或效率
收益仍未验证。本基准向父 Issue 提供证据，不关闭其剩余阶段。
