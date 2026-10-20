# 通用 Agent 网页验收

[English](agent-generic-web-acceptance.md)

以下记录对应 [Issue #1159](https://github.com/yyjeqhc/webcodex/issues/1159)
第一阶段，是用户协助执行的单次 ChatGPT 网页观察，不是效率配对测量或无人值守续接证明。

## 环境与证据

2026-10-16，专用 ChatGPT 测试连接使用新建 OpenAI Secure MCP Tunnel、隔离的
托管用户、Runner 和一次性 Project。Server/Runner 均报告干净构建
`cff2fe3da102`、版本 0.5.0，构建及源码对齐。用户保持相同的“极高”推理设置；
确切模型标识和浏览器版本不可得，不根据猜测填写。

操作员在模型执行前准备确定性 fixture，检查规范 Audit/trace 元数据，选择确切
记录 Session，再运行独立校验器与最终文件 oracle。仅一次性服务开启 full 捕获。
此处不公开私有 Session ID、机器路径、凭据或原始载荷；普通报告仍只读元数据。

| 案例 | 实际观察 | 独立最终状态证据 |
| --- | --- | --- |
| 失败后修复 | 两次真实执行，退出码 7→0，诊断与末尾标记完整 | 未创建 fixture 文件 |
| pending 与独立工作汇合 | 只启动一个原 Job，关闭 stdin 前创建独立文件，一次 readiness 汇合及终态观察，退出 0 | 独立文件字节精确 |
| 缺失产物 | 一次显式 finish，missing=1、verified=0、blocking fail | 声明 CSV 仍不存在 |
| 旧 revision | 旧编辑被拒绝，操作员确认字节未变，再 fresh-read 并应用一次编辑 | 外部标记完整且仅一次 |
| 混合文件 | 三次 artifact transfer、一次文本 create，保留已有目标 | 四个输入未变、五个目标正确，二进制签名与哈希一致 |
| 编码 CSV | 受控 UTF-8/UTF-16 转换退出 0，两个输出获得 verified 回执 | UTF-8/LF、四行合计 17、JSON 正确、输入哈希未变 |

缺失产物案例通过表示保护生效，不表示缺失的用户产物已交付。CSV 的真实完成
判定保留为**非阻断 `warn`**，含脏工作区/卫生警告与
`validation_inconclusive` / `source_unproven`。独立字节检查不会消除运行时对
验证来源时序稳定性的警告。

## 已复现并修复的校验问题

失败修复案例最初因 Host 的无害排版变化未通过逐字节命令比较；相同捕获在
`32562ad2` 的精确 Python 语法树检查下通过。已保留有界前后对照并删除原始捕获。
这份证据属于 schema-1，不能从已删除载荷重放后来的 schema-2。补充的
Audit/注册 Project 路径检查建立其观察到的 fixture 关联，不追认此前捕获了目录身份。

自检还复现了混合文件及 CSV 仅凭 bootstrap 审计和 driver 直接写出的正确文件
即可误通过的问题。schema-2 现在要求六类案例的真实操作及 fixture/Session/Project
绑定；无 mock 回归拒绝两条 lane 的该负例。本地 MCP/WS 覆盖六类及结构化 CSV
替代路径。这些脚本测试证明运行时机制，不增加真实模型样本数。

实际 CSV Session 在 finish 后执行了只读 `check_workspace_hygiene`，旧规则误判
该顺序。修复保留完整 Session，仅允许这一规范 PureRead 诊断在 finish 后执行；
后置执行、编辑和重复 finish 仍被拒绝。

有界捕获、隐私、不完整证据与支持路径见
[strict 验收契约](../implementation/chat-task-loop.zh-CN.md)。这些观察不能证明
通用模型可靠性、加速效果、浏览器后台调度保证或生产部署完成。
