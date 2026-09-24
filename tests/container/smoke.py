"""Run the production image twice with private storage and mocked Garmin I/O."""

import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def rpc(url, method, params=None, session=None, request_id=1):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    message = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    request = urllib.request.Request(url + "/mcp", json.dumps(message).encode(), headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode()
        if response.headers.get("Content-Type", "").startswith("text/event-stream"):
            body = next(line[6:] for line in body.splitlines() if line.startswith("data: "))
        result = json.loads(body) if body else {}
        assert "error" not in result, result
        return response.headers.get("Mcp-Session-Id"), result.get("result", {})


def initialize(url):
    session, result = rpc(url, "initialize", {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "container-smoke", "version": "1"},
    })
    assert session and result.get("capabilities"), result
    rpc(url, "notifications/initialized", session=session, request_id=None)
    return session


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else "garmin-mcp:test"
    name = "garmin-smoke-" + uuid.uuid4().hex[:12]
    volume = name + "-data"
    fixture_dir = str(Path(__file__).resolve().parent)
    common = [
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--memory=256m", "--cpus=0.5", "--network=none",
        "-v", volume + ":/data",
        "-v", fixture_dir + ":/fixtures:ro", "-e", "PYTHONPATH=/fixtures",
    ]
    docker("volume", "create", volume)
    try:
        docker("run", "--rm", *common, image, "python", "-c", """
import json, os
from pathlib import Path
from sitecustomize import token
p = Path(os.environ['GARMINTOKENS'])
p.mkdir(parents=True, exist_ok=True, mode=0o700)
(p / 'garmin_tokens.json').write_text(json.dumps({
    'di_token': token(1), 'di_refresh_token': 'original-refresh', 'di_client_id': 'test-client'
}))
""")
        for generation in range(2):
            # Bridge networking permits the host probe; Garmin I/O stays mocked.
            runtime_args = [arg for arg in common if arg != "--network=none"]
            docker("run", "-d", "--name", name, *runtime_args,
                   "-e", "PORT=18765", "-p", "127.0.0.1::18765", image)
            try:
                port = docker("port", name, "18765/tcp").rsplit(":", 1)[1]
                url = "http://127.0.0.1:" + port
                deadline = time.monotonic() + 30
                while True:
                    try:
                        with urllib.request.urlopen(url + "/healthz", timeout=2) as response:
                            assert response.status == 200
                        break
                    except (OSError, urllib.error.URLError):
                        if time.monotonic() >= deadline:
                            raise AssertionError("Container readiness exceeded 30s")
                        time.sleep(0.25)
                first, second = initialize(url), initialize(url)
                assert first != second
                _, result = rpc(url, "tools/list", session=first)
                names = {tool["name"] for tool in result["tools"]}
                assert {"get_devices", "upload_workout", "delete_course"} <= names
                assert not names.intersection({
                    "download_activity_file", "set_fit_download_dir", "download_course_gpx", "upload_course"
                })
                _, result = rpc(url, "tools/call", {"name": "get_devices", "arguments": {}}, second)
                assert not result.get("isError") and "Smoke watch" in json.dumps(result), result
                with urllib.request.urlopen(urllib.request.Request(
                    url + "/mcp", method="DELETE", headers={"Mcp-Session-Id": first}
                ), timeout=5) as response:
                    assert response.status == 200
                rpc(url, "tools/list", session=second)
                docker("exec", name, "python", "-c", """
import json, os, stat
from pathlib import Path
p = Path(os.environ['GARMINTOKENS']) / 'garmin_tokens.json'
assert json.loads(p.read_text())['di_refresh_token'] == 'rotated-refresh'
assert stat.S_IMODE(p.stat().st_mode) == 0o600
try:
    Path('/app/should-not-write').write_text('test')
except OSError:
    pass
else:
    raise AssertionError('Root filesystem is writable')
""")
                print(f"Container generation {generation + 1}: HTTP, sessions, tools, persistent tokens OK")
            except BaseException:
                print(docker("logs", name), file=sys.stderr)
                raise
            finally:
                docker("rm", "-f", name)
    finally:
        docker("volume", "rm", volume)


if __name__ == "__main__":
    main()
