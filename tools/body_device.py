"""已识别 ESP32-S3 的源文件和 WiFi 配置部署；不刷固件、不清场。"""
import argparse
import base64
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('board_main.py', 'main.py', 'es8311.py')
BACKUP_FILES = SOURCES + ('wifi.json', 'wifi_on.txt', 'player_on.txt')
BASELINE = '672f9bde'


class DeployError(RuntimeError):
    """只包含非敏感诊断信息的部署错误。"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


class SerialBoard:
    """复用原安装器的串口与分块写入；所有 REPL 原始回包只在内部解析。"""
    def __init__(self, port):
        sys.path.insert(0, str(ROOT))
        from firmware import install_wifi
        self.api = install_wifi
        self.serial = self.api.open_board(port)
        self.api.raw_enter(self.serial)

    def execute(self, code, marker, wait=10):
        output = self.api.raw_exec(self.serial, code, wait=wait)
        # raw REPL 回包：OK + stdout + EOT + stderr + EOT + >。
        parts = output.split(b'\x04')
        if len(parts) < 3 or parts[1].strip() or not parts[-1].endswith(b'>'):
            raise DeployError('板子 REPL 执行失败；原始输出已隐藏')
        line = re.search(rb'(?:^|[\r\n])' + marker.encode() + rb' ([^\r\n]*)', parts[0].removeprefix(b'OK'))
        if line is None:
            raise DeployError('板子 REPL 回包缺少确认标记')
        return line.group(1).decode('ascii')

    def identify(self):
        payload = self.execute(
            "import os,sys,json\n"
            "print('BID',json.dumps({'platform':sys.platform,'implementation':sys.implementation.name,"
            "'machine':os.uname().machine+' '+getattr(sys.implementation,'_machine','')}))\n", 'BID')
        return json.loads(payload)

    def info(self, name):
        if name not in BACKUP_FILES:
            raise DeployError('不允许访问该板上文件')
        payload = self.execute(
            "import os,hashlib,binascii\n"
            "try:\n"
            " f=open(%r,'rb'); h=hashlib.sha256(); n=0\n"
            " while True:\n"
            "  b=f.read(1024)\n"
            "  if not b: break\n"
            "  n+=len(b);h.update(b)\n"
            " f.close();print('BHASH',n,binascii.hexlify(h.digest()).decode())\n"
            "except OSError:\n print('BHASH','missing')\n" % name, 'BHASH')
        if payload == 'missing':
            return None
        match = re.fullmatch(r'(\d+) ([0-9a-f]{64})', payload)
        if not match:
            raise DeployError('板上文件 SHA256 回包无效')
        return {'size': int(match[1]), 'sha256': match[2]}

    def read(self, name, info):
        result = bytearray()
        for offset in range(0, info['size'], 768):
            encoded = self.execute(
                "import binascii\nf=open(%r,'rb');f.seek(%d);b=f.read(768);f.close()\n"
                "print('BDAT',binascii.b2a_base64(b).decode().strip())\n" % (name, offset), 'BDAT')
            try:
                result.extend(base64.b64decode(encoded, validate=True))
            except ValueError:
                raise DeployError('板上备份块格式错误') from None
        return bytes(result)

    def write(self, local, name):
        if name not in SOURCES + ('wifi.json', 'wifi_on.txt'):
            raise DeployError('不允许写入该板上文件')
        with redirect_stdout(io.StringIO()):
            ok = self.api.write_file(self.serial, str(local), name)
        if not ok:
            raise DeployError('%s 写入失败' % name)

    def reboot(self):
        # raw REPL 的 soft_reset 会继续停在 raw 模式并跳过 main.py；硬复位才正常开机。
        # 复位后的启动日志可能含网络名；不输出原始回包。
        self.api.raw_exec(self.serial, "import machine\nmachine.reset()\n", wait=2)

    def close(self):
        self.serial.close()


def verify(board, name, expected):
    actual = board.info(name)
    if actual is None or actual['sha256'] != digest(expected) or actual['size'] != len(expected):
        raise DeployError('%s SHA256 校验失败；未继续启用或重启' % name)


def deploy(board, config_path, backup_path, source_dir, baseline, root=ROOT):
    """先完整备份和来源检查，再写源码、配置、启用标记，全部校验后才重启。"""
    identity = board.identify()
    machine = re.sub(r'[^A-Z0-9]', '', str(identity.get('machine', '')).upper())
    if identity.get('platform') != 'esp32' or identity.get('implementation') != 'micropython' or 'ESP32S3' not in machine:
        raise DeployError('板子未识别为 MicroPython ESP32-S3，拒绝写入')
    root, backup_path = Path(root).resolve(), Path(backup_path).resolve()
    if not backup_path.is_relative_to(root / 'runtime') or not backup_path.name.startswith('device-backup-'):
        raise DeployError('备份须位于忽略的 runtime/device-backup-* 新目录')
    if backup_path.exists():
        raise DeployError('备份目录已存在，请使用新的 device-backup-* 目录')
    # 读取配置只用于验证及部署，禁止将解析错误或配置内容写入日志。
    config = Path(config_path).read_bytes()
    try:
        settings = json.loads(config.decode('utf-8-sig'))
        valid = isinstance(settings, dict) and all(isinstance(settings.get(key), str) and settings[key] for key in ('ssid', 'host'))
        valid = valid and isinstance(settings.get('password'), str) and isinstance(settings.get('port', 5000), int) and 1 <= settings.get('port', 5000) <= 65535
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise DeployError('WiFi 配置格式无效，内容已隐藏')
    desired = {name: (Path(source_dir) / name).read_bytes() for name in SOURCES}
    before, originals = {}, {}
    backup_path.mkdir(parents=True)
    for name in BACKUP_FILES:
        info = board.info(name)
        before[name] = info
        if info is not None:
            data = board.read(name, info)
            if len(data) != info['size'] or digest(data) != info['sha256']:
                raise DeployError('%s 备份 SHA256 校验失败，拒绝写入' % name)
            destination = backup_path / name
            destination.write_bytes(data)
            if digest(destination.read_bytes()) != info['sha256']:
                raise DeployError('%s 本地备份 SHA256 校验失败' % name)
            originals[name] = data
    manifest = {'identity': identity, 'files': before, 'baseline': BASELINE, 'complete': True}
    (backup_path / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for name in SOURCES:
        actual = before[name]
        # 只对来源批准比较允许 CRLF/LF；备份、部署和读回仍校验原始字节。
        approved = {digest(data.replace(b'\r\n', b'\n')) for data in (baseline[name], desired[name])}
        normalized = digest(originals[name].replace(b'\r\n', b'\n')) if actual else None
        if actual is None or normalized not in approved:
            safe_hash = actual['sha256'] if actual else 'missing'
            raise DeployError('%s 来源未知 sha256=%s；备份保留，拒绝替换' % (name, safe_hash))
    # 立即重读，防止备份后被其他串口会话修改；未通过前不进行任何写入。
    for name in BACKUP_FILES:
        if board.info(name) != before[name]:
            raise DeployError('%s 在备份后发生变化，拒绝写入' % name)
    written = []
    for name in SOURCES:
        if before[name]['sha256'] != digest(desired[name]):
            board.write(Path(source_dir) / name, name)
            verify(board, name, desired[name])
            written.append(name)
    # 使用私有临时副本调用现有写入器，配置和 WiFi 标记最后写入。
    with tempfile.TemporaryDirectory(prefix='device-stage-', dir=backup_path) as staging:
        for name, data in (('wifi.json', config), ('wifi_on.txt', b'1')):
            local = Path(staging) / name
            local.write_bytes(data)
            board.write(local, name)
            verify(board, name, data)
            written.append(name)
    for name, data in {**desired, 'wifi.json': config, 'wifi_on.txt': b'1'}.items():
        verify(board, name, data)
    if board.info('player_on.txt') != before['player_on.txt']:
        raise DeployError('player_on.txt 发生变化，未重启')
    board.reboot()
    return {'identified': 'MicroPython ESP32-S3', 'backup_files': len(originals),
            'written': written, 'sha256_verified': True, 'reboot_requested': True}


def baseline_sources():
    result = {}
    for name in SOURCES:
        response = subprocess.run(['git', 'show', '%s:firmware/board/%s' % (BASELINE, name)],
                                  cwd=ROOT, capture_output=True, timeout=15)
        if response.returncode:
            raise DeployError('无法读取批准的 Git 基线，拒绝写入')
        result[name] = response.stdout
    return result


def main():
    parser = argparse.ArgumentParser(description='备份并部署已识别的小暖 ESP32-S3；不刷固件')
    parser.add_argument('--port', required=True)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--backup', required=True, type=Path)
    args = parser.parse_args()
    board = None
    try:
        baseline = baseline_sources()
        board = SerialBoard(args.port)
        result = deploy(board, args.config, args.backup, ROOT / 'firmware/board', baseline)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except DeployError as exc:
        print('部署停止：%s' % exc)
    except Exception:
        print('部署停止：本地或串口操作失败，详细内容已隐藏；未请求重启')
    finally:
        if board:
            board.close()
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
