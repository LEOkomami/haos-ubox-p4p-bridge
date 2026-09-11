# Research notes

Findings verified against source and release data, with dates. `PROJECT_MEMORY.md` holds
the original investigation narrative; this file records what was checked and how.

## Target camera, from the Device info screen

Device identifiers are redacted in this public repository. Substitute your own.

```text
ID:               XXXXXXXXXXXXXXXXXXXX
Model:            Q5-wifi(pir)
Firmware version: 271.0.7.99
Wifi Version:     63.0.2.9
Vendor:           ZGWL
IP:               192.168.0.NNN
MAC:              xx:xx:xx:xx:xx:xx
```

The `pir` suffix implies a motion-triggered, power-saving design, so aggressive sleep is
expected and is treated as normal operation rather than an error.

## Still unverified

No P4P handshake has been attempted against this camera. All of these remain open:

- Whether this exact Q5 firmware speaks the protocol upstream implemented.
- Whether the device password can be obtained from the paired mobile app.
- Whether the camera wakes from a standalone P4P knock while fully asleep.
- Whether direct P2P works from an HAOS container with `host_network: true`.
- The camera's actual frame rate, which `input_fps` must match.
- Whether this model offers anything other than HEVC.

The paired mobile app is confirmed as **i-Cam+** (2026-09-11), which places the camera in
the UBox / UBIA family this design assumes. Protocol compatibility itself is still
unproven until a P4P handshake succeeds.

Upstream's `lan_tools.py` documents that the camera ignores unicast LAN search; discovery
must be broadcast to `x.x.x.255:32762`. The first real attempt on 2026-09-11 was unicast to
the camera IP and therefore uninformative. On Windows the reply is also dropped by the
firewall unless inbound UDP is allowed for the sending `python.exe`, because it arrives
from a different address than the broadcast target.

## Upstream, verified 2026-09-08 against commit 6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8

Committed 2026-07-22. The pin in the Dockerfile matches the recorded commit data.

Entry points used by `worker.py`:

```python
run_stream(uid=DEFAULT_UID, password=DEFAULT_PASSWORD, listen_sec=40, output=None)
run_relay_stream(uid=DEFAULT_UID, password=DEFAULT_PASSWORD, listen_sec=40, output=None)
```

Both are called positionally, and both open their output with `open(output, "wb")`, which
is the hook `worker.py` replaces. Direct mode writes with a plain write call; relay mode
also calls flush. Neither checks the return value of write, so the sink must complete
short writes itself.

`listen_sec` differs by mode, which is easy to get backwards:

- Direct: how long the handshake waits for the camera knock. The receive loop afterwards
  is unbounded, so `0` is wrong here.
- Relay: an overall end time, where `0` means run forever. The bridge passes `0`.

Upstream requirements are only `kcp>=0.1.6`. The bridge pins `kcp==0.1.6` with a hash.

Milestone strings that `upstream_log` recognizes, all confirmed present:

| Source line | String |
| --- | --- |
| `p4p_stream.py:166` | `[handshake] queryreq` |
| `p4p_stream.py:182` | `[handshake] knock +` |
| `p4p_stream.py:214` | `[handshake] CAMERA KNOCK` |
| `p4p_stream.py:242` | `[stream] KCP conv=` |
| `p4p_stream.py:233` | `[stream] handshake failed` |
| `p4p_stream.py:382` | `[stream] receiving video` |
| `p4p_stream.py:692` | `[relay] streaming` |

Counter lines, matched by anchored patterns and re-emitted as numbers only:

| Source line | Shape | Cadence |
| --- | --- | --- |
| `p4p_stream.py:462` | `[stream] pkts=N hevc_bytes=N frames=N` | every 5 s |
| `p4p_stream.py:699` | `[relay] cycle N: +N frames (total N frames, N B)` | per cycle |

The frame counter counts RDT video units, not decoded pictures, so it is a liveness signal
rather than a true frame count. It is still the fastest way to separate "connected but no
video" from "nothing arrived".

Upstream prints high-volume per-packet debug at `p4p_stream.py:419` and `:424`. Those are
drained and discarded; forwarding them would flood the Home Assistant log.

Video is raw HEVC with no container and no timestamps, which is why FFmpeg has to generate
them from `input_fps`.

## NAT findings

Upstream reports direct P2P failing from a public-IP VPS against a symmetric-NAT camera,
while a residential peer works, and documents running the client on a Raspberry Pi on the
home LAN as the intended architecture. That is exactly the HAOS Pi 4 position, which is
the main reason to expect direct mode to work here.

Relay mode re-establishes a session per cycle and gets roughly one GOP each time, so it is
a diagnostic, not a feed.

## Pins, verified 2026-09-08

| Dependency | Pin | Verified against |
| --- | --- | --- |
| `mahumadad/ubox-p4p` | `6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8` | recorded commit data |
| `kcp` 0.1.6 sdist | `1e3632509119bd6a24599ee043e21ef6842675413a41720c526d14896357afc4` | PyPI release data and the local archive |
| MediaMTX 1.21.0 `linux_arm64` | `a8113b5928ba1a934b81557b61b8a07954b76921a4b567d54c7f086f8b39d9a2` | GitHub release asset digest |

There is no musl `aarch64` wheel for `kcp`, so it builds from source and the Dockerfile
uses `--no-binary=kcp`.

MediaMTX 1.21.0 still accepts `source: publisher` per path. The bridge names one explicit
path from `stream_name` rather than using `all_others`, so an unexpected path cannot be
published.

## Home Assistant, as of 2026-09-08

- The developer documentation calls add-ons Apps. The UI may still say Add-ons.
- A Git repository used as an app repository needs `repository.yaml` at its root.
- Supervisor 2026.04 and later no longer inject a default `BUILD_FROM`, so the Dockerfile
  needs an explicit `FROM`. This one pins a digest.
- `build.yaml` is no longer recommended for new apps.
- `host_network: true` is available and is necessary here for UDP and NAT traversal.
- The Supervisor Watchdog is a per-app toggle in the UI. Nothing restarts a deliberately
  exiting app without it, which is why `DOCS.md` asks the user to enable it.

## go2rtc and AlexxIT WebRTC

go2rtc has no native UBIA or UBox P4P input protocol, which is what this bridge exists to
supply. It does accept HEVC over RTSP, but browser WebRTC video is H.264, so transcoding
may be needed at the go2rtc layer. Software transcoding a 2304x1296 stream on a Pi 4
should not be assumed cheap.

## Deliberately out of scope for phase 1

Upstream's `tools/pi_relay` is a different architecture: camera-side `shm_stream` pushing
raw H.264 over TCP, requiring camera bootstrap, SD-card binaries, and encoder patches that
must be reapplied after a reboot. It is a possible later fallback, and it is not the same
thing as wrapping `p4p_stream.py`. Phase 1 modifies nothing on the camera.

## Local verification, 2026-09-08

The full suite, including the real-media end-to-end test, passes on Windows with FFmpeg
9.0.1 and MediaMTX 1.21.0. MediaMTX confirmed the published track as H265 and a client
decoded a frame back off the RTSP URL, so the HEVC-to-RTSP half of the pipeline is proven
independently of the camera. What remains unproven is everything upstream of the pipe.
