import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def test_service_identity_rejects_unrelated_listeners(self):
        script = ROOT / 'start-body.ps1'
        self.assertTrue(script.exists(), 'safe startup script is missing')
        harness = '''param($Script)
. $Script -LibraryOnly
$root = 'C:\\Companion'
$cases = @(
  (Test-CompanionProcess ([pscustomobject]@{CommandLine='python -m uvicorn app.server:app --host 127.0.0.1 --port 8765 --app-dir C:\\Companion'}) $root),
  (Test-CompanionProcess ([pscustomobject]@{CommandLine='python -m http.server 8765'}) $root),
  (Test-CompanionProcess ([pscustomobject]@{CommandLine='python -m uvicorn other:app --port 8765'}) $root),
  (Test-CompanionProcess ([pscustomobject]@{CommandLine='python -m uvicorn app.server:app --app-dir C:\\Other'}) $root),
  (Test-BridgeProcess ([pscustomobject]@{CommandLine='python -m body_bridge --companion-url http://127.0.0.1:8765 --port 5000 --volume 10'}) 'http://127.0.0.1:8765' 5000),
  (Test-BridgeProcess ([pscustomobject]@{CommandLine='python wifi_demo.py'}) 'http://127.0.0.1:8765' 5000),
  (Test-BridgeProcess ([pscustomobject]@{CommandLine='python -m body_bridge --companion-url http://127.0.0.1:9999 --port 5000'}) 'http://127.0.0.1:8765' 5000),
  (Test-CompanionProcess ([pscustomobject]@{CommandLine='"C:\\Python 3.12\\python.exe" "-m" "uvicorn" "app.server:app" "--app-dir" "C:\\Companion"'}) $root),
  (Test-BridgeProcess ([pscustomobject]@{CommandLine='"C:\\Python 3.12\\python.exe" "-m" "body_bridge" "--companion-url" "http://127.0.0.1:8765" "--port" "5000"'}) 'http://127.0.0.1:8765' 5000),
  (Test-CompanionProcess ([pscustomobject]@{CommandLine='echo uvicorn app.server:app'}) $root),
  (Test-CompanionProcess ([pscustomobject]@{CommandLine='python -m uvicorn app.server:app --host 127.0.0.1 --port 8765'}) $root)
)
ConvertTo-Json -InputObject $cases -Compress
'''
        with tempfile.TemporaryDirectory() as tmp:
            test = Path(tmp) / 'test.ps1'
            test.write_text(harness, encoding='utf-8-sig')
            result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(test), str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [True, False, False, False, True, False, False, True, True, False, False])


if __name__ == '__main__':
    unittest.main()
