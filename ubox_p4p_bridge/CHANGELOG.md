# Changelog

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
