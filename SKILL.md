---
name: desktop-control-for-windows
description: Windows desktop UI automation for Codex using a UI-worker-isolated local-control workflow with real keyboard, mouse, screenshot, window, clipboard, image matching, scrolling, dragging, long-press, and batch plans. Use when Codex needs to operate Windows applications or websites through visible UI because no reliable API, DOM, CLI, or accessibility interface is available; when the task asks to click, type, drag, scroll, hold keys/buttons, inspect the screen, control a computer, automate desktop software, or interact with closed-source Windows UI. For live screen work, any non-UI-worker agent at any task depth may act as the coordinator and must delegate screenshots, image inspection, and UI execution to exactly one dedicated UI worker. If delegation is unavailable or disallowed, the coordinator must stop and ask for permission instead of running screenshot or UI-control commands itself. A delegated UI worker is a leaf worker and must not create another agent.
---

# Desktop Control for Windows

## Overview

Use this skill to operate visible Windows UI like a fast human: screenshot, reason from pixels, activate a target window, then issue keyboard/mouse actions through the bundled scripts. The active workflow is local Python automation only.

This skill has two roles:

- Coordinator: any agent at any depth that is not already the UI worker, decides whether visible UI control is needed, delegates one bounded UI task to a worker when delegation is available, and pauses for explicit permission when delegation is unavailable.
- UI worker: the already-delegated agent that takes screenshots, inspects pixels, and runs `scripts/ui_control.py` directly.

Mandatory delegation gate: for any live Windows UI-control task, first decide your role from the prompt you were given. If you were not explicitly spawned as the UI worker/screen-control worker for this UI task, you are the coordinator even if you are already a subagent of a larger task. Do not take screenshots, view screenshots, call `scripts/ui_control.py`, or inspect live screen images yourself. Delegate exactly one dedicated UI worker. If the current runtime policy or tool availability prevents delegation, stop before touching the UI and ask the user to explicitly authorize a UI worker or choose a non-UI path. Only skip delegation when you are already the UI worker or when you are debugging/editing this skill itself.

Never allow recursive UI-worker delegation. Ordinary task agents can be nested two or three levels deep and still create one dedicated UI worker for their own visible-UI phase. The leaf UI worker itself must not spawn, delegate to, message, or wait on any additional agent. Do the UI work locally with the bundled script and return a concise text report.

Global UI lock: all live UI workers share one lock file through `scripts/ui_control.py`. A UI worker must acquire the lock at the start of its UI phase, pass the returned `--lock-token` to every screenshot/window/mouse/keyboard/clipboard command, and release the lock before returning. If another worker already holds the lock, wait for it or return `partial` with the busy-lock details. This prevents parallel agents from fighting over the mouse, keyboard, foreground window, or clipboard.

Locale-sensitive text entry: before searching for a named UI target such as WeChat File Transfer Assistant, first inspect the app language/visible labels while holding the UI lock. If the UI is Chinese, pass the Chinese label as ASCII Unicode escapes to `type ... --decode-unicode-escapes --method paste` or `clipboard set ... --decode-unicode-escapes`, for example `\u6587\u4ef6\u4f20\u8f93\u52a9\u624b`; do not type raw Chinese through nested prompts, shell arguments, or command files. If the UI is English, use the English label or an ASCII-safe alias such as `filehelper`. If the language cannot be determined, prefer Unicode-escape input through the script over raw non-ASCII text and verify the resulting target before acting.

Source migrated from ClawHub `breckengan/control` v1.0.0 for local desktop control patterns.

## Migration Scope

Migrated local Control capabilities: absolute/relative mouse movement, smooth-duration movement through PyAutoGUI, left/right/middle/double click, mouse down/up, long mouse hold, drag, vertical/horizontal scroll, mouse position, text entry by keystrokes or clipboard paste, hotkeys, key down/up, key hold, screenshots, region screenshots, pixel color, image matching, screen size, window list/active/activate/info/minimize/maximize/restore/close, clipboard set/get, failsafe, optional approval, strict bounds checks, JSONL action logging, and batch plans.

Intentionally not copied: the upstream demo scripts and rule-based `ai_agent.py` app demos. In Codex, high-level reasoning should remain in the active agent loop, with `plan` for deterministic batching.

## Coordinator Protocol (Any Non-UI-Worker Agent)

For every real UI-control task, the coordinator must delegate to one single UI worker whenever the current runtime policy allows agent delegation. The worker performs screenshots, visual inspection, and UI execution. The coordinator must not take screenshots, view screenshots, run `scripts/ui_control.py`, or inspect screen images itself unless debugging the skill implementation. This keeps screen pixels, private window content, and visual reasoning out of the main conversation context.

No-direct-control fallback: if the coordinator cannot spawn or message a UI worker because the runtime policy, tool availability, or user permissions do not allow delegation, it must pause and ask the user for explicit permission to use a UI worker. It must not continue by doing local screenshot/image-inspection/UI-control work in its own context.

If you are already inside a delegated UI worker context, skip this protocol and follow **UI Worker Protocol** below. Do not call `spawn_agent`, `send_input`, `wait_agent`, `close_agent`, OpenSpace delegation tools, or any equivalent nested-worker mechanism.

Read `references/subagent-workflow.md` before delegating UI work. The coordinator must:

- Clarify the goal internally and define a narrow UI task for the subagent.
- Include the exact target app/window, desired outcome, safety limits, and whether irreversible actions are allowed.
- State explicitly in the worker prompt: "You are the UI worker. Do not spawn or delegate to another agent."
- Tell the subagent to acquire the global UI lock before touching the UI, pass `--lock-token` to every `scripts/ui_control.py` command, and release the lock before returning.
- Tell the subagent to use only local `scripts/ui_control.py`; do not use remote visual models, browser extensions, or external services.
- Tell the subagent to inspect the UI language before choosing search/input text; Chinese UI needs `--decode-unicode-escapes`, English UI may use English/ASCII aliases.
- Ask the subagent to return a concise text report with commands used, final state, screenshot file paths, and any unresolved uncertainty.
- Avoid requesting raw screenshots in the subagent final answer unless the user specifically needs them.

## UI Worker Protocol

Use this section only when the prompt explicitly says you are the screen-control worker, UI worker, or delegated worker for a Windows UI task, or when you are already running inside an agent spawned specifically for Windows UI control. Being a general-purpose subagent of a larger task does not make you the UI worker; in that case, follow the Coordinator Protocol when live UI control is needed.

Hard rules:

- Do not spawn another agent, delegate to another agent, or use OpenSpace to create a nested worker.
- Do not re-run the Coordinator Protocol.
- Use only this skill's `scripts/ui_control.py` and ordinary local shell commands needed to inspect outputs.
- Keep screenshots in a temp folder such as `$env:TEMP\codex-ui-subagent\`.
- Inspect screenshots inside your own context and return only text plus screenshot paths.
- If you cannot complete the UI task locally, report `partial` or `failed` with the blocker. Do not escalate by spawning another agent.

Worker loop:

1. Acquire the global UI lock with `lock acquire --owner "<task label>"` and keep the returned token private in your worker context.
2. Pass `--lock-token <token>` to every non-dry-run `scripts/ui_control.py` command until release.
3. Run `status --windows` and take a fresh screenshot while holding the lock.
4. Inspect screenshots locally and choose the smallest safe action.
5. Prefer hotkeys and clipboard paste over mouse coordinates when reliable.
6. Use `--dry-run` before long or risky plans.
7. Execute with `scripts/ui_control.py`.
8. Verify with another screenshot or non-image status command.
9. Release the lock with `lock release --token <token>` in cleanup.
10. Return outcome, summarized actions, final observed state, screenshot paths, and unresolved uncertainty.

## Decision Rules

- Prefer normal APIs, CLI commands, browser automation, or app-specific tooling when they exist and are reliable.
- For live Windows UI control, apply the mandatory delegation gate before any screenshot, image inspection, or `scripts/ui_control.py` call.
- Use `scripts/ui_control.py` for fast local Windows control: hotkeys, text paste/type, mouse click, drag, scroll, screenshots, clipboard, window activation, pixel checks, image matching, and action plans.
- Take a screenshot before acting unless the target coordinates/state are already known from the same interaction loop.
- Use hotkeys and clipboard paste before mouse navigation when it is faster and safer.
- Batch known actions with `plan` for speed, but keep visual decision loops stepwise: screenshot, inspect, act, verify.
- For localized apps such as WeChat, decide whether the visible UI is Chinese or English before searching. Use `--decode-unicode-escapes` for Chinese labels/messages in nested worker contexts; never rely on raw Chinese text surviving prompt, CLI, PowerShell, or log redirection layers.

## Local Control

This section is for UI workers and skill debugging only. A coordinator must not run these commands for a live UI task; it must delegate to one UI worker first or pause if delegation is unavailable.

Run from the skill directory:

```powershell
python scripts\ui_control.py lock acquire --owner "wechat-file-transfer"
python scripts\ui_control.py --lock-token <token> status --windows
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\screen.png"
python scripts\ui_control.py --lock-token <token> hotkey ctrl l
python scripts\ui_control.py --lock-token <token> type '\u6587\u4ef6\u4f20\u8f93\u52a9\u624b' --decode-unicode-escapes --method paste
python scripts\ui_control.py --lock-token <token> click --x 500 --y 300
python scripts\ui_control.py --lock-token <token> right-click --x 500 --y 300
python scripts\ui_control.py --lock-token <token> drag 100 100 700 450 --duration 0.5
python scripts\ui_control.py --lock-token <token> scroll -6 --x 900 --y 500
python scripts\ui_control.py --lock-token <token> hold-mouse --x 500 --y 300 --seconds 1.2
python scripts\ui_control.py lock release --token <token>
```

All commands print JSON. Check `ok`, `error`, output paths, active window, and coordinates before continuing.

Lock behavior: commands without `--lock-token` acquire a transient lock for that single command. A worker doing a multi-step visible UI task must use `lock acquire` and pass `--lock-token` across the whole phase so other workers cannot interleave actions between its screenshot/act/verify loop. Global options such as `--lock-token` must appear before the subcommand, for example `ui_control.py --lock-token <token> type ...`, not after it. Use `--lock-timeout <seconds>` on ordinary commands to control how long to wait for another worker; use `lock status` to inspect the current holder without taking the lock. Expired locks are treated as stale and removed automatically.

On Windows, `scripts/ui_control.py` enables DPI awareness at startup. Treat screenshots, mouse coordinates, pixel reads, and window rectangles as the same physical-pixel coordinate system. If `status` reports a screen size that does not match the active desktop/window size, stop and report the mismatch before clicking.

For complete CLI syntax, read `references/control-api.md`.

## Workflow

1. Acquire the global UI lock:

```powershell
python scripts\ui_control.py lock acquire --owner "short task label"
```

Use the returned token as `--lock-token <token>` for every command until release.

2. Inspect state:

```powershell
python scripts\ui_control.py --lock-token <token> status --windows
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\codex-ui.png"
```

3. Bring the target forward:

```powershell
python scripts\ui_control.py --lock-token <token> window activate "Notepad"
```

4. Use the fastest reliable primitive:

- Text fields: `type --method paste`, using `--decode-unicode-escapes` for Chinese escape text, then `press enter` or `hotkey`.
- Menus and shortcuts: `hotkey`, `press`, `key-hold`.
- Buttons and canvases: `click`, `double-click`, `right-click`, `drag`, `scroll`, `hold-mouse`.
- Repeated deterministic sequences: write a JSON action file and run `plan --file`.
- Unknown visible target: the UI worker must screenshot and inspect, then use coordinates or image matching.

5. Verify with another screenshot or status call.

On PowerShell, prefer `plan --file` over `plan --json` for generated JSON. Complex JSON passed as a native command argument can be re-quoted by PowerShell before Python receives it.

6. Release the lock:

```powershell
python scripts\ui_control.py lock release --token <token>
```

## Safety

- PyAutoGUI failsafe is enabled by default: move the mouse to a screen corner to abort.
- Add `--require-approval` for interactive confirmation before actions and `--log-file <path>` for JSONL action history.
- Add `--strict-bounds` when coordinates must remain inside the primary display.
- Do not type secrets, approve payments, grant elevated permissions, delete data, or make irreversible changes unless the user explicitly requested that exact action.
- Avoid controlling secure desktops, UAC prompts, password managers, banking flows, or other high-risk UI unless the user is present and the request is unambiguous.
- Use `--dry-run` when preparing a long plan and `--pause-after` to slow down risky actions.
- Screenshots and clipboard contents can contain sensitive information. Keep screenshots inside the UI worker context and return only paths/summaries to the coordinator.
- A UI worker must hold the global UI lock before touching the live desktop. If it cannot acquire the lock within a reasonable timeout, it should report `partial` instead of trying to compete with another worker.
- If UI text appears as `???`, `????`, boxes, mojibake, or mismatched search results, treat it as an encoding failure. Stop that input path, clear the field if needed, and retry with UI-language-aware `--decode-unicode-escapes` input instead of raw Chinese or the wrong-language alias.

## Dependencies

The local controller uses Python packages already common in this Codex environment: `pyautogui`, `Pillow`, `pygetwindow`, and `pyperclip`. Image matching with confidence needs `opencv-python`. If a package is missing, install only what is needed in the active Python environment:

```powershell
python -m pip install pyautogui pillow pygetwindow pyperclip opencv-python
```
