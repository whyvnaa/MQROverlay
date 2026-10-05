"""The path switch: the map shows the path you are on unless you pick the other one (Overlay.shown_path), without a
window."""

from types import SimpleNamespace

from mq_overlay.live import LiveState
from mq_overlay.overlay import Overlay


def fake(choice=None, planes=(0, 1), live=None, pinned=False):
    o = SimpleNamespace(path_choice=choice, live=live, pinned=pinned,
                        map=SimpleNamespace(planes_present=lambda: list(planes)))
    o.my_plane = lambda: Overlay.my_plane(o)
    return o


def on_path(plane: int) -> LiveState:
    live = LiveState()
    live.handle("out", f"%xt%mqj%ss%42%1001&2&1&i0&f5&f6&f{20 * plane}&f0&f0&f0&i1%")
    return live


def test_shows_the_path_you_are_on():
    assert Overlay.shown_path(fake(live=on_path(1))) == 1
    assert Overlay.shown_path(fake(live=on_path(0))) == 0
    assert Overlay.shown_path(fake(live=LiveState())) == 0  # no position yet: the front path
    assert Overlay.shown_path(fake(live=on_path(1), pinned=True)) == 0  # another zone: the front path


def test_your_choice_wins():
    assert Overlay.shown_path(fake(choice=0, live=on_path(1))) == 0
    assert Overlay.shown_path(fake(choice=1, live=None)) == 1


def test_one_path_zone():
    assert Overlay.shown_path(fake(choice=1, planes=(0,), live=on_path(1))) == 0


def test_find_me_goes_back_to_your_path():
    calls = []
    o = fake(choice=0, live=on_path(1))
    o.show_path = lambda: calls.append(Overlay.shown_path(o))
    o.map.center_on_me = lambda span: calls.append("zoom")
    Overlay.go_to_me(o)
    assert calls == [1, "zoom"] and o.path_choice is None
