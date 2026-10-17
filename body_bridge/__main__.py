"""启动：python -m body_bridge --volume 10。"""
import argparse
import asyncio
from urllib.parse import urlparse

from .client import CompanionClient
from .runtime import Bridge


async def serve(args):
    from wifi.wifi_link import Link
    client = CompanionClient(args.companion_url)
    link = Link(port=args.port)
    bridge = Bridge(link, client, args.volume, args.port)
    print('小暖实体桥接已启动；请将压力传感器静置约 1 秒进行校准。', flush=True)
    try:
        await bridge.run()
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description='连接同一个小暖与 ESP32-S3 实体')
    parser.add_argument('--companion-url', default='http://127.0.0.1:8765')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--volume', type=int, default=10)
    args = parser.parse_args()
    url = urlparse(args.companion_url)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.username or url.password:
        parser.error('Companion 地址须为本机 HTTP 服务')
    if not 1 <= args.port <= 65535 or not 0 <= args.volume <= 100:
        parser.error('端口须为 1..65535，音量须为 0..100')
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        print('实体桥接已停止。')


if __name__ == '__main__':
    main()
