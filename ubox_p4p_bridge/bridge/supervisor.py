"""Supervise MediaMTX and one P4P/FFmpeg session with bounded I/O and retries."""

import argparse
import json
import logging
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import quote

from discovery import discover
from settings import Settings, ffmpeg_command, mediamtx_config

LOG = logging.getLogger("bridge")


class Redactor(logging.Filter):
    def __init__(self, secrets):
        super().__init__()
        self.secrets = sorted({variant for secret in secrets if secret for variant in (
            secret, quote(secret, safe=""), secret.encode().hex(),
        )}, key=len, reverse=True)

    def filter(self, record):
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[redacted]")
        record.msg, record.args = message, ()
        return True


def configure_logging(settings):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.addFilter(Redactor([settings.camera_password, settings.rtsp_password,
                               os.environ.get("SUPERVISOR_TOKEN", "")]))
    LOG.handlers[:] = [handler]
    LOG.setLevel(settings.log_level.upper())


def child_environment(extra=None):
    # Do not give subprocesses Supervisor credentials or unrelated environment secrets.
    result = {key: os.environ[key] for key in (
        "PATH", "LANG", "TZ", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
    ) if key in os.environ}
    result.update(PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    result.update(extra or {})
    return result


def drain_lines(pipe, callback):
    """Bound memory on noisy children; discard entire oversized lines."""
    try:
        while True:
            line = pipe.readline(8193)
            if not line:
                return
            if len(line) > 8192:
                while line and not line.endswith(b"\n"):
                    line = pipe.readline(8193)
                continue
            callback(line.decode("utf-8", errors="replace").rstrip())
    except (OSError, ValueError):
        return


def thread_for(target, *args):
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


# Anchored so only these exact numeric shapes are ever echoed from upstream output.
DIRECT_COUNTERS = re.compile(r"^\[stream\] pkts=(\d+) hevc_bytes=(\d+) frames=(\d+)$")
RELAY_COUNTERS = re.compile(
    r"^\[relay\] cycle (\d+): \+\d+ frames \(total (\d+) frames, (\d+) B\)$")


def upstream_log(line):
    # Packet dumps may contain transformed secrets that string redaction cannot cover.
    # Translate recognized milestones; never forward arbitrary upstream text.
    direct = DIRECT_COUNTERS.match(line)
    if direct:
        # pkts>0 with frames=0 means P4P connected but delivered no video.
        LOG.info("P4P: packets=%s hevc_bytes=%s hevc_frames=%s", *direct.groups())
        return
    relay = RELAY_COUNTERS.match(line)
    if relay:
        LOG.info("P4P: relay cycle=%s total_frames=%s total_bytes=%s", *relay.groups())
        return
    for marker, description in (
        ("[handshake] queryreq", "P4P: querying masters"),
        ("[handshake] knock +", "P4P: requesting camera wake and relay login"),
        ("[handshake] CAMERA KNOCK", "P4P: received camera knock"),
        ("[stream] KCP conv=", "P4P: starting KCP session"),
        ("[stream] handshake failed", "P4P: camera handshake failed"),
        ("[stream] receiving video", "P4P: waiting for HEVC video"),
        ("[relay] streaming", "P4P: starting diagnostic relay cycles"),
        ("[worker] stopped", "P4P: worker failed; verify configuration and dependency compatibility"),
    ):
        if line.startswith(marker):
            LOG.info(description)
            return


class Activity:
    def __init__(self, now=None):
        self.started = time.monotonic() if now is None else now
        self.lock = threading.Lock()
        self.received_bytes = 0
        self.forwarded_bytes = 0
        self.frames = 0
        self.last_video = None
        self.last_forwarded = None
        self.last_published = None
        self.error = None

    def received(self, size):
        with self.lock:
            self.received_bytes += size
            self.last_video = time.monotonic()

    def forwarded(self, size):
        with self.lock:
            self.forwarded_bytes += size
            self.last_forwarded = time.monotonic()

    def progress(self, line):
        key, sep, value = line.partition("=")
        if key != "frame" or not sep:
            return
        try:
            frames = int(value.strip())
        except ValueError:
            return
        with self.lock:
            if frames > self.frames:
                self.frames = frames
                self.last_published = time.monotonic()

    def fail(self, reason):
        with self.lock:
            self.error = reason

    def reason_to_restart(self, now, startup_timeout, idle_timeout):
        with self.lock:
            if self.error:
                return self.error
            if self.last_published is None:
                return "no published video before startup deadline" if now - self.started >= startup_timeout else None
            for label, timestamp in (("camera video", self.last_video),
                                     ("FFmpeg input", self.last_forwarded),
                                     ("RTSP output", self.last_published)):
                if timestamp is not None and now - timestamp >= idle_timeout:
                    return f"{label} stalled"
        return None

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            return {
                "received_bytes": self.received_bytes, "forwarded_bytes": self.forwarded_bytes,
                "published_frames": self.frames,
                "last_video_age_seconds": None if self.last_video is None else round(now - self.last_video, 1),
                "last_publish_age_seconds": None if self.last_published is None else round(now - self.last_published, 1),
            }


def pump_video(source, destination, activity):
    try:
        while True:
            data = os.read(source.fileno(), 65536)
            if not data:
                activity.fail("P4P video output closed")
                return
            activity.received(len(data))
            remaining = memoryview(data)
            while remaining:
                written = os.write(destination.fileno(), remaining)
                if not written:
                    raise BrokenPipeError()
                activity.forwarded(written)
                remaining = remaining[written:]
    except (OSError, ValueError):
        activity.fail("video pipe closed")


def terminate_all(processes, grace=3):
    """Signal every process first, then wait, then kill any survivors."""
    live = [process for process in processes if process.poll() is None]
    for process in live:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace
    for process in live:
        try:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait(timeout=3)


class Bridge:
    def __init__(self, settings, runtime, source="/opt/ubox-p4p", mediamtx="mediamtx", ffmpeg="ffmpeg"):
        self.settings, self.runtime, self.source = settings, Path(runtime), source
        self.mediamtx_binary, self.ffmpeg_binary = mediamtx, ffmpeg
        self.stop = threading.Event()
        self.server = None
        self.server_thread = None
        self.state = None
        self.session = 0
        self.uid = settings.camera_uid
        self.activity = None

    def transition(self, state, reason=""):
        if state != self.state:
            LOG.info("state=%s%s", state, f": {reason}" if reason else "")
            self.state = state
        self.write_status()

    def write_status(self):
        status = {"state": self.state, "session": self.session,
                  "updated_at": int(time.time()), "mode": self.settings.mode}
        if self.activity:
            status.update(self.activity.snapshot())
        temporary = self.runtime / "status.tmp"
        temporary.write_text(json.dumps(status), encoding="utf-8")
        temporary.replace(self.runtime / "status.json")

    def spawn(self, command, **kwargs):
        return subprocess.Popen(command, env=kwargs.pop("env", child_environment()),
                                start_new_session=(os.name == "posix"), **kwargs)

    def start_server(self):
        # Catch collisions before accepting a connection from an unrelated RTSP server.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("0.0.0.0", self.settings.rtsp_port))
        config_path = self.runtime / "mediamtx.yml"
        config_path.write_text(json.dumps(mediamtx_config(self.settings)), encoding="utf-8")
        config_path.chmod(0o600)
        self.server = self.spawn([self.mediamtx_binary, str(config_path)],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=self.runtime)
        self.server_thread = thread_for(drain_lines, self.server.stdout,
                                       lambda line: LOG.info("MediaMTX: %s", line))
        deadline = time.monotonic() + 15
        while not self.stop.wait(0.1):
            self.check_server()
            try:
                with socket.create_connection(("127.0.0.1", self.settings.rtsp_port), timeout=0.3):
                    return
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("RTSP server did not become ready")

    def check_server(self):
        if self.server and self.server.poll() is not None:
            raise RuntimeError("MediaMTX exited; stopping app so HA watchdog can restart it")

    def pause(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.stop.wait(min(0.25, max(0, deadline - time.monotonic()))):
            self.check_server()
            if time.monotonic() >= deadline:
                return

    def resolve_uid(self):
        if self.uid:
            return True
        if not self.settings.auto_discover:
            self.transition("NEEDS_CONFIGURATION", "enter camera_uid in the app Configuration tab")
            return False
        self.transition("DISCOVERING", "searching LAN for an awake UBox camera")
        try:
            cameras = discover(self.settings.discovery_broadcast, self.stop, source=self.source)
        except OSError:
            LOG.warning("LAN discovery failed; check broadcast address and network")
            cameras = {}
        self.check_server()
        if len(cameras) == 1:
            self.uid = next(iter(cameras))
            LOG.info("Discovered camera UID %s at %s; selected for this app run", self.uid, cameras[self.uid])
            return True
        if len(cameras) > 1:
            LOG.warning("Multiple camera UIDs found: %s. Enter camera_uid to select one.", ", ".join(sorted(cameras)))
            self.transition("NEEDS_CONFIGURATION", "multiple cameras found; choose camera_uid")
        else:
            self.transition("WAITING_FOR_CAMERA", "no discovery reply; wake camera or enter its UID manually")
        return False

    def run_session(self):
        processes, threads = [], []
        self.session += 1
        activity = self.activity = Activity()
        self.transition("HANDSHAKING")
        try:
            ffmpeg = self.spawn(ffmpeg_command(self.settings, self.ffmpeg_binary),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0)
            processes.append(ffmpeg)
            threads.append(thread_for(drain_lines, ffmpeg.stderr, lambda line: LOG.warning("FFmpeg: %s", line)))
            threads.append(thread_for(drain_lines, ffmpeg.stdout, activity.progress))
            worker = self.spawn([sys.executable, str(Path(__file__).with_name("worker.py"))],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                env=child_environment({
                                    "UBOX_SOURCE": self.source, "UBOX_UID": self.uid,
                                    "UBOX_PASSWORD": self.settings.camera_password,
                                    "UBOX_MODE": self.settings.mode,
                                    "UBOX_HANDSHAKE": str(self.settings.handshake_seconds),
                                }))
            processes.append(worker)
            threads.append(thread_for(drain_lines, worker.stderr, upstream_log))
            threads.append(thread_for(pump_video, worker.stdout, ffmpeg.stdin, activity))
            next_status = 0.0
            while not self.stop.wait(0.25):
                self.check_server()
                reason = None
                if ffmpeg.poll() is not None:
                    reason = "FFmpeg exited"
                elif worker.poll() is not None:
                    reason = "P4P worker exited"
                else:
                    reason = activity.reason_to_restart(time.monotonic(),
                        self.settings.startup_timeout_seconds, self.settings.idle_timeout_seconds)
                if reason:
                    self.transition("STALLED", reason)
                    return reason
                stats = activity.snapshot()
                if stats["published_frames"] > 0:
                    self.transition("STREAMING") if self.state != "STREAMING" else None
                if time.monotonic() >= next_status:
                    self.write_status()
                    LOG.info("video: received_bytes=%d published_frames=%d last_publish_age=%s",
                             stats["received_bytes"], stats["published_frames"], stats["last_publish_age_seconds"])
                    next_status = time.monotonic() + 10
            return "app stopping"
        finally:
            terminate_all(processes)
            for thread in threads:
                thread.join(timeout=1)
            for process in processes:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe:
                        pipe.close()

    def run(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.transition("STARTING")
        try:
            self.start_server()
            LOG.info("RTSP endpoint: rtsp://HOME_ASSISTANT_IP:%d/%s (TCP)",
                     self.settings.rtsp_port, self.settings.stream_name)
            if not self.settings.rtsp_password:
                LOG.info("RTSP reads allowed without password from private networks; configure rtsp_password to require login")
            while not self.stop.is_set():
                self.check_server()
                if not self.resolve_uid():
                    self.pause(max(30, self.settings.retry_seconds))
                    continue
                if not self.settings.camera_password:
                    self.transition("NEEDS_CONFIGURATION", "enter camera_password in app Configuration, then restart")
                    self.pause(30)
                    continue
                reason = self.run_session()
                if not self.stop.is_set():
                    self.transition("RETRYING", reason)
                    self.pause(self.settings.retry_seconds)
        finally:
            self.transition("STOPPING")
            if self.server:
                terminate_all([self.server])
                if self.server_thread:
                    self.server_thread.join(timeout=1)
                self.server.stdout.close()
            self.transition("STOPPED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--options", default="/data/options.json")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        settings = Settings.from_dict(json.loads(Path(args.options).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        print("Invalid or unreadable options. Check configuration types, UID, ports and timeout limits in DOCS.md.", file=sys.stderr)
        return 1
    configure_logging(settings)
    try:
        with tempfile.TemporaryDirectory(prefix="ubox-bridge-") as runtime:
            bridge = Bridge(settings, runtime)
            for event in (signal.SIGINT, signal.SIGTERM):
                signal.signal(event, lambda *_: bridge.stop.set())
            bridge.run()
    except Exception as error:
        LOG.error("App stopped (%s). Check server logs, port availability and configuration.", type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
