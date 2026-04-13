# Desktop Control for Windows

[English](./README.md) | [简体中文](./README.zh-CN.md)

`Desktop Control for Windows` 是一个给 Codex 用的 Windows 桌面控制 skill，基于本地 Python 原语控制可见桌面应用。它可以移动和点击鼠标、输入文本、通过剪贴板粘贴、截图、读取像素、图像匹配、管理窗口、协调全局 UI 锁，并执行可重复的多步动作计划。

这个项目适合用于没有可靠 API、DOM、CLI 或应用专用自动化接口的场景。

## 仓库内容

- `SKILL.md`：coordinator 与 UI worker 的工作流说明
- `scripts/ui_control.py`：键盘、鼠标、屏幕、窗口、剪贴板、锁、overlay、plan 等命令
- `references/control-api.md`：CLI 示例
- `references/subagent-workflow.md`：worker 提示词模板
- `agents/openai.yaml`：Codex UI 元数据

## 安全模型

这个 skill 可以读取屏幕、读取或修改剪贴板、向前台窗口输入、点击、拖拽、滚动，以及关闭窗口。只有在你接受这种本地控制级别的会话里才应使用它。

推荐默认做法：

- 保持 PyAutoGUI failsafe 开启
- 多步任务使用全局 UI 锁
- 生成的 plan 先用 `--dry-run`
- UI worker 接管屏幕时先启动暖色 overlay，结束后再切换为冷色完成态 overlay
- 风险较高的手工测试使用 `--require-approval`
- plan JSON 只放动作本身字段，全局安全和锁参数放在命令行
- 除非用户明确要求，不要碰密钥、支付、UAC、密码管理器、银行流程和破坏性动作

内置控制器完全在本地运行，`scripts/ui_control.py` 不会调用外部网络服务。

## 作为 Codex Skill 安装

把这个仓库 clone 或复制到你的 Codex skills 目录：

```powershell
$skills = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME "skills" } else { Join-Path $HOME ".codex\skills" }
git clone https://github.com/BraveCowNoFear/desktop-control-for-windows.git (Join-Path $skills "desktop-control-for-windows")
```

在 Codex 使用的 Python 环境里安装依赖：

```powershell
python -m pip install -r requirements.txt
```

验证 CLI：

```powershell
cd (Join-Path $skills "desktop-control-for-windows")
python scripts\ui_control.py --help
python scripts\ui_control.py status --windows
```

## 快速命令示例

在 skill 根目录运行：

```powershell
python scripts\ui_control.py overlay --mode start --task "example"
python scripts\ui_control.py lock acquire --owner "example"
python scripts\ui_control.py --lock-token <token> status --windows
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\screen.png"
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\active.png" --active
python scripts\ui_control.py --lock-token <token> snapshot --out "$env:TEMP\state.png" --windows --active
python scripts\ui_control.py --lock-token <token> find-image C:\path\button.png --window "Chrome"
python scripts\ui_control.py --lock-token <token> hotkey ctrl l
python scripts\ui_control.py --lock-token <token> type "hello world" --method paste
python scripts\ui_control.py lock release --token <token>
python scripts\ui_control.py overlay --mode finish --status success --task "example" --completed "Finished the requested UI task"
```

像 `--lock-token`、`--dry-run`、`--require-approval` 这样的全局参数必须写在子命令前面。

如果 worker 需要一次同时拿到状态信息和截图，优先用 `snapshot`。如果目标窗口已知，截图、snapshot、图像搜索优先配合 `--active` 或 `--window`，这样能减少全屏匹配，提高稳定性。

Siri 风格状态边框的用法是：UI worker 接管屏幕时执行 `python scripts\ui_control.py overlay --mode start --task "..."`，会显示暖色、可点击穿透的边框；任务结束后执行 `python scripts\ui_control.py overlay --mode finish --status success|partial|failed ...`，会切到冷色完成态并展示结果，直到用户点击屏幕任意位置关闭。

## 来源

这个项目从 ClawHub `breckengan/control` v1.0.0 的本地桌面控制模式迁移而来。原始 ClawHub 条目标记为 MIT-0 许可。上游演示脚本和规则式 app demo 没有被带过来，Codex 侧仍应把高层推理放在主 agent 循环里，并用 `plan` 做确定性的本地批处理。

## 许可证

MIT-0，见 `LICENSE`。
