import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def fixture(root):
    files = {
        'app/server.py': '''from contextlib import asynccontextmanager
from . import brain, store, voice, weaver
store.init()
app = object()
async def _reply_stream(user_text=None, note=None, heard=None):
    yield "hello"
class ChatIn(BaseModel):
    text: str
async def chat(body):
    return StreamingResponse(_reply_stream(text, note=note, heard=heard), media_type="text/event-stream")
''',
        'static/app.js': '''async function speak(text, force = false) {
}
async function send(text, heard = null) {
  if (!text || busy) return;
}
setInterval(() => {
  streamReply("/api/nudge");
}, 60000);
''',
        'static/world.js': '''async function speak(text) {
}
async function stream(url, body) {
  if (busy) return;
}
''',
        'static/index.html': '<head>\n</head>\n',
        'static/world.html': '<head>\n</head>\n',
        '.env': 'SECRET DO NOT COPY', 'data/history.db': 'private history',
        'models/persona.json': 'private persona',
    }
    for name, value in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
    return files


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.original = fixture(self.root)

    def module(self):
        path = ROOT / 'install_companion.py'
        self.assertTrue(path.exists(), 'safe source installer is missing')
        spec = importlib.util.spec_from_file_location('installer_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_repeatable_source_only_install(self):
        module = self.module()
        changes = module.build_changes(self.root)
        self.assertEqual(len(changes), 8)
        first = module.install(self.root)
        after = {name: (self.root / name).read_bytes() for name in changes}
        second = module.install(self.root)
        self.assertEqual(second['changed'], [])
        self.assertEqual(after, {name: (self.root / name).read_bytes() for name in changes})
        self.assertEqual((self.root / 'static/app.js').read_text(encoding='utf-8').count('BEGIN XIAONUAN BODY VIEW'), 1)
        server = (self.root / 'app/server.py').read_text(encoding='utf-8')
        self.assertIn('source=body.source', server)
        self.assertIn('attach_body_routes(app, body_hub, _reply_stream, voice=voice)', server)
        backups = list(Path(first['backup']).rglob('*'))
        self.assertFalse(any(p.name in ('.env', 'history.db', 'persona.json') for p in backups))
        for name in ('.env', 'data/history.db', 'models/persona.json'):
            self.assertEqual((self.root / name).read_text(), self.original[name])

    def test_missing_anchor_writes_nothing(self):
        module = self.module()
        (self.root / 'static/world.js').write_text('unsupported source', encoding='utf-8')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaises(module.InstallError):
            module.install(self.root)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_check_cli_validates_without_writing(self):
        self.module()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = subprocess.run([sys.executable, str(ROOT / 'install_companion.py'), '--target', str(self.root), '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['changed']), 8)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_failed_write_rolls_back_own_changes(self):
        module = self.module()
        real = module._atomic_write
        calls = []
        def fail_once(path, content):
            calls.append(path)
            if len(calls) == 3:
                raise OSError('simulated disk failure')
            return real(path, content)
        with patch.object(module, '_atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError):
                module.install(self.root)
        for name, value in self.original.items():
            self.assertEqual((self.root / name).read_text(), value)
        self.assertFalse((self.root / 'app/body_runtime.py').exists())

    def test_concurrent_change_is_not_overwritten(self):
        module = self.module()
        real = module._atomic_write
        changed = self.root / 'static/app.js'
        def interfere(path, content):
            result = real(path, content)
            if path.name == 'server.py':
                changed.write_text('another owner edited this', encoding='utf-8')
            return result
        with patch.object(module, '_atomic_write', side_effect=interfere):
            with self.assertRaises(module.InstallError):
                module.install(self.root)
        self.assertEqual(changed.read_text(), 'another owner edited this')
        self.assertEqual((self.root / 'app/server.py').read_text(), self.original['app/server.py'])


if __name__ == '__main__':
    unittest.main()
