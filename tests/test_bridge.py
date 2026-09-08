from dataclasses import replace
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from discovery import candidate_uid
from settings import Settings, ffmpeg_command, mediamtx_config
from supervisor import Activity, Bridge, Redactor, child_environment, drain_lines, pump_video, upstream_log
from worker import VideoSink

ROOT = Path(__file__).resolve().parents[1]
TEST_UID = "ABCDEFGHIJKLMNOPQRST"


class ConfigurationTests(unittest.TestCase):
    def test_defaults_match_ha_metadata(self):
        import yaml
        config = yaml.safe_load((ROOT / "ubox_p4p_bridge/config.yaml").read_text())
        self.assertEqual(Settings.from_dict(config["options"]), Settings())
        self.assertEqual(set(config["schema"]), set(config["options"]))
        self.assertEqual(config["schema"]["camera_password"], "password")
        self.assertEqual(config["arch"], ["aarch64"])

    def test_translations_cover_every_option_exactly(self):
        import yaml
        config = yaml.safe_load((ROOT / "ubox_p4p_bridge/config.yaml").read_text())
        translations = yaml.safe_load((ROOT / "ubox_p4p_bridge/translations/en.yaml").read_text())
        entries = translations["configuration"]
        self.assertEqual(set(entries), set(config["options"]))
        for name, entry in entries.items():
            with self.subTest(option=name):
                self.assertEqual(set(entry), {"name", "description"})
                self.assertTrue(entry["name"] and entry["description"])

    def test_documentation_files_ha_renders_are_present(self):
        for name in ("DOCS.md", "CHANGELOG.md", "translations/en.yaml"):
            with self.subTest(name=name):
                self.assertTrue((ROOT / "ubox_p4p_bridge" / name).is_file())

    def test_reject_invalid_and_injected_options(self):
        cases = [
            {"stream_name": "q5\npaths: evil"}, {"rtsp_port": True},
            {"camera_uid": "ABC"}, {"mode": "direct; command"},
            {"rtsp_username": "any"}, {"camera_password": "one\ntwo"},
            {"discovery_broadcast": "localhost"}, {"input_fps": 0},
            {"auto_discover": "true"}, {"unknown": "option"},
            {"handshake_seconds": 120, "startup_timeout_seconds": 120},
        ]
        for values in cases:
            with self.subTest(values=list(values)), self.assertRaises(ValueError):
                Settings.from_dict(values)

    def test_no_secrets_in_repr_or_ffmpeg_arguments(self):
        settings = replace(Settings(), camera_password="device secret", rtsp_password="view secret")
        self.assertNotIn("secret", repr(settings))
        self.assertNotIn("secret", " ".join(ffmpeg_command(settings)))

    def test_publish_permission_is_loopback_only(self):
        config = mediamtx_config(Settings())
        publishers = [u for u in config["authInternalUsers"] if any(p["action"] == "publish" for p in u["permissions"])]
        self.assertEqual(len(publishers), 1)
        self.assertEqual(publishers[0]["ips"], ["127.0.0.1", "::1"])
        self.assertEqual(config["rtspTransports"], ["tcp"])
        self.assertFalse(config["moq"])
        self.assertFalse(config["paths"]["q5"]["overridePublisher"])

    def test_reader_password_survives_json_serialization(self):
        secret = 'test:"quoted"\\value'
        config = json.loads(json.dumps(mediamtx_config(replace(Settings(), rtsp_password=secret))))
        self.assertEqual(config["authInternalUsers"][1]["pass"], secret)
        self.assertEqual(config["authInternalUsers"][1]["user"], "viewer")


class WatchdogTests(unittest.TestCase):
    def test_initial_handshake_has_separate_deadline(self):
        activity = Activity(now=0)
        self.assertIsNone(activity.reason_to_restart(119, 120, 30))
        self.assertIn("startup", activity.reason_to_restart(120, 120, 30))

    def test_healthy_stream_is_not_restarted_due_to_age(self):
        activity = Activity(now=0)
        activity.last_video = activity.last_forwarded = activity.last_published = 3599
        self.assertIsNone(activity.reason_to_restart(3600, 120, 30))

    def test_camera_stall_and_blocked_ffmpeg_are_detected(self):
        for attribute, expected in (("last_video", "camera video"), ("last_forwarded", "FFmpeg input"), ("last_published", "RTSP output")):
            with self.subTest(attribute=attribute):
                activity = Activity(now=0)
                activity.last_video = activity.last_forwarded = activity.last_published = 100
                setattr(activity, attribute, 50)
                self.assertIn(expected, activity.reason_to_restart(101, 120, 30))

    def test_repeated_progress_does_not_reset_idle_timer(self):
        activity = Activity(now=0)
        with patch("supervisor.time.monotonic", return_value=5):
            activity.progress("frame=12")
        with patch("supervisor.time.monotonic", return_value=50):
            activity.progress("frame=12")
        self.assertEqual(activity.last_published, 5)
        self.assertIn("RTSP output", activity.reason_to_restart(51, 120, 30))


class PrivacyAndDiscoveryTests(unittest.TestCase):
    def test_redaction_and_environment_isolation(self):
        record = logging.LogRecord("test", 20, "", 0, "value %s", ("abc/123 abc%2F123 6162632f313233",), None)
        Redactor(["abc/123"]).filter(record)
        self.assertEqual(record.getMessage(), "value [redacted] [redacted] [redacted]")
        with patch.dict(os.environ, {"SUPERVISOR_TOKEN": "private", "UNRELATED_KEY": "secret"}):
            child = child_environment({"UBOX_UID": TEST_UID})
        self.assertNotIn("SUPERVISOR_TOKEN", child)
        self.assertNotIn("UNRELATED_KEY", child)

    def test_upstream_raw_diagnostics_are_not_forwarded(self):
        with self.assertLogs("bridge", level="INFO") as captured:
            upstream_log("relay login: transformed-secret-material")
            upstream_log("[handshake] CAMERA KNOCK from camera token=secret")
        self.assertEqual(len(captured.output), 1)
        self.assertNotIn("secret", captured.output[0])

    def test_upstream_counters_are_forwarded_as_numbers_only(self):
        with self.assertLogs("bridge", level="INFO") as captured:
            upstream_log("[stream] pkts=1200 hevc_bytes=345678 frames=910")
            upstream_log("[relay] cycle 3: +12 frames (total 40 frames, 51200 B)")
        self.assertIn("packets=1200 hevc_bytes=345678 hevc_frames=910", captured.output[0])
        self.assertIn("relay cycle=3 total_frames=40 total_bytes=51200", captured.output[1])

    def test_counter_lookalike_lines_are_not_forwarded(self):
        with self.assertLogs("bridge", level="INFO") as captured:
            upstream_log("[stream] pkts=1 hevc_bytes=2 frames=3 token=secret")
            upstream_log("prefix [stream] pkts=1 hevc_bytes=2 frames=3")
            upstream_log("[relay] cycle 1: +1 frames (total 1 frames, 1 B) secret")
            upstream_log("[handshake] queryreq to masters")
        self.assertEqual(len(captured.output), 1)
        self.assertNotIn("secret", captured.output[0])

    def test_oversized_log_line_is_discarded_whole(self):
        lines = []
        drain_lines(io.BytesIO(b"x" * 20000 + b"SECRET\nsafe\n"), lines.append)
        self.assertEqual(lines, ["safe"])

    def test_discovery_accepts_only_reply_with_exact_uid(self):
        self.assertEqual(candidate_uid({"msg_type": "0x1302", "uid": TEST_UID}), TEST_UID)
        for parsed in (None, {}, {"msg_type": "0x1301", "uid": TEST_UID},
                       {"msg_type": "0x1302", "uid": "short"}):
            self.assertIsNone(candidate_uid(parsed))

    def test_multiple_discovered_cameras_are_never_auto_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = Bridge(Settings(), folder)
            with patch("supervisor.discover", return_value={TEST_UID: "192.168.1.2", "B" * 20: "192.168.1.3"}):
                self.assertFalse(bridge.resolve_uid())
            self.assertEqual(bridge.uid, "")
            self.assertEqual(bridge.state, "NEEDS_CONFIGURATION")

    def test_single_discovered_uid_is_selected(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = Bridge(Settings(), folder)
            with patch("supervisor.discover", return_value={TEST_UID: "192.168.1.2"}):
                self.assertTrue(bridge.resolve_uid())
            self.assertEqual(bridge.uid, TEST_UID)


class PipelineTests(unittest.TestCase):
    def test_partial_pipe_writes_preserve_every_byte(self):
        activity = Activity()
        source, destination = unittest.mock.Mock(), unittest.mock.Mock()
        chunks = []

        def partial_write(fd, data):
            chunks.append(bytes(data[:2]))
            return min(2, len(data))

        with patch("supervisor.os.read", side_effect=[b"abcdefg", b""]), patch("supervisor.os.write", side_effect=partial_write):
            pump_video(source, destination, activity)
        self.assertEqual(b"".join(chunks), b"abcdefg")
        self.assertEqual(activity.forwarded_bytes, 7)
        self.assertEqual(activity.error, "P4P video output closed")

    def test_video_sink_completes_short_writes_upstream_ignores(self):
        written = []

        def short_write(fd, data):
            written.append(bytes(data[:3]))
            return min(3, len(data))

        sink = VideoSink(7)
        with patch("worker.os.write", side_effect=short_write):
            self.assertEqual(sink.write(b"0123456789"), 10)
        self.assertEqual(b"".join(written), b"0123456789")
        with patch("worker.os.write", return_value=0), self.assertRaises(BrokenPipeError):
            sink.write(b"x")

    def test_worker_keeps_binary_video_separate_in_both_modes(self):
        fake = '''import sys
def run_stream(uid, password, seconds, output):
    print("diagnostic " + password)
    with open(output, "wb") as video:
        video.write(b"\\x00\\x00\\x00\\x01\\x40\\xff")
def run_relay_stream(uid, password, seconds, output):
    assert seconds == 0
    run_stream(uid, password, seconds, output)
'''
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "p4p_stream.py").write_text(fake)
            for mode in ("direct", "relay"):
                env = child_environment({"UBOX_SOURCE": folder, "UBOX_UID": TEST_UID,
                    "UBOX_PASSWORD": "testsecret", "UBOX_MODE": mode, "UBOX_HANDSHAKE": "40"})
                result = subprocess.run([sys.executable, str(ROOT / "ubox_p4p_bridge/bridge/worker.py")],
                    env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"\x00\x00\x00\x01\x40\xff")
                self.assertIn(b"diagnostic", result.stderr)
