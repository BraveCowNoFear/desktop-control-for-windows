#!/usr/bin/env python3
"""Fast Windows UI control primitives for Codex."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import sys
import time
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator


def enable_dpi_awareness() -> bool:
    """Use physical pixels for all Windows screen and window coordinates."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
    except Exception:
        return False

    # Prefer per-monitor DPI awareness so pyautogui screenshots and Win32
    # window rectangles use the same coordinate system on scaled displays.
    try:
        result = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if result == 0:
            return True
    except Exception:
        pass
    try:
        result = ctypes.windll.user32.SetProcessDPIAware()
        return bool(result)
    except Exception:
        return False


DPI_AWARE = enable_dpi_awareness()

DEFAULT_LOCK_TIMEOUT_SECONDS = 120.0
DEFAULT_LOCK_TTL_SECONDS = 600.0
LOCK_POLL_SECONDS = 0.2
LOCK_FILE = Path(
    os.environ.get("CODEX_UI_CONTROL_LOCK_FILE", str(Path(tempfile.gettempdir()) / "codex-ui-control.lock.json"))
)
VALID_MOUSE_BUTTONS = {"left", "right", "middle"}
VALID_TYPE_METHODS = {"auto", "keys", "paste"}


def import_pyautogui():
    try:
        import pyautogui
    except Exception as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "pyautogui is required. Install with: python -m pip install pyautogui pillow"
        ) from exc
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    pyautogui.PAUSE = 0
    return pyautogui


def ok(**data: Any) -> dict[str, Any]:
    return {"ok": True, **data}


def fail(message: str, **data: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **data}


def emit(result: dict[str, Any]) -> int:
    data = json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n"
    sys.stdout.buffer.write(data.encode("utf-8", errors="replace"))
    return 0 if result.get("ok") else 1


def lock_record_public(record: dict[str, Any]) -> dict[str, Any]:
    token = str(record.get("token") or "")
    public = {key: value for key, value in record.items() if key != "token" and not key.startswith("_")}
    if token:
        public["tokenHash"] = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    public["lockFile"] = str(LOCK_FILE)
    public["expired"] = float(record.get("expiresAt", 0) or 0) <= time.time()
    return public


def read_ui_lock() -> dict[str, Any] | None:
    try:
        return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return {"corrupt": True, "expiresAt": 0, "owner": "unknown"}


def lock_expired(record: dict[str, Any] | None) -> bool:
    if not record:
        return True
    return float(record.get("expiresAt", 0) or 0) <= time.time()


def remove_stale_lock(record: dict[str, Any] | None) -> None:
    if not lock_expired(record):
        return
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def create_ui_lock(token: str, owner: str, ttl: float) -> dict[str, Any] | None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "token": token,
        "owner": owner,
        "pid": os.getpid(),
        "createdAt": time.time(),
        "expiresAt": time.time() + ttl,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(LOCK_FILE), flags)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False)
    return record


def acquire_ui_lock(timeout: float, ttl: float, owner: str) -> dict[str, Any]:
    token = uuid.uuid4().hex
    deadline = time.time() + max(timeout, 0)
    while True:
        record = read_ui_lock()
        if record is None or lock_expired(record):
            remove_stale_lock(record)
            created = create_ui_lock(token, owner, ttl)
            if created:
                return created
        if time.time() >= deadline:
            current = read_ui_lock()
            raise RuntimeError(f"UI control lock busy: {lock_record_public(current or {})}")
        time.sleep(LOCK_POLL_SECONDS)


def validate_ui_lock_token(token: str, ttl: float) -> dict[str, Any]:
    record = read_ui_lock()
    if not record:
        raise RuntimeError("UI control lock token provided, but no active lock exists")
    if lock_expired(record):
        remove_stale_lock(record)
        raise RuntimeError("UI control lock token expired")
    if record.get("token") != token:
        raise RuntimeError(f"UI control lock is held by another worker: {lock_record_public(record)}")
    record["expiresAt"] = time.time() + ttl
    LOCK_FILE.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return record


def release_ui_lock(token: str) -> dict[str, Any]:
    record = read_ui_lock()
    if not record:
        return ok(action="lock-release", released=False, reason="no active lock", lockFile=str(LOCK_FILE))
    if record.get("token") != token:
        raise RuntimeError(f"cannot release UI control lock held by another worker: {lock_record_public(record)}")
    LOCK_FILE.unlink()
    return ok(action="lock-release", released=True, lockFile=str(LOCK_FILE))


def refresh_ui_lock(token: str, ttl: float) -> dict[str, Any]:
    record = validate_ui_lock_token(token, ttl)
    return ok(action="lock-refresh", lock=lock_record_public(record))


@contextmanager
def ui_lock_for_command(args: argparse.Namespace) -> Iterator[dict[str, Any] | None]:
    if getattr(args, "command", None) == "lock" or getattr(args, "dry_run", False):
        yield None
        return
    ttl = max(float(getattr(args, "lock_ttl", DEFAULT_LOCK_TTL_SECONDS) or DEFAULT_LOCK_TTL_SECONDS), 1.0)
    token = getattr(args, "lock_token", None)
    if token:
        yield validate_ui_lock_token(token, ttl)
        return
    timeout = max(float(getattr(args, "lock_timeout", DEFAULT_LOCK_TIMEOUT_SECONDS) or 0), 0.0)
    owner = getattr(args, "lock_owner", None) or f"pid:{os.getpid()} command:{getattr(args, 'command', 'unknown')}"
    record = acquire_ui_lock(timeout, ttl, owner)
    record["_transient"] = True
    try:
        yield record
    finally:
        try:
            release_result = release_ui_lock(str(record["token"]))
            record["_released"] = bool(release_result.get("released"))
        except Exception:
            record["_released"] = False
            pass


def maybe_sleep(args: argparse.Namespace) -> None:
    delay = getattr(args, "pause_after", 0) or 0
    if delay > 0 and not getattr(args, "dry_run", False):
        time.sleep(delay)


def confirm_action(args: argparse.Namespace, description: str) -> None:
    if getattr(args, "dry_run", False) or not getattr(args, "require_approval", False):
        return
    response = input(f"Allow UI action: {description}? [y/N]: ").strip().lower()
    if response not in {"y", "yes"}:
        raise RuntimeError(f"action declined: {description}")


def append_log(args: argparse.Namespace, result: dict[str, Any]) -> None:
    log_file = getattr(args, "log_file", None)
    if not log_file:
        return
    entry = {"timestamp": time.time(), "result": result}
    path = Path(log_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def parse_region(values: list[int] | None) -> tuple[int, int, int, int] | None:
    if not values:
        return None
    if len(values) != 4:
        raise ValueError("region must be: left top width height")
    left, top, width, height = values
    if width <= 0 or height <= 0:
        raise ValueError("region width and height must be positive")
    return (left, top, width, height)


def require_non_negative(value: float, name: str) -> None:
    if value < 0:
        raise RuntimeError(f"{name} must be non-negative")


def require_positive_int(value: int, name: str) -> None:
    if value < 1:
        raise RuntimeError(f"{name} must be at least 1")


def require_bool(value: bool, name: str) -> None:
    if not isinstance(value, bool):
        raise RuntimeError(f"{name} must be a JSON boolean")


def require_choice(value: str, name: str, choices: set[str]) -> None:
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise RuntimeError(f"{name} must be one of: {allowed}")


def require_pair(x: int | None, y: int | None, name: str = "coordinates") -> None:
    if (x is None) != (y is None):
        raise RuntimeError(f"{name} require both x and y, or neither")


def check_point_bounds(args: argparse.Namespace, x: int, y: int) -> None:
    if not getattr(args, "strict_bounds", False):
        return
    pyautogui = import_pyautogui()
    size = screen_size(pyautogui)
    if not (0 <= x < size["width"] and 0 <= y < size["height"]):
        raise RuntimeError(f"point outside primary screen bounds: ({x}, {y}) not in {size}")


def check_region_bounds(args: argparse.Namespace, region: tuple[int, int, int, int] | None) -> None:
    if not getattr(args, "strict_bounds", False) or region is None:
        return
    left, top, width, height = region
    check_point_bounds(args, left, top)
    check_point_bounds(args, left + width - 1, top + height - 1)


def mouse_position(pyautogui) -> dict[str, int]:
    pos = pyautogui.position()
    return {"x": int(pos.x), "y": int(pos.y)}


def screen_size(pyautogui) -> dict[str, int]:
    width, height = pyautogui.size()
    return {"width": int(width), "height": int(height)}


def get_windows() -> list[dict[str, Any]]:
    try:
        import pygetwindow as gw
    except Exception as exc:
        raise RuntimeError("pygetwindow is required for window commands") from exc

    windows = []
    for win in gw.getAllWindows():
        title = (getattr(win, "title", "") or "").strip()
        if not title:
            continue
        windows.append(window_info(win))
    return windows


def active_window_object():
    try:
        import pygetwindow as gw
    except Exception as exc:
        raise RuntimeError("pygetwindow is required for window commands") from exc
    return gw.getActiveWindow()


def active_window() -> dict[str, Any] | None:
    win = active_window_object()
    return window_info(win) if win else None


def find_window(title: str):
    try:
        import pygetwindow as gw
    except Exception as exc:
        raise RuntimeError("pygetwindow is required for window commands") from exc
    query = title.lower()
    matches = [w for w in gw.getAllWindows() if query in ((w.title or "").lower())]
    matches = [w for w in matches if (w.title or "").strip()]
    if not matches:
        raise RuntimeError(f"no window title contains: {title}")
    return matches[0]


def window_info(win) -> dict[str, Any]:
    return {
        "title": getattr(win, "title", ""),
        "left": getattr(win, "left", None),
        "top": getattr(win, "top", None),
        "width": getattr(win, "width", None),
        "height": getattr(win, "height", None),
        "isActive": getattr(win, "isActive", None),
        "isMinimized": getattr(win, "isMinimized", None),
        "isMaximized": getattr(win, "isMaximized", None),
    }


def window_region(info: dict[str, Any]) -> tuple[int, int, int, int]:
    try:
        left = int(info["left"])
        top = int(info["top"])
        width = int(info["width"])
        height = int(info["height"])
    except Exception as exc:
        raise RuntimeError(f"window has incomplete geometry: {info}") from exc
    if width <= 0 or height <= 0:
        raise RuntimeError(f"window has invalid geometry: {info}")
    return (left, top, width, height)


def resolve_target_region(args: argparse.Namespace) -> tuple[tuple[int, int, int, int] | None, dict[str, Any] | None]:
    region = parse_region(getattr(args, "region", None))
    active = bool(getattr(args, "active", False))
    title = getattr(args, "window", None)
    target_count = int(region is not None) + int(active) + int(bool(title))
    if target_count > 1:
        raise RuntimeError("choose only one target: --region, --active, or --window")
    if active:
        win = active_window_object()
        if not win:
            raise RuntimeError("no active window")
        target = {"type": "active-window", **window_info(win)}
        return window_region(target), target
    if title:
        win = find_window(title)
        target = {"type": "window", "query": title, **window_info(win)}
        return window_region(target), target
    if region is not None:
        return region, {"type": "region", "left": region[0], "top": region[1], "width": region[2], "height": region[3]}
    return None, None


def clamp_window_region_to_primary_screen(
    pyautogui,
    region: tuple[int, int, int, int] | None,
    target: dict[str, Any] | None,
) -> tuple[tuple[int, int, int, int] | None, dict[str, Any] | None]:
    if region is None or not target or target.get("type") not in {"active-window", "window"}:
        return region, target
    screen = screen_size(pyautogui)
    left, top, width, height = region
    right = left + width
    bottom = top + height
    clamped_left = max(left, 0)
    clamped_top = max(top, 0)
    clamped_right = min(right, screen["width"])
    clamped_bottom = min(bottom, screen["height"])
    if clamped_right <= clamped_left or clamped_bottom <= clamped_top:
        return region, target
    clamped = (clamped_left, clamped_top, clamped_right - clamped_left, clamped_bottom - clamped_top)
    if clamped == region:
        return region, target
    return clamped, {
        **target,
        "requestedRegion": {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        },
        "clampedToPrimaryScreen": True,
    }


def set_clipboard(text: str) -> None:
    try:
        import pyperclip
    except Exception as exc:
        raise RuntimeError("pyperclip is required for clipboard commands") from exc
    pyperclip.copy(text)


def get_clipboard() -> str:
    try:
        import pyperclip
    except Exception as exc:
        raise RuntimeError("pyperclip is required for clipboard commands") from exc
    return pyperclip.paste()


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    result = ok(
        screen=screen_size(pyautogui),
        mouse=mouse_position(pyautogui),
        failsafe=pyautogui.FAILSAFE,
        coordinateSystem="physical_pixels",
        dpiAware=DPI_AWARE,
    )
    if args.windows:
        result["activeWindow"] = active_window()
        result["windows"] = get_windows()
    return result


def command_screenshot(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    region, target = resolve_target_region(args)
    region, target = clamp_window_region_to_primary_screen(pyautogui, region, target)
    check_region_bounds(args, region)
    out = Path(args.out).expanduser()
    confirm_action(args, f"screenshot to {out}")
    if args.dry_run:
        return ok(action="screenshot", out=str(out), region=region, target=target, dryRun=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = pyautogui.screenshot(region=region)
    img.save(out)
    maybe_sleep(args)
    return ok(action="screenshot", out=str(out), region=region, target=target, size=list(img.size))


def command_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    region, target = resolve_target_region(args)
    region, target = clamp_window_region_to_primary_screen(pyautogui, region, target)
    check_region_bounds(args, region)
    out = Path(args.out).expanduser()
    confirm_action(args, f"snapshot to {out}")
    result = ok(
        action="snapshot",
        screen=screen_size(pyautogui),
        mouse=mouse_position(pyautogui),
        failsafe=pyautogui.FAILSAFE,
        coordinateSystem="physical_pixels",
        dpiAware=DPI_AWARE,
        out=str(out),
        region=region,
        target=target,
    )
    if args.windows:
        result["activeWindow"] = active_window()
        result["windows"] = get_windows()
    if args.dry_run:
        result["dryRun"] = True
        return result
    out.parent.mkdir(parents=True, exist_ok=True)
    img = pyautogui.screenshot(region=region)
    img.save(out)
    maybe_sleep(args)
    result["size"] = list(img.size)
    return result


def command_pixel(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    check_point_bounds(args, args.x, args.y)
    color = pyautogui.pixel(args.x, args.y)
    return ok(action="pixel", x=args.x, y=args.y, rgb=list(color))


def command_move(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_bool(args.relative, "relative")
    require_non_negative(args.duration, "duration")
    if not args.relative:
        check_point_bounds(args, args.x, args.y)
    if args.dry_run:
        return ok(action="move", x=args.x, y=args.y, relative=args.relative, dryRun=True)
    confirm_action(args, f"move mouse to ({args.x}, {args.y}), relative={args.relative}")
    if args.relative:
        pyautogui.move(args.x, args.y, duration=args.duration)
    else:
        pyautogui.moveTo(args.x, args.y, duration=args.duration)
    maybe_sleep(args)
    return ok(action="move", mouse=mouse_position(pyautogui), relative=args.relative)


def command_click(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_pair(args.x, args.y)
    require_choice(args.button, "button", VALID_MOUSE_BUTTONS)
    require_positive_int(args.clicks, "clicks")
    require_non_negative(args.interval, "interval")
    if args.x is not None and args.y is not None:
        check_point_bounds(args, args.x, args.y)
    if args.dry_run:
        return ok(
            action="click",
            x=args.x,
            y=args.y,
            button=args.button,
            clicks=args.clicks,
            dryRun=True,
        )
    confirm_action(args, f"{args.button} click at ({args.x}, {args.y}) x{args.clicks}")
    pyautogui.click(x=args.x, y=args.y, button=args.button, clicks=args.clicks, interval=args.interval)
    maybe_sleep(args)
    return ok(action="click", mouse=mouse_position(pyautogui), button=args.button, clicks=args.clicks)


def command_mouse_button(args: argparse.Namespace, is_down: bool) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_pair(args.x, args.y)
    require_choice(args.button, "button", VALID_MOUSE_BUTTONS)
    require_non_negative(args.duration, "duration")
    if args.x is not None and args.y is not None:
        check_point_bounds(args, args.x, args.y)
    action = "mouse-down" if is_down else "mouse-up"
    if args.dry_run:
        return ok(action=action, x=args.x, y=args.y, button=args.button, dryRun=True)
    confirm_action(args, f"{action} {args.button} at ({args.x}, {args.y})")
    if args.x is not None and args.y is not None:
        pyautogui.moveTo(args.x, args.y, duration=args.duration)
    if is_down:
        pyautogui.mouseDown(button=args.button)
    else:
        pyautogui.mouseUp(button=args.button)
    maybe_sleep(args)
    return ok(action=action, mouse=mouse_position(pyautogui), button=args.button)


def command_hold_mouse(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_pair(args.x, args.y)
    require_choice(args.button, "button", VALID_MOUSE_BUTTONS)
    require_non_negative(args.seconds, "seconds")
    require_non_negative(args.duration, "duration")
    if args.x is not None and args.y is not None:
        check_point_bounds(args, args.x, args.y)
    if args.dry_run:
        return ok(action="hold-mouse", x=args.x, y=args.y, button=args.button, seconds=args.seconds, dryRun=True)
    confirm_action(args, f"hold {args.button} mouse for {args.seconds}s at ({args.x}, {args.y})")
    if args.x is not None and args.y is not None:
        pyautogui.moveTo(args.x, args.y, duration=args.duration)
    try:
        pyautogui.mouseDown(button=args.button)
        time.sleep(args.seconds)
    finally:
        pyautogui.mouseUp(button=args.button)
    maybe_sleep(args)
    return ok(action="hold-mouse", mouse=mouse_position(pyautogui), button=args.button, seconds=args.seconds)


def command_drag(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_choice(args.button, "button", VALID_MOUSE_BUTTONS)
    require_non_negative(args.duration, "duration")
    require_non_negative(args.move_duration, "move-duration")
    check_point_bounds(args, args.start_x, args.start_y)
    check_point_bounds(args, args.end_x, args.end_y)
    if args.dry_run:
        return ok(
            action="drag",
            start=[args.start_x, args.start_y],
            end=[args.end_x, args.end_y],
            button=args.button,
            dryRun=True,
        )
    confirm_action(args, f"drag from ({args.start_x}, {args.start_y}) to ({args.end_x}, {args.end_y})")
    try:
        pyautogui.moveTo(args.start_x, args.start_y, duration=args.move_duration)
        pyautogui.dragTo(args.end_x, args.end_y, duration=args.duration, button=args.button)
    finally:
        try:
            pyautogui.mouseUp(button=args.button)
        except Exception:
            pass
    maybe_sleep(args)
    return ok(action="drag", mouse=mouse_position(pyautogui), button=args.button)


def command_scroll(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_pair(args.x, args.y)
    require_bool(args.horizontal, "horizontal")
    if args.x is not None and args.y is not None:
        check_point_bounds(args, args.x, args.y)
    if args.dry_run:
        return ok(action="scroll", clicks=args.clicks, horizontal=args.horizontal, x=args.x, y=args.y, dryRun=True)
    confirm_action(args, f"scroll {args.clicks}, horizontal={args.horizontal}, at ({args.x}, {args.y})")
    if args.x is not None and args.y is not None:
        pyautogui.moveTo(args.x, args.y)
    if args.horizontal:
        pyautogui.hscroll(args.clicks)
    else:
        pyautogui.scroll(args.clicks)
    maybe_sleep(args)
    return ok(action="scroll", mouse=mouse_position(pyautogui), clicks=args.clicks, horizontal=args.horizontal)


def text_needs_paste(text: str) -> bool:
    return len(text) > 100 or any(ord(ch) > 127 for ch in text)


def decode_unicode_escapes(text: str) -> str:
    try:
        return text.encode("ascii").decode("unicode_escape")
    except UnicodeEncodeError as exc:
        raise RuntimeError("--decode-unicode-escapes expects ASCII-only escape text") from exc
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"invalid unicode escape text: {exc}") from exc


def read_text_input(args: argparse.Namespace) -> str:
    require_bool(getattr(args, "decode_unicode_escapes", False), "decode_unicode_escapes")
    sources = [args.text is not None, bool(args.stdin), bool(args.file)]
    if sum(sources) != 1:
        raise RuntimeError("provide exactly one text source: positional text, --stdin, or --file")
    if args.stdin:
        text = sys.stdin.read()
    elif args.file:
        text = Path(args.file).expanduser().read_text(encoding="utf-8-sig")
    else:
        text = args.text
    if getattr(args, "decode_unicode_escapes", False):
        text = decode_unicode_escapes(text)
    return text


def command_type(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    text = read_text_input(args)
    method = args.method
    require_choice(method, "method", VALID_TYPE_METHODS)
    require_bool(args.no_restore_clipboard, "no_restore_clipboard")
    if method == "auto":
        method = "paste" if text_needs_paste(text) else "keys"
    if args.wpm:
        require_positive_int(args.wpm, "wpm")
        chars_per_second = max((args.wpm * 5) / 60, 1)
        args.interval = 1.0 / chars_per_second
    require_non_negative(args.interval, "interval")
    require_non_negative(args.restore_delay, "restore-delay")
    if method == "keys" and any(ord(ch) > 127 for ch in text):
        raise RuntimeError("method=keys cannot type non-ASCII text reliably; use --method paste")
    if args.dry_run:
        return ok(action="type", method=method, chars=len(text), dryRun=True)
    confirm_action(args, f"type {len(text)} chars using {method}")
    restored = False
    if method == "paste":
        previous = None
        if not args.no_restore_clipboard:
            try:
                previous = get_clipboard()
            except Exception:
                previous = None
        set_clipboard(text)
        try:
            pyautogui.hotkey("ctrl", "v")
            if args.restore_delay > 0:
                time.sleep(args.restore_delay)
        finally:
            if previous is not None and not args.no_restore_clipboard:
                set_clipboard(previous)
                restored = True
    else:
        pyautogui.write(text, interval=args.interval)
    maybe_sleep(args)
    return ok(action="type", method=method, chars=len(text), clipboardRestored=restored)


def command_press(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_positive_int(args.presses, "presses")
    require_non_negative(args.interval, "interval")
    if args.dry_run:
        return ok(action="press", key=args.key, presses=args.presses, dryRun=True)
    confirm_action(args, f"press key {args.key} x{args.presses}")
    pyautogui.press(args.key, presses=args.presses, interval=args.interval)
    maybe_sleep(args)
    return ok(action="press", key=args.key, presses=args.presses)


def command_hotkey(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_non_negative(args.interval, "interval")
    if args.dry_run:
        return ok(action="hotkey", keys=args.keys, dryRun=True)
    confirm_action(args, f"hotkey {'+'.join(args.keys)}")
    pyautogui.hotkey(*args.keys, interval=args.interval)
    maybe_sleep(args)
    return ok(action="hotkey", keys=args.keys)


def command_key_state(args: argparse.Namespace, is_down: bool) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    action = "key-down" if is_down else "key-up"
    if args.dry_run:
        return ok(action=action, key=args.key, dryRun=True)
    confirm_action(args, f"{action} {args.key}")
    if is_down:
        pyautogui.keyDown(args.key)
    else:
        pyautogui.keyUp(args.key)
    maybe_sleep(args)
    return ok(action=action, key=args.key)


def command_key_hold(args: argparse.Namespace) -> dict[str, Any]:
    pyautogui = import_pyautogui()
    pyautogui.FAILSAFE = not args.no_failsafe
    require_non_negative(args.seconds, "seconds")
    if args.dry_run:
        return ok(action="key-hold", key=args.key, seconds=args.seconds, dryRun=True)
    confirm_action(args, f"hold key {args.key} for {args.seconds}s")
    try:
        pyautogui.keyDown(args.key)
        time.sleep(args.seconds)
    finally:
        pyautogui.keyUp(args.key)
    maybe_sleep(args)
    return ok(action="key-hold", key=args.key, seconds=args.seconds)


def command_clipboard(args: argparse.Namespace) -> dict[str, Any]:
    if args.clipboard_command == "set":
        text = args.text
        require_bool(getattr(args, "decode_unicode_escapes", False), "decode_unicode_escapes")
        if getattr(args, "decode_unicode_escapes", False):
            text = decode_unicode_escapes(text)
        if args.dry_run:
            return ok(action="clipboard-set", chars=len(text), dryRun=True)
        confirm_action(args, f"set clipboard to {len(text)} chars")
        set_clipboard(text)
        return ok(action="clipboard-set", chars=len(text))
    if args.clipboard_command != "get":
        raise RuntimeError(f"unknown clipboard command: {args.clipboard_command}")
    text = get_clipboard()
    result = ok(
        action="clipboard-get",
        chars=len(text),
        sha256=hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
    )
    if args.show:
        result["text"] = text
    elif args.preview:
        result["preview"] = text[: args.preview_chars]
        result["truncated"] = len(text) > args.preview_chars
    return result


def command_window(args: argparse.Namespace) -> dict[str, Any]:
    cmd = args.window_command
    if cmd == "list":
        return ok(action="window-list", windows=get_windows())
    if cmd == "active":
        return ok(action="window-active", activeWindow=active_window())
    win = find_window(args.title)
    if args.dry_run:
        return ok(action=f"window-{cmd}", window=window_info(win), dryRun=True)
    confirm_action(args, f"window {cmd}: {getattr(win, 'title', args.title)}")
    if cmd == "activate":
        if getattr(win, "isMinimized", False):
            win.restore()
            time.sleep(0.1)
        win.activate()
    elif cmd == "minimize":
        win.minimize()
    elif cmd == "maximize":
        win.maximize()
    elif cmd == "restore":
        win.restore()
    elif cmd == "close":
        win.close()
    elif cmd == "info":
        pass
    else:
        raise RuntimeError(f"unknown window command: {cmd}")
    maybe_sleep(args)
    return ok(action=f"window-{cmd}", window=window_info(win))


def command_find_image(args: argparse.Namespace) -> dict[str, Any]:
    image = str(Path(args.image).expanduser())
    pyautogui = import_pyautogui()
    region, target = resolve_target_region(args)
    region, target = clamp_window_region_to_primary_screen(pyautogui, region, target)
    if args.dry_run:
        return ok(action="find-image", image=image, confidence=args.confidence, region=region, target=target, dryRun=True)
    check_region_bounds(args, region)
    if is_uniform_image(image):
        location = locate_uniform_image(pyautogui, image, region)
        if not location:
            return ok(
                action="find-image",
                found=False,
                image=image,
                confidence=args.confidence,
                region=region,
                target=target,
                matchMethod="exact_uniform",
            )
        x, y, width, height = location
        return ok(
            action="find-image",
            found=True,
            image=image,
            confidence=args.confidence,
            region=region,
            target=target,
            matchMethod="exact_uniform",
            box={"x": x, "y": y, "width": width, "height": height},
            center={"x": x + width // 2, "y": y + height // 2},
        )
    try:
        location = pyautogui.locateOnScreen(image, confidence=args.confidence, region=region)
    except TypeError:
        location = pyautogui.locateOnScreen(image, region=region)
    except Exception as exc:
        return fail(str(exc), action="find-image", image=image, region=region, target=target)
    if not location:
        return ok(action="find-image", found=False, image=image, confidence=args.confidence, region=region, target=target)
    x, y, width, height = map(int, location)
    return ok(
        action="find-image",
        found=True,
        image=image,
        confidence=args.confidence,
        region=region,
        target=target,
        box={"x": x, "y": y, "width": width, "height": height},
        center={"x": x + width // 2, "y": y + height // 2},
    )


def is_uniform_image(image: str) -> bool:
    try:
        from PIL import Image
    except Exception as exc:
        raise RuntimeError("Pillow is required for image matching") from exc
    with Image.open(image) as img:
        extrema = img.convert("RGB").getextrema()
    return all(low == high for low, high in extrema)


def locate_uniform_image(pyautogui, image: str, region: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except Exception as exc:
        raise RuntimeError("opencv-python and Pillow are required for reliable solid-color image matching") from exc

    with Image.open(image) as img:
        needle = np.array(img.convert("RGB"))
    haystack = np.array(pyautogui.screenshot(region=region).convert("RGB"))
    needle_height, needle_width = needle.shape[:2]
    hay_height, hay_width = haystack.shape[:2]
    if needle_width > hay_width or needle_height > hay_height:
        return None

    result = cv2.matchTemplate(haystack, needle, cv2.TM_SQDIFF_NORMED)
    min_value, _, min_location, _ = cv2.minMaxLoc(result)
    if min_value > 1e-12:
        return None
    offset_x = region[0] if region else 0
    offset_y = region[1] if region else 0
    x, y = min_location
    return (int(offset_x + x), int(offset_y + y), int(needle_width), int(needle_height))


PROTECTED_PLAN_ACTION_KEYS = {
    "dry_run",
    "func",
    "lock_owner",
    "lock_timeout",
    "lock_token",
    "lock_ttl",
    "log_file",
    "no_failsafe",
    "pause_after",
    "plan_file",
    "plan_json",
    "require_approval",
    "stdin",
    "strict_bounds",
}


def apply_plan_action_fields(ns: argparse.Namespace, action: dict[str, Any]) -> None:
    blocked = []
    for key, value in action.items():
        attr = key.replace("-", "_")
        if attr in PROTECTED_PLAN_ACTION_KEYS:
            blocked.append(key)
            continue
        setattr(ns, attr, value)
    if blocked:
        raise RuntimeError(
            "plan action cannot override global/control fields: "
            + ", ".join(sorted(blocked))
        )


def execute_plan_action(action: dict[str, Any], base_args: argparse.Namespace) -> dict[str, Any]:
    cmd = action.get("command")
    ns = argparse.Namespace(**vars(base_args))
    apply_plan_action_fields(ns, action)

    defaults = {
        "button": "left",
        "clicks": 1,
        "presses": 1,
        "interval": 0.0,
        "duration": 0.0,
        "move_duration": 0.0,
        "relative": False,
        "horizontal": False,
        "method": "auto",
        "wpm": None,
        "stdin": False,
        "file": None,
        "decode_unicode_escapes": False,
        "no_restore_clipboard": False,
        "restore_delay": 0.05,
        "confidence": 0.8,
        "region": None,
        "active": False,
        "window": None,
        "windows": False,
        "x": None,
        "y": None,
    }
    for key, value in defaults.items():
        if not hasattr(ns, key):
            setattr(ns, key, value)
    if "start" in action and "end" in action:
        ns.start_x, ns.start_y = action["start"]
        ns.end_x, ns.end_y = action["end"]

    mapping: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
        "move": command_move,
        "click": command_click,
        "double-click": lambda a: (setattr(a, "clicks", 2), command_click(a))[1],
        "right-click": lambda a: (setattr(a, "button", "right"), command_click(a))[1],
        "middle-click": lambda a: (setattr(a, "button", "middle"), command_click(a))[1],
        "drag": command_drag,
        "scroll": command_scroll,
        "type": command_type,
        "press": command_press,
        "hotkey": command_hotkey,
        "key-down": lambda a: command_key_state(a, True),
        "key-up": lambda a: command_key_state(a, False),
        "key-hold": command_key_hold,
        "mouse-down": lambda a: command_mouse_button(a, True),
        "mouse-up": lambda a: command_mouse_button(a, False),
        "hold-mouse": command_hold_mouse,
        "clipboard-set": lambda a: (setattr(a, "clipboard_command", "set"), command_clipboard(a))[1],
        "window-activate": lambda a: (setattr(a, "window_command", "activate"), command_window(a))[1],
        "screenshot": command_screenshot,
        "snapshot": command_snapshot,
        "find-image": command_find_image,
    }
    if cmd == "sleep":
        seconds = float(action.get("seconds", 0))
        require_non_negative(seconds, "seconds")
        if not base_args.dry_run:
            time.sleep(seconds)
        return ok(action="sleep", seconds=seconds, dryRun=base_args.dry_run)
    if cmd not in mapping:
        return fail(f"unsupported plan command: {cmd}", action=action)
    return mapping[cmd](ns)


def command_plan(args: argparse.Namespace) -> dict[str, Any]:
    if args.plan_file:
        raw = Path(args.plan_file).expanduser().read_text(encoding="utf-8-sig")
    else:
        raw = args.plan_json
    actions = json.loads(raw)
    if not isinstance(actions, list):
        raise RuntimeError("plan must be a JSON list of action objects")
    confirm_action(args, f"execute plan with {len(actions)} actions")
    results = []
    held_keys: list[str] = []
    held_buttons: list[str] = []
    failed = False
    try:
        for idx, action in enumerate(actions, 1):
            if not isinstance(action, dict):
                results.append(fail("plan action must be an object", index=idx))
                failed = True
                break
            try:
                result = execute_plan_action(action, args)
            except Exception as exc:
                result = fail(str(exc), action=action)
                failed = True
            result["index"] = idx
            results.append(result)
            cmd = action.get("command")
            if result.get("ok"):
                if cmd == "key-down":
                    held_keys.append(action["key"])
                elif cmd == "key-up" and action.get("key") in held_keys:
                    held_keys.remove(action["key"])
                elif cmd == "mouse-down":
                    held_buttons.append(action.get("button", "left"))
                elif cmd == "mouse-up" and action.get("button", "left") in held_buttons:
                    held_buttons.remove(action.get("button", "left"))
            if not result.get("ok"):
                failed = True
                break
    finally:
        if failed and not args.dry_run and (held_keys or held_buttons):
            pyautogui = import_pyautogui()
            for key in reversed(held_keys):
                try:
                    pyautogui.keyUp(key)
                except Exception:
                    pass
            for button in reversed(held_buttons):
                try:
                    pyautogui.mouseUp(button=button)
                except Exception:
                    pass
    success = (not failed) and len(results) == len(actions) and all(item.get("ok") for item in results)
    return {"ok": success, "action": "plan", "count": len(actions), "results": results}


def command_lock(args: argparse.Namespace) -> dict[str, Any]:
    if args.lock_command == "acquire":
        owner = args.owner or f"pid:{os.getpid()} ui-worker"
        record = acquire_ui_lock(args.timeout, args.ttl, owner)
        return ok(
            action="lock-acquire",
            token=record["token"],
            lock=lock_record_public(record),
            useWith=f"--lock-token {record['token']}",
        )
    if args.lock_command == "release":
        return release_ui_lock(args.token)
    if args.lock_command == "refresh":
        return refresh_ui_lock(args.token, args.ttl)
    if args.lock_command == "status":
        record = read_ui_lock()
        return ok(action="lock-status", locked=bool(record and not lock_expired(record)), lock=lock_record_public(record or {}))
    raise RuntimeError(f"unsupported lock command: {args.lock_command}")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-failsafe", action="store_true", help="Disable PyAutoGUI corner failsafe")
    parser.add_argument("--dry-run", action="store_true", help="Describe actions without performing them")
    parser.add_argument("--pause-after", type=float, default=0, help="Sleep after the action")
    parser.add_argument("--require-approval", action="store_true", help="Prompt before performing UI actions")
    parser.add_argument("--strict-bounds", action="store_true", help="Reject points outside the primary screen")
    parser.add_argument("--log-file", help="Append JSONL action results to this file")
    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=DEFAULT_LOCK_TIMEOUT_SECONDS,
        help="Seconds to wait for the global UI control lock before failing",
    )
    parser.add_argument(
        "--lock-ttl",
        type=float,
        default=DEFAULT_LOCK_TTL_SECONDS,
        help="Seconds before a held UI control lock is considered stale",
    )
    parser.add_argument("--lock-token", help="Use an already acquired UI control lock token")
    parser.add_argument("--lock-owner", help="Owner label recorded when acquiring a transient UI control lock")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows UI automation primitives")
    add_common(parser)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status")
    p.add_argument("--windows", action="store_true")
    p.set_defaults(func=command_status)

    p = sub.add_parser("screenshot")
    p.add_argument("--out", required=True)
    screenshot_target = p.add_mutually_exclusive_group()
    screenshot_target.add_argument("--region", nargs=4, type=int)
    screenshot_target.add_argument("--active", action="store_true", help="Capture only the active window")
    screenshot_target.add_argument("--window", help="Capture only the first window whose title contains this text")
    p.set_defaults(func=command_screenshot)

    p = sub.add_parser("snapshot")
    p.add_argument("--out", required=True)
    p.add_argument("--windows", action="store_true", help="Include active window and window list metadata")
    snapshot_target = p.add_mutually_exclusive_group()
    snapshot_target.add_argument("--region", nargs=4, type=int)
    snapshot_target.add_argument("--active", action="store_true", help="Capture only the active window")
    snapshot_target.add_argument("--window", help="Capture only the first window whose title contains this text")
    p.set_defaults(func=command_snapshot)

    p = sub.add_parser("pixel")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(func=command_pixel)

    p = sub.add_parser("move")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--relative", action="store_true")
    p.add_argument("--duration", type=float, default=0)
    p.set_defaults(func=command_move)

    p = sub.add_parser("click")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--clicks", type=int, default=1)
    p.add_argument("--interval", type=float, default=0.1)
    p.set_defaults(func=command_click)

    p = sub.add_parser("double-click")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--interval", type=float, default=0.1)
    p.set_defaults(func=lambda a: (setattr(a, "clicks", 2), command_click(a))[1])

    p = sub.add_parser("right-click")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--interval", type=float, default=0.1)
    p.set_defaults(func=lambda a: (setattr(a, "button", "right"), setattr(a, "clicks", 1), command_click(a))[2])

    p = sub.add_parser("middle-click")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--interval", type=float, default=0.1)
    p.set_defaults(func=lambda a: (setattr(a, "button", "middle"), setattr(a, "clicks", 1), command_click(a))[2])

    p = sub.add_parser("mouse-down")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--duration", type=float, default=0)
    p.set_defaults(func=lambda a: command_mouse_button(a, True))

    p = sub.add_parser("mouse-up")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--duration", type=float, default=0)
    p.set_defaults(func=lambda a: command_mouse_button(a, False))

    p = sub.add_parser("hold-mouse")
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--duration", type=float, default=0)
    p.set_defaults(func=command_hold_mouse)

    p = sub.add_parser("drag")
    p.add_argument("start_x", type=int)
    p.add_argument("start_y", type=int)
    p.add_argument("end_x", type=int)
    p.add_argument("end_y", type=int)
    p.add_argument("--duration", type=float, default=0.5)
    p.add_argument("--move-duration", type=float, default=0)
    p.add_argument("--button", choices=["left", "right", "middle"], default="left")
    p.set_defaults(func=command_drag)

    p = sub.add_parser("scroll")
    p.add_argument("clicks", type=int)
    p.add_argument("--x", type=int)
    p.add_argument("--y", type=int)
    p.add_argument("--horizontal", action="store_true")
    p.set_defaults(func=command_scroll)

    p = sub.add_parser("type")
    p.add_argument("text", nargs="?")
    p.add_argument("--stdin", action="store_true")
    p.add_argument("--file")
    p.add_argument("--method", choices=["auto", "keys", "paste"], default="auto")
    p.add_argument("--interval", type=float, default=0)
    p.add_argument("--wpm", type=int)
    p.add_argument(
        "--decode-unicode-escapes",
        action="store_true",
        help="Decode ASCII Unicode escapes such as \\u6587 before typing/pasting",
    )
    p.add_argument("--no-restore-clipboard", action="store_true")
    p.add_argument("--restore-delay", type=float, default=0.05)
    p.set_defaults(func=command_type)

    p = sub.add_parser("press")
    p.add_argument("key")
    p.add_argument("--presses", type=int, default=1)
    p.add_argument("--interval", type=float, default=0.1)
    p.set_defaults(func=command_press)

    p = sub.add_parser("hotkey")
    p.add_argument("keys", nargs="+")
    p.add_argument("--interval", type=float, default=0.05)
    p.set_defaults(func=command_hotkey)

    p = sub.add_parser("key-down")
    p.add_argument("key")
    p.set_defaults(func=lambda a: command_key_state(a, True))

    p = sub.add_parser("key-up")
    p.add_argument("key")
    p.set_defaults(func=lambda a: command_key_state(a, False))

    p = sub.add_parser("key-hold")
    p.add_argument("key")
    p.add_argument("--seconds", type=float, required=True)
    p.set_defaults(func=command_key_hold)

    p = sub.add_parser("clipboard")
    clip_sub = p.add_subparsers(dest="clipboard_command", required=True)
    c = clip_sub.add_parser("get")
    c.add_argument("--show", action="store_true")
    c.add_argument("--preview", action="store_true")
    c.add_argument("--preview-chars", type=int, default=80)
    c.set_defaults(func=command_clipboard)
    c = clip_sub.add_parser("set")
    c.add_argument("text")
    c.add_argument(
        "--decode-unicode-escapes",
        action="store_true",
        help="Decode ASCII Unicode escapes such as \\u6587 before setting clipboard",
    )
    c.set_defaults(func=command_clipboard)

    p = sub.add_parser("window")
    win_sub = p.add_subparsers(dest="window_command", required=True)
    for name in ["list", "active"]:
        w = win_sub.add_parser(name)
        w.set_defaults(func=command_window)
    for name in ["activate", "info", "minimize", "maximize", "restore", "close"]:
        w = win_sub.add_parser(name)
        w.add_argument("title")
        w.set_defaults(func=command_window)

    p = sub.add_parser("find-image")
    p.add_argument("image")
    p.add_argument("--confidence", type=float, default=0.8)
    image_target = p.add_mutually_exclusive_group()
    image_target.add_argument("--region", nargs=4, type=int)
    image_target.add_argument("--active", action="store_true", help="Search only within the active window")
    image_target.add_argument("--window", help="Search only within the first window whose title contains this text")
    p.set_defaults(func=command_find_image)

    p = sub.add_parser("plan")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", dest="plan_file")
    src.add_argument("--json", dest="plan_json")
    p.set_defaults(func=command_plan)

    p = sub.add_parser("lock")
    lock_sub = p.add_subparsers(dest="lock_command", required=True)
    l = lock_sub.add_parser("acquire")
    l.add_argument("--timeout", type=float, default=DEFAULT_LOCK_TIMEOUT_SECONDS)
    l.add_argument("--ttl", type=float, default=DEFAULT_LOCK_TTL_SECONDS)
    l.add_argument("--owner")
    l.set_defaults(func=command_lock)
    l = lock_sub.add_parser("release")
    l.add_argument("--token", required=True)
    l.set_defaults(func=command_lock)
    l = lock_sub.add_parser("refresh")
    l.add_argument("--token", required=True)
    l.add_argument("--ttl", type=float, default=DEFAULT_LOCK_TTL_SECONDS)
    l.set_defaults(func=command_lock)
    l = lock_sub.add_parser("status")
    l.set_defaults(func=command_lock)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        lock_record = None
        with ui_lock_for_command(args) as lock_record:
            result = args.func(args)
        if lock_record is not None and result.get("ok"):
            ui_lock = lock_record_public(lock_record)
            if lock_record.get("_transient"):
                ui_lock["scope"] = "transient-command"
                ui_lock["released"] = bool(lock_record.get("_released"))
            else:
                ui_lock["scope"] = "provided-token"
                ui_lock["released"] = False
            result["uiLock"] = ui_lock
    except Exception as exc:
        result = fail(str(exc), command=getattr(args, "command", None))
    try:
        append_log(args, result)
    except Exception as exc:
        result = fail(f"action completed but logging failed: {exc}", result=result)
    return emit(result)


if __name__ == "__main__":
    raise SystemExit(main())
