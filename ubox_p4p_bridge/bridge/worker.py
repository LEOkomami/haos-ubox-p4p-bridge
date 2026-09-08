"""Adapt the pinned upstream API: binary-only stdout, unbuffered video writes."""

import os
import sys
from contextlib import redirect_stdout


class VideoSink:
    """Upstream ignores short writes, so a filling pipe would silently drop video."""

    def __init__(self, fd):
        self.fd = fd

    def write(self, data):
        remaining = memoryview(data)
        total = remaining.nbytes
        while remaining:
            written = os.write(self.fd, remaining)
            if not written:
                raise BrokenPipeError("video pipe accepted no bytes")
            remaining = remaining[written:]
        return total

    def flush(self):
        pass

    def close(self):
        os.close(self.fd)

    # Upstream closes explicitly, but stay a drop-in replacement for a file object.
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False


def main():
    video_fd = sys.stdout.fileno()
    sys.path.insert(0, os.environ.get("UBOX_SOURCE", "/opt/ubox-p4p"))
    # All upstream diagnostic prints, including import-time prints, go to stderr.
    with redirect_stdout(sys.stderr):
        import p4p_stream

        def video_output(path, mode):
            if path != "bridge-video" or mode != "wb":
                raise ValueError("Unexpected upstream output request")
            return VideoSink(os.dup(video_fd))

        p4p_stream.open = video_output
        uid = os.environ["UBOX_UID"]
        password = os.environ["UBOX_PASSWORD"]
        if os.environ.get("UBOX_MODE") == "relay":
            p4p_stream.run_relay_stream(uid, password, 0, "bridge-video")
        else:
            p4p_stream.run_stream(uid, password, int(os.environ["UBOX_HANDSHAKE"]), "bridge-video")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Upstream exceptions can include authentication material. Report type only.
        print(f"[worker] stopped with {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
