"""Build mode's logic on the real exported data: your inventory by item id, the guide, ways and places."""

from mq_overlay.builder import Builder, Options, way_short, way_text
from mq_overlay.data import DATA


def item_id(b: Builder, name: str) -> int:
    return next(it["id"] for it in b.bundle["items"].values() if it.get("name") == name)


def test_profile_from_messages():
    b = Builder(DATA)
    snap = {"inventory": {item_id(b, "Slingshot"): 1}, "worn": {13: item_id(b, "Training Katana")},
            "xp": 0, "badges": {"Shadow": 40}, "level": 23}
    p = b.profile(snap, Options())
    assert p.level == 23 and p.skill_points == 40
    assert {b.item(x)["name"] for x in p.owned} == {"Slingshot", "Training Katana"}
    assert b.profile(snap, Options(level=30)).level == 30


def test_where_you_fight():
    b = Builder(DATA)
    assert b.profile({}, Options(where="Fire")).target_element == "Fire"
    assert b.profile({}, Options(where="blunt")).target_element is None
    z = b.profile({}, Options(where="zone", zone="LV_OUT_Dungeon01"))
    assert z.target_element == "Fire" and z.target_level == 33


def test_learned_patterns_count_as_owned():
    b = Builder(DATA)
    cutlass = next(it for it in b.bundle["items"].values() if it.get("name") == "Dragon Flame Cutlass")
    pattern = next(w["pattern"] for w in b.bundle["ways"][cutlass["prefab"]] if w["kind"] == "craft")
    p = b.profile({"recipes": {cutlass["id"]}}, Options())
    assert p.owned.get(pattern) == 1


def test_guide_has_everything_build_mode_shows():
    b = Builder(DATA)
    snap = {"inventory": {item_id(b, "Slingshot"): 1, item_id(b, "Training Katana"): 1}, "badges": {"Shadow": 20}}
    opt = Options(level=20, slots=("melee", "ranged", "stun"))
    g = b.guide(b.profile(snap, opt), opt)
    assert g["menu"][0].hours == 0 and g["now"]["Ranged"]["name"] == "Slingshot"
    assert set(g["utility"]) == {"Stun"} and g["utility"]["Stun"]
    assert g["tribe"] == "Shadow" and g["badge"][0] > 0 and g["prices"] and g["shop"]
    top = g["menu"][-1]
    missing = top.missing()
    ways = g["costs"].ways(missing[0].item["prefab"], b.profile(snap, opt))
    assert ways and way_text(ways[0])


def test_shop_list_covers_every_tribe_and_armour_group():
    b = Builder(DATA)
    snap = {"inventory": {item_id(b, "Slingshot"): 1, item_id(b, "Training Katana"): 1}, "badges": {"Shadow": 20}}
    opt = Options(level=20, look=5, sources={"vendor", "chest", "enemy", "craft", "quest", "nick_cash"})
    p = b.profile(snap, opt)
    g = b.guide(p, opt)
    shop = g["shop"]
    assert list(shop["tribes"]) == ["Shadow", "Bone", "Outlaw", "Wild", "Grease", "Crossroads"]
    assert set(shop["armour"]) == {"Air", "Earth", "Fire", "Ice", "Lightning", None, "any"}
    outlaw = shop["tribes"]["Outlaw"]
    assert outlaw["element"] == "Fire" and outlaw["badge"][0] > 0
    assert set(outlaw["weapons"]) == {"Melee", "Ranged"} and set(outlaw["accessories"]) == {"Ears", "Wrist", "Tail"}
    names = [r["item"]["name"] for r in outlaw["weapons"]["Melee"]]
    assert "Dragon Flame Cutlass" in names  # the Fire sword at level 20
    for tribe in shop["tribes"].values():
        for rows in list(tribe["weapons"].values()) + list(tribe["accessories"].values()):
            for r in rows:
                assert r["later"] or r["from"] <= 25
                assert r["owned"] or (r["hours"] > 0 and way_short(r["way"]))
                assert r["kill_time"] > 0 and r["hits_by"]["melee"]["hit"] > 0
        assert tribe["build"]["kill_time"] <= tribe["now"]["kill_time"] + 1e-9
    # the Steel Sword is NickCash only and listed under Crossroads (no element, all blunt) with the sources chosen
    assert "Steel Sword" in [r["item"]["name"] for r in shop["tribes"]["Crossroads"]["weapons"]["Melee"]]
    # at least one recommendation per tribe: the Wild and Grease weapons are missing from the data, said so
    wild = shop["tribes"]["Wild"]
    assert wild["missing"]["Melee"] and any(r for rows in wild["accessories"].values() for r in rows)
    fire = shop["armour"]["Fire"]
    assert all(fire["slots"][s] for s in ("Hat", "Body", "Legs", "Backpack"))
    row = fire["slots"]["Body"][0]
    assert set(row["taken_by"]) == {"Air", "Earth", "Fire", "Ice", "Lightning", None, "mix"}
    assert row["taken_by"]["Fire"] < shop["now"]["taken_by"]["Fire"]
    assert fire["set"]["taken_by"]["mix"] < shop["now"]["taken_by"]["mix"] and fire["set"]["hours"] > 0


def test_no_way_list():
    b = Builder(DATA)
    opt = Options(level=30)
    p = b.profile({}, opt)
    _, costs = b.plan(p, opt)
    names = {it["name"] for it, _ in b.no_way(p, costs)}
    assert "Jacket o' the Phoenix" in names


def test_excluded_items_are_never_suggested():
    b = Builder(DATA)
    opt = Options(level=30)
    g = b.guide(b.profile({}, opt), opt)
    best = g["planner"].progression(b.profile({}, opt), "Shadow", prices=g["prices"], lo=30, hi=30)["levels"][0]["picks"]["Melee"]
    opt = Options(level=30, excluded={best["prefab"]})
    g = b.guide(b.profile({}, opt), opt)
    pl = g["planner"]
    prog = pl.progression(b.profile({}, opt), "Shadow", prices=g["prices"])
    assert all(seg["item"] is not best and seg["item"]["prefab"] != best["prefab"] for seg in prog["lanes"]["Melee"])
    assert best["prefab"] in pl.opt.item  # its card still opens


def test_better_in_your_bag_follows_the_badge_you_picked():
    b = Builder(DATA)
    opt = Options(level=27, slots=("melee",))

    def ids(*names):
        return [item_id(b, n) for n in names]
    katana, cutlass, shard, skull = ids("Training Katana", "Dragon Flame Cutlass", "Dull Shadow Shard Earrings", "Flaming Skull Earrings")
    snap = {"inventory": {cutlass: 1, shard: 1, skull: 1}, "worn": {13: katana}, "hotbar": {0: katana}, "level": 27}
    p = b.profile(snap, opt)
    pl, _, _ = b.planner(p, opt)
    fire = b.gear(snap, p, pl, "Outlaw")
    assert fire["bag_tribe"] == "Outlaw" and fire["better"]["Ears"]["name"] == "Flaming Skull Earrings"
    assert fire["better"]["Melee"]["name"] == "Dragon Flame Cutlass"
    del snap["inventory"][cutlass]  # no Fire weapon in the bag: the Fire earrings add less than the blunt ones
    air = b.gear(snap, b.profile(snap, opt), pl, "Outlaw")
    assert air["better"]["Ears"]["name"] == "Dull Shadow Shard Earrings" and "Melee" not in air["better"]



def test_build_style_decides_the_earrings_in_your_bag():
    """The user's case: a Fire melee weapon and an Air ranged one. Hybrid: blunt earrings (a hair better for the
    two together); a melee build: the Fire earrings."""
    b = Builder(DATA)
    cutlass, stars, shard, skull = [item_id(b, n) for n in ("Dragon Flame Cutlass", "Golden Stars",
                                                            "Dull Shadow Shard Earrings", "Flaming Skull Earrings")]
    snap = {"inventory": {shard: 1, skull: 1}, "hotbar": {0: cutlass, 1: stars}, "level": 28, "badges": {"Outlaw": 28}}
    for prefer, want in ((None, "Dull Shadow Shard Earrings"), ("melee", "Flaming Skull Earrings"), ("ranged", "Dull Shadow Shard Earrings")):
        opt = Options(level=28, prefer=prefer)
        p = b.profile(snap, opt)
        assert p.prefer == prefer
        pl, _, _ = b.planner(p, opt)
        assert b.gear(snap, p, pl, "Outlaw")["better"]["Ears"]["name"] == want
