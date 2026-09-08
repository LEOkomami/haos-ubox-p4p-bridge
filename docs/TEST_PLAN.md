# Test plan

This file lists what must be true. For the step-by-step procedure, including
proving the protocol on a laptop before building anything, see
[TESTING.md](TESTING.md).

## Automated

```bash
python tests/run_tests.py
```

23 tests. The media test is skipped unless real binaries are supplied:

```bash
BRIDGE_TEST_FFMPEG=/path/to/ffmpeg BRIDGE_TEST_MEDIAMTX=/path/to/mediamtx python tests/run_tests.py
```

Nothing in the suite contacts a camera, the P4P masters, or any cloud service. The media
test synthesizes HEVC with libx265 and drives the real supervisor against real MediaMTX
and FFmpeg, covering: reaching `STREAMING`, decoding a frame back off the RTSP URL,
rejecting a wrong reader password, recovering from a camera stall, recovering from an
FFmpeg kill, exiting on MediaMTX death, and keeping passwords out of the status file.

Coverage by area:

| Area | Tests |
| --- | --- |
| Option validation, injection, type confusion | `test_reject_invalid_and_injected_options` |
| HA metadata and translations stay in sync | `test_defaults_match_ha_metadata`, `test_translations_cover_every_option_exactly` |
| Publish restricted to loopback | `test_publish_permission_is_loopback_only` |
| Startup versus idle deadlines | `WatchdogTests` |
| Secret redaction and environment isolation | `PrivacyAndDiscoveryTests` |
| No raw upstream text forwarded | `test_upstream_raw_diagnostics_are_not_forwarded`, `test_counter_lookalike_lines_are_not_forwarded` |
| Byte-exact video under short writes | `test_partial_pipe_writes_preserve_every_byte`, `test_video_sink_completes_short_writes_upstream_ignores` |
| Discovery never auto-selects among several | `test_multiple_discovered_cameras_are_never_auto_selected` |

## Manual, on the Raspberry Pi

Automated tests cannot cover the build or the camera. Work through these in order and
record the outcome in `docs/RESEARCH_NOTES.md`.

### 1. Build

- [ ] The image builds on the Pi for `aarch64`.
- [ ] `kcp` compiles against musl and the extension import check succeeds.
- [ ] The MediaMTX hash check passes and the version check prints 1.21.0.
- [ ] The upstream commit assertion passes.

A hash mismatch means upstream re-tagged or the pin is stale, not that the download broke.
Re-verify against the release data before changing a pin.

### 2. Start with no camera

- [ ] The app starts, reaches `STARTING` then `WAITING_FOR_CAMERA` or
      `NEEDS_CONFIGURATION`, and does not crash.
- [ ] The log names the RTSP URL.
- [ ] No password appears anywhere in the log.
- [ ] Stopping the app leaves no MediaMTX, FFmpeg, or Python process behind.

### 3. Port conflict

- [ ] With go2rtc on 8554, the default 8557 still starts.
- [ ] Setting `rtsp_port` to a port already in use exits with a clear MediaMTX error rather
      than attaching to the other server.

### 4. Direct mode against the camera

Set the UID and the real device password, `mode: direct`, `handshake_seconds: 40`.

- [ ] `P4P: querying masters`
- [ ] `P4P: requesting camera wake and relay login`
- [ ] `P4P: received camera knock`
- [ ] `P4P: starting KCP session`
- [ ] `P4P: packets=` counters advance
- [ ] `hevc_frames` advances, not just `packets`
- [ ] `state=STREAMING`
- [ ] `rtsp://HA_IP:8557/q5` opens in VLC over TCP
- [ ] Playback speed looks right; if not, correct `input_fps`

### 5. Recovery

- [ ] Camera asleep leads to `STALLED` then `RETRYING`, never a wedged container.
- [ ] The stream returns on its own when the camera wakes.
- [ ] Restarting the app restores the stream.
- [ ] Rebooting Home Assistant restores the stream, since `boot: auto`.

### 6. Relay diagnosis, only if direct fails

- [ ] `mode: relay` logs relay cycle counters.
- [ ] Frames arrive, confirming credentials and protocol even if playback is choppy.

Relay working while direct does not indicates NAT traversal, not credentials.

### 7. Phase 2

- [ ] go2rtc reads the RTSP URL.
- [ ] A Home Assistant dashboard card shows video.
- [ ] If the browser shows nothing, transcoding to H.264 in go2rtc fixes it.
- [ ] Pi 4 CPU load with transcoding is acceptable, or hardware encoding is used.
