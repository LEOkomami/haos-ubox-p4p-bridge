# Architecture

## Pipeline

```text
Q5-wifi(pir) camera
      |  UBIA / UBox P4P over UDP: custom cipher, KCP, RDT framing, ICE-style traversal
      v
worker.py  ->  pinned upstream p4p_stream.py
      |  raw HEVC on the worker's stdout
      v
supervisor.py pump  ->  byte and stall accounting
      |  anonymous pipe
      v
FFmpeg  ->  -c:v copy, generated timestamps
      |  RTSP publish to 127.0.0.1
      v
MediaMTX
      |  host port 8557, TCP only
      v
go2rtc / AlexxIT WebRTC / VLC / Home Assistant
```

## Why processes and not one program

The upstream client is research code. It prints packet diagnostics to stdout and stderr,
raises freely, and has no health interface. Running it as a child process buys three
things that matter more than efficiency here:

- **Isolation.** Upstream crashes cannot take the RTSP server down with them.
- **Log control.** The supervisor decides what upstream text reaches Home Assistant.
- **Health from the outside.** Bytes on the pipe and FFmpeg's own progress output measure
  liveness without modifying upstream.

## Why an anonymous pipe and not a FIFO

The original scaffold used a named FIFO. A FIFO makes startup order load-bearing: the
writer blocks until a reader attaches, so a dead reader wedges the writer, and a stale
FIFO survives a crash. An anonymous pipe created by the supervisor cannot get out of sync
with the processes that own its ends, and closing either end is immediately observable.

`worker.py` replaces `p4p_stream.open` so the upstream call `open(output, "wb")` returns a
sink writing to that pipe. The sink loops until every byte is written, because upstream
ignores short write returns and a filling pipe would otherwise drop video silently.

## Timestamps

The P4P video path is raw HEVC with no container and no timestamps. FFmpeg is told the
frame rate with `-r`, `+genpts` supplies presentation timestamps, and the `setts`
bitstream filter rewrites them to an even cadence so MediaMTX sees a monotonic stream.
`input_fps` must therefore match the camera; a wrong value plays back too fast or too slow
rather than failing loudly.

## Health model

Three independent clocks, all evaluated in `Activity.reason_to_restart`:

| Clock | Advanced by | Detects |
| --- | --- | --- |
| `last_video` | bytes read from the worker | camera sleep, P4P session loss |
| `last_forwarded` | bytes written to FFmpeg | a blocked or wedged FFmpeg |
| `last_published` | FFmpeg frame progress | a stream that flows but never muxes |

Before the first published frame only `startup_timeout_seconds` applies, so a slow
handshake is never mistaken for a stall. After the first frame, all three use
`idle_timeout_seconds`.

Failure handling follows the brief: FFmpeg or worker death restarts the session, and
MediaMTX death exits the app so the Supervisor Watchdog restarts it whole. There is no
point retrying around a dead RTSP server, because every consumer's URL is already broken.

## Secret handling

- Options are read from `/data/options.json` and validated before any subprocess starts.
- The device password reaches the worker only through its environment, never argv, so it
  never appears in a process list.
- Children get an allowlisted environment. `SUPERVISOR_TOKEN` is not in it.
- A logging filter replaces the passwords and the Supervisor token, including their
  percent-encoded and hex forms.
- Redaction alone is not trusted for upstream output. Packet dumps can contain secrets
  transformed beyond any string match, so `upstream_log` forwards only recognized
  milestones and counter lines matched by fully anchored patterns, and discards the rest.
- The MediaMTX configuration is generated as JSON, which is valid YAML, so no user value
  is ever interpolated into YAML or a shell.

## Build pinning

The image is built once by GitHub Actions and published to ghcr.io. `config.yaml` names
it with `image:`, so the Supervisor pulls a finished image rather than compiling on the
host. That matters because `kcp` has no aarch64 Linux wheel: a source build always runs
Cython and `gcc -O3`, which is the wrong thing to do on the machine running the home.

`aarch64` only, and asserted twice: `BUILD_ARCH` and `uname -m`. The image pins the base
image digest, the upstream commit, the `kcp` source distribution hash, and the MediaMTX
release hash. The build then proves what it needs rather than assuming it: the `kcp` C
extension imports, FFmpeg has the HEVC demuxer and the RTSP muxer, and MediaMTX runs.
