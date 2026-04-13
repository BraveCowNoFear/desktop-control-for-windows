# Subagent Workflow

Use this workflow for real Windows UI automation. Any non-UI-worker agent, including a subagent two or three levels deep inside a larger task, may act as the coordinator. The coordinator must delegate screenshot-taking, image inspection, and UI execution to exactly one dedicated UI worker so its own context stays clean. The UI worker is a leaf: it must never create another worker or subagent.

Mandatory gate: for live Windows UI control, first decide your role from the prompt you were given. If you were not explicitly spawned as the UI worker/screen-control worker for this UI task, you are the coordinator even if you are already a subagent of a larger task. The coordinator must not run screenshot commands, inspect screen images, or call `scripts/ui_control.py` itself. It must spawn/message exactly one UI worker. When `spawn_agent` or an equivalent delegation tool is available, using this skill is sufficient authorization to create the worker. If the current runtime truly cannot delegate, the coordinator must stop and report that blocker instead of falling back to direct UI control or asking the user for a magic authorization phrase.

Global UI lock: all UI workers serialize live desktop access through `scripts/ui_control.py lock acquire/release`. A worker must hold this lock across its whole screenshot/act/verify loop and pass `--lock-token` to every non-dry-run UI command. If the lock is busy, the worker should wait within its timeout or return `partial`; it must not compete for the mouse, keyboard, foreground window, or clipboard.

Locale-sensitive search: before searching for a named UI target, the UI worker must inspect whether the app is showing a Chinese or English interface. For Chinese UI, pass ASCII Unicode escapes to `type ... --decode-unicode-escapes --method paste` or `clipboard set ... --decode-unicode-escapes`; for English UI, use the English label or ASCII alias. Do not default to `filehelper` or any other alias until the visible UI language supports it, and never pass raw Chinese through nested prompts or shell arguments.

## Coordinator Responsibilities

- Decide whether visible UI control is truly needed. Prefer API, CLI, Playwright, or app-specific automation when reliable.
- Spawn exactly one dedicated UI worker for each live UI task or coherent UI phase. This is allowed even when the coordinator is itself a task subagent.
- Give the UI worker a narrow, concrete outcome and the current safety boundary.
- Tell the UI worker explicitly that it is the UI worker and must not spawn or delegate to another agent.
- Tell the UI worker explicitly to start the warm overlay before touching the desktop, acquire the global UI lock, pass `--lock-token` to every command, release the lock, switch the overlay to the cool completion state, and only then return.
- Tell the UI worker explicitly to inspect the visible UI language before choosing a search term; use `--decode-unicode-escapes` for Chinese UI and English/ASCII aliases only for English UI.
- Do not personally call screenshot/image-viewing/UI-control commands for the live UI task.
- If delegation is unavailable or disallowed by missing tools or runtime policy, stop and report the blocker instead of doing the UI work in the main context. Do not ask the user for a passphrase or extra UI-worker authorization.
- Wait for the subagent's final text report, then decide whether another subagent pass is needed.
- If the user asks to approve a high-risk action, the coordinator makes that decision with the user before delegating.

## UI Worker Responsibilities

- Use this skill's `scripts\ui_control.py` for all local control.
- Do not call `spawn_agent`, `send_input`, `wait_agent`, `close_agent`, OpenSpace delegation tools, or any equivalent nested-agent mechanism.
- Do not re-apply the coordinator delegation rule to yourself. You are already the delegated UI worker.
- Start the warm overlay before touching the desktop, then acquire the global UI lock, keep the token private, pass `--lock-token` to every non-dry-run UI command, release it before finishing, and switch the overlay to the cool completion state.
- Inspect the app language before searching for contacts, buttons, menus, or labels. If the UI is Chinese, pass Unicode escapes to `--decode-unicode-escapes`; if the UI is English, use English text or ASCII aliases.
- Keep screenshots in a temp directory such as `$env:TEMP\codex-ui-subagent\`.
- Inspect screenshots locally in the subagent context and do not paste screenshots into the final response unless explicitly requested.
- Prefer hotkeys and clipboard paste over coordinate clicks when reliable.
- Use `--dry-run` before long `plan` sequences.
- Verify final state with a screenshot or non-image status command.
- Return a concise text report, not raw image content, and mention whether the overlay reached the cool completion state.

## Standard Spawn Prompt

Copy and fill this prompt when spawning the UI worker:

```text
Use $desktop-control-for-windows to perform this Windows UI task as the screen-control worker.

You are the UI worker, not the coordinator. Do not spawn, delegate to, message, or wait on another agent. Do not use OpenSpace delegation. Do not re-run the coordinator delegation protocol. Complete the task locally with `scripts\ui_control.py`, or return partial/failed with the blocker.

Task:
<describe the exact UI goal>

Target app/window:
<app name, window title, or "current foreground window">

Safety boundary:
- Use only local scripts\ui_control.py.
- Start the warm overlay first with `python scripts\ui_control.py overlay --mode start --task "<task label>"`. Then acquire the global UI lock, pass --lock-token to every UI command, release the lock, switch the overlay to the cool completion state with `overlay --mode finish`, and only then return.
- Before searching for File Transfer Assistant, inspect whether WeChat is in Chinese or English. Chinese UI: paste `\u6587\u4ef6\u4f20\u8f93\u52a9\u624b` through `type ... --decode-unicode-escapes --method paste`. English UI: use File Transfer Assistant or `filehelper`.
- Do not create nested agents or subagents.
- Do not use remote visual models, browser extensions, or external services.
- Do not type secrets, submit payments, delete data, install software, grant permissions, close unrelated windows, or make irreversible changes unless this prompt explicitly says to do so.
- Keep PyAutoGUI failsafe enabled.
- Use --require-approval for risky actions if you must perform them.

Workflow:
1. Start the warm overlay with `python scripts\ui_control.py overlay --mode start --task "<task label>"`.
2. Acquire the global UI lock with `lock acquire --owner "<task label>"`.
3. Run status/window checks and take screenshots only inside your subagent context, passing `--lock-token <token>`.
4. Inspect screenshots yourself, determine the UI language, and choose localized search/input text accordingly.
5. Prefer hotkeys/clipboard paste over mouse clicks when reliable.
6. Use --dry-run for any multi-step plan before executing.
7. Execute the task with `--lock-token <token>`, then verify the final UI state.
8. Release the lock.
9. Switch the overlay to the cool completion state with `python scripts\ui_control.py overlay --mode finish ...`.

Return only:
- Outcome: success/partial/failed
- Actions performed, summarized
- Final observed state
- Screenshot file paths you created
- Any coordinates or window titles that matter
- Whether the UI lock was acquired and released
- Whether the overlay switched from warm in-progress to cool completion state
- Any uncertainty or next recommended action for the coordinator
```

## Example Prompt

```text
Use $desktop-control-for-windows to perform this Windows UI task as the screen-control worker.

You are the UI worker, not the coordinator. Do not spawn, delegate to, message, or wait on another agent. Complete the task locally with `scripts\ui_control.py`, or return partial/failed with the blocker.

Task:
In the current foreground browser window, click the visible "Export" button, wait for the export dialog, and stop before confirming any file overwrite.

Target app/window:
Current foreground window.

Safety boundary:
- Use only local scripts\ui_control.py.
- Start the warm overlay first with `python scripts\ui_control.py overlay --mode start --task "<task label>"`. Then acquire the global UI lock, pass --lock-token to every UI command, release the lock, switch the overlay to the cool completion state with `overlay --mode finish`, and only then return.
- Before searching for a localized UI target, inspect the app language. Use `--decode-unicode-escapes` with Unicode-escaped Chinese for Chinese UI and English/ASCII aliases only for English UI.
- Do not create nested agents or subagents.
- Do not use remote visual models, browser extensions, or external services.
- Do not overwrite files or click a destructive confirmation.
- Keep PyAutoGUI failsafe enabled.

Workflow:
1. Start the warm overlay with `python scripts\ui_control.py overlay --mode start --task "<task label>"`.
2. Acquire the global UI lock with `lock acquire --owner "<task label>"`.
3. Run status/window checks and take screenshots only inside your subagent context, passing `--lock-token <token>`.
4. Inspect screenshots yourself, determine the UI language, and decide coordinates/actions and text accordingly.
5. Prefer hotkeys/clipboard paste over mouse clicks when reliable.
6. Use --dry-run for any multi-step plan before executing.
7. Execute the task with `--lock-token <token>`, then verify the final UI state.
8. Release the lock.
9. Switch the overlay to the cool completion state with `python scripts\ui_control.py overlay --mode finish ...`.

Return only:
- Outcome
- Actions performed
- Final observed state
- Screenshot file paths
- Coordinates/window titles used
- Whether the UI lock was acquired and released
- Whether the overlay switched from warm in-progress to cool completion state
- Remaining uncertainty
```

## Follow-up Pass Prompt

Use this when the first worker returns uncertainty:

```text
Continue the Windows UI task using $desktop-control-for-windows. You are still the UI worker, not the coordinator. Do not spawn, delegate to, message, or wait on another agent. Start the warm overlay first, acquire the global UI lock, pass --lock-token to every UI command, inspect the app language before choosing search/input text, use Unicode-escaped Chinese only when the UI is Chinese and English/ASCII aliases only when the UI is English, release the lock, switch the overlay to the cool completion state before returning, and return the same concise report format. Use the previous worker's reported screenshot paths and coordinates only as hints, not ground truth. Take a fresh screenshot in your own context, verify the current state, then perform the smallest safe next action.
```
