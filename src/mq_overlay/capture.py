"""Reads the game's own network traffic (SmartFox over plain TCP, port 9339) through Npcap's wpcap.dll, read-only.

Only packets of the game connection pass the capture filter. Each direction is put back together into the
NUL-terminated SmartFox messages, which go to a callback and are dropped right after: nothing is logged or stored
(the login message carries the password in plain text)."""

import ctypes
import os
import sys
import threading
from ctypes import POINTER, byref, c_char_p, c_int, c_ubyte, c_uint, c_uint32, c_ushort, c_void_p
from pathlib import Path

GAME_PORT = 9339
SYN, RST = 0x02, 0x04


class sockaddr(ctypes.Structure):
    _fields_ = [("sa_family", c_ushort), ("sa_data", ctypes.c_char * 14)]


class pcap_addr(ctypes.Structure):
    pass


pcap_addr._fields_ = [("next", POINTER(pcap_addr)), ("addr", POINTER(sockaddr)), ("netmask", POINTER(sockaddr)),
                      ("broadaddr", POINTER(sockaddr)), ("dstaddr", POINTER(sockaddr))]


class pcap_if(ctypes.Structure):
    pass


pcap_if._fields_ = [("next", POINTER(pcap_if)), ("name", c_char_p), ("description", c_char_p),
                    ("addresses", POINTER(pcap_addr)), ("flags", c_uint)]


class bpf_program(ctypes.Structure):
    _fields_ = [("bf_len", c_uint), ("bf_insns", c_void_p)]


class pcap_pkthdr(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long), ("caplen", c_uint32), ("len", c_uint32)]


def load_wpcap():
    """Npcap's wpcap.dll (System32/Npcap, or System32 for its WinPcap-compatible copy), or None if Npcap isn't
    installed. Called again by Sniffer.start(), so an install while the overlay runs is picked up."""
    if sys.platform != "win32":
        return None
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    folder = next((d for d in (system / "Npcap", system) if (d / "wpcap.dll").exists()), None)
    if folder is None:
        return None
    os.add_dll_directory(str(folder))
    try:
        lib = ctypes.CDLL(str(folder / "wpcap.dll"))
    except OSError:
        return None
    lib.pcap_findalldevs.argtypes = [POINTER(POINTER(pcap_if)), c_char_p]
    lib.pcap_freealldevs.argtypes = [POINTER(pcap_if)]
    lib.pcap_open_live.restype = c_void_p
    lib.pcap_open_live.argtypes = [c_char_p, c_int, c_int, c_int, c_char_p]
    lib.pcap_compile.argtypes = [c_void_p, POINTER(bpf_program), c_char_p, c_int, c_uint32]
    lib.pcap_setfilter.argtypes = [c_void_p, POINTER(bpf_program)]
    lib.pcap_freecode.argtypes = [POINTER(bpf_program)]
    lib.pcap_datalink.argtypes = [c_void_p]
    lib.pcap_next_ex.argtypes = [c_void_p, POINTER(POINTER(pcap_pkthdr)), POINTER(POINTER(c_ubyte))]
    lib.pcap_close.argtypes = [c_void_p]
    return lib


def tcp_segment(dlt: int, data: bytes):
    """(src ip, src port, dst ip, dst port, seq, flags, payload) of an IPv4 TCP packet, else None."""
    if dlt == 1:  # Ethernet, maybe VLAN tagged
        off, etype = 14, data[12:14]
        while etype in (b"\x81\x00", b"\x88\xa8"):
            etype = data[off + 2:off + 4]
            off += 4
        if etype != b"\x08\x00":
            return None
    elif dlt in (0, 108):  # loopback: 4-byte address family
        off = 4
    elif dlt in (12, 14, 101):  # raw IP
        off = 0
    else:
        return None
    ip = data[off:]
    if len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != 6:
        return None
    ihl = (ip[0] & 15) * 4
    total = int.from_bytes(ip[2:4], "big") or len(ip)  # 0 with segmentation offload
    tcp = ip[ihl:total]
    if len(tcp) < 20:
        return None
    doff = (tcp[12] >> 4) * 4
    return (bytes(ip[12:16]), int.from_bytes(tcp[0:2], "big"), bytes(ip[16:20]), int.from_bytes(tcp[2:4], "big"),
            int.from_bytes(tcp[4:8], "big"), tcp[13], bytes(tcp[doff:]))


class Stream:
    """One direction of a TCP connection put back in order, cut into NUL-terminated messages."""
    MAX_PENDING = 64
    MAX_BUFFER = 1 << 20

    def __init__(self):
        self.next: int | None = None
        self.buf = b""
        self.pending: dict[int, bytes] = {}

    def reset(self, seq: int | None = None) -> None:
        self.next, self.buf = seq, b""
        self.pending.clear()

    def feed(self, seq: int, flags: int, payload: bytes) -> list[bytes]:
        if flags & (SYN | RST):
            self.reset((seq + 1) % 2**32 if flags & SYN else None)
            return []
        if not payload:
            return []
        if self.next is None:  # joined a running connection: the first message is cut and gets ignored
            self.next = seq
        ahead = (seq - self.next) % 2**32
        if ahead >= 2**31:  # resent data, maybe partly new
            back = (self.next - seq) % 2**32
            if back >= len(payload):
                return []
            payload, ahead = payload[back:], 0
        if ahead:
            self.pending[seq] = payload
            if len(self.pending) > self.MAX_PENDING:  # lost a segment: start again from the newest data
                self.reset()
            return []
        self.buf += payload
        self.next = (self.next + len(payload)) % 2**32
        while self.next in self.pending:
            p = self.pending.pop(self.next)
            self.buf += p
            self.next = (self.next + len(p)) % 2**32
        *messages, self.buf = self.buf.split(b"\0")
        if len(self.buf) > self.MAX_BUFFER:
            self.buf = b""
        return [m for m in messages if m]


class Sniffer:
    """Captures the game connection on every network adapter with an IPv4 address, one thread each.
    on_message(direction, text): direction "out" = client to server, "in" = server to client."""

    def __init__(self, on_message, port: int = GAME_PORT):
        self.on_message = on_message
        self.port = port
        self.lib = load_wpcap()
        self.stop_flag = threading.Event()
        self.threads: list[threading.Thread] = []
        self.streams: dict[tuple, Stream] = {}
        self.lock = threading.Lock()
        self.error = "" if self.lib else "Npcap is not installed"

    @property
    def available(self) -> bool:
        return self.lib is not None

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self.threads)

    def adapters(self) -> list[bytes]:
        devs = POINTER(pcap_if)()
        err = ctypes.create_string_buffer(256)
        if self.lib.pcap_findalldevs(byref(devs), err) != 0:
            self.error = err.value.decode(errors="replace")
            return []
        names = []
        d = devs
        while d:
            a = d.contents.addresses
            while a:
                sa = a.contents.addr
                if sa and sa.contents.sa_family == 2 and sa.contents.sa_data[2:3] != b"\x7f":  # IPv4, not loopback
                    names.append(d.contents.name)
                    break
                a = a.contents.next
            d = d.contents.next
        self.lib.pcap_freealldevs(devs)
        return names

    def start(self) -> bool:
        """Open every adapter and read; False (with `error` saying why) when Npcap is missing or nothing opens.
        Can be called again later (after installing Npcap)."""
        if self.running:
            return True
        if not self.lib:
            self.lib = load_wpcap()
            if not self.lib:
                self.error = "Npcap is not installed"
                return False
        self.error, self.threads = "", []
        self.stop_flag.clear()
        for name in self.adapters():
            err = ctypes.create_string_buffer(256)
            handle = self.lib.pcap_open_live(name, 65535, 0, 200, err)
            if not handle:
                continue
            prog = bpf_program()
            if self.lib.pcap_compile(handle, byref(prog), f"tcp port {self.port}".encode(), 1, 0xFFFFFFFF) == 0:
                self.lib.pcap_setfilter(handle, byref(prog))
                self.lib.pcap_freecode(byref(prog))
            t = threading.Thread(target=self.run, args=(handle,), daemon=True)
            t.start()
            self.threads.append(t)
        if not self.threads and not self.error:
            self.error = "no network adapter could be opened"
        return bool(self.threads)

    def run(self, handle) -> None:
        dlt = self.lib.pcap_datalink(handle)
        hdr = POINTER(pcap_pkthdr)()
        data = POINTER(c_ubyte)()
        while not self.stop_flag.is_set():
            r = self.lib.pcap_next_ex(handle, byref(hdr), byref(data))
            if r == 0:
                continue
            if r < 0:
                break
            seg = tcp_segment(dlt, ctypes.string_at(data, hdr.contents.caplen))
            if not seg:
                continue
            src, sport, dst, dport, seq, flags, payload = seg
            if self.port not in (sport, dport):
                continue
            direction = "out" if dport == self.port else "in"
            with self.lock:
                stream = self.streams.setdefault((src, sport, dst, dport), Stream())
                messages = stream.feed(seq, flags, payload)
            for m in messages:
                try:
                    self.on_message(direction, m.decode("utf-8", errors="replace"))
                except Exception:  # a broken message must not stop the capture
                    pass
        self.lib.pcap_close(handle)

    def stop(self) -> None:
        self.stop_flag.set()
