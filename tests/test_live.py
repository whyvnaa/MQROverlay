"""Live positions without a game: messages built the way the client builds them (SyncEvent.EncodeData)."""

from mq_overlay.capture import SYN, Stream
from mq_overlay.live import LiveState, sync_events


def physic_basic(target: str, x: str, y: str, z: str = "0") -> str:
    return f"{target}&2&5.25&i0&f{x}&f{y}&f{z}&f0&f-3.5&f0&i1"


def test_own_position_from_outgoing_with_decimal_comma():
    live = LiveState()
    live.handle("out", f"%xt%mqj%ss%42%{physic_basic('1001', '231,5', '160,25')}%")
    me, others = live.snapshot()
    assert me == (231.5, 160.25) and others == {}
    assert live.me_id == "1001"


def test_other_players_from_incoming_batch_and_teleport():
    live = LiveState()
    live.handle("out", f"%xt%mqj%ss%42%{physic_basic('1001', '10', '20')}%")
    batch = f"$0[{physic_basic('2002', '30.5', '40')}$0.1[{physic_basic('3003', '50', '60')}"
    live.handle("in", f"%xt%ss%42%{batch}%")
    live.handle("in", "%xt%ss%42%1001&34&7.5&f99.5&f88&i0%")  # the server moves you (respawn)
    me, others = live.snapshot()
    assert me == (99.5, 88.0)
    assert others == {"2002": (30.5, 40.0), "3003": (50.0, 60.0)}


def test_your_path_from_z_and_teleports():
    live = LiveState()
    assert live.plane() is None
    live.handle("out", f"%xt%mqj%ss%42%{physic_basic('1001', '10', '20', '20')}%")
    assert live.plane() == 1  # back path: z 20
    live.handle("out", f"%xt%mqj%ss%42%{physic_basic('1001', '10', '20', '3,5')}%")
    assert live.plane() == 0  # crossing a bridge towards the front
    live.handle("in", "%xt%ss%42%1001&34&7.5&f99.5&f88&i1%")  # teleported onto the back path
    assert live.plane() == 1
    live.handle("in", f"%xt%ss%42%{physic_basic('2002', '1', '2', '0')}%")  # another player: not your path
    assert live.plane() == 1
    live.clear()
    assert live.plane() is None


def test_other_messages_are_ignored():
    live = LiveState()
    for d, m in [("in", "<msg t='sys'><body action='logOK'/></msg>"), ("in", "%xt%ss%42%1001&0&1&sidle%"),
                 ("out", "%xt%mqj%h%42%x%"), ("in", "%xt%ss%42%garbage%")]:
        live.handle(d, m)
    assert live.snapshot() == (None, {})
    assert list(sync_events("out", "%xt%mqj%ss%42%a&2&1&i0%")) == [["a", "2", "1", "i0"]]


def test_stream_reassembles_out_of_order_and_resent_segments():
    s = Stream()
    assert s.feed(1000, SYN, b"") == []
    assert s.feed(1001, 0, b"%xt%a%") == []
    assert s.feed(1013, 0, b"%xt%c%\0") == []  # arrives early
    assert s.feed(1007, 0, b"\0%xt%b") == [b"%xt%a%", b"%xt%b%xt%c%"]  # the early segment joins in
    s2 = Stream()
    s2.feed(0, SYN, b"")
    assert s2.feed(1, 0, b"one\0tw") == [b"one"]
    assert s2.feed(1, 0, b"one\0tw") == []  # resent
    assert s2.feed(7, 0, b"o\0three\0") == [b"two", b"three"]


def test_stream_joined_mid_connection():
    s = Stream()
    assert s.feed(5000, 0, b"t of a message\0%xt%ss%1%x%\0") == [b"t of a message", b"%xt%ss%1%x%"]
