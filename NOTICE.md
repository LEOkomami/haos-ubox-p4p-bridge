# Notice

## Independent interoperability work

This project is **not affiliated with, endorsed by, or supported by** UBox, UBIA, ZGWL,
i-Cam+, or any camera vendor or manufacturer. No vendor name is used to imply any
relationship; names appear only to identify the hardware and ecosystem this software
interoperates with.

The purpose is interoperability: letting the owner of a camera receive video from their
own device on their own network using open protocols, instead of being restricted to a
vendor mobile application.

## No vendor code is redistributed

This repository contains no vendor APK, shared object, firmware image, extracted key
material, or any other proprietary binary, and the container build downloads none.

## Third-party components

None of these are vendored into the repository. They are fetched at container build time
against pinned versions and verified hashes.

| Component | License | Role |
| --- | --- | --- |
| [mahumadad/ubox-p4p](https://github.com/mahumadad/ubox-p4p) | MIT | The P4P protocol client. Fetched at commit `6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8`. |
| [MediaMTX](https://github.com/bluenviron/mediamtx) | MIT | The RTSP server. Version 1.21.0, `linux_arm64`, SHA-256 verified. Its LICENSE is installed into the image. |
| [kcp](https://pypi.org/project/kcp/) | MIT | Python KCP bindings. Version 0.1.6, built from a hash-pinned source distribution. |
| FFmpeg | LGPL / GPL depending on build | Repackages HEVC into RTSP. Provided by the Home Assistant base image; not redistributed here. |
| [Home Assistant base image](https://github.com/home-assistant/docker-base) | Apache-2.0 | The container base, pinned by digest. |

The protocol understanding this project depends on comes from the upstream reverse
engineering work. Credit for it belongs there.

## Warranty and risk

Provided as is, with no warranty, under the terms in `LICENSE`. Running it is at the
operator's own risk.

Use it only with hardware you own or are authorized to access. Receiving video from a
camera requires that camera's device password; possession of a UID alone grants nothing,
and this software must not be used to access a device you do not control.

Phase 1 deliberately performs no camera firmware modification and requires no telnet
access or SD-card payload. Should a later phase adopt the upstream camera-side relay
approach, understand before doing so that modifying camera firmware can void a warranty
and can permanently disable the device.
