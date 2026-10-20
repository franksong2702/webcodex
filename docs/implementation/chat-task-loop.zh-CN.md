# ChatGPT 任务执行与证据

[English](chat-task-loop.md)

`work_on_project` 保持严格的 selector 校验。参数组合错误时说明授权发现路径，
不回显被拒的 selector，也不据此判断 Runner 离线：已知项目使用规范 Project
或已签发的 `project_ref`，未知项目使用 `list_projects`；路径必须配合确切的
`client_id`。复杂任务先调查规则和代码、明确可观察的完成条件、展示简短计划，
然后继续已授权执行。默认仍为 `on_demand`，展示计划不会创建持久 Goal。
读取续接沿用原参数；执行结果未知或仍在运行时保留原 Job，先做独立工作，
再汇合确切的阻塞 Job。工具成功、Job 结束、步骤勾选不能证明用户目标完成。

## 隔离验收与严格评测

现有 [评测运行器](../../scripts/agent_loop_benchmark.py) 支持清单中的六个
`generic_agent_disposable_fixture` 案例。每个样本使用普通临时目录；源码 revision
仍固定清单与运行时证据规则。[共享 fixture](../../scripts/e2e_generic_agent_ws.py)
提供有界文件 oracle。Host driver 必须把提供的固定 locale、时区和 Python 环境
应用到经 WebCodex 执行的命令。

通用样本新增 `WEBCODEX_BENCH_TARGET`、`WEBCODEX_BENCH_WORKSPACE`、
`WEBCODEX_BENCH_FIXTURE_ENVIRONMENT`（JSON 子进程环境）、
`WEBCODEX_BENCH_FIXTURE_COMMAND`（指定的失败压力、等待 EOF、冲突复制或 CSV 转换脚本）以及
`WEBCODEX_BENCH_FIXTURE_COORDINATION`（项目外协调目录）。过期读取案例中，
driver 保留确切读取回执后发出 `first-read`，等待 `external-written`，执行旧
revision 的编辑，确认拒绝后发出 `stale-rejected`，等待 `rejection-checked`
再重新读取和完成。外部写入只使用一个已验证的普通文件描述符，不跟随被替换
的符号链接。协调信号本身不是工具选择、权限或执行的运行时证据。

严格验收使用 `--strict`、明确的 `--case-id`，以及强制 lane 的 `--pairs`
或 `--experiment tool_selection --samples`。零退出码要求所选案例和次数完整，
任务及必需验证通过、有运行时 lane 证据、所有可用文件 oracle 通过。
缺失案例、`partial`、`unsupported`、缺失必需证据均不能通过；driver 自报不能
证明执行。

六个通用案例均须同时通过独立 fixture oracle 和
[独立校验器](../../scripts/agent_temporal_evidence.py)的案例专属运行时证明。
只有 bootstrap 的审计、正确的最终文件或 driver 自报 pass 都不能证明执行。
普通报告仍只读取元数据；缺失或无法证明的证据保持 `partial`，捕获结果与要求
矛盾时判失败。

每个通用样本都在可编辑 Project 外创建私有、绑定案例/base/fingerprint 与
fixture 身份的 `WEBCODEX_BENCH_TEMPORAL_TRACE_ROOT`。driver 必须把它配置为
**一次性测试 Server** 的 full trace 目录，并提供审计数据库及规范
`workflow_session_id`（不能使用不透明 Session ref）。使用普通 checkout 模式的
`work_on_project(client_id=..., path=WEBCODEX_BENCH_WORKSPACE)` 进入项目；
校验器核对实际成功 bootstrap 的根、返回 Session、resolved Project 与记录的案例
操作。managed-worktree 模式、其他 cwd/default cwd/resource，以及无法证明路径的
注册 Project 别名均不能建立该绑定；已有注册 Project 仍可用显式 path 形式进入。
相关模型调用使用授权 `_wc.record`；返回回执前停止并排空自有测试服务。不得启用
共享服务捕获，也不得把凭据创建放进模型工具调用。

混合文件案例核验三次实际 artifact transfer 的来源/目标路径、字节数及哈希，另需
提供的冲突保留 note 脚本或对 `sorted/note-2.txt` 的已应用结构化 create。CSV 案例
核验提供的转换脚本或两个确切输出的已应用结构化 create，随后实际 finish receipts
的哈希必须等于独立读取的 fixture 字节，task outcome 也须明确为不阻塞的完成状态。
任意/no-op 脚本、pending 命令、dry-run 编辑或工具数量均不能替代这些操作。
额外验证脚本允许存在，但每次都必须证明真实终态成功，且 CSV 的验证须在最后 finish 前完成；
重复执行受控 mutation 不予放行。非 blocking 的 `pass`/`warn` 可建立 CSV 完成，
`fail`/blocking 不能；缺少明确 task outcome 仍为 `partial`。
不支持输出 receipts 的基线结果仍可读取，但不能通过此 CSV 证明。四类时序案例
保留原有命令、Job、过期 revision 与阻塞 closeout 的实际语义检查及串行顺序边界。
独立文件 transfer 调用可以重叠。CSV closeout 仍须在所有记录的任务操作之后，
唯一新增例外是规范工具 `check_workspace_hygiene`：其 PureRead/project:read 契约
允许 finish 后诊断。该调用仍完整捕获并核验根/Session/Project；不会放行后置执行、
编辑、第二次 finish 或任意观察工具，outcome 与输出哈希规则保持不变。

校验器检查私有普通文件、trace UUID、压缩前后大小及 SHA-256 索引，关联规范
Audit 结果和确切作用域，拒绝未记录调用和不确定顺序，仅读取所选有效参数与最终
MCP 响应。schema-2 proof 只包含封闭检查/可用性原因和协调器生成的 fixture 身份
哈希（规范路径与目录 device/inode，不代表内容新鲜度），且必须匹配本样本 oracle
身份。配对样本使用独立根，不要求两个 fixture 身份相同。旧 schema-1 结果仍可读，
但不会自动获得新的 strict 验收。每个样本结束后删除自有捕获目录，包括失败样本。
捕获哈希只证明本地完整性，不是独立 Host 认证。嵌套 Code Mode 的聚合数量不能证明
案例的逐次参数/结果，仍不足以通过通用 strict；本校验器未新增 nested-child payload 解码。

额外的 `read_session_discussion_summary` 调用仍须通过 Audit、作用域和顺序检查。
捕获参数必须选择当前确切 Session，或由此前成功 bootstrap 明确映射到该 Session
的短 ref。该工具是 Session 观察器，无需 Project 字段或讨论响应；校验器不读取
讨论正文。其他调用仍保留原有 Project 和结果检查。

指定 Python 命令须具有完全相同的语法树；展开循环、改写引号或末尾换行不影响
执行证据。新增或改变语句、注释（包括编码声明）仍被拒绝。检查不会执行捕获的
源码，也不替代真实退出码、诊断、顺序或派发次数要求。

使用 `--candidate host_code_mode` 比较 Direct/Host，两者满足全部门禁时六类
案例均可合格；原有嵌套 `code_mode` 默认保持不变。缺少逐个规范子调用证据时
嵌套案例保持不完整，不能从外层组合计数补造。Host lane 只证明规范运行调用，
不证明同一个 JavaScript cell 或精确模型回合。失败修复使用指定固定脚本；
后台独立工作使用 `from pathlib import Path` 后接
`Path('independent.txt').write_text('independent work completed')`，或针对该文件和
内容的一次确切 `edit_project_files` create，在释放 EOF 前完成。

真实 Server/Runner 确定性 smoke 验证校验器与实际执行链路，不能证明 ChatGPT
选择了正确动作。可执行命令见英文对应文档。

## ChatGPT Host 验收

仅使用隔离临时项目和授权 Runner，直接发送：

> 调查这个 fixture，展示简短计划，修复 `add(a,b)` 返回 a+b，运行提供的失败
> 测试，诊断并修复，再次验证、审阅实际 diff 并交付。无需常规确认继续执行，
> 不得声称未观察到的验证。

应观察到计划、调查、带 revision 的编辑、真实失败与修复、通过的重跑、审阅和
有证据的交付。再加入截断读取、一个长 Job 与独立文件工作：读取使用确切续接，
长 Job 仅启动一次，独立工作后再汇合。跨聊天恢复原 Session，核对事实与当前
源码。错误 selector 应被拒绝并沿授权发现恢复，不应捏造离线判断。缺失产物或
验证证据时应如实报告未完成或 unproven。这些验收依赖真实 Host 观察，独立于
本地传输测试和模拟 driver 测试。
