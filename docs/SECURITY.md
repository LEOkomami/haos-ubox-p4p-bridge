# Security

## Reporting

Open an issue in this repository. Do not include a device password, a UID paired with a
password, or a packet capture of a handshake.

## Never commit

- The camera device password.
- The mobile app or cloud account password.
- Cloud tokens.
- Packet captures of the P4P handshake. They contain authentication material.

`.gitignore` covers `options.json`, `*.pcap*`, `*.log`, `*.h265`, `.env`, and the local
`.research/` and `.tools/` folders.

## What the app does with secrets

| Secret | Where it lives | Where it never goes |
| --- | --- | --- |
| `camera_password` | Home Assistant app options, then the worker's environment | argv, logs, status file |
| `rtsp_password` | app options, then the generated MediaMTX config at mode 0600 | argv, logs |
| `SUPERVISOR_TOKEN` | the supervisor's own environment | any child environment |

The logging filter redacts the passwords and the token in their literal, percent-encoded,
and hex forms. Because that cannot cover a secret transformed by the protocol, raw
upstream output is not forwarded at all; only recognized milestones and anchored counter
patterns are.

## Network exposure

`host_network: true` is required because P4P depends on UDP source ports and NAT
traversal, which a bridged container breaks. The consequence is that the RTSP port sits on
the host, so it is treated as hostile by default:

- Publishing to the path is allowed from `127.0.0.1` and `::1` only.
- `overridePublisher` is false, so an established stream cannot be displaced.
- RTSP over UDP is disabled. TCP only.
- Everything MediaMTX can serve except RTSP is off: RTMP, HLS, WebRTC, SRT, MoQ, the API,
  metrics, pprof, and playback.
- With `rtsp_password` blank, unauthenticated reads are limited to loopback and private
  ranges. Set `rtsp_password` if anything untrusted shares the LAN.

## Supply chain

No vendor APK, shared object, firmware image, or other proprietary binary is in this
repository, and none is downloaded at build time. The dependencies this project names are
pinned:

| Dependency | Pin |
| --- | --- |
| Home Assistant base image | digest |
| `mahumadad/ubox-p4p` | commit `6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8`, verified after checkout |
| `kcp` 0.1.6 | source distribution SHA-256, with `--require-hashes` |
| MediaMTX 1.21.0 | release tarball SHA-256 |

Build toolchains are installed as a virtual package and removed in the same layer. The
image is built by GitHub Actions (`.github/workflows/build-image.yml`) and published to
ghcr.io; the Supervisor pulls it by the tag named in `config.yaml`, so the Pi never runs
the build. The workflow refuses to overwrite an already-published version tag.

**Known gap.** `kcp` 0.1.6 ships only a Cython source file, and its `[build-system]`
requires `poetry-core`, `cython == 3.0.11`, `entrypoint`, and `setuptools`. pip fetches
those into an isolated build environment, and `--require-hashes` does not extend to PEP
518 build dependencies, so they are resolved unpinned at build time, on the CI runner rather than the Pi. Only `cython` carries
an upstream `==` pin. Closing this properly means either vendoring a prebuilt wheel or
building with `--no-build-isolation` against explicitly pinned build dependencies.

## Legal position

This is independent interoperability work for hardware the operator owns. It is not
affiliated with, endorsed by, or supported by UBox, UBIA, ZGWL, or any camera vendor, and
it redistributes no vendor code. Phase 1 deliberately performs no camera firmware
modification.
