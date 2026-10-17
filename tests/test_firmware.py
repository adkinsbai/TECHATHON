import ast
import audioop
import os
from pathlib import Path
import struct
import tempfile
import threading
import types
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.now = 0
    def sleep(self, seconds):
        self.now += seconds
    def monotonic(self):
        return self.now
    def ticks_ms(self):
        return int(self.now * 1000)


class Link:
    def __init__(self, fail=False):
        self.packets = []
        self.modes = []
        self.fail = fail
        self.attempts = 0
    def set_mode(self, mode):
        self.modes.append(mode)
    def send_audio(self, piece):
        self.attempts += 1
        if self.attempts > 4:
            raise OSError('test guards against infinite retry')
        if self.fail:
            return False
        self.packets.append(bytes(piece))
        return True
    def log(self, message):
        pass


def selected(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    node = next(node for node in tree.body if getattr(node, 'name', None) == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


class FirmwareTests(unittest.TestCase):
    def test_mode_changes_clear_unplayed_audio(self):
        clock = Clock()
        ns = {'time': clock}
        Ring = selected('firmware/board/board_main.py', 'Ring', ns)
        ring = Ring(64)
        ring.write(b'old speech')
        tree = ast.parse((ROOT / 'firmware/board/board_main.py').read_text(encoding='utf-8'))
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.comparators[0], ast.Name) and n.test.comparators[0].id == 'T_MODE')
        audio = types.SimpleNamespace(mode=1)
        audio.set_mode = lambda mode: setattr(audio, 'mode', mode)
        ns.update(ring=ring, audio=audio, payload=b'\x02', MODE_IDLE=0, stats={})
        exec(compile(ast.Module(body=branch.body, type_ignores=[]), 'mode_switch', 'exec'), ns)
        self.assertEqual(ring.level(), 0, 'record mode must discard previous playback')
        self.assertTrue(ring.write(b'new speech'))
        self.assertEqual(bytes(ring.take(64)), b'new speech')

    def playback(self, agent=False, fail=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wav = Path(tmp.name) / 'speech.wav'
        # Short utterance deliberately needs a padded final board write.
        with wave.open(str(wav), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(struct.pack('<100h', *([10000] * 100)))
        clock, link = Clock(), Link(fail)
        ns = dict(time=clock, wave=wave, audioop=audioop, RATE=24000, AUD_BYTES=4096,
                  MODE_PLAY=1, MODE_IDLE=0, LEAD_SECONDS=.5, os=os,
                  tempfile=tempfile, tts_to_wav=lambda text, path: None)
        if agent:
            fn = selected('wifi/agent_demo.py', 'speak_wav', ns)
            try:
                result = fn(link, str(wav))
            except OSError:
                result = False
        else:
            ns['tempfile'] = types.SimpleNamespace(gettempdir=lambda: str(wav.parent))
            # speak uses this fixed filename; copy our deterministic PCM fixture there.
            (wav.parent / 'esp32_say.wav').write_bytes(wav.read_bytes())
            Player = selected('wifi/wifi_demo.py', 'Player', ns)
            player = object.__new__(Player)
            player.lock = threading.RLock()
            player.wake = threading.Event()
            player.volume, player.link = 10, link
            result = player.speak('test')
        return link, clock, result

    def test_legacy_tts_has_exact_ten_percent_amplitude_and_padded_tail(self):
        link, clock, result = self.playback()
        self.assertTrue(result)
        self.assertEqual(struct.unpack('<h', link.packets[0][:2])[0], 1000)
        self.assertEqual(len(link.packets[-1]), 4096)
        self.assertEqual(link.packets[-1][400:], bytes(4096 - 400))
        self.assertGreaterEqual(clock.now, .2 + .2 + 4096 / 96000 + .35)
        self.assertEqual(link.modes[-1], 0)

    def test_legacy_tts_aborts_failed_send_without_retrying_a_partial_frame(self):
        link, clock, result = self.playback(fail=True)
        self.assertFalse(result)
        self.assertEqual(link.attempts, 1)
        self.assertEqual(link.modes[-1], 0)

    def test_agent_defaults_ten_percent_and_pads_tail(self):
        link, clock, result = self.playback(agent=True)
        self.assertEqual(struct.unpack('<h', link.packets[0][:2])[0], 1000)
        self.assertEqual(len(link.packets[-1]), 4096)
        self.assertGreaterEqual(clock.now, .15 + 4096 / 96000 + .35)

    def test_agent_aborts_failed_send_without_retrying_a_partial_frame(self):
        link, clock, result = self.playback(agent=True, fail=True)
        self.assertEqual(link.attempts, 1)
        self.assertEqual(link.modes[-1], 0)


if __name__ == '__main__':
    unittest.main()
