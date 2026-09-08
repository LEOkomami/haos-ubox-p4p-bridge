# How to test this for real

`TEST_PLAN.md` lists what must be true. This file is the procedure: what to run, in what
order, and what each failure actually means.

The order matters. Each stage answers one question, and a stage that fails makes every
later stage a waste of time. Do not start with the container build.

```text
Stage 0   Does this camera speak P4P at all?        laptop, no Docker, ~10 minutes
Stage 1   Does the app build and start on the Pi?   HAOS, no camera needed
Stage 2   Does the app get video from the camera?   HAOS + camera
Stage 3   Does it survive the camera sleeping?      HAOS + camera + patience
Stage 4   Does it reach the dashboard?              go2rtc
```

## Stage 0: prove the protocol on a laptop first

The single most valuable test, and the one most easily skipped. The upstream client is
plain portable Python with no POSIX-only code, so it runs on Windows, macOS, or Linux
directly. If P4P does not work here, it will not work inside a container either, and you
will have spent an hour on an ARM build to learn the same thing.

The machine must be on the **same LAN** as the camera. Direct P2P is documented as failing
from a public-IP host against a symmetric-NAT camera.

```bash
git clone https://github.com/mahumadad/ubox-p4p
cd ubox-p4p
python3 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install "kcp>=0.1.6"
```

`kcp` is a C extension. On Windows a prebuilt wheel installs immediately; on Linux you may
need a compiler and Python headers.

### 0a. Discovery, which needs no password

Start here, because it costs nothing and settles the project's biggest open question.

```bash
python3 lan_tools.py discover --subnet 192.168.0.255 --timeout 12 --bursts 6
```

Use your own subnet broadcast address. If the machine has several interfaces, such as a VPN
or Bluetooth adapter, name the subnet explicitly rather than relying on
`255.255.255.255`, which may leave through the wrong one.

Wake the camera first. A PIR model that has been idle will not answer, so walk in front of
it, or open the vendor app, then run the command within a few seconds.

| Result | What it means | Next |
| --- | --- | --- |
| A reply with a 20-character UID | **The camera speaks the UBox LAN protocol.** The ecosystem hypothesis is confirmed | 0b |
| Nothing, camera definitely awake | Either not a UBox camera, or discovery is filtered. Try `python3 lan_tools.py probe CAMERA_IP` to bypass broadcast | 0b anyway |
| Nothing, camera asleep | Not a result. Wake it and retry | retry |

A `probe` reply when broadcast discovery is silent means the protocol is fine and your
network is dropping broadcast traffic. Note that, because the app's `auto_discover` will
have the same problem, and you should set `camera_uid` manually.

### 0b. Get the device password

This is the real blocker, and no amount of code works around it. The **device** password
is not necessarily your app account password.

Where to look, in order of likelihood:

1. The vendor mobile app, under the camera's own settings. Look for Device password,
   Security, or Camera password rather than Account.
2. The sticker on the camera body or in the box. Cheap cameras often ship a default.
3. Whatever you set during pairing, if the app made you choose one.
4. The app's share or QR feature, which sometimes reveals the credential used for direct
   access.

Do not brute force it. Repeated failed authentication on these devices tends to make them
stop answering, and you will then be debugging a lockout instead of a protocol.

### 0c. Pull real video to a file

Keep the password out of argv and shell history:

```bash
export UBOX_UID=YOUR_20_CHAR_UID          # Windows: $env:UBOX_UID = "..."
export UBOX_PASSWORD=YOUR_DEVICE_PASSWORD # Windows: $env:UBOX_PASSWORD = "..."
python3 p4p_stream.py --listen 40 -o live.h265
```

Wake the camera, then watch stderr. The sequence you want:

```text
[handshake] queryreq -> N masters
[handshake] knock + relay_login -> N relays
[handshake] CAMERA KNOCK from ...        <- the moment that matters
[stream] KCP conv=0x...
[stream] receiving video...
[stream] pkts=... hevc_bytes=... frames=...
```

Let it run 30 seconds, stop it with Ctrl+C, then check the file:

```bash
ffprobe live.h265
ffplay live.h265          # or open it in VLC
```

Interpret it like this:

| Symptom | Meaning |
| --- | --- |
| `CAMERA KNOCK` then `hevc_bytes` climbing | **Everything works.** Note the frame rate from `ffprobe`; it becomes `input_fps` |
| `handshake failed - no camera knock` | The camera never answered. Asleep, wrong UID, or traversal blocked |
| Knock arrives, `pkts` climb, `frames` stays 0 | Connected but no video. Almost always the device password |
| `hevc_bytes` climbs but the file will not play | Timestamp or bitstream problem, which is what the app's FFmpeg stage exists to fix. Not a blocker |
| Works, then stops after seconds | Normal for a PIR camera. The app handles this; a bare client does not |

If direct mode never gets a knock, try relay as a diagnostic:

```bash
python3 p4p_stream.py --relay --listen 0 -o relay.h265
```

Relay working while direct does not means your credentials and the protocol are fine and
the problem is NAT traversal. Relay is choppy by design, one GOP per cycle, and is not a
usable feed. Relay failing too points at the UID or the password.

**Do not continue past Stage 0 until you have seen HEVC bytes.** Everything after this
assumes the protocol works.

## Stage 1: build and start on the Pi, with no camera

Now prove the packaging, separately from the camera.

Add the repository in **Settings, Add-ons, Add-on Store**, overflow menu, **Repositories**,
then install **UBox P4P Bridge**.

The build compiles `kcp` from source, because there is no musl `aarch64` wheel, so expect
several minutes. Watch for these in the build log:

- The `kcp` compile succeeding, which is the most likely failure.
- The MediaMTX checksum check passing.
- The upstream commit assertion passing.

Then start it **with `camera_password` still blank** and read the Log tab:

```text
state=STARTING
RTSP endpoint: rtsp://HOME_ASSISTANT_IP:8557/q5 (TCP)
state=NEEDS_CONFIGURATION: enter camera_password in app Configuration, then restart
```

That is a pass. It proves MediaMTX bound its port, the options validated, and the state
machine is running, without involving the camera at all.

Also confirm the RTSP port is actually listening, from another machine:

```bash
ffprobe -rtsp_transport tcp rtsp://HOME_ASSISTANT_IP:8557/q5
```

Expect a failure saying the path has no publisher, **not** a connection refused. No
publisher means the server is up and waiting, which is exactly right at this point.

Finally, turn on the **Watchdog** toggle on the Info tab. The app exits deliberately if
MediaMTX dies, and nothing restarts it otherwise.

## Stage 2: real video through the app

Set `camera_uid` and `camera_password`, leave `mode: direct`, set `input_fps` to whatever
Stage 0c measured, and restart. Wake the camera.

```text
state=HANDSHAKING
P4P: querying masters
P4P: requesting camera wake and relay login
P4P: received camera knock
P4P: starting KCP session
P4P: waiting for HEVC video
P4P: packets=340 hevc_bytes=125400 hevc_frames=210
state=STREAMING
video: received_bytes=188228 published_frames=42 last_publish_age=0.3
```

Then, from a different machine on the LAN, in VLC: **Media, Open Network Stream**, and

```text
rtsp://HOME_ASSISTANT_IP:8557/q5
```

Force TCP. In VLC that is **Tools, Preferences, Input / Codecs, Live555 stream transport,
RTP over RTSP (TCP)**. The server refuses UDP on purpose.

If the picture plays too fast or too slow, `input_fps` is wrong. Raw HEVC carries no
timestamps, so that value generates them; it is not detected.

Three numbers localize any failure here:

| Pattern | Where the problem is |
| --- | --- |
| No `P4P: packets` line at all | Nothing arrived. Camera asleep, wrong UID, traversal blocked |
| `packets` rising, `hevc_frames` at 0 | Connected, no video. Device password |
| `hevc_frames` rising, `received_bytes` flat | The worker is not reaching the pipe. A bridge bug, report it |
| `received_bytes` rising, `published_frames` flat | FFmpeg will not mux this bitstream. Report it with the FFmpeg warning lines |
| All three rising, VLC shows nothing | Reader side. Transport, credentials, or HEVC support in your player |

## Stage 3: recovery, the part that decides whether this is usable

A camera that streams once is not the same as a camera you can leave running. Test each of
these deliberately.

**Camera sleeps.** Stop triggering it and wait. Expect `STALLED: camera video stalled`,
then `RETRYING`, then recovery on its own when you walk past it again. A wedged container
that never leaves `STREAMING` while showing no traffic is a bug.

**App restart.** Restart from the UI. It should return to `STREAMING` without help.

**Host reboot.** Reboot Home Assistant. `boot: auto` should bring it back.

**Long soak.** Leave it overnight, then check the log. This is where you find out whether
the camera can be kept awake at all, which is the largest open question in the project and
cannot be answered in a five minute test.

If you want reads to require a login before going further, set `rtsp_password` and confirm
the URL then needs credentials:

```text
rtsp://viewer:YOUR_RTSP_PASSWORD@HOME_ASSISTANT_IP:8557/q5
```

## Stage 4: go2rtc and the dashboard

Only once VLC is solid. Add to go2rtc:

```yaml
streams:
  q5: rtsp://HOME_ASSISTANT_IP:8557/q5
```

Add a Picture Glance or WebRTC card and open it. If go2rtc reports the stream but the
browser shows a black frame, that is the HEVC to H.264 gap, not a bridge fault. Transcode
at the go2rtc layer:

```yaml
streams:
  q5:
    - rtsp://HOME_ASSISTANT_IP:8557/q5
    - "ffmpeg:q5#video=h264#hardware"
```

Watch CPU on the Pi while that runs. Software transcoding a 2304x1296 stream on a Pi 4 is
expensive; drop resolution or frame rate rather than accepting a pegged CPU.

## What to record

For each stage, note the outcome in `docs/RESEARCH_NOTES.md` under a dated heading,
especially:

- The camera's real frame rate from Stage 0c.
- Whether discovery works by broadcast or only by direct probe.
- Whether direct mode establishes, or only relay.
- How the camera behaves over hours, not seconds.

Those four answers are what the project's remaining open questions actually depend on.
When reporting a problem, include the state transitions and the counter lines. Never
include the device password or a packet capture of a handshake.
