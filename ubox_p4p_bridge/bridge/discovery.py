"""Bounded LAN discovery using only the pinned upstream packet builder/parser."""

import socket
import sys
import time

from settings import UID_PATTERN


UID_OFFSETS = (12, 16, 20, 24, 28)


def uid_from_payload(plain):
    """Locate the 20-byte UID field in a decrypted LAN search reply.

    Upstream reads offset 20 first and accepts any 10+ alphanumeric run, so on firmware
    that places the UID at offset 16 it returns the UID's tail plus a byte of the next
    field. The true field is the 20-byte all-alphanumeric slice whose preceding byte is
    not alphanumeric (a header byte), which a late read can never satisfy because the
    byte before it is part of the UID itself. Ambiguity returns None rather than a guess.
    """
    found = set()
    for offset in UID_OFFSETS:
        chunk = plain[offset:offset + 20]
        if len(chunk) != 20:
            continue
        try:
            text = chunk.decode("ascii")
        except UnicodeDecodeError:
            continue
        if not UID_PATTERN.fullmatch(text):
            continue
        if offset and chr(plain[offset - 1]).isalnum():
            continue
        found.add(text)
    return found.pop() if len(found) == 1 else None


def candidate_uid(parsed):
    # Ignore request echoes and unknown packets. Never store raw packet/token data.
    if not parsed or parsed.get("msg_type") != "0x1302":
        return None
    raw = parsed.get("raw_hex")
    if raw:
        try:
            uid = uid_from_payload(bytes.fromhex(raw))
        except ValueError:
            uid = None
        if uid:
            return uid
    uid = parsed.get("uid", "")
    return uid if UID_PATTERN.fullmatch(uid) else None


def discover(broadcast, stop, seconds=8, source="/opt/ubox-p4p"):
    sys.path.insert(0, source) if source not in sys.path else None
    from lan_tools import LAN_SEARCH_PORT, build_lansearchreq, parse_lan_response

    found = {}
    packet = build_lansearchreq()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        sock.settimeout(0.25)
        deadline = time.monotonic() + seconds
        next_send = 0.0
        while not stop.is_set() and time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_send:
                sock.sendto(packet, (broadcast, LAN_SEARCH_PORT))
                next_send = now + 1
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            try:
                uid = candidate_uid(parse_lan_response(data, addr))
            except (ValueError, IndexError, TypeError):
                continue
            if uid:
                found[uid] = addr[0]
                if len(found) >= 64:
                    break
    return found

