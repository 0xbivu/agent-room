"""Router review checks: private tmux socket, dummy agent, in-memory API only."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


class Stop(BaseException):
    pass


class Sandbox:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="room-router-check-")
        self.socket = str(Path(self.temp.name) / "tmux.sock")
        self.execute("new-session", "-d", "-s", "router-check", "/bin/cat")
        self.pane = self.execute("list-panes", "-t", "router-check", "-F", "#{pane_id}").stdout.strip()
        loader = importlib.machinery.SourceFileLoader("router_check", str(Path(__file__).resolve().parents[1] / "room"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.room = importlib.util.module_from_spec(spec)
        loader.exec_module(self.room)
        self.room.DIR = self.temp.name
        self.room.SESSIONS = self.temp.name
        self.session = "20000101-000000"
        (Path(self.temp.name) / self.session).mkdir()
        self.now = 100.0
        self.step = 0
        self.session_calls = 0
        self.limit = 0
        self.events = {}
        self.messages = []
        self.live = {"claude": (self.pane, "claude", 0, "router-check")}
        self.delivered = []
        self.spawned = []
        self.keys = []
        self.commands = []
        self.buffer = None
        self.fail_paste = False
        self.crash_on_spawn = False
        self.launch_error = False
        self.screen = lambda: "❯ "
        self.on_step = lambda: None
        self.room.CORE = ("claude",)
        self.room.api = self.api
        self.room.agents = lambda: dict(self.live)
        self.real_spawn = self.room.spawn
        self.room.room_agents = lambda: {}
        self.room.spawn = self.spawn
        self.room.tmux = self.tmux
        self.room.last_lines = lambda *args: self.screen()
        self.room.model_lists = lambda: {}
        self.room.record_conversations = lambda live: None
        self.room.alert = lambda asking: None
        self.room.main = lambda args: self.commands.append(args)
        self.room.subprocess = SimpleNamespace(run=self.run_command)
        self.room.time = SimpleNamespace(time=lambda: self.now, sleep=self.sleep)

    def execute(self, *args, **kwargs):
        return subprocess.run(["tmux", "-S", self.socket, *args], text=True, capture_output=True, **kwargs)

    def close(self):
        self.execute("kill-server")
        self.temp.cleanup()

    def add(self, sender, text):
        self.messages.append({"id": len(self.messages) + 1, "from": sender, "text": text, "ts": self.now})

    def api(self, path, data=None):
        if path == "/session":
            self.session_calls += 1
            if self.session_calls > 1:
                self.step += 1
                if self.step > self.limit:
                    raise Stop
                self.on_step()
            return {"id": self.session}
        if path == "/sessions":
            return {"sessions": []}
        if path == "/messages" and data is not None:
            self.add(data["from"], data["text"])
            return self.messages[-1]
        if path == "/messages":
            return list(self.messages)
        if path.startswith("/messages?since="):
            for sender, text in self.events.pop(self.step, []):
                self.add(sender, text)
            since = int(path.split("=")[1])
            return [m for m in self.messages if m["id"] > since]
        return {}

    def sleep(self, seconds):
        self.now += seconds

    def spawn(self, name, kind, **kwargs):
        self.spawned.append(self.now)
        if self.launch_error:
            original_tmux = self.room.tmux
            self.room.tmux = lambda *args, **kwargs: ""
            try:
                self.real_spawn(name, kind, **kwargs)
            finally:
                self.room.tmux = original_tmux
            return
        if not self.crash_on_spawn:
            self.live[name] = (self.pane, kind, self.now, "router-check")

    def tmux(self, *args, check=False):
        if args[0] == "send-keys":
            self.keys.append(args[3:])
        call = list(args)
        if args[0] == "paste-buffer" and self.fail_paste:
            self.fail_paste = False
            call[call.index("-t") + 1] = "%99999999"
        result = self.execute(*call)
        if check:
            result.check_returncode()
        if args[0] == "paste-buffer" and result.returncode == 0:
            self.delivered.append(self.buffer)
        # Mirror production tmux(): unsuccessful commands return empty stdout.
        return result.stdout.strip()

    def run_command(self, args, **kwargs):
        assert args[:2] == ["tmux", "load-buffer"], args
        self.buffer = kwargs["input"]
        result = self.execute(*args[1:], input=self.buffer)
        if kwargs.get("check"):
            result.check_returncode()
        return result

    def run(self, steps, events=None):
        self.step, self.limit, self.session_calls = 0, steps, 0
        self.events = dict(events or {})
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.room.router()
        except Stop:
            pass


class RouterChecks(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.close)

    def test_crash_respawns_have_backoff(self):
        s = self.sandbox
        s.live.clear()
        s.crash_on_spawn = True
        s.run(65)
        self.assertGreaterEqual(len(s.spawned), 3)
        self.assertTrue(all(b - a > 20 for a, b in zip(s.spawned, s.spawned[1:])), s.spawned)

    def test_stable_startup_dialog_stops_after_three_attempts(self):
        s = self.sandbox
        s.screen = lambda: "Bypass Permissions mode\n❯ No, exit\n  Yes, I accept"
        s.run(8)
        self.assertEqual(len(s.keys), 3)
        self.assertEqual(sum("is stuck" in m["text"] for m in s.messages), 1)

    def test_changing_startup_dialog_stops_after_three_attempts(self):
        s = self.sandbox
        s.screen = lambda: f"Bypass Permissions mode\nLoading {s.step}\n❯ No, exit\n  Yes, I accept"
        s.run(8)
        self.assertLessEqual(len(s.keys), 3)
        self.assertEqual(sum("is stuck" in m["text"] for m in s.messages), 1)

    def test_startup_retry_count_resets_when_dialog_disappears(self):
        s = self.sandbox
        s.screen = lambda: "❯ " if s.step == 4 else "Bypass Permissions mode\n❯ No, exit\n  Yes, I accept"
        s.run(8)
        self.assertEqual(len(s.keys), 6)
        self.assertEqual(sum("is stuck" in m["text"] for m in s.messages), 1)

    def test_hop_limit_warns_once_and_user_resumes_delivery(self):
        s = self.sandbox
        events = {i: [("codex", f"@claude agent-{i}")] for i in range(2, 52)}
        events[1] = [("user", "start")]
        events[52] = [("user", "resume")]
        events[53] = [("codex", "@claude after-resume")]
        s.run(53, events)
        self.assertEqual(sum("Paused agent-to-agent" in m["text"] for m in s.messages), 1)
        direct = [text.split("[end catch-up]\n")[-1] for text in s.delivered]
        self.assertFalse(any("agent-51" in text for text in direct))
        self.assertTrue(any("after-resume" in text for text in direct))

    def test_pending_delivery_survives_agent_respawn(self):
        s = self.sandbox
        s.live["claude"] = (s.pane, "claude", s.now, "router-check")
        s.on_step = lambda: s.live.clear() if s.step == 2 else None
        s.run(30, {1: [("user", "@claude queued-task")]})
        self.assertEqual(len(s.spawned), 1)
        self.assertEqual(len(s.delivered), 1)
        self.assertIn("queued-task", s.delivered[0])

    def test_router_restart_does_not_duplicate_delivered_messages(self):
        s = self.sandbox
        s.run(1, {1: [("user", "@claude delivered-task")]})
        s.run(3)
        self.assertEqual(len(s.delivered), 1)

    def test_router_restart_preserves_pending_messages(self):
        s = self.sandbox
        s.live["claude"] = (s.pane, "claude", s.now, "router-check")
        s.run(1, {1: [("user", "@claude queued-task")]})
        self.assertEqual(s.delivered, [])
        s.now += 30
        s.run(3)
        self.assertEqual(len(s.delivered), 1)

    def test_launch_error_keeps_router_running(self):
        s = self.sandbox
        s.live.clear()
        s.launch_error = True
        s.run(3)
        self.assertGreaterEqual(s.step, 3)

    def test_failed_paste_retries_delivery(self):
        s = self.sandbox
        s.fail_paste = True
        s.run(1, {1: [("user", "@claude retry-task")]})
        saved = s.room.router_state(s.session)
        self.assertEqual(saved["cursor"]["claude"], 0)
        self.assertEqual(len(saved["pending"]), 1)
        s.run(3)
        self.assertEqual(len(s.delivered), 1)
        saved = s.room.router_state(s.session)
        self.assertEqual(saved["cursor"]["claude"], 1)
        self.assertEqual(saved["pending"], [])

    def test_router_restart_does_not_replay_cli_commands(self):
        s = self.sandbox
        s.live["claude"] = (s.pane, "claude", s.now, "router-check")
        s.run(1, {1: [("user", "/model claude opus high"), ("user", "@claude queued-task")]})
        s.now += 30
        s.run(3)
        self.assertEqual(s.commands, [["model", "claude", "opus", "high"]])

    def test_router_crash_during_command_does_not_replay_it(self):
        for command in ("/model claude opus high", "/clear", "/new", "/resume 20000101-000000"):
            with self.subTest(command=command):
                s = Sandbox()
                try:
                    def interrupted_command(args):
                        s.commands.append(args)
                        raise Stop

                    s.room.main = interrupted_command
                    s.run(1, {1: [("user", command), ("user", "@claude next-task")]})
                    s.run(3)
                    self.assertEqual(len(s.commands), 1)
                    self.assertEqual(len(s.delivered), 1)
                finally:
                    s.close()

    def test_truncated_catchup_is_marked(self):
        s = self.sandbox
        s.live["agy"] = (s.pane, "agy", 0, "router-check")
        s.run(1, {1: [("codex", "@agy " + "x" * 2000), ("user", "@all status")]})
        catchup = next(text for text in s.delivered if "[room catch-up:" in text)
        self.assertIn("[cut; room log", catchup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
