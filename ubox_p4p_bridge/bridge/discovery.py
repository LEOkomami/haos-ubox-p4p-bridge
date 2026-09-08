"""Bounded LAN discovery using only the pinned upstream packet builder/parser."""

import socket
import sys
import time

from settings import UID_PATTERN


def candidate_uid(parsed):
    # Ignore request echoes and unknown packets. Never store raw packet/token data.
    if not parsed or parsed.get("msg_type") != "0x1302":
        return None
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

