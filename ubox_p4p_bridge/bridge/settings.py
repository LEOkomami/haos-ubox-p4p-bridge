"""Validate HA options before starting any subprocess or network activity."""

from dataclasses import dataclass, field, fields
import ipaddress
import re

UID_PATTERN = re.compile(r"[A-Za-z0-9]{20}")


@dataclass(frozen=True)
class Settings:
    camera_uid: str = ""
    camera_password: str = field(default="", repr=False)
    auto_discover: bool = True
    discovery_broadcast: str = "255.255.255.255"
    mode: str = "direct"
    stream_name: str = "q5"
    rtsp_port: int = 8557
    rtsp_username: str = "viewer"
    rtsp_password: str = field(default="", repr=False)
    handshake_seconds: int = 40
    startup_timeout_seconds: int = 120
    idle_timeout_seconds: int = 30
    retry_seconds: int = 10
    input_fps: int = 15
    log_level: str = "info"

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict):
            raise ValueError("Options must be an object")
        known = {f.name for f in fields(cls)}
        if set(values) - known:
            raise ValueError("Unknown options; compare configuration with DOCS.md")
        result = cls(**values)
        for item in fields(cls):
            default_type = type(item.default)
            if type(getattr(result, item.name)) is not default_type:
                raise ValueError(f"Invalid type for {item.name}")
        if result.camera_uid and not UID_PATTERN.fullmatch(result.camera_uid):
            raise ValueError("camera_uid must be 20 ASCII letters/digits, or blank")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", result.stream_name):
            raise ValueError("Invalid stream_name")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", result.rtsp_username) or result.rtsp_username == "any":
            raise ValueError("Invalid rtsp_username (any is reserved)")
        for name in ("camera_password", "rtsp_password"):
            password = getattr(result, name)
            if any(ord(c) < 32 or ord(c) == 127 for c in password):
                raise ValueError(f"Control characters are not supported in {name}")
        if result.mode not in ("direct", "relay"):
            raise ValueError("mode must be direct or relay")
        if result.log_level not in ("info", "debug", "warning", "error"):
            raise ValueError("Invalid log_level")
        try:
            address = ipaddress.IPv4Address(result.discovery_broadcast)
        except ipaddress.AddressValueError:
            raise ValueError("discovery_broadcast must be an IPv4 address") from None
        if address.is_multicast or address.is_loopback or address.is_unspecified:
            raise ValueError("discovery_broadcast must be a LAN broadcast address")
        for name, low, high in (
            ("rtsp_port", 1024, 65535), ("handshake_seconds", 10, 120),
            ("startup_timeout_seconds", 60, 600), ("idle_timeout_seconds", 5, 300),
            ("retry_seconds", 5, 300), ("input_fps", 1, 60),
        ):
            if not low <= getattr(result, name) <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
        # Upstream does STUN/discovery and a 30-second punch after the handshake.
        if result.startup_timeout_seconds < result.handshake_seconds + 45:
            raise ValueError("startup_timeout_seconds must exceed handshake_seconds by at least 45")
        return result


def mediamtx_config(settings):
    """JSON is valid YAML; never interpolate user input into YAML or a shell."""
    reader = {
        "user": settings.rtsp_username if settings.rtsp_password else "any",
        "pass": settings.rtsp_password,
        "ips": [] if settings.rtsp_password else [
            "127.0.0.1", "::1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
        ],
        "permissions": [{"action": "read", "path": settings.stream_name}],
    }
    return {
        "logLevel": "debug" if settings.log_level == "debug" else "info",
        "rtsp": True, "rtspAddress": f":{settings.rtsp_port}",
        "rtspTransports": ["tcp"], "rtmp": False, "hls": False,
        "webrtc": False, "srt": False, "moq": False, "api": False, "metrics": False,
        "pprof": False, "playback": False,
        "authMethod": "internal",
        "authInternalUsers": [
            {"user": "any", "ips": ["127.0.0.1", "::1"],
             "permissions": [{"action": "publish", "path": settings.stream_name}]},
            reader,
        ],
        "paths": {settings.stream_name: {"source": "publisher", "overridePublisher": False}},
    }


def ffmpeg_command(settings, binary="ffmpeg"):
    return [
        binary, "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-progress", "pipe:1", "-stats_period", "1",
        "-fflags", "+genpts", "-f", "hevc", "-r", str(settings.input_fps),
        "-i", "pipe:0", "-map", "0:v:0", "-an", "-c:v", "copy",
        "-bsf:v", f"setts=ts=N/({settings.input_fps}*TB):duration=1/({settings.input_fps}*TB)",
        "-f", "rtsp", "-rtsp_transport", "tcp",
        f"rtsp://127.0.0.1:{settings.rtsp_port}/{settings.stream_name}",
    ]
