---
name: runtime-error-fix
description: 排查并修复 KCode 桌面端运行时错误日志。先询问 runtime.jsonl 的路径，再按用户提供的工作区内路径读取 error 级记录，逐条判定哪些是产品缺陷，定位根因后修复并只运行受影响的验证。
triggers:
  - 查日志并修 bug
  - 读取 runtime.jsonl
  - error 日志
  - 日志报错修复
  - 哪些是 bug 要改
  - 分析日志缺陷
  - runtime error fix
risk: write
enabled: false
category: observability
---

# Runtime 错误日志排查与修复

## 目标

用户给出运行时日志路径 → 读取其中 error 级记录 → 区分「产品缺陷」与「按设计 / 模型侧 / 环境侧」→ 只对确认的缺陷修源码并做定向验证。

**铁律：没有根因和源码证据，不动手改代码。**

## 步骤

### 1. 先询问日志路径（必须，不要跳过）

第一次执行时**必须**先用 `request_user_input` 问用户日志位置，不要凭默认路径假设。可问成多选：

- 选项示例：`%APPDATA%\com.kcode.app\runtime-data\logs\runtime.jsonl`（默认目录）
- 选项示例：自定义目录（用户在设置里改过日志目录）
- 选项示例：用户会把文件复制到工作区内

拿到路径后注意两点：

1. **文件工具和 `run_command` 都拒绝工作区外路径**（`read_file` 要求 workspace-relative；`run_command` 的 `cwd` 也必须在工作区内）。所以日志必须位于工作区内才能用本仓库工具直接读。
2. 若用户给的路径在工作区外（典型就是 `%APPDATA%`），先让用户把文件复制进工作区，例如：

   ```powershell
   New-Item -ItemType Directory -Force .tmp-logs | Out-Null
   Copy-Item "$env:APPDATA\com.kcode.app\runtime-data\logs\runtime.jsonl" .tmp-logs\runtime.jsonl
   ```

   复制动作由用户执行或经其确认后执行；不要尝试绕过路径安全检查。

### 2. 确认文件并读 error 记录

- 用 `list_directory` 确认日志所在目录，`read_file` 读文件。**不要整文件 dump**：大会话可达数万行，直接读会炸上下文。
- 先只取结构与规模（行数、时间范围、`level` 分布）：

  ```powershell
  (Get-Content .tmp-logs/runtime.jsonl | Measure-Object -Line).Lines
  ```

- 再筛 error 级记录。runtime.jsonl 每行是 `{level, timestampMs, event, fields{...}}`：

  ```powershell
  rg -n '"level"\s*:\s*"error"' .tmp-logs/runtime.jsonl
  ```

  数量可控（几十行）时直接 `read_file` 逐条看；数量大时按 `event` 聚合先看分布：

  ```powershell
  rg -o '"event"\s*:\s*"[^"]+"' .tmp-logs/runtime.jsonl | Group-Object { $_ -replace '.*"event"\s*:\s*"([^"]+)".*','$1' } | Sort-Object Count -Descending
  ```

- 注意日志可能含 `logs_cleared` 记录：用户手动清过日志时，窗口内没有 error 不等于没发生过错误，结论里要如实说明。

### 3. 逐条判定是否 bug

error 记录绝大多数落进下面几类，先按表判定，剩不下的再深挖源码。

| 类别 | 判定 |
| --- | --- |
| `tool_failed` + `path must be relative` / 绝对路径 | **不是 bug**：工作区沙箱按设计拒绝工作区外路径（含符号链接与目录联接逃逸防护），属模型侧调用问题 |
| `tool_failed` + 插件未启用 | **不是 bug**：按设计拒绝，需在设置里启用 |
| `tool_failed` + `patch syntax is invalid` / `patch exceeds a safety limit` | **不是 bug**：模型侧补丁构造错误或有意保守的大小上限 |
| `tool_failed` + PowerShell 语法错误（`ParserError`、`无法将…`、bash heredoc 提示） | **不是 bug**：模型把 bash 写法带到 PowerShell |
| `tool_failed` + `no matches (exit code 1)` | **正常结果**：确认的无匹配，保留退出码 1 |
| `tool_failed` + `test result: FAILED` / `panicked at` / `AssertionError` | **待修**：真实测试失败，必须定位根因，不能被 `Finished` 或管道输出掩盖 |
| `turn_failed` + provider 空响应 / HTTP 错误 | **待核对**：核对 Provider 用量、收尾逻辑与当前运行版本，不能仅凭模型名称或旧日志断言 |
| `apply_patch_loop` 熔断 | **待核对**：熔断只说明恢复预算耗尽，须检查会话中的原始补丁、每次 `tool_result` 诊断和目标文件实际写入结果 |
| 规则未覆盖的新形态 | **待人工判定**：先读源码和运行版本，不直接算 bug |

判定口径：

- **历史 error 不等于当前缺陷。** 必须先核对当前源码和实际运行版本；文件 mtime 和 `git status` 只作线索，不是证明。
- **不自动重跑有副作用的历史命令**（可能写文件、改系统、访问外部服务）。
- 结论要落到具体文件行（如 `src-tauri/src/tools/command_diagnostics.rs:123`），方便用户复核。
- 明确区分三类结论：已确认无须修改 / 证据不足待核对 / 已确认需要修复。**不能把未确认项写成「没有缺陷」。**

### 4. 修复确认的缺陷

只修第 3 步中「已确认需要修复」且根因清楚的项：

1. 用 `search_repository` / `read_file` 定位根因所在源码，读够上下文再动手。
2. 遵循仓库既有模式修改；不夹带无关重构。
3. 每个公共契约或安全分支的改动，随改动一起**编写**测试。
4. 按 `AGENTS.md` 的分层验证执行：
   - 仅 `src/`、CSS 或展示状态 → `pnpm build`
   - Rust 单模块 / 内部逻辑 → `cargo fmt --check` + `cargo check`
   - IPC、Provider、AgentRuntime、工具、存储、协议或安全边界 → 上述外加 `tests/` 下直接相关的集成目标
   - 命中「测试触发条件」（改动了已有测试断言的行为、新增或修改测试代码、触及安全分支、公共契约交付）时，才跑对应 `cargo test`，且只跑受影响范围。
5. 未启动 `pnpm tauri dev` 实际验证变更路径前，不得声称桌面工作流已完成。

### 5. 汇报

按类别输出，每条 error 一行：时间 + 事件 + 已确认原因或待核对项；然后分别列出「已修复」「无须修改」「证据不足」三组，并说明本轮做了什么验证、哪些检查未执行。

```text
时间窗内 N 条 error，集中在会话 <threadId>（<最近活跃时间>）：

1. HH:MM tool_failed run_command
   完整输出包含 test result: FAILED。
   → 真实测试失败，已定位到 <file>:<line>，属产品缺陷，已修复。

2. HH:MM tool_failed read_file 绝对路径
   → 工作区沙箱按设计拒绝，无须修改。

3. HH:MM turn_failed provider 空响应
   → 证据不足，需核对运行版本与 Provider 用量，未改动。

验证：cargo fmt --check、cargo check 通过；跑了 <模块> 测试。未执行：全量 Rust、Playwright、桌面启动验收。
```

## 注意

- 日志可能很大：优先 `rg` 过滤 + 分段 `read_file`，不要整文件读入。
- `runtime.jsonl` 里 `assistant_tool_calls` 的 `arguments` 可能被截断，别当完整参数用；要看完整内容去 `sessions/<threadId>.jsonl`（格式是 `{type, createdAtMs, data{...}}`，与 runtime 的事件名体系不同，别混用字段名）。
- 修复涉及安全分支（路径规范化、权限字段、Shell 策略、凭据脱敏）时，对应测试不得省略。
- 工作区里为读日志临时复制的内容，用完告知用户可删除，不要悄悄提交进仓库。
