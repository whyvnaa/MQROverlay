"""Waypoints without a window: the way through the zones' portals, the portal to head for, a bridge first when the
target is on the other path, and the real exported zones."""

from mq_overlay.data import GameData
from mq_overlay.waypoints import Nav, ZoneGraph, short_name, target


class FakeData:
    def __init__(self, zones: dict[str, list[dict]]):
        self.zones = {k.lower(): {"name": k, "title": k.title()} for k in zones}
        self._z = {k.lower(): {"markers": v} for k, v in zones.items()}

    def with_nav(self, zone, nav):
        self._z[zone.lower()]["nav"] = nav
        return self

    def zone(self, name):
        return self._z.get((name or "").lower())


def portal(x, to, plane=0):
    return {"cat": "portal", "x": x, "y": 0.0, "plane": plane, "tip": f"Portal to {to}", "to": to}


def bridge(x):
    return {"cat": "bridge", "x": x, "y": 0.0, "plane": 0, "both": True, "tip": "Way between the front and back path"}


DATA = FakeData({
    "A": [portal(10, "B"), portal(90, "C")],
    "B": [portal(5, "A"), portal(50, "D"), portal(60, "D")],
    "C": [portal(0, "A")],
    "D": [portal(0, "B"), bridge(20), bridge(80)],
})
WP = {"zone": "D", "x": 70.0, "y": 0.0, "plane": 1, "label": "the chest"}


def test_zone_path_fewest_portals():
    g = ZoneGraph(DATA)
    assert g.path("A", "D") == ["a", "b", "d"]
    assert g.path("C", "D") == ["c", "a", "b", "d"]
    assert g.path("D", "D") == ["d"]


def test_points_at_the_portal_toward_the_waypoint():
    g = ZoneGraph(DATA)
    t = target(DATA, g, "A", WP, (50.0, 0.0))
    assert (t["x"], t["final"]) == (10, False) and t["label"] == "Portal to B"
    assert t["goal"] == "the chest, D · 2 zones"
    t = target(DATA, g, "B", WP, (58.0, 0.0))  # two portals lead there: the closer one
    assert t["x"] == 60


def test_in_the_waypoints_zone_a_bridge_first_when_on_the_other_path():
    g = ZoneGraph(DATA)
    t = target(DATA, g, "D", WP, (10.0, 0.0), my_plane=0)
    assert t["x"] == 20 and "back path" in t["label"]  # 10 -> 20 -> 70 is shorter than 10 -> 80 -> 70
    assert t["goal"] == "the chest"
    t = target(DATA, g, "D", WP, (10.0, 0.0), my_plane=1)
    assert t["final"] and t["x"] == 70
    assert target(DATA, g, "D", WP, (10.0, 0.0), my_plane=None)["final"]  # path unknown: straight there


def test_no_way_and_no_waypoint():
    g = ZoneGraph(FakeData({"A": [], "B": []}))
    assert target(DATA, g, "A", None, None) is None
    assert target(FakeData({"A": [], "B": []}), g, "A", {**WP, "zone": "B"}, None) is None


def test_real_zones_are_connected():
    data = GameData()
    g = ZoneGraph(data)
    assert len(g.links) > 40
    path = g.path("LV_CRS_Trail01", "LV_CRS_townsquare01")
    assert path and path[0] == "lv_crs_trail01" and path[-1] == "lv_crs_townsquare01"


def strip(key, plane, x0, x1, down=()):
    """An area: a flat stretch of one path from x0 to x1."""
    return {"key": key, "plane": plane, "down": list(down), "points": [v for x in range(x0, x1 + 1) for v in (x, 0)]}


# The front path is cut in two (0..40 and 60..100), the back path runs through: to get from the left front part to
# the right one you cross to the back at 20 and come to the front again at 80.
SPLIT = [strip(1, 0, 0, 40), strip(2, 0, 60, 100), strip(3, 1, 0, 100)]


def test_short_marker_names():
    assert short_name("Chest: Fanged Mystic Belt 6.7 %, Fanged Mystic Crown 6.7 %") == "Chest"
    assert short_name("Way between the front and back path: press up to go to the back") == "Bridge"
    assert short_name("Hazard: BON TwistedSpikes1x1 1") == "Hazard"
    assert short_name("Quest item: Col_KNI_MiniShards1_RNTrail1") == "Quest item"
    assert short_name("Quest item: Clue") == "Quest item: Clue"
    assert short_name("Scatterfoot (Accessories vendor) · Lv 12") == "Scatterfoot (Accessories vendor)"
    assert short_name("Portal to The Hive") == "Portal to The Hive"


def test_a_bridge_before_a_portal_names_the_waypoint_not_the_portal():
    data = FakeData({"A": [portal(90, "B", plane=1), bridge(20)], "B": [portal(0, "A")]})
    wp = {"zone": "B", "x": 5.0, "y": 0.0, "plane": 0, "label": "Chest: Oak Plank Armor 50 %"}
    t = target(data, ZoneGraph(data), "A", wp, (10.0, 0.0), my_plane=0)
    assert (t["x"], t["label"], t["goal"]) == (20, "Bridge to the back path", "Chest, B")


def split_zone(markers=()):
    return FakeData({"E": [bridge(20), bridge(80), *markers]}).with_nav("E", SPLIT)


def test_front_path_ends_so_the_way_goes_over_the_back_and_to_the_front_again():
    data = split_zone()
    g = ZoneGraph(data)
    wp = {"zone": "E", "x": 90.0, "y": 0.0, "plane": 0, "label": "the chest"}
    t = target(data, g, "E", wp, (10.0, 0.0), my_plane=0)  # same path as you, but not in one piece
    assert (t["x"], t["final"]) == (20, False) and "back path" in t["label"]
    t = target(data, g, "E", wp, (30.0, 0.0), my_plane=1)  # on the back path now: on to the second bridge
    assert t["x"] == 80 and "front path" in t["label"]
    t = target(data, g, "E", wp, (85.0, 0.0), my_plane=0)
    assert t["final"] and t["x"] == 90.0
    assert target(data, g, "E", {**wp, "x": 30.0}, (10.0, 0.0), my_plane=0)["final"]  # the same part: straight there


def test_one_way_links_and_the_portal_with_the_shorter_way():
    nav = Nav({"nav": [strip(1, 0, 0, 40, down=[2]), strip(2, 0, 60, 100), strip(3, 1, 0, 100)],
               "markers": [bridge(20), bridge(80)]})
    assert nav.route((10.0, 0.0), 0, (90.0, 0.0), 0) == (80.0, None)  # down from 1 into 2: no bridge needed
    first = nav.route((90.0, 0.0), 0, (10.0, 0.0), 0)[1]  # not back up the same way: over the back path
    assert first["x"] == 80
    data = split_zone([portal(35, "F"), portal(95, "F")])
    data.zones["f"], data._z["f"] = {"name": "F", "title": "F"}, {"markers": [portal(0, "E")]}
    g = ZoneGraph(data)
    wp = {"zone": "F", "x": 5.0, "y": 0.0, "plane": 0, "label": "the chest"}
    t = target(data, g, "E", wp, (70.0, 0.0), my_plane=0)  # the portal at 35 is on the other part of the front path
    assert t["x"] == 95 and "Portal to F" in t["label"]


def test_zone_data_older_than_the_zone_is_not_used():
    old = Nav({"nav": [strip(1, 0, 0, 100)], "markers": [bridge(20)]})  # the bridge has no back area
    assert not old and not Nav({"markers": [bridge(20)]}) and not Nav(None)


def test_real_zones_have_the_games_areas():
    data = GameData()
    g = ZoneGraph(data)
    assert sum(bool(g.nav(z)) for z in data.zones) >= 55
    nav = g.nav("LV_BON_Highway01")  # the back path is in two parts
    assert len(nav.bridges) == 2 and len({a for a in nav.cells[1].values()}) == 2
    assert not g.nav("LV_CRS_Trail01")  # the game's data there is of an older Trail01
