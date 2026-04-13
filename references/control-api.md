# Local Control API

Use `scripts/ui_control.py` for deterministic Windows keyboard, mouse, screen, window, clipboard, and image operations. Commands return JSON and exit nonzero on hard failures.

On Windows, the script enables process DPI awareness before importing UI libraries. Coordinates in screenshots, mouse commands, pixel reads, image matching, and window rectangles are physical pixels. Use `status --windows` before coordinate-heavy work and confirm the reported screen size and window rectangles are in the same scale.

## Global Options

```powershell
python scripts\ui_control.py --dry-run <command> ...
python scripts\ui_control.py --no-failsafe <command> ...
python scripts\ui_control.py --pause-after 0.2 <command> ...
python scripts\ui_control.py --require-approval <command> ...
python scripts\ui_control.py --strict-bounds <command> ...
python scripts\ui_control.py --log-file C:\path\actions.jsonl <command> ...
python scripts\ui_control.py --lock-timeout 30 <command> ...
python scripts\ui_control.py --lock-token <token> <command> ...
```

- Global options must appear before the subcommand. Use `python scripts\ui_control.py --lock-token <token> click ...`, not `python scripts\ui_control.py click ... --lock-token <token>`.
- Keep failsafe enabled unless there is a strong reason to disable it.
- Use `--dry-run` to inspect a generated action plan without moving the mouse or typing.
- Use `--pause-after` after actions that need UI settle time.
- Use `--require-approval` for risky manual tests.
- Use `--strict-bounds` to reject primary-screen out-of-bounds coordinates.
- Use `--log-file` for action history. Results avoid logging typed text by default.
- Commands automatically use a global UI lock so parallel workers do not fight over the mouse, keyboard, foreground window, or clipboard.
- For multi-command UI phases, run `lock acquire` first, then pass `--lock-token <token>` to every non-dry-run command, and release the lock at the end.
- The Siri-style overlay is separate from the UI lock. Start it when the worker begins, then finish it after the lock is released so the completion message can stay visible without blocking other workers.
- Use `--lock-timeout` to control how long a command waits for another worker's lock. Expired locks are treated as stale and removed automatically.
- Single commands that acquire their own transient lock include `uiLock.scope: "transient-command"` and `uiLock.released: true` after the command completes. Commands run with a worker-provided token include `uiLock.scope: "provided-token"` and leave release responsibility with the worker.

## Global UI Lock

```powershell
python scripts\ui_control.py lock acquire --owner "wechat-file-transfer"
python scripts\ui_control.py --lock-token <token> status --windows
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\screen.png"
python scripts\ui_control.py lock status
python scripts\ui_control.py lock refresh --token <token>
python scripts\ui_control.py lock release --token <token>
```

`lock acquire` returns a token. Keep it inside the UI worker context and pass it as a global option before the subcommand, for example `--lock-token <token> screenshot ...`. Commands without a token acquire a transient per-command lock; that is fine for isolated reads, but a real UI worker should hold one lock across its whole screenshot/act/verify loop.

## Overlay

```powershell
python scripts\ui_control.py overlay --mode start --task "export report"
python scripts\ui_control.py overlay --mode finish --status success --task "export report" --completed "Opened the export dialog" --completed "Saved the PDF"
python scripts\ui_control.py overlay --mode finish --status failed --task "export report" --error "The Save button never appeared" --details "Stopped before any destructive action."
python scripts\ui_control.py overlay --mode close
```

- `overlay --mode start` launches a warm-color, click-through border that signals the UI worker currently owns the screen.
- `overlay --mode finish` switches the same overlay into a cool completion state, shows the task summary and errors, and waits for the user to click anywhere to dismiss it.
- `overlay --mode close` force-closes the shared overlay state if cleanup is needed.
- `overlay --mode show` still exists for one-shot manual tests and supports `--auto-close`.

## Status And Screenshots

```powershell
python scripts\ui_control.py --lock-token <token> status --windows
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\screen.png"
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\region.png" --region 100 100 800 500
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\active.png" --active
python scripts\ui_control.py --lock-token <token> screenshot --out "$env:TEMP\chrome.png" --window "Chrome"
python scripts\ui_control.py --lock-token <token> snapshot --out "$env:TEMP\state.png" --windows --active
python scripts\ui_control.py --lock-token <token> pixel 500 300
python scripts\ui_control.py --lock-token <token> find-image C:\path\button.png --confidence 0.85
python scripts\ui_control.py --lock-token <token> find-image C:\path\button.png --active
python scripts\ui_control.py --lock-token <token> find-image C:\path\button.png --window "Notepad"
```

`status --windows` lists titled windows and the current active window, including minimized or off-screen windows when the platform reports them. `find-image` returns the match box and center when the template is found.
Use `snapshot` instead of separate `status --windows` and `screenshot` calls when a worker needs both metadata and an image. Use `--active` or `--window` instead of a full-screen screenshot/search when the target app is already known. The controller converts the selected window rectangle into the region passed to PyAutoGUI and includes `target` metadata in the JSON result. On Windows, maximized windows can report invisible border offsets; window targets are clamped to the primary screen and the original rectangle is retained as `target.requestedRegion`.

Solid-color templates are matched with an exact-pixel path instead of confidence matching, because normalized template matching can report false positives for zero-variance images. For single-pixel color checks, prefer `pixel`.

## Mouse

```powershell
python scripts\ui_control.py --lock-token <token> move 500 300
python scripts\ui_control.py --lock-token <token> move 40 -20 --relative
python scripts\ui_control.py --lock-token <token> click --x 500 --y 300
python scripts\ui_control.py --lock-token <token> click --x 500 --y 300 --button right
python scripts\ui_control.py --lock-token <token> right-click --x 500 --y 300
python scripts\ui_control.py --lock-token <token> middle-click --x 500 --y 300
python scripts\ui_control.py --lock-token <token> double-click --x 500 --y 300
python scripts\ui_control.py --lock-token <token> mouse-down --x 500 --y 300 --button left
python scripts\ui_control.py --lock-token <token> mouse-up --button left
python scripts\ui_control.py --lock-token <token> hold-mouse --x 500 --y 300 --seconds 1.5
python scripts\ui_control.py --lock-token <token> drag 100 100 700 450 --duration 0.5
python scripts\ui_control.py --lock-token <token> scroll -8 --x 900 --y 500
python scripts\ui_control.py --lock-token <token> scroll 6 --horizontal
```

Scroll direction follows PyAutoGUI: positive is up/left, negative is down/right.

## Keyboard

```powershell
python scripts\ui_control.py --lock-token <token> type "hello world" --method auto
python scripts\ui_control.py --lock-token <token> type '\u6587\u4ef6\u4f20\u8f93\u52a9\u624b' --decode-unicode-escapes --method paste
Get-Content C:\path\text.txt -Raw | python scripts\ui_control.py --lock-token <token> type --stdin --method paste
python scripts\ui_control.py --lock-token <token> type --file C:\path\text.txt --method paste
python scripts\ui_control.py --lock-token <token> press enter
python scripts\ui_control.py --lock-token <token> press tab --presses 3
python scripts\ui_control.py --lock-token <token> hotkey ctrl s
python scripts\ui_control.py --lock-token <token> key-down shift
python scripts\ui_control.py --lock-token <token> key-up shift
python scripts\ui_control.py --lock-token <token> key-hold space --seconds 2
```

Use `type --method paste` for Chinese, long text, or text containing characters PyAutoGUI cannot type directly. In nested Codex/PowerShell worker paths, do not pass raw Chinese through prompts, command arguments, or generated shell files; pass ASCII Unicode escapes with `--decode-unicode-escapes`, or write UTF-8 text to a file/stdin inside the worker context, then paste. Before searching localized apps, inspect whether the visible UI is Chinese or English and choose the matching label. Avoid putting secrets in command-line arguments; if the user explicitly provides secret text for UI entry, pass it through `--stdin` or `--file`. Clipboard paste saves and restores the previous clipboard by default; add `--no-restore-clipboard` only when preserving the pasted text in the clipboard is desired.

## Clipboard

```powershell
python scripts\ui_control.py --lock-token <token> clipboard get
python scripts\ui_control.py --lock-token <token> clipboard get --preview
python scripts\ui_control.py --lock-token <token> clipboard get --show
python scripts\ui_control.py --lock-token <token> clipboard set '\u6587\u4ef6\u4f20\u8f93\u52a9\u624b' --decode-unicode-escapes
```

Treat clipboard contents as sensitive. `clipboard get` returns only length and hash by default; `--preview` prints a short preview, and `--show` prints the full clipboard text.

## Windows

```powershell
python scripts\ui_control.py --lock-token <token> window list
python scripts\ui_control.py --lock-token <token> window active
python scripts\ui_control.py --lock-token <token> window activate "Chrome"
python scripts\ui_control.py --lock-token <token> window info "Notepad"
python scripts\ui_control.py --lock-token <token> window minimize "Calculator"
python scripts\ui_control.py --lock-token <token> window maximize "Notepad"
python scripts\ui_control.py --lock-token <token> window restore "Notepad"
python scripts\ui_control.py --lock-token <token> window close "Untitled - Notepad"
```

Window matching is case-insensitive substring matching. If multiple windows match, the first titled match is used.

## Plans

For fast repeated UI operations, create a JSON file:

```json
[
  {"command": "hotkey", "keys": ["ctrl", "l"]},
  {"command": "type", "text": "\\u6587\\u4ef6\\u4f20\\u8f93\\u52a9\\u624b", "decode-unicode-escapes": true, "method": "paste"},
  {"command": "press", "key": "enter"},
  {"command": "sleep", "seconds": 1.0},
  {"command": "snapshot", "out": "C:\\Temp\\after.png", "windows": true, "active": true}
]
```

Run:

```powershell
python scripts\ui_control.py --lock-token <token> plan --file C:\path\actions.json
```

On PowerShell, prefer `plan --file` for JSON actions. Passing complex JSON through `plan --json` can be mangled by native-command argument parsing and should be reserved for very small ASCII-only snippets after a dry-run check.

Plan actions may set only action-specific fields. They cannot override global/control fields such as `dry-run`, `require-approval`, `no-failsafe`, `strict-bounds`, `pause-after`, `log-file`, `lock-token`, `lock-timeout`, `lock-ttl`, `lock-owner`, `plan-file`, `plan-json`, `func`, or `stdin`. For plan text input, use a `text` value or `file`; do not make a plan sub-action read from process stdin. Plan-supplied choices and booleans are validated the same way direct CLI arguments are validated.

Supported plan commands: `move`, `click`, `double-click`, `right-click`, `middle-click`, `drag`, `scroll`, `type`, `press`, `hotkey`, `key-down`, `key-up`, `key-hold`, `mouse-down`, `mouse-up`, `hold-mouse`, `clipboard-set`, `window-activate`, `screenshot`, `snapshot`, `find-image`, and `sleep`. If any sub-action fails or raises an exception, the plan returns `ok:false` with the failing action index and releases tracked held keys/buttons.
