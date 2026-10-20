# Thread Panel 连续阅读 UI 验收

验收日期：2026-10-02 至 2026-10-03（Asia/Taipei）。

## 源码与复用

- 工作分支：`feat/thread-panel-reading-ui`。
- 基线：`9fced2fdeaae9e18300c11d6fa1b250e71c8c86c`，已继承 #828、#832、#833、#842；没有重复移植已合并的 PR，作者历史保留。
- `117e3895`：连续阅读、文件导航、Diff 行号、折行与阅读状态。
- `e6eb52f8`：真实 ChatGPT 原生入口的线程绑定元数据修复。
- `ec769233`：限制关闭折行后的横向滚动范围；最终程序构建源码为 `ec76923309fb336957eb1b838b84a8116bed0862`。
- 原 `feature/work-result-thread-panel-poc` 分支及主工作区原有修改均保留。后续验收文档提交不改变已测试程序。

## 实现边界

线程侧栏统一随页面纵向滚动。Changed files 与 Final Changes 分别提供吸顶选择器和前后文件导航；导航只包含已加载文件，其余文件通过显式分页加载。Diff 显示旧、新行号，默认折行，关闭折行后由代码区横向滚动。窄屏路径和工具栏可以换行。

相同快照复用已挂载文件节点，保留展开状态、阅读模式及各模式锚点；分页和同快照刷新保持位置。新快照清除旧状态，迟到响应仍经过身份和版本校验。全文、Markdown 安全渲染、懒加载、分页、内容与缓存上限沿用 #842。

没有增加后端 API 或工具参数。真实宿主修复只为已经准入、已经通过身份与 Window/Session 校验的原生线程入口保留绑定元数据，不改变执行权限。当前 App 资源为 `ui://webcodex/work-result/v22`；下文保留的 `v19` 截图名称记录较早的阅读 UI 验收构建，旧资源继续按既有规则失效。

## 自动验证

| 验证 | 结果 |
| --- | --- |
| 嵌入式 App 完整 Node 回归 | 395 项通过 |
| 最终 CSS / 资源版本修正后，重跑 Work Result Node 回归 | 139 项通过 |
| 最终构建相关 Rust：work_result、retired_app_resources、result_app 资源与绑定 | 42 + 1 + 1 项通过 |
| 前端构建、资源产物一致性、Desktop TypeScript / Vite 构建 | 通过 |
| 最终 Rust 格式、Git 空白和冲突检查 | 通过 |

新增回归覆盖文件导航范围、挂载节点保持、Diff hunk 行号和空侧、折行/折叠刷新、各模式锚点、快照变更与异步预览隔离。线程入口测试覆盖有 UI extension 和空 capability 对象两种真实请求形态。

Windows 编译存在原有 unused 警告。一次中间 Rust 测试把整个 clientCapabilities 删除，触发预期协议拒绝；修正测试输入为空 capability 对象后，相关测试全部通过，没有放宽协议或认证。

## 四程序构建

使用 `dogfood` profile，在独立目录产出 Desktop、CLI、Server、Runner。四者均为 0.4.4、同一 `ec769233` 提交、`git_dirty=false`；构建身份完整记录在本地 `target/thread-panel-reading-ui/build-identity.json`。

Desktop 使用 `tauri/custom-protocol` 嵌入已构建的前端资源。程序路径相对于本轮构建目录：

- `desktop/dogfood/webcodex-desktop.exe`
- `runtime/dogfood/webcodex.exe`
- `runtime/dogfood/webcodex-server.exe`
- `runtime/dogfood/webcodex-runner.exe`

## 真实 ChatGPT 宿主验证

使用内置浏览器的新测试对话和仅含生成公开文本的 `public-reading-demo-native` 项目，实际经过 ChatGPT → 原有 Tunnel → 新 Server/Runner → 项目修改 → 原生 WebCodex review 侧栏。没有用模拟宿主截图代替这轮证据。

ChatGPT 实际修改 25 个已跟踪文件，完成 `sample-v1` 到 `sample-v2` 的替换并封存。独立字节检查确认 25 个文件均仅发生预期替换，mismatch 为 0，旧文本剩余为 0；净变更为 +630 / −630。完成检查为非阻塞 warn，符合保留未提交测试修改的预期。

| 场景 | 观察结果 |
| --- | --- |
| Changed files / Final Changes | 均独立从 5 项分页至 25 项；选择器仅列出已加载项 |
| 多文件选择与前后导航 | 可切换文件，保留既有展开内容 |
| 长 Diff | 连续页面滚动，导航吸顶；546 行受原有内容上限约束的 Diff 可阅读 |
| 800 / 620 / 390 像素侧栏 | 实际宿主 iframe 宽度验证；页面未出现横向溢出 |
| 超长代码行关闭折行 | 在 390 像素侧栏内，代码区宽 320、内容宽 8,287、页面内容宽 375；两种文件列表均通过 |
| 全文分页 | 从 32,768 字节加载到完整 57,378 字节；完整加载后才启用 Markdown |
| Markdown | 真实表格、长段落和窄屏路径正常显示 |
| 滚轮、PageDown | 页面连续阅读；深处导航保持吸顶 |
| 同快照刷新与模式状态 | 真实自动刷新期间阅读位置稳定；更细的模式锚点和迟到响应由确定性回归覆盖 |
| 原生侧栏关闭再打开 | 正确绑定公开测试 Project 与同一 Session |
| 新封存快照 | Server 重启后通过同一 Session 再次封存，Final Changes 重新出现并可分页、阅读 |
| 浅色 / 深色 | 通过宿主浏览器媒体偏好验证 |
| 触控模拟 | 内置浏览器拒绝相关 CDP 触控指令，未验证；也不声明真实手机验收 |

原有最终变更快照保存在 Server 内存中，重启后需要重新封存；本轮没有扩展快照持久化后端。重新封存只调用完成和展示入口，没有再次修改测试文件。

## 实测发现及处理

1. ChatGPT 缓存旧 v15 资源和旧工具定义：使用现有插件的刷新工具入口更新，未重装插件或扩展权限。
2. 初始样例目录由沙箱账户创建，Git 所有权检查失败：保留原目录，以当前账户创建新的公开测试仓库。虽然用户后续允许精确路径临时信任，最终没有添加全局 `safe.directory`。
3. 原生线程入口传入空 UI capability 对象时，响应遗漏线程绑定元数据：由 `e6eb52f8` 修复并经真实宿主与 Rust 回归验证。
4. 390 像素下关闭折行会撑宽整个文件列表：Grid 子项的内在宽度导致溢出，`ec769233` 对两个文件列表设置 `min-width: 0`；最终实际宿主验证已通过。

## 截图与隐私

最终 v19 截图在采集时就限定于安全侧栏区域，保存前及交付前均人工复核。画面只包含公开示例；没有历史聊天、账号、项目列表、私人路径、Tunnel ID、凭据或诊断详情。截图仅保存在本地交付目录，没有提交或上传 GitHub。

- `thread-panel-v19-wide-800-light.jpg`
- `thread-panel-v19-diff-scrolled-800-dark.jpg`
- `thread-panel-v19-full-text-800-dark.jpg`
- `thread-panel-v19-markdown-620-light.jpg`
- `thread-panel-v19-narrow-390-light.jpg`
- `thread-panel-v19-final-changes-800-light.jpg`
- `thread-panel-v19-narrow-diff-390-light.jpg`

旧 A/B 图及中间构建截图保留，但不作为最终 v19 的证据。

## 环境回退

真实测试确实暂时替换了用户指定 Desktop，并通过其生命周期入口停启原有 Server/Runner/Tunnel。切换前在零活动任务、服务停止后保存一致性数据，恢复副本逐项核对了 17,221 个文件。

回退核验发现 Windows 大小写不敏感导致最初程序备份中的 Desktop 与 CLI 文件名冲突。已从本机原安装包提取原 Desktop，验证 SHA-256 与切换前记录完全相同，并把四个程序改为按 desktop/runtime 子目录独立备份。原 Desktop SHA-256 为 `C9E4D14272ACFC4259D6F6A594006B723E75CC323C4A1AE724371E12716AA62C`。没有用近似版本替代。

首次保留测试数据时，退出中的 WebView 短暂占用文件，使移动中断。停止后的文件经核对归拢；一个退出期间产生的缓存差异额外保留了两个版本。随后使用同目录原子重命名保存测试目录，并恢复切换前的一致性备份。没有删除原备份或测试数据。

最终回退结果：

- 四个在用程序全部匹配切换前 SHA-256。
- 原运行时选择、fingerprint、revision 4 和连接配置恢复；runtime_autostart 为原值 true。
- 原 Tunnel 配置逐字节一致，autostart 为原值 false；通过 Desktop 手动恢复到 1 个本地就绪。
- 原 Runner 连接正常，提交 `1546b557ee7c`、dirty=true，保留其原始构建状态；8 个原项目，运行和排队任务均为 0。
- ChatGPT 插件执行了回退后的工具刷新；临时浏览器视口、主题、触控覆盖已清除，测试页面和夹具服务已关闭。
- 最终新构建保留供后续使用；本地 `rollback-verification.json` 记录恢复检查。

本轮没有推送、发布 PR/issue、打标签或发布版本。尚未验证的范围是触控输入和真实手机设备；选区发送至 ChatGPT 仍留待后续。
