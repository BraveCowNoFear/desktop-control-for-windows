import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ui_control.py"


class UiControlLockTests(unittest.TestCase):
    def run_cli(self, env: dict[str, str], *args: str) -> tuple[int, dict]:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        data = json.loads(completed.stdout)
        return completed.returncode, data

    def make_env(self, tmpdir: Path, *, thread_id: str, idle_seconds: str = "1") -> dict[str, str]:
        env = os.environ.copy()
        env["CODEX_UI_CONTROL_LOCK_FILE"] = str(tmpdir / "lock.json")
        env["CODEX_UI_OVERLAY_STATE_FILE"] = str(tmpdir / "default-overlay.json")
        env["CODEX_UI_OVERLAY_IDLE_SECONDS"] = idle_seconds
        env["CODEX_THREAD_ID"] = thread_id
        return env

    def test_stale_overlay_bound_lock_can_be_recovered(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ui-control-lock-") as tmp:
            tmpdir = Path(tmp)
            env = self.make_env(tmpdir, thread_id="thread-stale")
            lock_path = Path(env["CODEX_UI_CONTROL_LOCK_FILE"])
            state_path = tmpdir / "overlay.json"
            token = "deadbeefdeadbeefdeadbeefdeadbeef"
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
            now = time.time()
            lock_path.write_text(
                json.dumps(
                    {
                        "token": token,
                        "owner": "stale-test",
                        "pid": 123,
                        "threadId": "thread-stale",
                        "createdAt": now - 300,
                        "updatedAt": now - 300,
                        "expiresAt": now + 3600,
                        "overlaySessionExpected": True,
                        "overlayStateFile": str(state_path),
                    }
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "phase": "working",
                        "status": "success",
                        "task": "stale-demo",
                        "summary": "stuck",
                        "updatedAt": now - 120,
                        "activityAt": now - 120,
                        "startedAt": now - 180,
                        "threadId": "thread-stale",
                        "lockTokenHash": token_hash,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            status_code, status = self.run_cli(env, "lock", "status")
            self.assertEqual(status_code, 0)
            self.assertFalse(status["locked"])

            acquire_code, acquire = self.run_cli(env, "lock", "acquire", "--timeout", "0.5", "--owner", "next-worker")
            self.assertEqual(acquire_code, 0, acquire)
            self.assertEqual(acquire["action"], "lock-acquire")

    def test_custom_overlay_state_file_is_kept_alive_via_pointer(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ui-control-pointer-") as tmp:
            tmpdir = Path(tmp)
            env = self.make_env(tmpdir, thread_id="thread-pointer")
            env.pop("CODEX_UI_OVERLAY_STATE_FILE", None)
            pointer_path = Path(env["CODEX_UI_CONTROL_LOCK_FILE"] + ".overlay-state.json")
            custom_state_path = tmpdir / "custom-overlay.json"
            now = time.time()
            custom_state_path.write_text(
                json.dumps(
                    {
                        "phase": "working",
                        "status": "success",
                        "task": "pointer-demo",
                        "summary": "active",
                        "updatedAt": now - 10,
                        "activityAt": now - 10,
                        "startedAt": now - 20,
                        "threadId": "thread-pointer",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            pointer_path.write_text(
                json.dumps(
                    {
                        "stateFile": str(custom_state_path),
                        "threadId": "thread-pointer",
                        "updatedAt": now - 10,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            acquire_code, acquire = self.run_cli(env, "lock", "acquire", "--owner", "pointer-worker")
            self.assertEqual(acquire_code, 0, acquire)
            first_activity = json.loads(custom_state_path.read_text(encoding="utf-8"))["activityAt"]
            self.assertIn("lockTokenHash", json.loads(custom_state_path.read_text(encoding="utf-8")))

            time.sleep(0.05)
            status_code, status = self.run_cli(env, "--lock-token", acquire["token"], "status")
            self.assertEqual(status_code, 0, status)
            second_activity = json.loads(custom_state_path.read_text(encoding="utf-8"))["activityAt"]
            self.assertGreater(second_activity, first_activity)

    def test_missing_thread_id_overlay_is_not_hijacked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ui-control-thread-") as tmp:
            tmpdir = Path(tmp)
            env = self.make_env(tmpdir, thread_id="thread-new")
            state_path = Path(env["CODEX_UI_OVERLAY_STATE_FILE"])
            now = time.time()
            state_path.write_text(
                json.dumps(
                    {
                        "phase": "working",
                        "status": "success",
                        "task": "legacy-overlay",
                        "summary": "legacy",
                        "updatedAt": now,
                        "activityAt": now,
                        "startedAt": now - 5,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            acquire_code, acquire = self.run_cli(env, "lock", "acquire", "--owner", "thread-worker")
            self.assertEqual(acquire_code, 0, acquire)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotIn("lockTokenHash", state)
            self.assertNotIn("threadId", state)


if __name__ == "__main__":
    unittest.main()
