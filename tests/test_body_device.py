import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('body_device', ROOT / 'tools/body_device.py')
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


class FakeBoard:
    def __init__(self, files, identity=None):
        self.files = dict(files)
        self.identity_data = identity or {'platform': 'esp32', 'implementation': 'micropython', 'machine': 'ESP32S3 octal RAM'}
        self.writes, self.rebooted = [], False
        self.corrupt = None
    def identify(self): return self.identity_data
    def info(self, name):
        data = self.files.get(name)
        return None if data is None else {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    def read(self, name, info): return self.files[name]
    def write(self, local, name):
        self.writes.append(name)
        self.files[name] = b'bad' if name == self.corrupt else Path(local).read_bytes()
    def reboot(self): self.rebooted = True


class DeviceDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'firmware/board'
        self.source.mkdir(parents=True)
        self.baseline = {name: (name + ':baseline').encode() for name in device.SOURCES}
        for name, data in self.baseline.items():
            (self.source / name).write_bytes(data + b':desired' if name == 'board_main.py' else data)
        self.config = self.root / 'firmware/wifi.json'
        self.config.write_text(json.dumps({'ssid': 'fixture', 'password': 'private-fixture', 'host': '192.0.2.1', 'port': 5000}), encoding='utf-8')
        self.backup = self.root / 'runtime/device-backup-test'
        self.files = dict(self.baseline, **{'wifi.json': b'{"password":"old-secret"}', 'wifi_on.txt': b'1', 'player_on.txt': b'1', 'user.py': b'preserve'})
        self.board = FakeBoard(self.files)
    def tearDown(self): self.temp.cleanup()
    def deploy(self):
        return device.deploy(self.board, self.config, self.backup, self.source, self.baseline, self.root)

    def test_backup_hash_verified_preserves_unrelated_and_config_flag_last(self):
        result = self.deploy()
        self.assertTrue(self.board.rebooted)
        self.assertEqual(self.board.writes, ['board_main.py', 'wifi.json', 'wifi_on.txt'])
        self.assertEqual(self.board.files['user.py'], b'preserve')
        self.assertEqual(self.board.files['player_on.txt'], b'1')
        self.assertEqual((self.backup / 'wifi.json').read_bytes(), self.files['wifi.json'])
        manifest = json.loads((self.backup / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(set(manifest['files']), set(device.BACKUP_FILES))
        self.assertNotIn('secret', json.dumps(result))

    def test_unknown_source_is_backed_up_but_never_overwritten(self):
        self.board.files['main.py'] = b'custom user code'
        with self.assertRaisesRegex(device.DeployError, 'main.py.*sha256'):
            self.deploy()
        self.assertEqual(self.board.writes, [])
        self.assertFalse(self.board.rebooted)
        self.assertEqual((self.backup / 'main.py').read_bytes(), b'custom user code')

    def test_known_baseline_crlf_is_approved_but_backup_keeps_exact_original(self):
        self.baseline['main.py'] = b'known\nsource\n'
        (self.source / 'main.py').write_bytes(self.baseline['main.py'])
        self.board.files['main.py'] = b'known\r\nsource\r\n'
        self.deploy()
        self.assertEqual((self.backup / 'main.py').read_bytes(), b'known\r\nsource\r\n')
        self.assertEqual(self.board.files['main.py'], self.baseline['main.py'])

    def test_whitespace_change_is_not_an_approved_line_ending_variant(self):
        self.baseline['main.py'] = b'known\nsource\n'
        (self.source / 'main.py').write_bytes(self.baseline['main.py'])
        self.board.files['main.py'] = b'known \r\nsource\r\n'
        with self.assertRaises(device.DeployError): self.deploy()
        self.assertEqual(self.board.writes, [])

    def test_unidentified_board_refuses_before_write_or_backup(self):
        self.board.identity_data['machine'] = 'ESP32 generic'
        with self.assertRaises(device.DeployError): self.deploy()
        self.assertEqual(self.board.writes, [])
        self.assertFalse(self.backup.exists())

    def test_hash_mismatch_stops_before_config_flag_and_reboot(self):
        self.board.corrupt = 'board_main.py'
        with self.assertRaisesRegex(device.DeployError, 'SHA256'):
            self.deploy()
        self.assertEqual(self.board.writes, ['board_main.py'])
        self.assertFalse(self.board.rebooted)

    def test_backup_must_be_new_and_under_ignored_runtime(self):
        self.backup = self.root / 'outside/device-backup-test'
        with self.assertRaises(device.DeployError): self.deploy()
        self.assertEqual(self.board.writes, [])

    def test_corrupted_download_never_writes_board(self):
        self.board.read = lambda name, info: b'broken download'
        with self.assertRaisesRegex(device.DeployError, '备份 SHA256'):
            self.deploy()
        self.assertEqual(self.board.writes, [])


class SerialProtocolTests(unittest.TestCase):
    def board(self, response):
        from types import SimpleNamespace
        board = device.SerialBoard.__new__(device.SerialBoard)
        board.serial = object()
        board.api = SimpleNamespace(raw_exec=lambda serial, code, wait: response)
        return board

    def test_raw_repl_marker_and_empty_stderr_parse_without_printing_payload(self):
        board = self.board(b'OKBDAT cHJpdmF0ZQ==\r\n\x04\x04>')
        self.assertEqual(board.execute('fixture', 'BDAT'), 'cHJpdmF0ZQ==')

    def test_raw_repl_error_is_redacted(self):
        board = self.board(b'OK\x04Traceback: private-secret\x04>')
        with self.assertRaises(device.DeployError) as caught:
            board.execute('fixture', 'BDAT')
        self.assertNotIn('private-secret', str(caught.exception))

    def test_remote_file_access_is_allowlisted(self):
        board = self.board(b'')
        with self.assertRaises(device.DeployError): board.info('user.py')


if __name__ == '__main__': unittest.main()
