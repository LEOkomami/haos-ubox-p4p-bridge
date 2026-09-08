# Troubleshooting

User-facing symptoms are in `ubox_p4p_bridge/DOCS.md`. This file covers build and
development failures.

## Reading the log

One state per line, `state=NAME`, with a reason after a colon on entry to `STALLED` and
`RETRYING`. Every ten seconds while a session runs:

```text
video: received_bytes=188228 published_frames=42 last_publish_age=0.3
```

`received_bytes` counts bytes read off the P4P worker; `published_frames` comes from
FFmpeg's own progress output. Separately, upstream's counters appear as:

```text
P4P: packets=1200 hevc_bytes=345678 hevc_frames=910
```

Those numbers localize a failure quickly:

| Pattern | Meaning |
| --- | --- |
| no `packets` at all | nothing arrived. Camera asleep, wrong UID, or NAT traversal failed |
| `packets` rising, `hevc_frames` at zero | P4P connected, camera sent no video. Suspect the device password or the camera's stream settings |
| `hevc_frames` rising, `received_bytes` flat | the worker is not reaching the pipe. A bridge bug; check the sink |
| `received_bytes` rising, `published_frames` flat | FFmpeg is not muxing. Usually a bitstream it will not accept |
| both rising, VLC shows nothing | a reader-side problem. Auth, transport, or codec support |

## Build failures

**The `BUILD_ARCH` assertion fails.** Building for the wrong architecture. This app is
`aarch64` only; adding `amd64` would need its own MediaMTX asset and hash.

**`kcp` fails to compile.** The build stage needs `build-base` and `python3-dev`, and the
package must build from source because there is no musl `aarch64` wheel. Confirm
`--no-binary=kcp` is still present before changing anything else.

**The MediaMTX checksum check fails.** The pin is stale or the release was re-uploaded.
Check the real digest in the release data and update `MEDIAMTX_VERSION` and
`MEDIAMTX_SHA256` together.

**The upstream revision assertion fails.** The commit was rewritten or force-pushed. Read
the current `p4p_stream.py` before repinning. `worker.py` depends on `run_stream` and
`run_relay_stream` keeping their positional signatures and on output still being opened
through an `open(path, "wb")` call. `upstream_log` depends on the exact milestone and
counter strings, which are tabulated in `docs/RESEARCH_NOTES.md`.

**The FFmpeg HEVC demuxer check fails.** The base image's FFmpeg build changed. Without
the HEVC demuxer the whole approach fails, so the build should stop here.

## Runtime failures

**The app exits immediately with an invalid options message.** Validation runs before
anything else and deliberately does not echo the offending value. The usual causes are a
UID that is not exactly 20 letters and digits, and `startup_timeout_seconds` not exceeding
`handshake_seconds` by at least 45.

**`MediaMTX exited`.** Intentional: the app stops rather than run without an RTSP server.
Enable the Supervisor Watchdog toggle so the app restarts. The common cause is a port
conflict.

**Nothing recovers after many retries.** Classify the failure before changing timeouts.
Relay mode reaching frames means the credentials and protocol are fine and the problem is
direct P2P traversal. Relay failing too points at the UID or the device password.

**Playback runs fast or slow.** `input_fps` does not match the camera. Raw HEVC carries no
timestamps, so the cadence is generated, not detected.

## Development notes

Run the media test with real binaries before trusting any change to the pipeline. The
default skip hides the only test that exercises FFmpeg and MediaMTX for real, so a green
run without those variables set proves much less than it appears to.

`os.killpg` and `start_new_session` are POSIX-only. On Windows the supervisor falls back
to `terminate`, which is enough for the tests but is not the production path.
