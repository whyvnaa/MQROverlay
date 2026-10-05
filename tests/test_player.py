"""Your character from made-up messages in the upstream server's formats."""

from mq_overlay.player import PlayerState, parse_login


def login_info(level=23, bananas=4321, nc=12, xp=99000, badge_points=40, tribe=4) -> str:
    """CharacterDataModel.ToString for a made-up monkey (sections split by "[")."""
    head = ["7", "Momo", "1", str(bananas), str(nc), "0", "2400", "", "2400", str(level), "0", str(xp), "1000", "5000",
            "1.5", "2.0", "0", str(badge_points), str(tribe), "230", "1", "2|0|1", "4|40|1", "6|0|0"]
    sections = ["<".join(head), "custom", "1001{1{0{0>2002{5{1{0", "", "1&2&3", "0|1001|1|2002",
                "", "", "13=500=0:15=600=1", "0", "0", "0", "0", "1", "1|2|3|4|5|6|7|8|9|10|11|12|13",
                "77,3003,2,5,1,6,2|78,3004,1,9,4", "2<1", "", ""]
    return "[".join(sections)


def test_login_gives_everything():
    p = PlayerState()
    p.handle("in", f"%xt%ci%-1%42%{login_info()}%99%LV_CRS_Trail01%")
    s = p.snapshot()
    assert (s["level"], s["bananas"], s["nick_cash"], s["xp"], s["tribe"]) == (23, 4321, 12, 99000, "Shadow")
    assert s["badges"] == {"Crossroads": 0, "Shadow": 40, "Outlaw": 0}
    assert s["inventory"] == {1001: 1, 2002: 5}
    assert s["worn"] == {13: 500, 15: 600}
    assert s["hotbar"] == {0: 1001, 1: 2002}
    assert s["recipes"] == {3003, 3004}
    assert s["source"] == "login" and s["known"]


def test_other_players_short_info_is_ignored():
    assert parse_login("7<Momo<1[custom[13=500=0[0[1[2<3") is None


def test_changes_after_login():
    p = PlayerState()
    p.handle("in", f"%xt%ci%-1%42%{login_info()}%99%LV_CRS_Trail01%")
    p.handle("in", "%xt%ce%-1%24<100<2<20<1<20<0<-1<125%42%")  # you level up
    p.handle("in", "%xt%ce%-1%31<100<2<20<1<20<0<-1<125%77%")  # someone else does
    p.handle("in", "%xt%cz%-1%79,3005,1,9,4%")
    p.handle("in", "%xt%hs%-1%0|1001|1|2002|2|3005%")
    p.handle("in", "%xt%iq%-1%77%13=999=0%")  # someone else's gear
    p.handle("in", "%xt%iq%-1%42%13=501=0:15=600=1%")  # yours
    s = p.snapshot()
    assert s["level"] == 24 and 3005 in s["recipes"] and s["hotbar"][2] == 3005 and s["worn"] == {13: 501, 15: 600}


def test_inventory_cash_xp_badges():
    p = PlayerState()
    p.handle("in", "%xt%ip%-1%1001{1{0{0|2002{5{1{0|3003{0{0{0%0%")
    p.handle("in", "%xt%ca%-1%12345%67%")
    p.handle("in", "%xt%cp%-1%5500%9000%")
    p.handle("in", "%xt%cA%-1%2|0|1<4|40|1<6|0|0%4%0%")
    s = p.snapshot()
    assert s["inventory"] == {1001: 1, 2002: 5}  # empty stacks dropped
    assert (s["bananas"], s["nick_cash"], s["xp"], s["tribe"]) == (12345, 67, 5500, "Shadow")
    assert s["badges"] == {"Crossroads": 0, "Shadow": 40, "Outlaw": 0}
    assert p.level_from_xp([1000, 3000, 6000, 10000]) == 3


def test_worn_gear_before_a_login_was_seen():
    p = PlayerState()
    p.handle("out", "%xt%mqj%ie%-1%13=500=0:15=600=1%")
    assert p.snapshot()["worn"] == {13: 500, 15: 600}
    p.handle("in", "%xt%iq%-1%77%13=999=0:15=888=0%")  # someone else
    assert p.snapshot()["worn"] == {13: 500, 15: 600}
    p.handle("in", "%xt%iq%-1%42%13=500=0:15=600=1:16=700=0%")  # you, with one more piece
    assert p.snapshot()["worn"] == {13: 500, 15: 600, 16: 700}


def test_saved_copy_survives_a_restart(tmp_path):
    cache = tmp_path / "character.json"
    p = PlayerState(cache)
    p.handle("in", f"%xt%ci%-1%42%{login_info(level=30)}%99%LV_CRS_Trail01%")
    again = PlayerState(cache).snapshot()
    assert again["level"] == 30 and again["inventory"] == {1001: 1, 2002: 5} and again["recipes"] == {3003, 3004}
    assert again["source"] == "saved" and again["known"]
    text = cache.read_text(encoding="utf-8")
    assert "Momo" not in text and "%xt%" not in text  # parsed numbers only


def test_junk_is_counted_not_raised():
    p = PlayerState()
    p.handle("in", "%xt%ca%-1%lots%x%")
    p.handle("in", "not smartfox")
    assert p.errors == 1 and p.snapshot()["known"] is False
