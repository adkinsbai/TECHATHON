"""Probe an attached MicroPython ESP32-S3 without replacing board files.

Temporarily interrupts main.py, reads source hashes and GPIO8/9, then resets
normally. --save-config recovers wifi.json to the ignored local path only.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.body_device import SerialBoard, SOURCES, DeployError, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--seconds', type=int, default=3, choices=range(1, 31))
    parser.add_argument('--save-config', action='store_true')
    args = parser.parse_args()
    board, identified = None, False
    try:
        board = SerialBoard(args.port)
        identity = board.identify()
        machine = re.sub(r'[^A-Z0-9]', '', str(identity.get('machine', '')).upper())
        if (identity.get('platform') != 'esp32' or identity.get('implementation') != 'micropython'
                or 'ESP32S3' not in machine):
            raise DeployError('Not a MicroPython ESP32-S3; probe stopped.')
        identified = True
        result = {'identity': identity, 'sources': {name: board.info(name) for name in SOURCES}}
        if args.save_config:
            target = ROOT / 'firmware' / 'wifi.json'
            if target.exists():
                raise DeployError('Local firmware/wifi.json already exists; refusing to overwrite.')
            info = board.info('wifi.json')
            if not info:
                raise DeployError('No wifi.json on the board.')
            data = board.read('wifi.json', info)
            if digest(data) != info['sha256'] or len(data) != info['size']:
                raise DeployError('Wi-Fi config readback failed.')
            config = json.loads(data.decode('utf-8-sig'))
            if not isinstance(config, dict) or not config.get('host') or not config.get('ssid'):
                raise DeployError('Invalid Wi-Fi config; content hidden.')
            with target.open('xb') as output:
                output.write(data)
            result['config_saved'] = True
        payload = board.execute(
            "from machine import ADC,Pin\nimport time,json\n"
            "adcs=[ADC(Pin(p)) for p in (8,9)]\n"
            "for a in adcs: a.atten(ADC.ATTN_11DB)\n"
            "samples=[]\n"
            "for i in range(%d):\n"
            " samples.append([a.read() for a in adcs]);time.sleep_ms(100)\n"
            "print('BADC',json.dumps(samples))\n" % (args.seconds * 10),
            'BADC', wait=args.seconds + 5)
        result['samples_gpio8_gpio9'] = json.loads(payload)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except DeployError as exc:
        print(str(exc))
        return 1
    except Exception:
        print('Probe failed; raw serial output and Wi-Fi credentials are hidden.')
        return 1
    finally:
        if board:
            try:
                if identified:
                    board.reboot()
            finally:
                board.close()


if __name__ == '__main__':
    raise SystemExit(main())
