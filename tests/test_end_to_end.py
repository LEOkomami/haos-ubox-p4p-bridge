"""Real MediaMTX/FFmpeg with a synthetic camera. Never contacts a camera/cloud."""

from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest

from settings import Settings
from supervisor import Bridge, configure_logging

FFMPEG = os.environ.get("BRIDGE_TEST_FFMPEG")
MEDIAMTX = os.environ.get("BRIDGE_TEST_MEDIAMTX")


def eventually(predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for test condition")


@unittest.skipUnless(FFMPEG and MEDIAMTX, "Set BRIDGE_TEST_FFMPEG and BRIDGE_TEST_MEDIAMTX for real media tests")
class MediaTests(unittest.TestCase):
    def test_rtsp_decode_stall_recovery_ffmpeg_failure_and_server_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            video = folder / "sample.h265"
            subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc2=size=320x240:rate=15", "-t", "2", "-c:v", "libx265",
                "-preset", "ultrafast", "-x265-params", "log-level=error:keyint=15:bframes=0:pools=1",
                "-f", "hevc", str(video)], check=True, capture_output=True, timeout=30)
            (folder / "mode.txt").write_text("video")
            (folder / "p4p_stream.py").write_text('''from pathlib import Path
import time
BASE = Path(__file__).parent
def run_stream(uid, password, seconds, output):
    data = (BASE / "sample.h265").read_bytes()
    with open(output, "wb") as video:
        while True:
            if (BASE / "mode.txt").read_text() == "video":
                video.write(data)
            time.sleep(0.2)
''')
            with socket.socket() as reserved:
                reserved.bind(("127.0.0.1", 0))
                port = reserved.getsockname()[1]
            settings = replace(Settings(), camera_uid="ABCDEFGHIJKLMNOPQRST", camera_password="test-only-device-secret",
                               rtsp_port=port, rtsp_password="test-view-secret", idle_timeout_seconds=5, retry_seconds=5)
            configure_logging(settings)
            bridge = Bridge(settings, folder / "runtime", source=str(folder), mediamtx=MEDIAMTX, ffmpeg=FFMPEG)
            created, errors = [], []
            original_spawn = bridge.spawn

            def track_spawn(command, **kwargs):
                child = original_spawn(command, **kwargs)
                created.append((command, child))
                return child

            bridge.spawn = track_spawn

            def run_bridge():
                try:
                    bridge.run()
                except Exception as error:
                    errors.append(error)

            thread = threading.Thread(target=run_bridge)
            thread.start()
            try:
                eventually(lambda: bridge.state == "STREAMING")
                snapshot = folder / "frame.jpg"
                result = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
                    "-i", f"rtsp://viewer:test-view-secret@127.0.0.1:{port}/q5", "-frames:v", "1", "-y", str(snapshot)],
                    capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertGreater(snapshot.stat().st_size, 100)
                # A wrong reader password must fail even though localhost can publish.
                denied = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
                    "-i", f"rtsp://viewer:wrong@127.0.0.1:{port}/q5", "-frames:v", "1", "-f", "null", "-"],
                    capture_output=True, timeout=15)
                self.assertNotEqual(denied.returncode, 0)
                session = bridge.session
                (folder / "mode.txt").write_text("stall")
                eventually(lambda: bridge.state == "RETRYING", timeout=20)
                (folder / "mode.txt").write_text("video")
                eventually(lambda: bridge.session > session and bridge.state == "STREAMING")
                session = bridge.session
                active_ffmpeg = next(p for command, p in reversed(created) if command[0] == FFMPEG and p.poll() is None)
                active_ffmpeg.kill()
                eventually(lambda: bridge.session > session and bridge.state == "STREAMING")
                bridge.server.kill()
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
                self.assertTrue(errors)
                self.assertIn("MediaMTX", str(errors[0]))
                self.assertEqual(bridge.state, "STOPPED")
                self.assertTrue(all(p.poll() is not None for _, p in created))
                status = json.loads((folder / "runtime/status.json").read_text())
                self.assertNotIn("password", json.dumps(status))
            finally:
                bridge.stop.set()
                thread.join(timeout=15)

