import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

CHAT_SPEECH = '''function stopSpeaking() {
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (window.speechSynthesis) speechSynthesis.cancel();
  Avatar.speaking(false);
}

async function speak(text, force = false) {
  if (!voiceOn && !force) return;
  text = cleanForSpeech(text);
  if (!text) return;
  stopSpeaking();
  if (ttsMode === "glm" && persona?.voice !== "browser") {
    try {
      const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      if (!res.ok) throw new Error((await res.json()).detail);
      const url = URL.createObjectURL(await res.blob());
      const audio = new Audio(url);
      currentAudio = audio;
      audio.onplay = () => Avatar.speaking(true);
      audio.onended = audio.onpause = () => { Avatar.speaking(false); URL.revokeObjectURL(url); };
      await audio.play();
      return;
    } catch (e) {
      console.warn("GLM TTS 不可用，改用浏览器语音：", e.message);
      ttsMode = "browser";
      $("voiceStatus").textContent = `GLM 语音合成不可用（${e.message.slice(0, 80)}），正在使用浏览器自带的声音。`;
    }
  }
  if (!window.speechSynthesis) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN";
  const zh = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("zh"));
  u.voice = zh.find((v) => /Xiaoxiao|Xiaoyi|女|Female|Tingting/i.test(v.name)) || zh[0] || null;
  u.pitch = 1.15;
  u.rate = 1.02;
  u.onstart = () => Avatar.speaking(true);
  u.onend = u.onerror = () => Avatar.speaking(false);
  speechSynthesis.speak(u);
}
'''

WORLD_SPEECH = '''async function speak(text) {
  if (!getVoiceOn()) return;
  text = text.replace(/[（(][^）)]*[）)]/g, "").replace(/[\\p{Extended_Pictographic}]/gu, "").trim();
  try {
    const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!res.ok) throw new Error();
    const url = URL.createObjectURL(await res.blob());
    const audio = new Audio(url);
    Cat.talking = true;
    audio.onended = () => { Cat.talking = false; URL.revokeObjectURL(url); };
    audio.play();
  } catch {
    if (!window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "zh-CN"; u.pitch = 1.15;
    speechSynthesis.speak(u);
  }
}
'''


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
        'static/app.js': CHAT_SPEECH + '''async function send(text, heard = null) {
  if (!text || busy) return;
}
setInterval(() => {
  streamReply("/api/nudge");
}, 60000);
''',
        'static/world.js': WORLD_SPEECH + '''async function stream(url, body) {
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

    @unittest.skipUnless(os.name == 'nt', 'Windows extended path regression')
    def test_deep_windows_target_supports_backup_atomic_writes_and_repeat_install(self):
        module = self.module()
        deep = self.root.joinpath(*(['deep-source-' + 'x' * 45] * 5))
        extended = Path('\\\\?\\' + str(deep.absolute()))
        fixture(extended)
        self.addCleanup(shutil.rmtree, Path('\\\\?\\' + str(self.root.absolute())) / deep.relative_to(self.root).parts[0])
        first = module.install(deep)
        self.assertEqual(len(first['changed']), 8)
        self.assertTrue(Path(first['backup']).is_dir())
        self.assertEqual(module.install(deep)['changed'], [])
        self.assertIn(b'body_hub', (extended / 'app/server.py').read_bytes())

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
            self.assertEqual((self.root / name).read_text(encoding='utf-8'), value)
        self.assertFalse((self.root / 'app/body_runtime.py').exists())

    def test_original_with_extra_module_imports_is_patched(self):
        module = self.module()
        server = self.root / 'app/server.py'
        server.write_text(self.original['app/server.py'].replace(
            'from . import brain, store, voice, weaver', 'from . import brain, speech_stream, store, voice, weaver'), encoding='utf-8')
        module.install(self.root)
        text = server.read_text(encoding='utf-8')
        self.assertIn('from . import brain, speech_stream, store, voice, weaver\nfrom .body_runtime import BodyHub, attach_body_routes', text)
        self.assertEqual(text.count('async def _reply_stream('), 1)
        self.assertEqual(module.install(self.root)['changed'], [])

    def pr2_shape(self):
        """Turn an installed fixture into the PR #2 (voice pack) integrated shape."""
        module = self.module()
        module.install(self.root)
        server = self.root / 'app/server.py'
        text = server.read_text(encoding='utf-8')
        text = text.replace('from . import brain, store, voice, weaver', 'from . import brain, speech_stream, store, voice, weaver')
        text = text.replace('''async def _reply_stream(user_text=None, note=None, heard=None, source="web"):
    async for chunk''', '''async def _reply_stream(user_text=None, note=None, heard=None, source="web", tts=False):
    sp = speech_stream.Speaker(None) if tts else None
    async for chunk''')
        text = text.replace('source=body.source)', 'source=body.source, tts=body.tts)')
        text = text.replace('    source: Literal["web", "body"] = "web"\n', '    source: Literal["web", "body"] = "web"\n    tts: bool = False\n')
        server.write_text(text, encoding='utf-8', newline='\n')
        chat = self.root / 'static/app.js'
        text = chat.read_text(encoding='utf-8')
        text = text.replace('  bodySpeechForced = false;\n', '  bodySpeechForced = false;\n  audioQueue.length = 0;\n  queuePlaying = false;\n', 1)
        text = text.replace('''      if (speechCancelled()) return;
      console.warn("GLM TTS 不可用，改用浏览器语音：", e.message);
      ttsMode = "browser";''', '''      if (!speechCancelled()) console.warn("这句语音没合成出来（不换声音）：", e.message);
      return;''')
        chat.write_text(text, encoding='utf-8', newline='\n')
        world = self.root / 'static/world.js'
        text = world.read_text(encoding='utf-8')
        text = text.replace('  bodyWorldSpeechGeneration += 1;\n', '  bodyWorldSpeechGeneration += 1;\n  worldAudioQ.length = 0;\n  worldQPlaying = false;\n', 1)
        text = text.replace('''    if (speechCancelled() || !window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "zh-CN"; u.pitch = 1.15;
    speechSynthesis.speak(u);''', '    Cat.talking = false;')
        world.write_text(text, encoding='utf-8', newline='\n')
        self.assertNotIn('console.warn("GLM TTS', chat.read_text(encoding='utf-8'))
        self.assertNotIn('SpeechSynthesisUtterance', world.read_text(encoding='utf-8'))
        return module

    def test_pr2_integrated_server_is_recognised_as_installed(self):
        module = self.pr2_shape()
        before = {name: (self.root / name).read_bytes() for name in module.SOURCE}
        result = module.install(self.root)
        self.assertEqual(result['changed'], [])
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in module.SOURCE})
        server = (self.root / 'app/server.py').read_text(encoding='utf-8')
        for definition in ('async def _reply_stream(', 'async def _reply_stream_impl(',
                           'attach_body_routes(app, body_hub', 'body_hub = BodyHub(store)', 'from typing import Literal'):
            self.assertEqual(server.count(definition), 1, definition)
        for name, marker in (('static/app.js', 'let bodySpeechGeneration'), ('static/world.js', 'let bodyWorldSpeechGeneration')):
            self.assertEqual((self.root / name).read_text(encoding='utf-8').count(marker), 1, name)

    def test_bundled_companion_snapshot_is_already_installed(self):
        module = self.module()
        source = ROOT / 'companion'
        desired = module.build_changes(source)
        for name in module.SOURCE:
            self.assertEqual(desired[name], (source / name).read_bytes(), name)

    def test_partial_or_duplicate_integration_is_refused(self):
        module = self.module()
        module.install(self.root)
        server = self.root / 'app/server.py'
        installed = server.read_text(encoding='utf-8')
        broken = (installed.replace('attach_body_routes(app, body_hub, _reply_stream, voice=voice)\n', ''),
                  installed.replace('class ChatIn', 'async def _reply_stream(user_text=None):\n    yield ""\nclass ChatIn'),
                  installed.replace('body_hub = BodyHub(store)\n', 'body_hub = BodyHub(store)\nbody_hub = BodyHub(store)\n'))
        for text in broken:
            server.write_text(text, encoding='utf-8')
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            with self.assertRaises(module.InstallError):
                module.install(self.root)
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

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
