"""Install the body extension into an existing Companion, without touching its data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

HERE = Path(__file__).resolve().parent
SOURCE = ('app/server.py', 'static/app.js', 'static/world.js',
          'static/index.html', 'static/world.html')
COPIES = {'app/body_runtime.py': 'body_runtime.py',
          'static/body-client.js': 'body-client.js',
          'static/body-client.css': 'body-client.css'}
ALLOWED = (*SOURCE, *COPIES)
MARK = 'XIAONUAN BODY VIEW'


class InstallError(RuntimeError):
    pass


def _path(root, name):
    path = root / name
    for candidate in (root, *path.relative_to(root).parents):
        # Relative parents are checked below with their root restored.
        candidate = candidate if candidate.is_absolute() else root / candidate
        if candidate.is_symlink() or candidate.is_junction():
            raise InstallError(f'Refusing redirected source path: {candidate}')
    if path.is_symlink() or path.is_junction():
        raise InstallError(f'Refusing redirected source file: {path}')
    return path


def _read(root, name):
    path = _path(root, name)
    return path.read_bytes() if path.exists() else None


def _replace(text, old, new, label):
    if text.count(new) == 1 and old not in text:
        return text
    if text.count(old) != 1 or new in text:
        raise InstallError(f'Unsupported or ambiguous source anchor: {label}')
    return text.replace(old, new, 1)


def _block(text, content, style):
    begin, end = (f'// BEGIN {MARK}', f'// END {MARK}') if style == 'js' else (f'<!-- BEGIN {MARK} -->', f'<!-- END {MARK} -->')
    content = content.strip()
    if content.startswith(begin) and content.endswith(end):
        content = content[len(begin):-len(end)].strip()
    block = f'{begin}\n{content.rstrip()}\n{end}'
    if begin in text or end in text:
        if text.count(begin) != 1 or text.count(end) != 1:
            raise InstallError('Broken extension markers')
        a, b = text.index(begin), text.index(end) + len(end)
        if a >= b:
            raise InstallError('Reversed extension markers')
        return text[:a] + block + text[b:]
    if style == 'js':
        return text.rstrip() + '\n\n' + block + '\n'
    return _replace(text, '</head>', block + '\n</head>', 'HTML head')


def _audio_patch(text, world=False):
    """Cancel pending TTS as well as active playback when body ownership changes."""
    if world:
        edits = (
            ('async function speak(text) {', '''let bodyWorldSpeechGeneration = 0, bodyWorldAudio = null;
function stopWorldSpeaking() {
  bodyWorldSpeechGeneration += 1;
  if (bodyWorldAudio) { bodyWorldAudio.pause(); bodyWorldAudio = null; }
  if (window.speechSynthesis) speechSynthesis.cancel();
  Cat.talking = false;
}

async function speak(text) {'''),
            ('  if (!getVoiceOn()) return;', '''  if (!getVoiceOn()) return;
  stopWorldSpeaking();
  const speechGeneration = bodyWorldSpeechGeneration;
  const speechCancelled = () => speechGeneration !== bodyWorldSpeechGeneration || window.BodyClient?.routesAudio;'''),
            ('    if (!res.ok) throw new Error();', '    if (speechCancelled()) return;\n    if (!res.ok) throw new Error();'),
            ('    const url = URL.createObjectURL(await res.blob());', '    const blob = await res.blob();\n    if (speechCancelled()) return;\n    const url = URL.createObjectURL(blob);'),
            ('    const audio = new Audio(url);\n    Cat.talking = true;', '    const audio = new Audio(url);\n    bodyWorldAudio = audio;\n    Cat.talking = true;'),
            ('    audio.onended = () => { Cat.talking = false; URL.revokeObjectURL(url); };', '''    audio.onplay = () => { if (speechCancelled()) audio.pause(); };
    audio.onended = audio.onpause = () => {
      Cat.talking = false; URL.revokeObjectURL(url);
      if (bodyWorldAudio === audio) bodyWorldAudio = null;
    };'''),
            ('    audio.play();\n  } catch {', '    await audio.play();\n  } catch {'),
            ('    if (!window.speechSynthesis) return;', '    if (speechCancelled() || !window.speechSynthesis) return;'),
        )
    else:
        edits = (
            ('function stopSpeaking() {', '''let bodySpeechGeneration = 0, bodySpeechForced = false;
function stopSpeaking() {
  bodySpeechGeneration += 1;
  bodySpeechForced = false;'''),
            ('  stopSpeaking();\n  if (ttsMode === "glm"', '''  stopSpeaking();
  const speechGeneration = bodySpeechGeneration;
  bodySpeechForced = force;
  const speechCancelled = () => speechGeneration !== bodySpeechGeneration || (window.BodyClient?.routesAudio && !force);
  if (ttsMode === "glm"'''),
            ('      if (!res.ok) throw new Error((await res.json()).detail);', '      if (speechCancelled()) return;\n      if (!res.ok) throw new Error((await res.json()).detail);'),
            ('      const url = URL.createObjectURL(await res.blob());', '      const blob = await res.blob();\n      if (speechCancelled()) return;\n      const url = URL.createObjectURL(blob);'),
            ('      audio.onplay = () => Avatar.speaking(true);', '      audio.onplay = () => { if (speechCancelled()) { audio.pause(); return; } Avatar.speaking(true); };'),
            ('    } catch (e) {\n      console.warn("GLM TTS', '    } catch (e) {\n      if (speechCancelled()) return;\n      console.warn("GLM TTS'),
            ('  if (!window.speechSynthesis) return;', '  if (speechCancelled() || !window.speechSynthesis) return;'),
        )
    for index, (old, new) in enumerate(edits):
        if text.count(new) == 1:
            continue
        text = _replace(text, old, new, f'{"world" if world else "chat"} audio cancellation {index}')
    return text


def _build(root, original):
    for name in SOURCE:
        if original[name] is None:
            raise InstallError(f'Missing Companion source: {name}')
    texts = {name: original[name].decode('utf-8').replace('\r\n', '\n') for name in SOURCE}
    server = texts['app/server.py']
    for old, new, label in (
        ('from contextlib import asynccontextmanager', 'from contextlib import asynccontextmanager\nfrom typing import Literal', 'typing import'),
        ('from . import brain, store, voice, weaver', 'from . import brain, store, voice, weaver\nfrom .body_runtime import BodyHub, attach_body_routes', 'body import'),
        ('store.init()\n', 'store.init()\nbody_hub = BodyHub(store)\n', 'store initialization'),
        ('async def _reply_stream(user_text=None, note=None, heard=None):', 'async def _reply_stream_impl(user_text=None, note=None, heard=None):', 'reply implementation'),
        ('class ChatIn(BaseModel):\n    text: str', 'class ChatIn(BaseModel):\n    text: str\n    source: Literal["web", "body"] = "web"', 'chat source'),
        ('_reply_stream(text, note=note, heard=heard)', '_reply_stream(text, note=note, heard=heard, source=body.source)', 'chat route'),
    ):
        # Several insertions contain their old anchor as a prefix.
        if new not in server:
            server = _replace(server, old, new, label)
        elif server.count(new) != 1:
            raise InstallError(f'Duplicate installed anchor: {label}')
    wrapper = '''async def _reply_stream(user_text=None, note=None, heard=None, source="web"):
    async for chunk in body_hub.relay(_reply_stream_impl, user_text=user_text, note=note, heard=heard, source=source):
        yield chunk


attach_body_routes(app, body_hub, _reply_stream, voice=voice)


'''
    if wrapper not in server:
        server = _replace(server, 'class ChatIn(BaseModel):', wrapper + 'class ChatIn(BaseModel):', 'serialized reply wrapper')
    texts['app/server.py'] = server
    js = texts['static/app.js']
    for old, new, label in (
        ('async function speak(text, force = false) {', 'async function speak(text, force = false) {\n  if (window.BodyClient?.routesAudio && !force) return;', 'chat audio'),
        ('if (!text || busy) return;', 'if (!text || busy || window.BodyClient?.busy) return;', 'chat busy'),
        ('  streamReply("/api/nudge");', '  if (!window.BodyClient?.busy) streamReply("/api/nudge");', 'nudge busy'),
    ):
        if new not in js:
            js = _replace(js, old, new, label)
    texts['static/app.js'] = _block(_audio_patch(js), (HERE / 'companion_extension/chat-hooks.js').read_text(encoding='utf-8'), 'js')
    js = texts['static/world.js']
    for old, new, label in (
        ('async function speak(text) {', 'async function speak(text) {\n  if (window.BodyClient?.routesAudio) return;', 'world audio'),
        ('async function stream(url, body) {\n  if (busy) return;', 'async function stream(url, body) {\n  if (busy || window.BodyClient?.busy) return;', 'world busy'),
    ):
        if new not in js:
            js = _replace(js, old, new, label)
    texts['static/world.js'] = _block(_audio_patch(js, world=True), (HERE / 'companion_extension/world-hooks.js').read_text(encoding='utf-8'), 'js')
    for name in ('static/index.html', 'static/world.html'):
        texts[name] = _block(texts[name], '<link rel="stylesheet" href="/static/body-client.css">\n<script src="/static/body-client.js" defer></script>', 'html')
    result = {name: text.encode('utf-8') for name, text in texts.items()}
    for name, source in COPIES.items():
        result[name] = (HERE / 'companion_extension' / source).read_bytes()
    compile(result['app/server.py'], 'server.py', 'exec')
    compile(result['app/body_runtime.py'], 'body_runtime.py', 'exec')
    return result


def build_changes(root):
    """Return all eight desired source files, with paths relative to Companion."""
    root = Path(root).absolute()
    return _build(root, {name: _read(root, name) for name in ALLOWED})


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.body-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(root):
    root = Path(root).absolute()
    original = {name: _read(root, name) for name in ALLOWED}
    desired = _build(root, original)
    changed = [name for name in ALLOWED if original[name] != desired[name]]
    manifest = {'target': str(root), 'backup': None, 'changed': changed,
                'hashes': {name: hashlib.sha256(value).hexdigest() for name, value in desired.items()}}
    if not changed:
        return manifest
    # Validate the complete snapshot before any mutation, then each file just before replacement.
    if any(_read(root, name) != original[name] for name in ALLOWED):
        raise InstallError('Companion source changed during installation planning')
    backup = root / '.body-backups' / uuid.uuid4().hex
    if (root / '.body-backups').is_symlink() or (root / '.body-backups').is_junction():
        raise InstallError('Refusing redirected backup directory')
    backup.mkdir(parents=True)
    manifest['backup'] = str(backup)
    for name in changed:
        if original[name] is not None:
            dst = backup / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(original[name])
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    written = []
    try:
        for name in changed:
            if _read(root, name) != original[name]:
                raise InstallError(f'Concurrent source change; refusing overwrite: {name}')
            _atomic_write(_path(root, name), desired[name])
            written.append(name)
    except BaseException:
        for name in reversed(written):
            # Preserve concurrent edits made after our write, even during rollback.
            if _read(root, name) == desired[name]:
                if original[name] is None:
                    _path(root, name).unlink()
                else:
                    _atomic_write(_path(root, name), original[name])
        raise
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--target', required=True, type=Path)
    ap.add_argument('--remember', action='store_true')
    ap.add_argument('--check', action='store_true', help='validate and list source changes without writing')
    args = ap.parse_args()
    if args.check and args.remember:
        ap.error('--check cannot be combined with --remember')
    if args.check:
        desired = build_changes(args.target)
        result = {'target': str(args.target.absolute()), 'backup': None,
                  'changed': [name for name, value in desired.items() if _read(args.target, name) != value]}
    else:
        result = install(args.target)
    if args.remember:
        _atomic_write(HERE / '.local-body.json', json.dumps({'companion_root': str(args.target.resolve()), 'python': sys.executable}, ensure_ascii=False, indent=2).encode('utf-8'))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
