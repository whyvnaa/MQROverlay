"""Build mode's logic: your character (player.py) as a planner profile, the planner (build_planner.py, a copy of the
knowledge base's), and everything Build mode shows: the prices for the progression over all levels (progression.py
works it out per tribe), utility slots, upgrades per slot, item comparisons, the shop list (per tribe and armour
group) and the gear nobody knows how to get. No Qt here, so it can be tested on its own."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .build_planner import ELEMENTS, MIX, SLOT_NAMES, TRIBE_ELEMENT, Build, Costs, Economy, Planner, Profile, Way

SOURCES = [("vendor", "Vendors"), ("chest", "Chests"), ("enemy", "Enemies"), ("craft", "Crafting"), ("quest", "Quests"),
           ("nick_cash", "NickCash"), ("unknown", "No known way")]
HOTBAR = [("melee", "Melee"), ("ranged", "Ranged"), ("stun", "Stun"), ("heal", "Heal"), ("poison", "Poison"), ("buff", "Buff")]
WHERE = ([("level", "Zones around my level"), ("all", "All zones"), ("zone", "This zone"), ("pick", "Zone:")]
         + [(el, el) for el in ELEMENTS] + [("blunt", "Blunt")])


@dataclass
class Options:
    level: int | None = None  # None: your level from the game
    defence: float = 0.3  # how much defence counts in the strength of a build (the upgrades per slot)
    slots: tuple[str, ...] = ("melee", "ranged")  # your hotbar template (HOTBAR keys)
    prefer: str | None = None  # build style: "melee", "ranged" (that weapon decides, accessories serve it) or None (hybrid)
    where: str = "level"  # WHERE keys: zones around your level, the zone you are in, or one attack element
    zone: str | None = None  # the zone you are in (for where == "zone")
    sources: set[str] = field(default_factory=lambda: {"vendor", "chest", "enemy", "craft", "quest"})
    look: int = 5  # the shop list looks this many levels above yours
    view: str = "progress"  # the middle column: "progress" (the best gear by level) or "shop" (the shop list)
    shop_tab: str = "Shadow"  # the shop list's tab: a tribe or "Armour"
    shop_group: str = "any"  # the armour tab's group: an element, "blunt" or "any"
    tribe: str | None = None  # the progression's badge tribe (None: your build's)
    effort: float | None = None  # the progression leaves out items that take more hours than this
    switch: float = 5.0  # the progression: what a change of an item must bring (percent of strength x levels)
    stage: int | None = None  # the level the progression shows (None: yours)
    time: float = 0.0  # the progression: what an hour of getting an item weighs (0: time is irrelevant)
    pick: str | None = None  # the zone chosen for where == "pick"
    excluded: set[str] = field(default_factory=set)  # prefabs of items you don't want: nothing suggests them

    @property
    def unknown(self) -> bool:
        """Items nobody knows how to get count too (the progression, the shop list)."""
        return "unknown" in self.sources

    @property
    def weapons(self) -> tuple[str, ...]:
        return tuple(s for s in self.slots if s in ("melee", "ranged")) or ("melee",)

    @property
    def utility(self) -> tuple[str, ...]:
        return tuple(s.capitalize() for s in self.slots if s in ("stun", "heal", "poison", "buff"))


class Builder:
    def __init__(self, root: Path):
        self.path = root / "builder.json"
        self._bundle: dict | None = None
        self._ids: dict[int, str] = {}

    @property
    def available(self) -> bool:
        return self.path.exists()

    @property
    def bundle(self) -> dict:
        if self._bundle is None:
            self._bundle = json.loads(self.path.read_text(encoding="utf-8"))
            self._ids = {it["id"]: p for p, it in self._bundle["items"].items() if it.get("id")}
        return self._bundle

    def item(self, prefab: str) -> dict:
        return self.bundle["items"].get(prefab) or {"prefab": prefab, "name": prefab}

    def zone_info(self, name: str | None) -> dict | None:
        z = self.bundle["zones"].get(name or "")
        if not z:
            for k, v in self.bundle["zones"].items():
                if k.lower() == (name or "").lower():
                    return v
        return z

    def level_of(self, snap: dict) -> int | None:
        xp = snap.get("xp")
        if xp is None:
            return None
        return 1 + sum(1 for t in self.bundle["stats"]["level_xp"] if t and xp >= t)

    def profile(self, snap: dict, opt: Options) -> Profile:
        """Your character as the planner sees it: inventory and worn gear (by item id), learned patterns (as owned
        patterns), level (yours from the game unless you set one), all skill points in one tribe (switching is free;
        one point per level until the game has sent yours),
        and where you fight."""
        self.bundle  # noqa: B018 (loads the id map)
        owned: dict[str, int] = {}
        for item_id, n in list(snap.get("inventory", {}).items()) + [(i, 1) for i in snap.get("worn", {}).values()]:
            p = self._ids.get(item_id)
            if p:
                owned[p] = owned.get(p, 0) + n
        for item_id in snap.get("recipes", ()):  # a learned pattern: crafting that item needs no pattern
            for w in self.bundle["ways"].get(self._ids.get(item_id) or "", []):
                if w["kind"] == "craft":
                    owned[w["pattern"]] = 1
        level = max(1, min(opt.level or snap.get("level") or self.level_of(snap) or 1, 60))
        target_level, target_element = None, MIX
        zone = opt.zone if opt.where == "zone" else opt.pick if opt.where == "pick" else None
        if self.zone_info(zone):
            z = self.zone_info(zone)
            target_level, target_element = z.get("level") or None, TRIBE_ELEMENT.get(z.get("tribe"))
        elif opt.where in ELEMENTS:
            target_element = opt.where
        elif opt.where == "blunt":
            target_element = None
        # skill points: yours from the game; until the game has told us, one per level (what the user's own
        # character has: level 27, 27 points)
        points = sum(snap["badges"].values()) if snap.get("badges") else level
        return Profile(level=level, owned=owned, skill_points=points, mix_all=opt.where == "all",
                       weapons=opt.weapons, prefer=opt.prefer if opt.prefer in opt.weapons else None,
                       defence_weight=opt.defence, target_level=target_level,
                       target_element=target_element)

    def planner(self, profile: Profile, opt: Options) -> tuple[Planner, Costs, list[Build]]:
        """A planner for these options and the menu of builds now. Drops are priced with your kill speed: first with
        an average one, then again with the kill time of what you own (the cheapest build)."""
        eco = Economy(nick_cash="nick_cash" in opt.sources,
                      sources=frozenset(opt.sources - {"nick_cash", "unknown"}) | ({"tribe_drop"} if "enemy" in opt.sources else set()))
        costs = Costs(self.bundle, eco)
        exclude = frozenset(opt.excluded)
        pl = Planner(self.bundle, costs.hours, eco, exclude)
        pl.unknown = opt.unknown
        menu = pl.menu(profile)
        if menu:
            eco.kill_time = max(0.5, min(menu[0].kill_time, 10.0))
            costs = Costs(self.bundle, eco)
            pl = Planner(self.bundle, costs.hours, eco, exclude)
            pl.unknown = opt.unknown
            menu = pl.menu(profile)
        return pl, costs, menu

    def plan(self, profile: Profile, opt: Options) -> tuple[list[Build], Costs]:
        pl, costs, menu = self.planner(profile, opt)
        return menu, costs

    def fight_zones(self) -> list[tuple[str, str]]:
        """Every zone with enemies, by level: (level name, "Title (Lv 12, Outlaw)")."""
        rows = []
        for z in self.bundle["fight_zones"]:
            info = self.bundle["zones"].get(z["zone"]) or {}
            rows.append((z["level"], info.get("title") or z["zone"], z["zone"], z.get("tribe") or ""))
        return [(name, f"{title} (Lv {level}, {tribe})") for level, title, name, tribe in sorted(rows)]

    def gear(self, snap: dict, profile: Profile, pl: Planner, badge: str | None = None) -> dict:
        """What you wear, from the game: "worn" (slot label -> item: your worn gear, and per hotbar weapon slot the
        strongest attack weapon on your hotbar), "tribe" (where your skill points are) and "better" (slot label ->
        an item you own and can use at your level that belongs to the best set you can put together from your bag
        with the settings you chose, where what you wear in that slot would do less). badge: the progression's
        Badge choice (a tribe; None or Auto: the tribe whose set from your bag kills fastest). Weapons and
        accessories are picked together (Planner.best_set), so with the badge in Outlaw a Fire weapon and Fire
        earrings from your bag are suggested as a pair, even if each alone does less with what you wear now.
        "bag_tribe": the tribe that set is for, "best": that set. Every swap that helps is named, however little (the user
        2026-10-05: "show better options all the time"); the build style (Options.prefer) decides which weapon the
        accessories serve."""
        self.bundle  # noqa: B018 (loads the id map)
        badges = snap.get("badges") or {}
        tribe = max(badges, key=badges.get) if any(badges.values()) else snap.get("tribe") or "Crossroads"
        if tribe not in pl.TRIBES:
            tribe = "Crossroads"
        worn: dict[str, dict] = {}
        hotbar: dict[str, list] = {}
        labels = pl.slot_labels(profile)
        for item_id in list((snap.get("worn") or {}).values()) + list((snap.get("hotbar") or {}).values()):
            it = pl.opt.item.get(self._ids.get(item_id) or "")
            label = pl.slot_label(it) if it else None
            if not label or not it["scaled_sum"] or label not in labels:
                continue
            if it["is_weapon"]:
                hotbar.setdefault(label, []).append(it)
            else:
                worn[label] = it
        for label, weapons in hotbar.items():  # of several (a stun weapon is one too): the one that kills fastest
            worn[label] = min(weapons, key=lambda it: pl.smooth_kill(worn | {label: it}, profile, tribe))
        armour = {SLOT_NAMES[s] for s in ("SlotHair", "SlotBody", "SlotLegs", "SlotBackpack")}

        pool: dict[str, list] = {}  # what you own and can use now, per slot (worn gear included)
        for it in list(worn.values()) + [pl.opt.item.get(p) for p in profile.owned]:
            label = pl.slot_label(it) if it else None
            if (not label or label not in labels or not it["scaled_sum"] or not it["name"]
                    or (it["level_req"] or 0) > profile.level or it["prefab"] in pl.opt.exclude):
                continue
            if all(it is not other for other, _ in pool.get(label, ())):
                pool.setdefault(label, []).append((it, 0.0))
        sets = [(t, pl.best_set(profile, t, pool)["picks"]) for t in ([badge] if badge in pl.TRIBES else pl.TRIBES)]
        bag_tribe, best = min(sets, key=lambda s: pl.smooth_kill(s[1], profile, s[0]))
        _, bag_def = pl.opt.badge_bonus(TRIBE_ELEMENT.get(bag_tribe), profile.skill_points)

        def taken(picks: dict) -> float:
            return pl.taken([it for k, it in picks.items() if k in armour], profile, bag_def)

        def kill(picks: dict) -> float:
            return pl.smooth_kill(picks, profile, bag_tribe)
        better = {}
        for label, it in best.items():
            have = worn.get(label)
            if it is have:
                continue
            score = taken if label in armour else kill
            back = {k: v for k, v in best.items() if k != label} | ({label: have} if have else {})
            if score(back) > score(best) + 1e-9:  # what you wear in this slot would make that set worse
                better[label] = it
        return {"worn": worn, "better": better, "tribe": tribe, "bag_tribe": bag_tribe, "best": best}

    @staticmethod
    def current(menu: list[Build]) -> dict:
        """Your best build from what you own (slot label -> item), or nothing."""
        if menu and menu[0].hours == 0:
            return {k: o.item for k, o in menu[0].picks.items() if o.item}
        return {}

    def guide(self, profile: Profile, opt: Options, snap: dict | None = None) -> dict:
        """Everything Build mode shows (a second or two: run it off the GUI thread). "now": what you wear (gear();
        without anything from the game: the best set from what you own, gear()'s "best", ranked like the
        progression), "gear": gear(), "prices": hours to get every item (Planner.price_table), which the
        progression is worked out from."""
        pl, costs, menu = self.planner(profile, opt)
        gear = self.gear(snap or {}, profile, pl, opt.tribe)
        known = bool(gear["worn"])
        now = gear["worn"] if known else gear["best"]
        tribe = gear["tribe"] if known else gear["bag_tribe"] if now else None
        ev = pl.evaluate(now, profile, tribe=tribe) if now else None
        element = TRIBE_ELEMENT.get(tribe)
        badge = pl.opt.badge_bonus(element, profile.skill_points) if element else (0, 0)
        return {"now": now, "now_ev": ev, "gear": gear, "costs": costs, "menu": menu, "planner": pl,
                "prices": pl.price_table(profile),
                "slots": pl.slot_upgrades(profile, now, 10), "utility": pl.utility(profile, now, opt.utility),
                "tribe": tribe, "badge": badge, "no_way": self.no_way(profile, costs, opt.excluded),
                "shop": self.shop_list(pl, costs, profile, now, opt)}

    @staticmethod
    def shop_list(pl: Planner, costs: Costs, profile: Profile, now: dict, opt: Options) -> dict:
        """The planner's shop list (Planner.recommend) with the cheapest way to get each listed item ("way")."""
        shop = pl.recommend(profile, now, ahead=max(0, opt.look))
        lists = [rows for t in shop["tribes"].values() for group in (t["weapons"], t["accessories"]) for rows in group.values()]
        lists += [rows for a in shop["armour"].values() for rows in a["slots"].values()]
        for rows in lists:
            for r in rows:
                r["way"] = None if r["owned"] or r["hours"] == float("inf") else costs.best(r["item"]["prefab"], profile)
        return shop

    def icon_named(self, name: str) -> Path | None:
        """The icon of the item with this name (for the hotbar chips)."""
        return next((self.icon(p) for p, it in self.bundle["items"].items() if it.get("name") == name), None)

    def crest(self, tribe: str) -> Path:
        return self.path.parent / "art" / "crests" / f"{tribe.lower()}.png"

    def icon(self, prefab: str) -> Path | None:
        rel = (self.bundle["items"].get(prefab) or {}).get("icon")
        return self.path.parent / "art" / rel if rel else None

    def no_way(self, profile: Profile, costs: Costs, excluded: set[str] | frozenset = frozenset()) -> list[tuple[dict, str]]:
        """Gear and weapons up to your level with no known way to get them, strongest first: (item, reason)."""
        out = []
        for p, it in self.bundle["items"].items():
            if not (it.get("is_gear") or it.get("is_weapon")) or not it.get("scaled_sum") or profile.owned.get(p):
                continue
            if p in excluded:
                continue
            if (it.get("level_req") or 0) > profile.level or (it.get("level_req") or 0) < profile.level - 15:
                continue
            why = costs.why_not(p)
            if why:
                out.append((it, "no one knows where its pattern comes from" if why == "pattern" else "no known source"))
        return sorted(out, key=lambda x: (-(x[0].get("scaled_sum") or 0), x[0].get("name") or ""))


def slot_order(label: str) -> int:
    order = ["Melee", "Ranged"] + list(SLOT_NAMES.values()) + ["Stun", "Heal", "Poison", "Buff"]
    return order.index(label) if label in order else 99


def way_text(w: Way) -> str:
    """Short: "Craft (Plans) · 18 h · 3,500 bananas"."""
    bits = [w.label]
    if w.kind != "owned":
        bits.append(duration(w.hours))
    if w.days >= 0.5:
        bits.append(f"{w.days:.0f} days")
    if w.bananas:
        bits.append(f"{w.bananas:,} bananas")
    if w.nick_cash:
        bits.append(f"{w.nick_cash:,} NC")
    return " · ".join(bits)


def way_short(w: Way | None) -> str:
    """The way without its hours: "Buy from Smith in Zone A · 3,500 bananas"."""
    if w is None:
        return "no known way"
    bits = [w.label]
    if w.days >= 0.5:
        bits.append(f"{w.days:.0f} days")
    if w.bananas:
        bits.append(f"{w.bananas:,} bananas")
    if w.nick_cash:
        bits.append(f"{w.nick_cash:,} NC")
    return " · ".join(bits)


def duration(hours: float) -> str:
    if hours == float("inf"):
        return "no known way"
    if hours < 1 / 60:
        return "now" if hours <= 0 else "a moment"
    if hours < 1:
        return f"{hours * 60:.0f} min"
    return f"{hours:.1f} h"
