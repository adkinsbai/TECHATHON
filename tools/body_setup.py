"""Side-effect-free dependency preflight for the Windows launcher."""
import argparse
import importlib.util
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-deps', action='store_true', required=True)
    parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        print('This audio bridge requires Python 3.12 (audioop is used by wifi_link).')
        return 1
    missing = [name for name in ('httpx', 'miniaudio', 'fastapi', 'uvicorn', 'multipart')
               if importlib.util.find_spec(name) is None]
    if missing:
        print('Missing packages: ' + ', '.join(missing))
        return 1
    print('Python 3.12 and bridge/server packages are available.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
