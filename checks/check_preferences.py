"""Preference lifecycle regressions: temporary data and a private tmux socket only."""
import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'room'


class PreferencesChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='room-preferences-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.socket = str(self.root / 'tmux.sock')
        self.addCleanup(lambda: self.execute('kill-server'))
        self.sid = '20000101-000001'
        self.counter = 1
        self.sessions = {self.sid}
        self.launches = []
        (self.root / 'data' / 'sessions' / self.sid).mkdir(parents=True)
        self.load()
        self.execute('new-session', '-d', '-s', 'room', '-n', 'team', '/bin/cat')
        for kind in self.room.CORE:
            self.room.set_model(kind, kind, self.room.DEFAULTS[kind][0], 'high')
            self.room.spawn(kind, kind, window='room:team')

    def execute(self, *args, **kwargs):
        kwargs.setdefault('text', True)
        kwargs.setdefault('capture_output', True)
        return subprocess.run(['tmux', '-S', self.socket, *args], **kwargs)

    def load(self):
        loader = importlib.machinery.SourceFileLoader('preferences_check', str(SOURCE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        room = importlib.util.module_from_spec(spec)
        loader.exec_module(room)
        # Redirect all module-owned paths, including any new preferences file.
        for key, value in list(vars(room).items()):
            if isinstance(value, str) and value.startswith(str(SOURCE.parent)):
                setattr(room, key, str(self.root) + value[len(str(SOURCE.parent)):])
        room.HOME = str(self.root / 'home')
        Path(room.WS).mkdir(exist_ok=True)
        room.api = self.api
        room.tmux = self.tmux
        room.cli = self.cli
        room.record_conversations = lambda live: None
        room.subprocess = SimpleNamespace(run=self.run_command)
        self.room = room

    def cli(self, kind, model, effort, *args):
        self.launches.append((kind, model, effort))
        return '/bin/cat'

    def tmux(self, *args, check=False):
        args = list(args)
        if args[0] in ('new-session', 'new-window', 'split-window'):
            args[-1] = '/bin/cat'
        result = self.execute(*args)
        if check:
            result.check_returncode()
        return result.stdout.strip()

    def run_command(self, args, **kwargs):
        if args[0] == 'tmux':
            return self.execute(*args[1:], **kwargs)
        if args[:2] == ['docker', 'build']:
            return subprocess.CompletedProcess(args, 0, 'scratch-image', '')
        if args[:2] == ['docker', 'inspect']:
            return subprocess.CompletedProcess(args, 0, 'true scratch-image', '')
        if args[:2] == ['docker', 'rm']:
            return subprocess.CompletedProcess(args, 0, '', '')
        raise AssertionError(f'unexpected external command: {args}')

    def api(self, path, data=None):
        if path == '/session':
            return {'id': self.sid}
        if path == '/sessions':
            return {'sessions': [{'id': sid} for sid in sorted(self.sessions)]}
        if path == '/sessions/new':
            self.counter += 1
            self.sid = f'20000101-{self.counter:06d}'
            self.sessions.add(self.sid)
            (Path(self.room.SESSIONS) / self.sid).mkdir()
            return {'id': self.sid}
        if path == '/sessions/resume':
            self.sid = data['id']
            return {'id': self.sid}
        if path == '/clear':
            return {'ok': True}
        if path.startswith('/messages?since='):
            return []
        raise AssertionError(f'unexpected API call: {path}')

    def assert_efforts(self, expected):
        records = self.room.room_agents()
        self.assertEqual({kind: records[kind]['effort'] for kind in self.room.CORE},
                         {kind: expected for kind in self.room.CORE})
        latest = {kind: effort for kind, model, effort in self.launches}
        self.assertEqual({kind: latest[kind] for kind in self.room.CORE},
                         {kind: expected for kind in self.room.CORE})

    def test_model_without_effort_preserves_high(self):
        for kind in self.room.CORE:
            self.room.main(['model', kind, self.room.DEFAULTS[kind][0]])
        self.assert_efforts('high')

    def test_spawn_model_without_effort_preserves_high(self):
        for kind in self.room.CORE:
            self.room.kill(kind, forget=False)
            self.room.main(['spawn', kind, kind, self.room.DEFAULTS[kind][0]])
        self.assert_efforts('high')

    def test_new_preserves_high(self):
        self.room.main(['new'])
        self.assert_efforts('high')

    def test_down_up_preserves_high(self):
        self.room.down()
        self.load()
        self.room.up()
        for kind in self.room.CORE:
            self.room.spawn(kind, kind, window='room:team')
        self.assert_efforts('high')

    def test_clear_preserves_high(self):
        self.room.main(['clear'])
        self.assert_efforts('high')

    def test_fresh_preserves_high(self):
        self.room.main(['fresh'])
        self.assert_efforts('high')

    def test_kill_respawn_preserves_high(self):
        for kind in self.room.CORE:
            self.room.kill(kind)
            self.room.spawn(kind, kind, window='room:team')
        self.assert_efforts('high')

    def test_high_to_low_survives_process_reload_and_new(self):
        for kind in self.room.CORE:
            self.room.main(['model', kind, self.room.DEFAULTS[kind][0], 'low'])
        self.assert_efforts('low')
        self.load()
        self.room.main(['new'])
        self.assert_efforts('low')

    def test_low_down_up_preserves_low(self):
        for kind in self.room.CORE:
            self.room.main(['model', kind, self.room.DEFAULTS[kind][0], 'low'])
        self.room.down()
        self.load()
        self.room.up()
        for kind in self.room.CORE:
            self.room.spawn(kind, kind, window='room:team')
        self.assert_efforts('low')

    def test_one_agent_change_preserves_other_preferences(self):
        self.room.main(['model', 'codex', self.room.DEFAULTS['codex'][0], 'low'])
        self.load()
        self.room.main(['new'])
        self.assertEqual({kind: record['effort'] for kind, record in self.room.room_agents().items()},
                         {'claude': 'high', 'codex': 'low', 'agy': 'high'})

    def test_helper_inherits_core_effort(self):
        self.room.main(['spawn', 'helper', 'codex'])
        self.assertEqual(self.room.room_agents()['helper']['effort'], 'high')
        self.assertEqual(self.launches[-1][2], 'high')

    def test_reused_helper_name_uses_new_cli_preferences(self):
        self.room.main(['spawn', 'helper', 'codex', self.room.DEFAULTS['codex'][0], 'low'])
        self.room.kill('helper')
        self.room.main(['spawn', 'helper', 'agy'])
        self.assertEqual(self.launches[-1], ('agy', self.room.DEFAULTS['agy'][0], 'high'))

    def test_resume_does_not_restore_historical_effort(self):
        old = self.sid
        self.room.main(['new'])
        for kind in self.room.CORE:
            self.room.main(['model', kind, self.room.DEFAULTS[kind][0], 'low'])
        self.room.main(['resume', old])
        self.assert_efforts('low')


if __name__ == '__main__':
    with contextlib.redirect_stdout(io.StringIO()):
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PreferencesChecks)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
