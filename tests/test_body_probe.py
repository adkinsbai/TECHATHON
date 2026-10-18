import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import body_probe
from tools.body_device import digest


class FakeBoard:
    def __init__(self, port):
        self.identity = {'platform': 'esp32', 'implementation': 'micropython', 'machine': 'ESP32S3'}
        self.config = b'{"ssid":"private-network","password":"private-password","host":"192.168.137.1"}'
        self.corrupt = False
        self.rebooted = self.closed = self.sampled = False

    def identify(self):
        return self.identity

    def info(self, name):
        data = self.config if name == 'wifi.json' else b'source'
        return {'size': len(data), 'sha256': digest(data)}

    def read(self, name, info):
        return b'corrupt' if self.corrupt else self.config

    def execute(self, code, marker, wait):
        self.sampled = True
        return '[[4095,4095]]'

    def reboot(self):
        self.rebooted = True

    def close(self):
        self.closed = True


class ProbeTests(unittest.TestCase):
    def run_probe(self, board, root, *args):
        output = io.StringIO()
        with patch.object(body_probe, 'SerialBoard', return_value=board), \
                patch.object(body_probe, 'ROOT', root), \
                patch('sys.argv', ['body_probe', '--port', 'COM7', *args]), \
                contextlib.redirect_stdout(output):
            code = body_probe.main()
        self.assertNotIn('private-password', output.getvalue())
        self.assertNotIn('private-network', output.getvalue())
        self.assertTrue(board.closed)
        return code, output.getvalue()

    def test_unidentified_board_is_neither_sampled_nor_reset(self):
        board = FakeBoard('COM7')
        board.identity['machine'] = 'ESP32'
        code, _ = self.run_probe(board, Path('.'))
        self.assertEqual(code, 1)
        self.assertFalse(board.sampled)
        self.assertFalse(board.rebooted)

    def test_probe_samples_and_normally_resets_without_saving_config(self):
        board = FakeBoard('COM7')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, output = self.run_probe(board, root)
            self.assertEqual(code, 0)
            self.assertFalse((root / 'firmware/wifi.json').exists())
        self.assertTrue(board.rebooted)
        self.assertEqual(json.loads(output)['samples_gpio8_gpio9'], [[4095, 4095]])

    def test_config_is_saved_only_after_readback_verification(self):
        board = FakeBoard('COM7')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'firmware').mkdir()
            code, _ = self.run_probe(board, root, '--save-config')
            self.assertEqual(code, 0)
            self.assertEqual((root / 'firmware/wifi.json').read_bytes(), board.config)
        self.assertTrue(board.rebooted)

    def test_existing_config_is_preserved(self):
        board = FakeBoard('COM7')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'firmware').mkdir()
            target = root / 'firmware/wifi.json'
            target.write_bytes(b'existing')
            code, _ = self.run_probe(board, root, '--save-config')
            self.assertEqual(code, 1)
            self.assertEqual(target.read_bytes(), b'existing')
        self.assertTrue(board.rebooted)

    def test_corrupt_readback_does_not_create_config(self):
        board = FakeBoard('COM7')
        board.corrupt = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'firmware').mkdir()
            code, _ = self.run_probe(board, root, '--save-config')
            self.assertEqual(code, 1)
            self.assertFalse((root / 'firmware/wifi.json').exists())
        self.assertTrue(board.rebooted)
