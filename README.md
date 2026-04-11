# Desktop Control for Windows

Desktop Control for Windows is a Codex skill for controlling visible Windows desktop applications through local Python primitives. It can move and click the mouse, type text, paste through the clipboard, take screenshots, inspect pixels, match images, manage windows, and run deterministic multi-step action plans.

This is intended for cases where no reliable API, DOM, CLI, or app-specific automation surface exists.

## What Is Included

- `SKILL.md` with the coordinator/UI-worker workflow.
- `scripts/ui_control.py` with local keyboard, mouse, screen, window, clipboard, lock, and plan commands.
- `references/control-api.md` with CLI examples.
- `references/subagent-workflow.md` with worker prompt templates.
- `agents/openai.yaml` with Codex UI metadata.

## Safety Model

This skill can read the screen, read or modify the clipboard, type into the active window, click, drag, scroll, and close windows. Use it only in sessions where that level of local control is acceptable.

Recommended defaults:

- Keep PyAutoGUI failsafe enabled.
- Use the global UI lock for multi-step tasks.
- Use `--dry-run` for generated plans.
- Use `--require-approval` for risky manual tests.
- Avoid secrets, payments, UAC prompts, password managers, banking flows, and destructive actions unless the user explicitly requested the exact action.

The bundled controller is local-only. `scripts/ui_control.py` does not call external network services.

## Install As A Codex Skill

Clone or copy this repository into your Codex skills directory:

```powershell
$skills = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME "skills" } else { Join-Path $HOME ".codex\skills" }
git clone https://github.com/Clr168/desktop-control-for-windows.git (Join-Path $skills "desktop-control-for-windows")
```

Install Python dependencies in the Python environment Codex will use:

```powershell
python -m pip install -r requirements.txt
```

Verify the CLI:

```powershell
cd (Join-Path $skills "desktop-control-for-windows")
python scripts\ui_control.py --help
python scripts\ui_control.py status --windows
```

## Quick CLI Examples

Run commands from the skill directory:

```powershell
python scripts\ui_control.py lock acquire --owner "example"
python scripts\ui_control.py --lock-token <token> status --windows
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\screen.png"
python scripts\ui_control.py --lock-token <token> hotkey ctrl l
python scripts\ui_control.py --lock-token <token> type "hello world" --method paste
python scripts\ui_control.py lock release --token <token>
```

Global options such as `--lock-token`, `--dry-run`, and `--require-approval` must appear before the subcommand.

## Provenance

This project was migrated from the local desktop-control patterns in ClawHub `breckengan/control` v1.0.0. The original ClawHub listing identifies that package as MIT-0 licensed. Upstream demo scripts and rule-based app demos were intentionally not copied; Codex should keep high-level reasoning in the agent loop and use `plan` for deterministic local batching.

## License

MIT-0. See `LICENSE`.
