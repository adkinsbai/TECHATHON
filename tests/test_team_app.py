"""团队测试版入口：用户数据目录、密钥保存与设置接口。"""
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xiaonuan_app.setup_routes import _save_key  # noqa: E402


class SaveKeyTests(unittest.TestCase):
    def test_replaces_only_the_key_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = pathlib.Path(tmp) / ".env"
            env.write_text("DEEPSEEK_API_KEY=old\nDEEPSEEK_MODEL=custom\n# note\n", encoding="utf-8")
            _save_key(env, "sk-new")
            lines = env.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines.count("DEEPSEEK_API_KEY=sk-new"), 1)
            self.assertNotIn("DEEPSEEK_API_KEY=old", lines)
            self.assertIn("DEEPSEEK_MODEL=custom", lines)
            self.assertIn("# note", lines)

    def test_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = pathlib.Path(tmp) / "home" / ".env"
            _save_key(env, "sk-new")
            self.assertEqual(env.read_text(encoding="utf-8"), "DEEPSEEK_API_KEY=sk-new\n")


class LauncherVersionTests(unittest.TestCase):
    def test_takeover_waits_for_the_old_tcp_bridge_after_http_closes(self):
        from unittest.mock import patch
        from xiaonuan_app import launcher
        body_checks = []

        def port_in_use(port):
            if port == launcher.APP_PORT:
                return False
            body_checks.append(port)
            return len(body_checks) == 1

        with patch.object(launcher, '_listener_pid', return_value=123), \
                patch.object(launcher, '_port_in_use', side_effect=port_in_use), \
                patch.object(launcher.httpx, 'post'), patch.object(launcher.time, 'sleep') as sleep:
            launcher._stop_old_instance()
        self.assertEqual(body_checks, [launcher.BODY_PORT, launcher.BODY_PORT])
        sleep.assert_called_once_with(.25)

    def test_build_info_version(self):
        from xiaonuan_app import launcher
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "build-info.json").write_text('﻿{"commit": "abc1234", "built": "2026-10-17 06:00"}',
                                                            encoding="utf-8")
            old = launcher.APP_DIR
            launcher.APP_DIR = pathlib.Path(tmp)
            try:
                self.assertEqual(launcher.app_version(), "abc1234 · 2026-10-17 06:00")
            finally:
                launcher.APP_DIR = old


class ShutdownRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_needs_takeover_header(self):
        import httpx
        from fastapi import FastAPI
        from xiaonuan_app.setup_routes import attach_setup_routes
        calls = []
        app = FastAPI()
        attach_setup_routes(app, home=".", link=None, hub=None, brain=None, config=None, body_port=5000,
                            version="v", request_shutdown=lambda: calls.append(1))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
            self.assertEqual((await c.post("/api/setup/shutdown")).status_code, 403)
            self.assertEqual(calls, [])
            r = await c.post("/api/setup/shutdown", headers={"X-Xiaonuan": "takeover"})
            self.assertEqual(r.status_code, 200)
        self.assertEqual(calls, [1])


class ConfigHomeTests(unittest.TestCase):
    def test_xiaonuan_home_moves_data_and_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, ".env").write_text("DEEPSEEK_API_KEY=sk-home\n", encoding="utf-8")
            code = ("from app import config; print(config.DATA_DIR); print(config.DEEPSEEK_API_KEY); "
                    "print(config.MODELS_DIR)")
            env = {**os.environ, "XIAONUAN_HOME": tmp, "XIAONUAN_MODELS_DIR": tmp + "\\models"}
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "companion", env=env,
                                 capture_output=True, text=True, timeout=60, check=True).stdout.splitlines()
            self.assertEqual(pathlib.Path(out[0]), pathlib.Path(tmp) / "data")
            self.assertEqual(out[1], "sk-home")
            self.assertEqual(pathlib.Path(out[2]), pathlib.Path(tmp) / "models")


class SourceShutdownTests(unittest.TestCase):
    def test_shutdown_exits_with_an_open_sse_client(self):
        import httpx
        import socket

        # Keep data and ports separate from the owner's running application.
        def available_port():
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                return sock.getsockname()[1]

        api_port, body_port = available_port(), available_port()
        with tempfile.TemporaryDirectory() as tmp:
            fixture = pathlib.Path(tmp) / 'serve.py'
            fixture.write_text(
                'import sys\n'
                f'sys.path.insert(0, {str(ROOT)!r})\n'
                'from xiaonuan_app import launcher\n'
                f'launcher.APP_PORT = {api_port}\n'
                f'launcher.BODY_PORT = {body_port}\n'
                'launcher.webbrowser.open = lambda *a, **k: None\n'
                'launcher.main()\n', encoding='utf-8')
            env = {**os.environ, 'XIAONUAN_HOME': tmp, 'XIAONUAN_MODELS_DIR': tmp,
                   'PYTHONIOENCODING': 'utf-8'}
            with (pathlib.Path(tmp) / 'server.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([sys.executable, str(fixture)], cwd=ROOT, env=env,
                                           stdout=log, stderr=subprocess.STDOUT)
                try:
                    with httpx.Client(base_url=f'http://127.0.0.1:{api_port}',
                                      trust_env=False, timeout=3) as client:
                        deadline = time.monotonic() + 30
                        while True:
                            self.assertIsNone(process.poll(), 'isolated source app exited early')
                            try:
                                if client.get('/api/setup/status').status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            self.assertLess(time.monotonic(), deadline, 'source app did not start')
                            time.sleep(.1)
                        with client.stream('GET', '/api/body/stream') as stream:
                            self.assertEqual(stream.status_code, 200)
                            self.assertTrue(next(stream.iter_lines()).startswith('event: hello'))
                            response = client.post('/api/setup/shutdown',
                                                   headers={'X-Xiaonuan': 'takeover'})
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(process.wait(timeout=12), 0)
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
