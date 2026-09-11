# Changelog

## 0.1.3

Auto-discovery only. **No change to the P4P handshake, streaming, or anything the add-on
does when `camera_uid` is set explicitly.**

- LAN discovery now locates the UID field itself rather than trusting upstream's reader.
  Upstream reads offset 20 and accepts any 10+ alphanumeric run; on the tested Q5 firmware
  the UID sits at offset 16, so upstream reported the last 16 characters plus a stray byte,
  which `auto_discover` then rejected as malformed. The bridge scans candidate offsets and
  returns a UID only when exactly one 20-character field qualifies, falling back to the
  upstream value when the raw payload is unavailable.
- Still recommended to set `camera_uid` explicitly and leave `auto_discover` off; discovery
  cannot wake a sleeping camera, so it only ever works when the camera is already awake.

## 0.1.2

The Pi no longer builds anything.

- `image:` added to `config.yaml`. The Supervisor now pulls a prebuilt aarch64 image from
  `ghcr.io/leokomami/ubox-p4p-bridge-aarch64` instead of building the Dockerfile on the
  host. The kcp compile (Cython plus `gcc -O3`) runs on GitHub's build servers.
- GitHub Actions workflow `build-image.yml` builds and publishes on every change under
  `ubox_p4p_bridge/`, refuses to overwrite an already-published version, and verifies the
  pushed manifest. Build only; tests stay local.
- A test keeps `config.yaml` `version` and the Dockerfile `BUILD_VERSION` in sync, because
  the Supervisor pulls the tag named by `version` and CI tags with `BUILD_VERSION`.
- Fixed a false build failure: the FFmpeg capability checks used `grep -q`, which exits on
  first match and SIGPIPEs ffmpeg; under the base image's `pipefail` shell that returned
  exit 141 after everything had actually passed. The same line would have failed an
  on-device build on the Pi, after the compile had already run.

## 0.1.1

Safety release. No functional changes to the stream.

- `boot: manual` instead of `boot: auto`. An experimental app whose build runs a compiler
  on the host must never restart itself unattended, or a bad boot becomes a loop the user
  cannot break into. A test now pins this.
- Documented that installing from source compiles `kcp` with Cython and `gcc -O3` on the
  Pi itself, because PyPI publishes no aarch64 Linux wheel. Do not install from source on
  a Pi that also runs your Home Assistant; use the prebuilt image once it exists.
- Corrected `docs/SECURITY.md`: `--require-hashes` does not cover PEP 518 build
  dependencies, so kcp's build chain (poetry-core, cython, entrypoint, setuptools) resolves
  unpinned during a source build.

## 0.1.0

First experimental release. Not yet validated against a real camera.

- Bridges UBox / UBIA P4P video to RTSP: `p4p_stream.py` to FFmpeg to MediaMTX.
- Publishes `rtsp://HOME_ASSISTANT_IP:8557/q5` over TCP, using port 8557 to avoid go2rtc.
- Supervises MediaMTX, FFmpeg, and the P4P worker as a state machine, and reports
  `STARTING`, `DISCOVERING`, `NEEDS_CONFIGURATION`, `WAITING_FOR_CAMERA`, `HANDSHAKING`,
  `STREAMING`, `STALLED`, and `RETRYING`.
- Restarts the streaming session on a stall, and exits when MediaMTX itself dies so the
  Supervisor Watchdog can restart the app.
- Separate startup and idle deadlines, so a slow first handshake is not mistaken for a
  stall.
- Optional LAN discovery of a single camera UID. Never auto-selects when several reply.
- Validates every option before starting a subprocess or touching the network.
- Redacts the device password from logs, keeps the Supervisor token out of child
  environments, and forwards only recognized upstream milestones and numeric counters
  rather than raw P4P diagnostics.
- Publishing to the RTSP path is restricted to loopback. Unauthenticated reads are
  restricted to private address ranges unless `rtsp_password` is set.
- Pins the upstream revision, the `kcp` source distribution hash, and the MediaMTX release
  hash, and verifies the FFmpeg HEVC demuxer and RTSP muxer at build time.
