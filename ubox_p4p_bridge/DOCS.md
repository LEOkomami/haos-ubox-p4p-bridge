# UBox P4P Bridge

Publishes a UBox / UBIA / i-Cam+ style camera as a standard RTSP stream that go2rtc,
the AlexxIT WebRTC integration, VLC, or a generic Home Assistant camera can read.

This is independent interoperability work. It is not affiliated with, endorsed by, or
supported by UBox, UBIA, ZGWL, or any camera vendor. It ships no vendor binaries.

## Status

Experimental. The pipeline is verified against synthetic HEVC, but the P4P handshake has
not yet been confirmed against a real `Q5-wifi(pir)`. Expect to iterate.

## Requirements

- Home Assistant OS on `aarch64` hardware. Raspberry Pi 4 is the target.
- The camera's 20-character UID and its **device** password.
- The camera on the same LAN as Home Assistant. Direct P2P from a public-IP host does not
  work for the symmetric-NAT case upstream tested, so a residential peer is required.

The device password is the camera password from the mobile app, which may differ from the
app or cloud account password. Enter it only in this app's Configuration tab. It is stored
in Home Assistant's app options and never written to the logs.

## Before you install

Installing from the repository pulls a **prebuilt image**; nothing is compiled on your Pi.
The image is built by GitHub Actions from the same Dockerfile. The only way to trigger a
build on the Pi itself is to copy the add-on folder into `/addons/` as a local add-on, which
compiles a C extension with Cython and `gcc -O3` on the host. Avoid that on a Pi that also
runs Home Assistant. The app does not start itself on boot (`boot: manual`), so a failed
start can never become a boot loop.

## Setup

1. Install the app and open its **Configuration** tab.
2. Set `camera_password`. Leave `camera_uid` blank to auto-discover a single camera on the
   LAN, or paste the 20-character UID from the camera's Device info screen.
3. Save, then start the app.
4. Open the **Log** tab and follow the state transitions.
5. When the state reaches `STREAMING`, open the RTSP URL in VLC:

   ```text
   rtsp://HOME_ASSISTANT_IP:8557/q5
   ```

   Force TCP. The server does not accept RTSP over UDP.

6. Turn on the **Watchdog** toggle on the app's Info tab. If MediaMTX itself dies, the app
   exits on purpose so the Supervisor can restart it cleanly; without the Watchdog toggle
   nothing performs that restart.

## States

The log reports one state per line as `state=NAME`.

| State | Meaning |
| --- | --- |
| `STARTING` | Bringing up the RTSP server. |
| `DISCOVERING` | Broadcasting a LAN search because `camera_uid` is blank. |
| `NEEDS_CONFIGURATION` | Missing password, or discovery found several cameras. Fix the options. |
| `WAITING_FOR_CAMERA` | Discovery got no reply. The camera is probably asleep. |
| `HANDSHAKING` | P4P handshake and NAT traversal in progress. |
| `STREAMING` | FFmpeg is publishing frames to MediaMTX. |
| `STALLED` | Video, the FFmpeg input, or the RTSP output stopped advancing. |
| `RETRYING` | Waiting `retry_seconds` before the next session. |

Alongside the states, the log reports the upstream counters every few seconds:

```text
P4P: packets=1200 hevc_bytes=345678 hevc_frames=910
```

`packets` above zero with `hevc_frames` at zero means P4P connected but the camera sent no
video. That points at the device password or the camera's stream configuration, not the
network.

## Options

| Option | Default | Notes |
| --- | --- | --- |
| `camera_uid` | blank | 20 letters/digits, or blank to auto-discover. |
| `camera_password` | blank | Required. The camera's device password. |
| `auto_discover` | `true` | LAN broadcast search when `camera_uid` is blank. |
| `discovery_broadcast` | `255.255.255.255` | Set a subnet broadcast such as `192.168.0.255` if the global one is filtered. |
| `mode` | `direct` | `direct` for sustained video, `relay` for diagnosis only. |
| `stream_name` | `q5` | The RTSP path segment. |
| `rtsp_port` | `8557` | Deliberately not `8554`, which go2rtc commonly uses. |
| `rtsp_username` | `viewer` | Used only when `rtsp_password` is set. `any` is reserved. |
| `rtsp_password` | blank | See Access control below. |
| `handshake_seconds` | `40` | How long the direct handshake waits for the camera knock. Ignored in relay mode. |
| `startup_timeout_seconds` | `120` | Give up on a session that never publishes a frame. Must exceed `handshake_seconds` by at least 45, because upstream also runs discovery and a 30-second punch phase. |
| `idle_timeout_seconds` | `30` | Restart the session after this much silence on an already-running stream. |
| `retry_seconds` | `10` | Delay between sessions. |
| `input_fps` | `15` | The camera's frame rate. Raw HEVC carries no timestamps, so this value generates them. |
| `log_level` | `info` | Use `debug` for MediaMTX detail. |

### Access control

Only `127.0.0.1` and `::1` may publish, so nothing on the LAN can hijack the path.

For reading, leaving `rtsp_password` blank allows unauthenticated reads from loopback and
from private ranges only (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`). Setting
`rtsp_password` requires `rtsp_username` and `rtsp_password` from every reader instead:

```text
rtsp://viewer:YOUR_RTSP_PASSWORD@HOME_ASSISTANT_IP:8557/q5
```

Set `rtsp_password` if anything untrusted shares the LAN.

## Connecting go2rtc and the Home Assistant UI

Prove the URL in VLC first. Then add the stream to go2rtc:

```yaml
streams:
  q5: rtsp://HOME_ASSISTANT_IP:8557/q5
```

If `rtsp_password` is set, put the credentials in the URL and remember that the go2rtc
configuration file then contains a secret.

The camera delivers HEVC. go2rtc accepts HEVC over RTSP, but browser WebRTC video is
H.264, so some browsers will show nothing. If playback fails, transcode in go2rtc rather
than in this app:

```yaml
streams:
  q5:
    - rtsp://HOME_ASSISTANT_IP:8557/q5
    - "ffmpeg:q5#video=h264#hardware"
```

Software transcoding of a 2304x1296 stream is expensive on a Raspberry Pi 4. Prefer the
hardware path, and drop resolution or frame rate before accepting a CPU-bound transcode.

## Relay mode

`mode: relay` exists to answer one question: does this camera talk P4P at all when direct
P2P will not establish? Upstream re-establishes a relay session per cycle and gets roughly
one GOP each time, so the result is choppy by design. Use it to confirm the credentials
and the protocol, then go back to `direct`. Do not treat relay output as a usable camera
feed.

## Troubleshooting

**Stuck in `WAITING_FOR_CAMERA`.** The camera is a PIR model and sleeps. Trigger it by
walking in front of it, or open the vendor app to wake it, then watch the log. If
discovery never replies, set `camera_uid` manually and set `auto_discover` to `false`.

**Stuck in `NEEDS_CONFIGURATION`.** Either `camera_password` is blank, or discovery found
more than one camera. The log lists the UIDs it saw; put the one you want in `camera_uid`.

**`P4P: camera handshake failed`.** No camera knock arrived within `handshake_seconds`.
Raise it toward 120, raise `startup_timeout_seconds` to match, and confirm the camera is
awake and on the same subnet.

**Repeated `STALLED: camera video stalled`.** The camera stopped sending. On a PIR model
between motion events this is expected, and the app retries. If it never recovers while
the camera is clearly awake, try `mode: relay` to separate a credential problem from a NAT
problem.

**`STALLED: no published video before startup deadline`.** P4P delivered bytes but FFmpeg
never produced a frame, or nothing arrived at all. Check the `hevc_frames` counter to tell
those apart.

**The app exits with a MediaMTX error.** Something else is on `rtsp_port`. go2rtc uses
`8554`; pick another free port above 1024.

**VLC will not open the URL.** Force RTSP over TCP, and if `rtsp_password` is set include
the credentials. Reads without a password only work from private address ranges.

## Support and scope

Report problems against this repository, not to the camera vendor. Phase 1 deliberately
avoids camera firmware modification, telnet, and SD-card payloads.
