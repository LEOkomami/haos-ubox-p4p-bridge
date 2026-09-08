# Codex Build Brief

## Mission

Turn this handoff into a reliable Home Assistant OS app for the target `Q5-wifi(pir)` camera.

The first milestone is not polished Home Assistant UI integration. The first milestone is proving this exact camera can produce a stable RTSP stream through the standalone UBox P4P client while running inside HAOS on a Raspberry Pi 4.

## Read first

1. `PROJECT_MEMORY.md`
2. `README.md`
3. `docs/RESEARCH_NOTES.md`
4. Upstream `mahumadad/ubox-p4p` README and current `p4p_stream.py`

Do not assume the upstream interface is frozen. Check the current CLI before pinning a release or commit.

## Constraints

- Target: Home Assistant OS on Raspberry Pi 4.
- Initial architecture: `aarch64` only.
- Use the Home Assistant app model, formerly add-ons.
- No device password in Git.
- No vendor APK, `.so`, firmware dump, or copyrighted binary in this repository.
- No camera firmware modification in phase 1.
- The camera may sleep because it is a PIR model.
- Avoid RTSP port `8554` because go2rtc may already use it.
- Default bridge RTSP port: `8557`.

## Phase 1 tasks

### A. Validate the build

- Make sure the Dockerfile builds for `linux/arm64`.
- Confirm `kcp>=0.1.6` installs on the selected base image.
- Confirm FFmpeg exists and supports HEVC demux plus RTSP publish.
- Confirm the pinned MediaMTX version has a Linux ARM64 asset.
- Prefer pinning the upstream UBox P4P source to a known commit after the first successful test.

### B. Validate Home Assistant metadata

- Validate `repository.yaml`.
- Validate `ubox_p4p_bridge/config.yaml` against current HA Supervisor schema.
- Keep `host_network: true` initially.
- Keep the password field masked with schema type `password`.
- Add translations only if they validate cleanly.

### C. Improve runtime supervision

The current `run.sh` is intentionally simple.

Improve it so these processes are supervised:

```text
MediaMTX
FFmpeg
p4p_stream.py
```

Required behavior:

- If MediaMTX dies, stop the app.
- If FFmpeg dies, restart the streaming pipeline.
- If P4P handshake fails, wait and retry.
- If direct streaming stalls, detect lack of HEVC output and restart rather than waiting forever.
- Redact the device password from all logs.
- Log state transitions clearly.

Prefer an explicit state machine or a small Python supervisor if Bash becomes fragile.

### D. First camera test

Use:

```text
UID: XXXXXXXXXXXXXXXXXXXX
Mode: direct
Handshake wait: 40 seconds
```

The real device password must be entered through the HA app configuration and must never be committed.

Expected direct-mode evidence:

- query to P4P masters
- relay login / wake sequence
- camera knock
- KCP traffic
- HEVC byte/frame counters

Then validate:

```text
rtsp://HA_IP:8557/q5
```

with VLC.

### E. Diagnostic relay mode

If direct P2P cannot establish, expose a relay option.

Use upstream relay mode as a diagnostic, not as proof of a production-quality stream. The upstream project describes the relay path as short GOP cycles and choppy.

## Phase 2 tasks

After VLC works:

- Integrate with AlexxIT go2rtc / WebRTC.
- Determine whether HEVC can be viewed directly in the intended HA clients.
- If not, add an optional H.264 output path.
- Investigate Raspberry Pi 4 V4L2 hardware transcoding instead of defaulting to CPU-only x264.
- Add a documented go2rtc configuration example.

## Phase 3 tasks

Only after the stream is stable:

- Add a small status web page or HA ingress page.
- Show states: waiting, handshake, streaming, stalled, retrying.
- Show received bytes, frame count, uptime, last frame time.
- Add a Test connection button if practical.
- Add multi-camera support only after one Q5 works reliably.

## Do not mix in the upstream camera-side pi_relay yet

Upstream `tools/pi_relay` is a separate camera modification path based on camera-side `shm_stream` and H.264 over TCP. It may be a powerful fallback later, but it is not the same thing as wrapping `p4p_stream.py`.

## Definition of done for first real release

- Installs from a GitHub HA app repository.
- Builds on Raspberry Pi 4 aarch64.
- Stores credentials only in HA app options.
- Reconnects after a sleeping or unavailable camera.
- Provides a stable RTSP URL.
- Clear README setup instructions.
- Clear warning that this is independent interoperability work and not affiliated with UBox / UBIA.
- No copied proprietary vendor binaries.
