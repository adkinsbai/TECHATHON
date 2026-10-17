"""团队测试版入口：用户数据目录、密钥保存与设置接口。"""
import os
import pathlib
import subprocess
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
