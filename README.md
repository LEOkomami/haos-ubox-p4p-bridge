# HAOS UBox P4P Bridge

A Home Assistant OS app, formerly called an add-on, that publishes a UBox / UBIA / i-Cam+
style camera as a standard RTSP stream.

These cameras expose no ordinary RTSP or ONVIF endpoint. They speak a proprietary P4P
protocol over UDP: a custom block cipher, KCP with an RDT framing layer, ICE-style NAT
traversal, and raw H.265. This app wraps the
[mahumadad/ubox-p4p](https://github.com/mahumadad/ubox-p4p) reverse engineering client and
turns its output into a URL that go2rtc, VLC, or Home Assistant can read.

Independent interoperability work. Not affiliated with any camera vendor. See
[NOTICE.md](NOTICE.md).

## Status

**Experimental. The camera side is unproven.**

| Part | State |
| --- | --- |
| HEVC to RTSP pipeline | Verified end to end against synthetic HEVC with real FFmpeg and MediaMTX |
| Supervision, stall recovery, secret handling | Covered by 23 automated tests |
| Build pins | Upstream commit, `kcp` hash, and MediaMTX hash verified against release data |
| `aarch64` container build on a Pi 4 | Not yet run |
| P4P handshake against a real `Q5-wifi(pir)` | **Not yet attempted** |

Everything below the pipe is proven. Everything above it is a hypothesis, including
whether this camera model speaks the protocol at all. Expect to iterate.

## Target camera

From the camera's Device info screen. Device identifiers are redacted in this public repository. Substitute your own.

| Field | Value |
| --- | --- |
| Model | `Q5-wifi(pir)` |
| Vendor | `ZGWL` |
| Device UID | `XXXXXXXXXXXXXXXXXXXX` |
| Firmware | `271.0.7.99` |
| WiFi version | `63.0.2.9` |
| LAN IP | `192.168.0.NNN` |
| MAC | `xx:xx:xx:xx:xx:xx` |

The device password is deliberately not in this repository and must be entered only in the
app's Configuration tab.

## Pipeline

```text
Q5-wifi(pir) camera
      |  UBIA / UBox P4P over UDP
      v
p4p_stream.py, wrapped by worker.py
      |  raw H.265 on a pipe
      v
FFmpeg, stream copy with generated timestamps
      |  RTSP publish to loopback
      v
MediaMTX inside this app
      |  host port 8557, TCP
      v
go2rtc / AlexxIT WebRTC / VLC / Home Assistant
```

Result:

```text
rtsp://HOME_ASSISTANT_IP:8557/q5
```

Port 8557 rather than 8554, because go2rtc commonly holds 8554 and both run with host
networking.

## Requirements

- Home Assistant OS on `aarch64`. Raspberry Pi 4 is the target, and this is the only
  architecture the image builds for.
- The camera's 20-character UID and its **device** password, which may differ from the
  mobile app account password.
- The camera on the same LAN as Home Assistant. Upstream found direct P2P failing from a
  public-IP VPS against a symmetric-NAT camera while a residential peer worked, which is
  the whole reason this belongs on the Pi.

## Install

Push this repository to GitHub, then in Home Assistant open the app or add-on store, use
the overflow menu, choose Repositories, and add the repository URL. `repository.yaml` at
the root is what makes it an app repository.

For local development instead, copy `ubox_p4p_bridge/` to `/addons/ubox_p4p_bridge/` on
the Home Assistant host and use Check for updates. It appears under Local apps.

Then:

1. Set `camera_password`. Leave `camera_uid` blank to auto-discover a single LAN camera, or
   paste the UID.
2. Start the app and watch the Log tab.
3. When the state reaches `STREAMING`, open the RTSP URL in VLC, forcing TCP.
4. Enable the **Watchdog** toggle on the Info tab. The app exits deliberately if MediaMTX
   dies, and without the Watchdog nothing restarts it.

Full option reference, states, and troubleshooting: [`ubox_p4p_bridge/DOCS.md`](ubox_p4p_bridge/DOCS.md).

Testing against real hardware, starting with a laptop test that needs no container:
[docs/TESTING.md](docs/TESTING.md).

## Test order

Prove one layer at a time, and do not skip ahead:

1. **Direct mode first.** The Pi sits on a residential LAN, which matches the path
   upstream documents as suitable for sustained P2P.
2. **Watch the counters.** `P4P: packets=` rising with `hevc_frames` stuck at zero means
   P4P connected but the camera sent no video, which points at the device password rather
   than the network.
3. **VLC before anything else.** If VLC cannot play it, go2rtc will not save you.
4. **Then go2rtc**, and only then a dashboard card.
5. **Transcode last.** If the browser shows nothing, it is the HEVC to H.264 gap; fix it in
   go2rtc, not here.
6. **Relay only to diagnose.** If direct never establishes, `mode: relay` answers whether
   the credentials and protocol work at all. Upstream re-establishes a session per cycle
   and gets roughly one GOP each time, so it is choppy by design and is not a feed.

## Two upstream approaches, which are not the same thing

An earlier version of this investigation conflated them. They are unrelated:

1. **`p4p_stream.py`**, which this app uses. A standalone P4P client. Needs only the UID
   and device password, touches nothing on the camera, and emits raw H.265.
2. **`tools/pi_relay/`**, which this app does not use. A different architecture, pushing
   raw H.264 over TCP from a camera-side `shm_stream`. Upstream documents camera bootstrap,
   SD-card binaries, and encoder patches that must be reapplied after every reboot.

Phase 1 modifies nothing on the camera: no firmware flashing, no binary patching, no
telnet, no SD-card payload. Those remain a possible later fallback, at substantially
higher risk.

## Layout

```text
.
├── README.md                  this file
├── PROJECT_MEMORY.md          original investigation context
├── CODEX_BRIEF.md             build brief and phase plan
├── NOTICE.md                  non-affiliation and third-party components
├── LICENSE                    MIT
├── repository.yaml            marks this as an HA app repository
├── docs/
│   ├── ARCHITECTURE.md        pipeline, health model, design decisions
│   ├── RESEARCH_NOTES.md      verified upstream facts, pins, open questions
│   ├── TESTING.md             step-by-step procedure for testing against real hardware
│   ├── TEST_PLAN.md           automated coverage and the manual Pi checklist
│   ├── TROUBLESHOOTING.md     build and development failures
│   └── SECURITY.md            secret handling, exposure, supply chain
├── tests/
│   ├── run_tests.py
│   ├── test_bridge.py         unit and validation tests
│   └── test_end_to_end.py     real FFmpeg and MediaMTX, synthetic camera
└── ubox_p4p_bridge/
    ├── config.yaml            HA app metadata and option schema
    ├── Dockerfile             aarch64, fully pinned
    ├── requirements.txt       kcp, hash-pinned
    ├── run.sh
    ├── DOCS.md                the app's Documentation tab
    ├── CHANGELOG.md
    ├── translations/en.yaml   option names and descriptions in the UI
    └── bridge/
        ├── supervisor.py      state machine, process supervision, watchdogs
        ├── settings.py        option validation, MediaMTX and FFmpeg config
        ├── discovery.py       bounded LAN UID discovery
        └── worker.py          adapter around the pinned upstream client
```

## Development

```bash
python tests/run_tests.py
```

The end-to-end test skips unless you supply real binaries, and it is the only test that
exercises FFmpeg and MediaMTX for real:

```bash
BRIDGE_TEST_FFMPEG=/path/to/ffmpeg BRIDGE_TEST_MEDIAMTX=/path/to/mediamtx python tests/run_tests.py
```

It builds HEVC with libx265, runs the real supervisor, reads a frame back off RTSP, and
exercises stall recovery, an FFmpeg kill, and MediaMTX death. Nothing in the suite contacts
a camera or any cloud service.

Before changing the upstream pin, read the current `p4p_stream.py`. `worker.py` depends on
`run_stream` and `run_relay_stream` keeping their positional signatures and on output being
opened through an `open(path, "wb")` call, and the log translation depends on exact
upstream strings. Those dependencies are tabulated in
[docs/RESEARCH_NOTES.md](docs/RESEARCH_NOTES.md).

## Highest-risk unknowns

In roughly the order they will bite:

1. Whether this exact Q5 firmware speaks the protocol upstream implemented.
2. Whether the device password can be recovered from the paired mobile app.
3. Whether a PIR camera can be woken and kept awake by a standalone P4P knock.
4. Whether direct P2P works from an HAOS container with `host_network: true`.
5. Whether `kcp` compiles cleanly against musl on `aarch64` in the HAOS build.
6. Whether the real camera's HEVC bitstream survives a stream copy into RTSP.
7. Whether the Pi 4 can transcode to H.264 if the browser needs it.

## References

- [mahumadad/ubox-p4p](https://github.com/mahumadad/ubox-p4p)
- [AlexxIT/WebRTC](https://github.com/AlexxIT/WebRTC) and [AlexxIT/go2rtc](https://github.com/AlexxIT/go2rtc)
- [MediaMTX](https://github.com/bluenviron/mediamtx)
- [Home Assistant app development](https://developers.home-assistant.io/docs/apps/)
- [Home Assistant app repositories](https://developers.home-assistant.io/docs/apps/repository/)
