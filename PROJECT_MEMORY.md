# Project Memory

This file preserves the complete working context for the Q5 Home Assistant camera project so another coding agent can continue without needing the original chat.

## 1. User objective

The user wants to connect an inexpensive WiFi IP camera to Home Assistant.

Home Assistant runs on a Raspberry Pi 4 using Home Assistant OS. The preferred final deployment is a GitHub repository that can be added to Home Assistant as a custom App / Add-on repository, without requiring a second computer.

The user is comfortable building and iterating with Codex and wants the project stored in GitHub, then installed into HAOS from that repository.

## 2. Camera information

The camera Device info screen shows:

```text
ID:               XXXXXXXXXXXXXXXXXXXX
Model:            Q5-wifi(pir)
Firmware version: 271.0.7.99
Wifi Version:     63.0.2.9
Vendor:           ZGWL
IP:               192.168.0.NNN
MAC:              xx:xx:xx:xx:xx:xx
```

Known observations:

- The model includes `pir`, strongly suggesting a PIR-triggered, low-power or battery-oriented design.
- The camera may sleep aggressively.
- The local IP is useful for diagnostics but the P4P client primarily needs the 20-character UID plus a device password.
- The user's current device password is not known and must not be committed to GitHub.

## 3. App / ecosystem identification

The investigation found strong similarity to UBox / UBIA / i-Cam+ style cameras.

This identification is still a hypothesis until the user confirms which mobile app is actually used with this device.

Do not state as a proven fact that the user's exact Q5 is supported until a real P4P handshake succeeds.

## 4. Why ordinary RTSP / ONVIF was not treated as the primary path

The camera has not yet exposed a known standard RTSP URL.

The reverse engineering project below documents UBox / UBIA cameras using a proprietary P4P protocol over UDP instead of a normal always-on RTSP endpoint:

https://github.com/mahumadad/ubox-p4p

The goal therefore changed from guessing RTSP URLs to creating a bridge:

```text
proprietary P4P -> raw video -> RTSP -> Home Assistant
```

Standard RTSP / ONVIF probing can still be used as a quick sanity check, but it should not distract from the P4P path unless the exact Q5 unexpectedly exposes a standard service.

## 5. UBox P4P upstream project

Repository:

https://github.com/mahumadad/ubox-p4p

Upstream description as of 2026-09-07:

- Full reverse engineering of a UBox / UBIA smart-camera P4P protocol.
- Custom block cipher.
- KCP plus an RDT framing layer.
- ICE-style NAT traversal.
- Standalone Python client that communicates without the vendor mobile app for the basic P4P video path.

Important implementation facts from current upstream source:

### Required credentials

`p4p_stream.py` accepts:

```text
--uid
--password
--listen
--relay
-o / --output
```

It also reads:

```text
UBOX_UID
UBOX_PASSWORD
```

The upstream CLI error says the UID and device password come from the UBox app.

### Output

The P4P video demux produces raw H.265 / HEVC NAL data.

The upstream `requirements.txt` currently contains only:

```text
kcp>=0.1.6
```

### Direct mode

Command shape:

```bash
python3 p4p_stream.py \
  --uid CAMERA_UID \
  --password DEVICE_PASSWORD \
  --listen 40 \
  -o live.h265
```

Important nuance:

- In direct mode, `--listen` controls how long the handshake waits for the camera knock.
- Once a direct stream is established, the receive loop runs continuously.
- Therefore `--listen 0` is not appropriate for direct mode because the handshake loop would immediately have no waiting window.

### Relay mode

Command shape:

```bash
python3 p4p_stream.py \
  --uid CAMERA_UID \
  --password DEVICE_PASSWORD \
  --listen 0 \
  --relay \
  -o live.h265
```

Important nuance:

- In relay mode, `--listen 0` is treated as no overall end time.
- Upstream describes relay streaming as repeated fresh sessions that provide roughly one GOP at a time.
- This can produce a choppy but useful diagnostic stream.

### NAT findings

Upstream currently states:

- Direct P2P from a public-IP VPS fails for the tested symmetric-NAT camera case.
- A residential peer path works.
- The README explicitly describes running `p4p_stream.py` on a Raspberry Pi or old PC on the home LAN as the intended architecture for sustained direct video.

This is why the HAOS Raspberry Pi 4 is a promising location for the bridge.

## 6. Upstream Pi relay is a different solution

The upstream repository also has:

```text
tools/pi_relay/
```

This must not be confused with `p4p_stream.py`.

The `tools/pi_relay` architecture is:

```text
camera-side shm_stream -> raw H.264 over TCP -> Pi rtsp_relay.py -> FFmpeg -> MediaMTX
```

Upstream currently documents that this path requires camera-side work, including:

- `shm_stream` on the camera.
- Camera bootstrap.
- Encoder timeout patches.
- SD-card / camera-side binaries.
- Re-applying changes after camera reboot in the documented flow.

Earlier discussion treated the Pi relay as if it were simply the standalone P4P bridge. That was inaccurate. The clean first phase for this project should use the standalone P4P client and avoid firmware or SD-card modification.

## 7. Home Assistant environment

Target hardware:

```text
Raspberry Pi 4
Home Assistant OS
Expected architecture: aarch64
```

The user has not yet confirmed the architecture screen, so the project should check this at install/build time or clearly state that the first scaffold supports `aarch64` only.

Home Assistant's current developer docs call add-ons `Apps`.

Relevant 2026 Home Assistant facts:

- Local apps can be developed under `/addons`.
- A Git repository used as an app repository needs `repository.yaml` at its root.
- New apps should use an explicit `FROM` in the Dockerfile.
- Since Supervisor 2026.04, do not rely on an automatically provided `BUILD_FROM` default.
- `build.yaml` is no longer recommended for new projects.
- Home Assistant base images include `bashio`.
- `host_network: true` is available and is appropriate to investigate because P4P depends heavily on UDP behavior and NAT traversal.

## 8. AlexxIT WebRTC / go2rtc

User specifically asked whether this project could help:

https://github.com/AlexxIT/WebRTC

Conclusion:

- Yes, as the viewing/output layer.
- No, not as the missing UBox P4P protocol implementation.

Current AlexxIT WebRTC documentation says:

- It uses go2rtc.
- It can consume RTSP and many other protocols.
- Basic users can let the integration download and run go2rtc automatically.
- Advanced users can run the dedicated go2rtc HA app.

Current go2rtc protocol tables include RTSP, HTTP, ONVIF, DVRIP, HomeKit, Tapo, Tuya, and other inputs, but not a native `ubox://` or UBIA P4P input.

Therefore the desired architecture is:

```text
Q5 P4P -> custom HAOS bridge -> RTSP -> go2rtc -> WebRTC / HA dashboard
```

### Codec concern

go2rtc accepts HEVC / H.265 on RTSP input, but browser WebRTC video output is H.264.

Plan:

1. First prove raw H.265 can be received and re-published as RTSP.
2. Test the RTSP URL in VLC.
3. Then connect go2rtc.
4. If browser playback fails because of HEVC, configure transcoding to H.264.
5. Prefer Raspberry Pi hardware acceleration if practical. Do not assume software transcoding of the main 2304x1296 stream will be cheap on a Pi 4.

## 9. Proposed HAOS bridge design

First-phase architecture:

```text
Q5 camera
   |
   | UBIA / UBox P4P over UDP
   v
p4p_stream.py
   |
   | raw HEVC through a FIFO
   v
FFmpeg
   |
   | RTSP publish, video copy only
   v
MediaMTX
   |
   | host RTSP port 8557
   v
go2rtc / VLC / Home Assistant
```

Why MediaMTX:

- Small dedicated RTSP server.
- FFmpeg can publish into it.
- Stable endpoint for go2rtc and VLC.

Why port `8557`:

- go2rtc commonly uses `8554`.
- Both apps may run with host networking.
- Using `8554` in both would create a port conflict.

## 10. Original scaffold behavior, superseded

Recorded for history. The first scaffold handed over with this file:

- Targeted `aarch64`.
- Used `ghcr.io/home-assistant/base:latest` explicitly.
- Installed Python, pip, FFmpeg, git, curl, and build packages.
- Created a Python virtual environment.
- Cloned `mahumadad/ubox-p4p` during the image build.
- Installed upstream Python requirements.
- Downloaded MediaMTX ARM64.
- Read the camera settings with `bashio`.
- Created a named FIFO.
- Started FFmpeg first as the FIFO reader.
- Started `p4p_stream.py` as the FIFO writer.
- Published the resulting HEVC into MediaMTX over localhost RTSP.
- Retried after a failed session.

**This is no longer what the repository contains.** The implementation was rebuilt as a
Python supervisor. See `docs/ARCHITECTURE.md` for what exists now. The differences that
matter when reading older notes:

- The base image is pinned by digest, not `latest`.
- Options are read and validated in Python from `/data/options.json`, not with `bashio`.
- The named FIFO was replaced by an anonymous pipe the supervisor owns, because a FIFO
  makes startup order load-bearing and a dead reader wedges the writer.
- `p4p_stream.py` is not invoked as a CLI. `worker.py` imports it and replaces its `open`
  so video lands on a pipe while every diagnostic print goes to stderr.
- The upstream commit, the `kcp` source distribution, and the MediaMTX release are all
  hash-pinned, and the build verifies the `kcp` extension, the FFmpeg HEVC demuxer, the
  FFmpeg RTSP muxer, and MediaMTX before finishing.

## 11. The stall problem, and how it was solved

Direct `p4p_stream.py` has no external idle timeout once the stream is established. If the
camera sleeps while the Python process stays alive and simply receives no more frames, a
naive wrapper waits forever.

The original scaffold used a configurable `direct_restart_seconds` and ran direct mode
under a blunt overall timeout, which also killed healthy long-lived streams.

That option no longer exists. The supervisor now watches three independent clocks and
restarts only the streaming session:

- `last_video`, advanced by bytes read from the worker, catches camera sleep.
- `last_forwarded`, advanced by bytes written to FFmpeg, catches a wedged FFmpeg.
- `last_published`, advanced by FFmpeg's own frame progress, catches a stream that flows
  but never muxes.

`startup_timeout_seconds` applies until the first published frame and `idle_timeout_seconds`
after it, so a slow handshake is never mistaken for a stall and a healthy stream is never
restarted on age alone. The supervisor also forwards upstream's own packet, byte, and frame
counters, which is what separates "P4P connected but no video" from "nothing arrived".

## 12. Camera sleeping and wake behavior

The camera model includes `pir`, so sleep behavior may be the largest practical problem.

Upstream UBox research documents several power-save and wake limitations on tested cameras. Do not assume that successful authentication automatically means the camera can be kept continuously awake.

Desired app states eventually:

```text
WAITING_FOR_CAMERA
HANDSHAKING
STREAMING
STALLED
RETRYING
```

The app should log these states clearly.

## 13. Credentials and secrets

Never put any of the following in source control:

- device password
- mobile app account password
- cloud token
- captured authentication packets containing secrets

The camera UID is already part of the working project context and is stored as the default test UID, but a public release should consider replacing it with a blank example value.

The Home Assistant app schema should use the `password` input type for `camera_password` so the UI treats it as a password field.

## 14. MediaMTX notes

Latest release observed during handoff:

```text
v1.21.0
```

Current configuration still supports:

```yaml
source: publisher
paths:
  all_others:
```

The scaffold uses a generated path named from the configured `stream_name`.

The app should only enable RTSP initially. HLS and WebRTC inside MediaMTX are unnecessary because go2rtc / AlexxIT will handle the Home Assistant frontend path.

## 15. Initial acceptance criteria

MVP success means all of these are true:

1. The app builds on HAOS Raspberry Pi 4 aarch64.
2. The app starts without a container crash.
3. The configured UID and password reach `p4p_stream.py` without appearing in logs.
4. The P4P client logs a successful camera handshake.
5. HEVC bytes are produced.
6. FFmpeg accepts the HEVC input.
7. MediaMTX shows the configured path as published.
8. VLC on another LAN device opens `rtsp://HA_IP:8557/q5`.
9. App restart recovers the stream.
10. Camera sleep results in retry behavior instead of a permanently wedged container.

Second-phase success:

1. go2rtc reads the RTSP stream.
2. Home Assistant displays live video.
3. If required, H.265 is transcoded to H.264.
4. CPU usage is acceptable on the Raspberry Pi 4.

## 16. Questions still open

- Which exact mobile app is paired with this camera, i-Cam+, UBox, or another branded app?
- What is the camera device password?
- Is the device password different from the user's cloud/app password?
- Does the camera wake from the standalone P4P knock while fully asleep?
- Does the Q5 provide H.265 only in this mode?
- What frame rate does this exact Q5 produce?
- Can direct P2P work from an HAOS app container with `host_network: true`?
- Is a host network capability or additional Linux capability needed beyond the normal container privileges?
- Does MediaMTX `v1.21.0` run cleanly in the Home Assistant Alpine base image on ARM64?
- Does the Python `kcp` package compile reliably in the HAOS build environment?
- Can Raspberry Pi 4 hardware transcoding be used cleanly from a Home Assistant app if H.264 is required?

## 17. Do not do yet

Until the pure P4P test is exhausted, avoid:

- camera firmware flashing
- camera binary patching
- enabling Telnet solely for this project
- SD-card `shm_stream` deployment
- camera encoder patches

Those may become a later fallback based on the upstream `tools/pi_relay` work, but they substantially increase risk and complexity.

## 18. Useful URLs

```text
https://github.com/mahumadad/ubox-p4p
https://github.com/AlexxIT/WebRTC
https://github.com/AlexxIT/go2rtc
https://github.com/AlexxIT/hassio-addons
https://github.com/bluenviron/mediamtx
https://developers.home-assistant.io/docs/apps/
https://developers.home-assistant.io/docs/apps/tutorial/
https://developers.home-assistant.io/docs/apps/configuration/
https://developers.home-assistant.io/docs/apps/repository/
```
