# GENERATED: a copy of MonkeyQuest/scripts/build_planner.py, written by its export_overlay.py.
# Edit it there and re-export; changes here are overwritten.
"""Build planner for MQReborn: from what you own, a menu of builds (how strong vs how many hours to get the missing
pieces) and later the fastest route to a level. Uses the damage and defence model of build_optimizer.py.

Strength of a build at your level (enemies of your level, or a target):
- kill time: per weapon of your hotbar template, hits to kill × cooldown (build_optimizer's model), averaged over the
  template's weapons; the reference is a plain hit of your ability power every second.
- damage taken: per attack element of the zones around your level (a general build) or the target's element,
  max(floor, enemy ability power − your defence against it); the floor (10 % of the enemy's ability power) stands in
  for MQReborn's unknown minimum damage (UNVERIFIED). Reference: your base defence, no armour.
- strength = (1 − w) · reference kill time / kill time + w · reference damage taken / damage taken, w = how much you
  care about defence (0 = only kill speed). 1.0 = a naked monkey; 2.0 = twice as good.

The tribe follows the build: all skill points sit in one tribe and switching is free (patch 1.7.4), so each build gets
the tribe whose element helps its weapons most (badge damage only counts for weapons of the tribe's element; badge
defence counts against everything).

Search: per slot, only the items that are not worse and not more expensive than another (Pareto lists of hours vs
value); the accessories are merged per "focus" element (their element lines only help weapons of that element), the
weapons per class, then damage with armour. What is left is every build that no other build beats on both hours and
strength; the menu shows the points where the best build changes.

The shop list (recommend()) is the broad view next to that: per tribe the weapons of its element (with the badge
damage you would get there), accessories per element and armour per resist element, each with what it adds to your
build (hit, hits to kill, kill time, damage taken per attack element), hours to get and "from level X"; only cut to
what beats what you wear, never to one item per slot.

The progression (progression(), stage()) is the view over all levels, without any model of how fast you level: per
tribe badge the strongest full set at every level (all slots together; skill points grow one per level), then a search
over all levels for the lanes per slot that lose the least against those sets when every change of an item has a cost
(smooth(): so an item that is 1 % better for one level never shows, and time to get counts only if asked for), and
for any level every alternative per slot with what it costs you against the best set and how hard it is to get
(effort()). Costs.find() lists the zones an item is in.

Self-contained (standard library only), working on the data bundle of scripts/builder_data.py, so the overlay can run
this very file on your live inventory (export_overlay.py copies it there; edit it here only)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

ELEMENTS = ["Air", "Earth", "Fire", "Ice", "Lightning"]
TRIBE_ELEMENT = {"Shadow": "Air", "Bone": "Earth", "Outlaw": "Fire", "Wild": "Ice", "Grease": "Lightning"}
ELEMENT_TRIBE = {v: k for k, v in TRIBE_ELEMENT.items()}
DAMAGE_SLOTS = ["SlotEars", "SlotWrist", "SlotTail"]
DEFENCE_SLOTS = ["SlotHair", "SlotBody", "SlotLegs", "SlotBackpack"]
SLOT_NAMES = {"SlotEars": "Ears", "SlotWrist": "Wrist", "SlotTail": "Tail", "SlotHair": "Hat", "SlotBody": "Body",
              "SlotLegs": "Legs", "SlotBackpack": "Backpack"}
ATTACK_ACTIONS = ("Melee", "Throw", "DamageZone")
MIX = "mix"  # attack element of a general build: the zones around your level
WEAPON_CLASSES = ("melee", "ranged")
SIDE_WEIGHT = 0.02  # a build style (Profile.prefer): how much the other hotbar weapon's kill time still counts
DAMAGE_FLOOR = 0.10  # share of the enemy's ability power you always take (stand-in for MQReborn's minimum, UNVERIFIED)
REFERENCE_COOLDOWN = 1.0
LEVEL_CAP = 60  # the last level: what you wear there you keep for good
CAP_WEIGHT = 1e6  # progression: how much the last level counts against any other (stands in for "forever")
EPS = 1e-9


@dataclass
class Profile:
    level: int
    owned: dict[str, int] = field(default_factory=dict)  # prefab -> count (inventory and worn gear)
    skill_points: int = 0
    weapons: tuple[str, ...] = WEAPON_CLASSES  # weapon slots of the hotbar template ("melee", "ranged")
    prefer: str | None = None  # build style: "melee" or "ranged" (that weapon decides, the other counts SIDE_WEIGHT),
    #                            None = hybrid (both weapons count the same; the user 2026-10-05: a choice per style)
    defence_weight: float = 0.3
    target_level: int | None = None
    target_element: str | None = MIX  # an element, None for blunt attackers, MIX for the zones around your level
    mix_all: bool = False  # MIX: every fight zone of the game instead of the ones around your level


@dataclass
class Option:
    """One choice for one slot: an item (or nothing) with the hours it takes to get."""
    slot: str
    item: dict | None
    hours: float

    @property
    def prefab(self) -> str | None:
        return self.item["prefab"] if self.item else None


@dataclass
class Build:
    hours: float
    strength: float
    kill_time: float
    damage_taken: float
    tribe: str | None
    picks: dict[str, Option]  # slot label -> option
    hits: dict[str, dict] = field(default_factory=dict)  # weapon class -> {"hit", "hits", "time"}
    w_lo: float | None = None  # tradeoffs(): defence weights where this build is the strongest
    w_hi: float | None = None
    w_pick: float | None = None  # tradeoffs(): the weight where it comes closest to the best

    def missing(self) -> list[Option]:
        return [o for o in self.picks.values() if o.item and o.hours > 0]


def pareto(points: list, cost: Callable, value: Callable) -> list:
    """Points that no other point beats with less or equal cost and more or equal value (ties: the first one)."""
    out, best = [], -math.inf
    for p in sorted(points, key=lambda p: (cost(p), -value(p))):
        v = value(p)
        if v > best + EPS:
            out.append(p)
            best = v
    return out


def pareto3(points: list, cost: Callable, a: Callable, b: Callable) -> list:
    """Pareto set on (cost low, a high, b high)."""
    out: list = []
    for p in sorted(points, key=lambda p: (cost(p), -a(p), -b(p))):
        if not any(a(q) >= a(p) - EPS and b(q) >= b(p) - EPS for q in out):
            out.append(p)
    return out


def weapon_class(w: dict) -> str:
    return "melee" if w.get("action_type") == "Melee" else "ranged"


def weapon_weights(p: Profile) -> dict[str, float]:
    """How much each hotbar weapon's kill time counts in a set's ranking: the build style's weapon fully, the other
    one SIDE_WEIGHT (so it is still chosen well for its own slot, but accessories serve the preferred weapon)."""
    return {c: 1.0 if p.prefer in (None, c) else SIDE_WEIGHT for c in p.weapons}


class Model:
    """The game numbers from the bundle: stats per level, badges, the attack elements of the zones."""

    def __init__(self, bundle: dict, exclude: frozenset = frozenset()):
        """exclude: prefabs the search leaves out (items you don't want); they stay in `item` for lookups."""
        self.b = bundle
        self.exclude = frozenset(exclude)
        # the bundle leaves out empty fields; fill them so the search can index every item the same way
        blank = dict.fromkeys(("name", "subcategory", "element", "action_type", "currency", "rarity"), None) | dict.fromkeys(
            ("level_req", "cooldown", "price", "scaled_blunt", "scaled_element", "scaled_defence", "scaled_resist",
             "scaled_sum", "is_weapon", "is_gear"), 0)
        self.item = {p: blank | it for p, it in bundle["items"].items()}
        self.items = [it for p, it in self.item.items() if p not in self.exclude
                      and ((it["is_weapon"] and it["action_type"] in ATTACK_ACTIONS) or it["subcategory"] in SLOT_NAMES)]

    def stat(self, effect: str, grp: str, level: int) -> int:
        table = {("AbilityPower", "Player"): ("player", "ap"), ("Defence", "Player"): ("player", "defence"),
                 ("IncreaseHitPoints", "Player"): ("player", "hp"), ("AbilityPower", "Enemy"): ("enemy", "ap"),
                 ("IncreaseHitPoints", "Enemy"): ("enemy", "hp"), ("IncreaseExperience", "Enemy"): ("enemy", "xp")}[(effect, grp)]
        return self.b["stats"][table[0]][table[1]][max(1, min(level, 65)) - 1]

    def badge_bonus(self, element: str | None, skill_points: int) -> tuple[int, int]:
        """(damage, defence) from skill points in one tribe: badge level = points // 5 (confirmed in-game 2026-10-01)."""
        level = skill_points // 5
        if not element or level < 1:
            return 0, 0
        i = min(level, 65) - 1
        return self.b["stats"]["badge_damage"][element][i], self.b["stats"]["badge_defence"][element][i]

    def zone_mix(self, lo: int, hi: int) -> dict:
        """Share of attack elements (None = blunt) among the fight zones with a level in [lo, hi]."""
        cache = self.__dict__.setdefault("_mixes", {})
        if (lo, hi) not in cache:
            zs = [z for z in self.b["fight_zones"] if lo <= z["level"] <= hi] or self.b["fight_zones"]
            counts: dict = {}
            for z in zs:
                el = TRIBE_ELEMENT.get(z["tribe"])
                counts[el] = counts.get(el, 0) + 1
            cache[(lo, hi)] = {el: c / len(zs) for el, c in counts.items()}
        return cache[(lo, hi)]

    @staticmethod
    def acc_score(it: dict, element: str | None) -> int:
        """An accessory's damage for a weapon of `element`: blunt always, its element line only for that element."""
        return (it.get("scaled_blunt") or 0) + ((it.get("scaled_element") or 0) if element and it.get("element") == element else 0)

    @staticmethod
    def resist_weights(mix: dict) -> dict:
        """How often a resist line of each element counts: against its own element and against blunt attacks."""
        return {el: mix.get(el, 0) + mix.get(None, 0) for el in ELEMENTS}

    @staticmethod
    def armour_score(it: dict, element: str | None, weights: dict | None = None) -> float:
        """Defence of an armour piece against an attack element (blunt: every resist line counts; MIX: resist lines
        weighted by how often they count)."""
        res = it.get("scaled_resist") or 0
        if element == MIX:
            return (it.get("scaled_defence") or 0) + res * (weights or {}).get(it.get("element"), 0)
        return (it.get("scaled_defence") or 0) + (res if (element is None or it.get("element") == element) else 0)


# Bananas per hour at your level in the best trail of your level (research 2026-10-04, knowledge/MECHANICS.md 4.7):
# banana pickups, and pickups plus selling all the loot (sell price = 10 % of the buy price). UNVERIFIED estimates.
BANANAS_PICKUP = [(1, 2270), (5, 2300), (10, 1700), (20, 1520), (30, 1570), (40, 1580), (50, 1600), (60, 1470)]
BANANAS_SELLING = [(1, 3130), (5, 3200), (10, 3430), (20, 5550), (30, 9300), (40, 10500), (50, 14500), (60, 17100)]
ENEMY_ROLL = 0.25  # chance of a roll on the tiered tribe table per kill (1.6.3.2; more with stars)


def interpolate(table: list[tuple[int, float]], x: float) -> float:
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def tier_shares(level: int) -> tuple[float, float, float]:
    """Which tier an enemy's tribe roll uses, by enemy level (MQReborn 1.6.3.2)."""
    return (1.0, 0.0, 0.0) if level < 20 else (0.66, 0.34, 0.0) if level < 40 else (0.3, 0.6, 0.1)


@dataclass
class Economy:
    """How fast you earn things (research 2026-10-04; UNVERIFIED estimates, knowledge/OPEN_QUESTIONS.md M17)."""
    sell_loot: bool = True  # bananas from selling loot count (else only banana pickups)
    kill_time: float = 3.0  # seconds per kill (the planner uses your current build's)
    move_factor: float = 1.6  # walking a trail takes this times the straight tour (jumps, detours)
    quest_minutes: float = 12.0  # one quest, walking included
    quest_xp_share: float = 0.5  # share of leveling XP from quests (gear doesn't speed it up; UNVERIFIED)
    kill_overhead: float = 10.0  # seconds between kills: walking, engaging (the run model: ~10-15 s an enemy)
    nick_cash: bool = False  # count NickCash shop items
    nick_cash_per_day: float = 400.0  # from daily quests and daily boxes (capped per day)
    day_hours: float = 0.5  # how much one day of waiting (daily boxes, NickCash) weighs, in hours of play
    sources: frozenset = frozenset({"vendor", "chest", "enemy", "tribe_drop", "craft", "quest"})

    def bananas_per_hour(self, level: int) -> float:
        return interpolate(BANANAS_SELLING if self.sell_loot else BANANAS_PICKUP, level)

    def run_minutes(self, run: dict | None) -> float:
        """One run through a trail: walking its tour (every banana, enemy, spawner, idol, chest and breakable),
        fighting (3 s to engage each enemy; a spawner: 3 hits and one enemy, 7 s spawn cadence), opening (chest 3 s,
        breakable 1.5 s) and 40 s to leave and come back (everything resets when you re-enter)."""
        if not run:
            return 10.0
        k = self.kill_time
        secs = (self.move_factor * run["tour"] / 6 + run["enemies"] * (k + 3) + run["spawners"] * (1.5 + k + 7)
                + 3 * run["chests"] + 1.5 * run["breakables"] + 40)
        return secs / 60


@dataclass
class Way:
    """One way to get an item, priced: hours of play, plus bananas and NickCash spent (hours already include the time
    to farm the bananas)."""
    kind: str  # owned, vendor, chest, enemy, tribe_drop, craft, quest
    hours: float
    bananas: int = 0
    nick_cash: int = 0
    days: float = 0.0  # days of waiting (daily boxes, NickCash income)
    label: str = ""
    where: list = field(default_factory=list)  # [{"zone", "at", "label"}] places on the map
    parts: list = field(default_factory=list)  # craft: [(prefab, needed, owned, Way | None)]
    raw: dict | None = None


class Costs:
    """Hours to get any item from its ways (bundle["ways"]): the cheapest way, worked out recursively for crafting.

    vendor   price / bananas per hour at your level (NickCash: only with Economy.nick_cash, as days of NC income)
    chest    1 / chance runs of its zone (chests and breakables reset when you re-enter); daily boxes and gathering
             spots: 1 / chance days
    enemy    1 / (chance × that monster's count in the zone) runs, in the zone where that is fastest; the drop line
             must allow the zone's level
    tribe_drop  the tiered tribe table: 25 % roll per kill × the item's share of the tier at the zone's level,
             over all enemies of a zone of that tribe
    craft    the pattern (unless you own it) + every missing ingredient at its own cheapest way
    quest    the quest and the quests before it in its line × quest_minutes
    Owned items cost 0. None = no known way (no ways, or a pattern nobody knows where to get)."""

    def __init__(self, bundle: dict, economy: Economy | None = None):
        self.b = bundle
        self.eco = economy or Economy()
        self.memo: dict = {}
        self.profile: Profile | None = None

    def title(self, zone: str | None) -> str:
        return (self.b["zones"].get(zone or "") or {}).get("title") or zone or "?"

    def name(self, prefab: str) -> str:
        return (self.b["items"].get(prefab) or {}).get("name") or prefab

    def run_hours(self, zone: str) -> float:
        return self.eco.run_minutes((self.b["zones"].get(zone) or {}).get("run")) / 60

    def cost(self, w: Way) -> float:
        """What the planner minimises: hours of play plus the waiting days, weighted."""
        return w.hours + w.days * self.eco.day_hours

    def price(self, w: dict, p: Profile, stack: frozenset) -> Way | None:
        k = w["kind"]
        if k not in self.eco.sources:
            return None
        if k == "vendor":
            who = f"{w['vendor'] or 'a vendor'} in {self.title(w['zone'])}"
            where = [{"zone": w["zone"], "at": w["at"], "label": w["vendor"] or "Vendor"}]
            if w["currency"] == "Banana":
                return Way("vendor", w["price"] / self.eco.bananas_per_hour(p.level), bananas=w["price"],
                           label=f"Buy from {who}", where=where, raw=w)
            if w["currency"] == "NickCash" and self.eco.nick_cash:
                return Way("vendor", 0.0, nick_cash=w["price"], days=w["price"] / self.eco.nick_cash_per_day,
                           label=f"Buy from {who}", where=where, raw=w)
            return None
        if k == "chest":
            if not w["chance"] or not w["zone"]:
                return None
            what = {"harvest": "Gathering spot", "breakable": "Breakable"}.get(w["cat"], "Chest")
            where = [{"zone": w["zone"], "at": w["at"], "label": what}]
            if w.get("daily"):  # once a day: days of waiting, a short visit each day
                return Way("chest", 0.1 / w["chance"], days=1 / w["chance"], where=where, raw=w,
                           label=f"Daily {what.lower()} in {self.title(w['zone'])} ({w['chance'] * 100:.3g} % a day)")
            return Way("chest", self.run_hours(w["zone"]) / w["chance"],
                       label=f"{what} in {self.title(w['zone'])} ({w['chance'] * 100:.3g} %)", where=where, raw=w)
        if k == "enemy":
            best = None
            for zone, count, at in w["zones"]:
                zl = (self.b["zones"].get(zone) or {}).get("level") or 0
                if not w["chance"] or not (w["min_level"] or 0) <= zl <= (w["max_level"] or 99):
                    continue
                h = self.run_hours(zone) / (w["chance"] * (count or 1))  # a spawner's enemy: about 1 per run
                if best is None or h < best[0]:
                    best = (h, zone, at)
            if best is None:
                return None
            h, zone, at = best
            places = [{"zone": z, "at": a, "label": f"{w['name'] or 'Enemy'} ×{c or '?'}"} for z, c, a in w["zones"]]
            places.sort(key=lambda d: d["zone"] != zone)
            return Way("enemy", h, label=f"{w['name']} drop ({w['chance'] * 100:.3g} %), best in {self.title(zone)}",
                       where=places, raw=w)
        if k == "tribe_drop":
            best = None
            for zone, kills in w["zones"]:
                zl = (self.b["zones"].get(zone) or {}).get("level") or 0
                per_kill = ENEMY_ROLL * sum(s * c for s, c in zip(tier_shares(zl), w["tiers"]))
                if per_kill > 0 and kills:
                    h = self.run_hours(zone) / (per_kill * kills)
                    if best is None or h < best[0]:
                        best = (h, zone, per_kill)
            if best is None:
                return None
            h, zone, per_kill = best
            return Way("tribe_drop", h, raw=w, where=[{"zone": zone, "at": None, "label": f"{w['tribe']} enemies"}],
                       label=f"Any {w['tribe']} enemy ({per_kill * 100:.2g} % a kill), best in {self.title(zone)}")
        if k == "quest":
            return Way("quest", (w["chain"] + 1) * self.eco.quest_minutes / 60,
                       label=f"Quest reward: {w['title']}" + (f" (after {w['chain']} quests)" if w["chain"] else ""),
                       where=[{"zone": w["zone"], "at": None, "label": w["title"]}] if w["zone"] else [], raw=w)
        if k == "craft":
            # patterns are learned for good and only the ingredients are used up (UICrafting.cs:824-835, UseItem.cs)
            parts, hours, bananas, nc, days = [], 0.0, 0, 0, 0.0
            pat = w["pattern"]
            if not p.owned.get(pat):
                pw = self.best(pat, p, stack)
                if pw is None:
                    return None
                parts.append((pat, 1, 0, pw))
                hours, bananas, nc, days = pw.hours, pw.bananas, pw.nick_cash, pw.days
            for prefab, n in w["parts"]:
                have = min(n, p.owned.get(prefab, 0))
                if have >= n:
                    parts.append((prefab, n, have, None))
                    continue
                pw = self.best(prefab, p, stack, buy_more=True)
                if pw is None:
                    return None
                miss = n - have
                parts.append((prefab, n, have, pw))
                hours += miss * pw.hours
                bananas += miss * pw.bananas
                nc += miss * pw.nick_cash
                days = max(days, miss * pw.days)  # daily sources run side by side
            return Way("craft", hours, bananas, nc, days, label=f"Craft ({w['station'] or 'crafting'})", parts=parts, raw=w)
        return None

    def ways(self, prefab: str, p: Profile, stack: frozenset = frozenset(), buy_more: bool = False) -> list[Way]:
        """Every way to get the item, cheapest first (an owned item: just "owned"; buy_more: the price of one more,
        for crafting parts you have too few of)."""
        if p.owned.get(prefab) and not buy_more:
            return [Way("owned", 0.0, label="In your inventory")]
        if prefab in stack:
            return []
        groups: dict = {}  # the chests of one zone are all opened in the same run
        for r in self.b["ways"].get(prefab, []):
            key = (r["zone"], r["cat"], bool(r.get("daily"))) if r["kind"] == "chest" and r.get("chance") and r.get("zone") else id(r)
            groups.setdefault(key, []).append(r)
        out = [w for w in ((self.price(rs[0], p, stack | {prefab}) if len(rs) == 1 else self.chests(rs))
                           for rs in groups.values()) if w]
        return sorted(out, key=lambda w: (self.cost(w), w.nick_cash))

    CHEST_WORDS = {"harvest": ("Gathering spot", "gathering spots"), "breakable": ("Breakable", "breakables")}

    def chests(self, rs: list[dict]) -> Way | None:
        """Several chests (or breakables, gathering spots) of one zone that can hold the item: one run opens them
        all, so the chance a run is 1 - the chance that every one misses."""
        if "chest" not in self.eco.sources:
            return None
        zone = rs[0]["zone"]
        one, many = self.CHEST_WORDS.get(rs[0]["cat"], ("Chest", "chests"))
        miss = 1.0
        for r in rs:
            miss *= 1 - min(r["chance"], 1.0)
        chance = max(1 - miss, 1e-9)
        where = [{"zone": zone, "at": r["at"], "label": f"{one} ({r['chance'] * 100:.3g} %)"} for r in rs]
        if rs[0].get("daily"):
            return Way("chest", 0.1 / chance, days=1 / chance, where=where, raw=rs[0],
                       label=f"{len(rs)} daily {many} in {self.title(zone)} ({chance * 100:.3g} % a day)")
        return Way("chest", self.run_hours(zone) / chance, where=where, raw=rs[0],
                   label=f"{len(rs)} {many} in {self.title(zone)} ({chance * 100:.3g} % a run)")

    def find(self, prefab: str) -> list[dict]:
        """Where the item itself can be found, zone by zone (like the map search): [{"zone", "title", "level",
        "spots" (how many chests, enemies, ... have it), "text"}], most spots first. Crafting is not a place."""
        zones: dict[str, dict] = {}

        def add(zone: str | None, word: str, n: int = 1) -> None:
            if zone:
                counts = zones.setdefault(zone, {})
                counts[word] = counts.get(word, 0) + n
        for r in self.b["ways"].get(prefab, []):
            k = r["kind"]
            if k == "chest":
                add(r["zone"], self.CHEST_WORDS.get(r["cat"], ("Chest", "chests"))[1])
            elif k == "enemy":
                for zone, count, _ in r["zones"]:
                    add(zone, r["name"] or "enemies", count or 1)
            elif k == "tribe_drop":
                for zone, kills in r["zones"]:
                    add(zone, f"{r['tribe']} enemies", kills or 1)
            elif k == "vendor":
                add(r["zone"], f"sold by {r['vendor'] or 'a vendor'}", 0)
            elif k == "quest":
                add(r["zone"], f"quest: {r['title']}", 0)
        out = []
        for zone, counts in zones.items():
            z = self.b["zones"].get(zone) or {}
            text = ", ".join(f"{n} {word}" if n else word for word, n in sorted(counts.items(), key=lambda x: -x[1]))
            out.append({"zone": zone, "title": self.title(zone), "level": z.get("level"), "spots": sum(counts.values()),
                        "text": text})
        return sorted(out, key=lambda d: (-d["spots"], d["title"]))

    def best(self, prefab: str, p: Profile, stack: frozenset = frozenset(), buy_more: bool = False) -> Way | None:
        if p is not self.profile:  # prices depend on the profile (level, what you own)
            self.profile, self.memo = p, {}
        key = (prefab, buy_more)
        if key not in self.memo:
            ws = self.ways(prefab, p, stack, buy_more)
            if stack and not ws and prefab in stack:
                return None  # a crafting loop: don't remember the dead end
            self.memo[key] = ws[0] if ws else None
        return self.memo[key]

    def hours(self, it: dict, p: Profile) -> float | None:
        """The planner's price of an item: hours plus weighted waiting days (cost())."""
        w = self.best(it["prefab"], p)
        return None if w is None else self.cost(w)

    def why_not(self, prefab: str) -> str | None:
        """Why an item has no known way: "pattern" (craft only, and nobody knows where its pattern comes from) or
        "unknown" (no source at all). None if there is a way (maybe not with the chosen sources)."""
        raw = self.b["ways"].get(prefab, [])
        if not raw:
            return "unknown"
        if all(r["kind"] == "craft" for r in raw) and all(not self.b["ways"].get(r["pattern"]) for r in raw):
            return "pattern"
        return None


def effort(way: Way | None, hours: float | None) -> tuple[str, str]:
    """How an item is got and how hard that is, in a few words: ("buy", "easy"), ("enemy drop", "long farm"), ..."""
    if way is None or hours is None:
        return "no known way", ""
    if way.kind == "owned":
        return "you have it", ""
    raw = way.raw or {}
    kind = {"vendor": "NickCash shop" if way.nick_cash else "buy", "enemy": "enemy drop", "tribe_drop": "enemy drop",
            "craft": "craft", "quest": "quest",
            "chest": ("daily " if way.days >= 0.5 else "") + {"harvest": "gathering", "breakable": "breakable"}.get(raw.get("cat"), "chest")}[way.kind]
    if way.days >= 2:
        return kind, f"{way.days:.0f} days of waiting"
    grade = "easy" if hours < 1 else "some farming" if hours < 5 else "long farm" if hours < 20 else "very long farm"
    return kind, grade


class Planner:
    def __init__(self, bundle: dict, hours: Callable[[dict, Profile], float | None], economy: Economy | None = None,
                 exclude: frozenset = frozenset()):
        """hours(item, profile): hours of play to get the item (0 if owned), None if there is no known way.
        exclude: prefabs of items you don't want: no search, list or lane shows them."""
        self.opt = Model(bundle, exclude)
        self.hours = hours
        self.eco = economy or Economy()
        self.unknown = False  # the shop list (recommend()) also lists items with no known way (hours: infinite)

    # ------------------------------------------------------------------ candidates
    def options(self, slot_filter: Callable[[dict], bool], p: Profile) -> list[Option]:
        out = []
        for it in self.opt.items:
            if not slot_filter(it) or (it["level_req"] or 0) > p.level or not it["scaled_sum"] or not it["name"]:
                continue
            h = 0.0 if p.owned.get(it["prefab"]) else self.hours(it, p)
            if h is not None:
                out.append(Option("", it, h))
        return out

    # ------------------------------------------------------------------ model
    def enemy(self, p: Profile) -> tuple[int, int, int]:
        tl = p.target_level or p.level
        return tl, self.opt.stat("IncreaseHitPoints", "Enemy", tl), self.opt.stat("AbilityPower", "Enemy", tl)

    def attack_mix(self, p: Profile) -> dict:
        tl = p.target_level or p.level
        if p.target_element == MIX:
            return self.opt.zone_mix(0, 999) if p.mix_all else self.opt.zone_mix(tl - 5, tl + 5)
        return {p.target_element: 1.0}

    @staticmethod
    def kill_time(hit: float, hp: int, cooldown: float | None) -> tuple[int, float]:
        hits = math.ceil(hp / hit) if hit > 0 else 10**6
        return hits, hits * max(cooldown or 0, 0.5)

    def weapon_hit(self, w: dict, base: float) -> float:
        hit = base + (w["scaled_sum"] or 0)
        return round(0.5 * hit) if w["action_type"] == "DamageZone" else hit  # damage zones: 50 % per tick (1.7.5)

    def taken(self, armour: list[dict], p: Profile, badge_def: int) -> float:
        _, _, enemy_ap = self.enemy(p)
        base = self.opt.stat("Defence", "Player", p.level) + badge_def
        total = 0.0
        for el, share in self.attack_mix(p).items():
            d = base + sum(self.opt.armour_score(a, el) for a in armour)
            total += share * max(DAMAGE_FLOOR * enemy_ap, enemy_ap - d)
        return total

    def reference(self, p: Profile) -> tuple[float, float]:
        _, hp, enemy_ap = self.enemy(p)
        ap = self.opt.stat("AbilityPower", "Player", p.level)
        ref_kill = self.kill_time(ap, hp, REFERENCE_COOLDOWN)[1]
        ref_taken = max(DAMAGE_FLOOR * enemy_ap, enemy_ap - self.opt.stat("Defence", "Player", p.level))
        return ref_kill, ref_taken

    def strength(self, kill: float, taken: float, p: Profile, w: float | None = None) -> float:
        """How many times better than no gear: kill speed and toughness ratios combined as a weighted product
        (geometric mean), so a build that is good at both can beat one that is great at one (a weighted sum only
        ever picks the two ends of the trade-off)."""
        ref_kill, ref_taken = self.reference(p)
        w = p.defence_weight if w is None else w
        return (ref_kill / kill) ** (1 - w) * (ref_taken / taken) ** w

    # ------------------------------------------------------------------ search
    def damage_frontier(self, p: Profile) -> list[dict]:
        """Pareto list (hours, kill time) of weapon + accessory sets, each with its tribe."""
        _, hp, _ = self.enemy(p)
        ap = self.opt.stat("AbilityPower", "Player", p.level)
        slots = {s: self.options(lambda it, s=s: it["subcategory"] == s, p) for s in DAMAGE_SLOTS}
        weapons = {c: self.options(lambda it, c=c: it["is_weapon"] and it["action_type"] in ("Melee", "Throw", "DamageZone")
                                   and weapon_class(it) == c, p) for c in p.weapons}
        results = []
        weights = weapon_weights(p)
        for focus in ELEMENTS + [None]:
            # accessory sets as (hours, blunt, element lines of the focus element); "nothing" is always allowed
            acc = [((), 0.0, 0, 0)]
            for s in DAMAGE_SLOTS:
                opts = [Option(SLOT_NAMES[s], None, 0.0)] + [Option(SLOT_NAMES[s], o.item, o.hours) for o in slots[s]]
                per = pareto3(opts, lambda o: o.hours, lambda o: (o.item or {}).get("scaled_blunt") or 0,
                              lambda o, f=focus: ((o.item or {}).get("scaled_element") or 0) if f and o.item and o.item["element"] == f else 0)
                merged = [(picks + (o,), h + o.hours, b + ((o.item or {}).get("scaled_blunt") or 0),
                           e + (((o.item or {}).get("scaled_element") or 0) if focus and o.item and o.item["element"] == focus else 0))
                          for picks, h, b, e in acc for o in per]
                acc = pareto3(merged, lambda t: t[1], lambda t: t[2], lambda t: t[3])
            for tribe in ELEMENTS:
                badge_dmg, _ = self.opt.badge_bonus(tribe, p.skill_points)
                # per weapon class: Pareto (hours, own damage) separately for weapons of the focus element and others
                wl = {}
                for c, opts in weapons.items():
                    def own(o, t=tribe, b=badge_dmg):
                        return (o.item["scaled_sum"] or 0) + (b if o.item["element"] == t else 0)
                    same = pareto([o for o in opts if focus and o.item["element"] == focus], lambda o: o.hours, own)
                    other = pareto([o for o in opts if not (focus and o.item["element"] == focus)], lambda o: o.hours, own)
                    wl[c] = same + other
                for picks, ah, b, e in acc:
                    per_class = {}
                    for c, opts in wl.items():
                        rows = []
                        for o in opts:
                            w = o.item
                            base = ap + b + (e if focus and w["element"] == focus else 0) + (badge_dmg if w["element"] == tribe else 0)
                            hit = self.weapon_hit(w, base)
                            hits, t = self.kill_time(hit, hp, w["cooldown"])
                            rows.append((o, hit, hits, t))
                        per_class[c] = pareto(rows, lambda r: r[0].hours, lambda r: -r[3])
                    combos = [((), ah, 0.0)]
                    for c, weight in weights.items():
                        combos = [(cs + ((c, r),), h + r[0].hours, t + weight * r[3]) for cs, h, t in combos for r in per_class.get(c, [])]
                    for cs, h, t in combos:
                        results.append({"hours": h, "kill_time": t / max(sum(weights.values()), EPS), "tribe": tribe,
                                        "acc": picks, "weapons": cs})
        return pareto(results, lambda r: r["hours"], lambda r: -r["kill_time"])

    def armour_frontier(self, p: Profile) -> list[dict]:
        """Pareto list (hours, defence weighted by the attack mix) of armour sets."""
        mix = self.attack_mix(p)
        weights = self.opt.resist_weights(mix) if p.target_element == MIX else None
        mode = MIX if p.target_element == MIX else p.target_element

        def value(o: Option) -> float:
            return self.opt.armour_score(o.item, mode, weights) if o.item else 0.0
        sets = [((), 0.0, 0.0)]
        for s in DEFENCE_SLOTS:
            opts = [Option(SLOT_NAMES[s], None, 0.0)] + [Option(SLOT_NAMES[s], o.item, o.hours)
                                                         for o in self.options(lambda it, s=s: it["subcategory"] == s, p)]
            per = pareto(opts, lambda o: o.hours, value)
            sets = pareto([(picks + (o,), h + o.hours, v + value(o)) for picks, h, v in sets for o in per],
                          lambda t: t[1], lambda t: t[2])
        return [{"hours": h, "armour": picks} for picks, h, _ in sets]

    def menu(self, p: Profile, min_gain: float = 0.03) -> list[Build]:
        """Every build that no other build beats on hours and strength, thinned to steps of at least min_gain."""
        builds = self.combine(self.damage_frontier(p), self.armour_frontier(p), p)
        front = pareto(builds, lambda b: round(b.hours, 6), lambda b: b.strength)
        out = []
        for b in front:
            if not out or b.strength >= out[-1].strength * (1 + min_gain):
                out.append(b)
        return out

    # ------------------------------------------------------------------ any build, over time
    def evaluate(self, picks: dict[str, dict], p: Profile, tribe: str | None = None) -> dict:
        """Kill time, damage taken, strength and tribe of a given build (slot label -> item) at p's level, with the
        best tribe for it (or the given one: "Outlaw", "Crossroads" for none). A weapon slot left empty hits with
        your ability power once a second."""
        _, hp, _ = self.enemy(p)
        ap = self.opt.stat("AbilityPower", "Player", p.level)
        accs = [picks[SLOT_NAMES[s]] for s in DAMAGE_SLOTS if picks.get(SLOT_NAMES[s])]
        armour = [picks[SLOT_NAMES[s]] for s in DEFENCE_SLOTS if picks.get(SLOT_NAMES[s])]
        weapons = [(c, picks.get(c.capitalize())) for c in p.weapons]
        weights = weapon_weights(p)
        if tribe:
            tribes = {TRIBE_ELEMENT.get(tribe)}
        else:
            tribes = {w["element"] for _, w in weapons if w and w["element"]} or {None}
        best = None
        for tribe in tribes:
            bd, bdef = self.opt.badge_bonus(tribe, p.skill_points)
            times, hits = [], {}
            for c, w in weapons:
                if w:
                    base = ap + sum(self.opt.acc_score(a, w["element"]) for a in accs) + (bd if w["element"] == tribe else 0)
                    hit = self.weapon_hit(w, base)
                    n, t = self.kill_time(hit, hp, w["cooldown"])
                else:
                    hit = ap + sum(self.opt.acc_score(a, None) for a in accs)
                    n, t = self.kill_time(hit, hp, REFERENCE_COOLDOWN)
                times.append(weights[c] * t)
                hits[c] = {"hit": hit, "hits": n, "time": t}
            kill = sum(times) / sum(weights.values()) if times else self.reference(p)[0]
            taken = self.taken(armour, p, bdef)
            s = self.strength(kill, taken, p)
            if best is None or s > best["strength"]:
                best = {"strength": s, "kill_time": kill, "damage_taken": taken, "tribe": ELEMENT_TRIBE.get(tribe), "hits": hits}
        return best

    def explain(self, item: dict, slot: str, picks: dict[str, dict], p: Profile) -> dict:
        """What putting `item` into `slot` does to your build (picks) at p's level: {"now", "with"}, each the
        evaluate() result plus "taken_by" (damage taken per attack element, None = blunt) and "item" (what sits in the
        slot)."""
        out = {}
        for key, build in (("now", picks), ("with", picks | {slot: item})):
            ev = self.evaluate(build, p)
            _, bdef = self.opt.badge_bonus(next((el for el, tr in ELEMENT_TRIBE.items() if tr == ev["tribe"]), None),
                                           p.skill_points)
            armour = [build[SLOT_NAMES[s]] for s in DEFENCE_SLOTS if build.get(SLOT_NAMES[s])]
            _, _, enemy_ap = self.enemy(p)
            base = self.opt.stat("Defence", "Player", p.level) + bdef
            ev["taken_by"] = {el: max(DAMAGE_FLOOR * enemy_ap, enemy_ap - base - sum(self.opt.armour_score(a, el) for a in armour))
                              for el in self.attack_mix(p)}
            ev["item"] = build.get(slot)
            out[key] = ev
        return out

    def level_hours(self, level: int, strength: float, p: Profile) -> float:
        """Hours of fighting to finish `level` with a build of this strength: the share of the level's XP that comes
        from kills (Economy.quest_xp_share comes from quests, the same with any gear), at enemy XP of your level, each
        kill taking the walk between enemies plus the reference kill time ÷ strength."""
        eco = self.eco
        t = self.opt.b["stats"]["level_xp"]
        need = (t[level - 1] if level - 1 < len(t) else 0) - (t[level - 2] if 1 < level <= len(t) + 1 else 0)
        if need <= 0:
            return 0.0
        kills = need * (1 - eco.quest_xp_share) / max(self.opt.stat("IncreaseExperience", "Enemy", level), 1)
        ref_kill, _ = self.reference(Profile(level=level))
        return kills * (eco.kill_overhead + ref_kill / strength) / 3600

    def menu_cached(self, p: Profile, min_gain: float) -> list[Build]:
        key = (p.level, min_gain, p.weapons, p.prefer, p.defence_weight, p.skill_points, id(p.owned), p.target_level, p.target_element)
        cache = self.__dict__.setdefault("_menus", {})
        if key not in cache:
            cache[key] = self.menu(p, min_gain)
        return cache[key]

    def route(self, p: Profile, to_level: int, value: float = 1.0, keep: int = 12) -> dict:
        """The best upgrade plan from your level to to_level. At every level you may switch to one of that level's menu
        builds (Pareto builds, keeping any better piece you already got), paying the hours for the pieces you don't have
        yet; each level then takes level_hours with the build's strength. Minimises farming hours + value × fighting
        hours over all such upgrade points (kept to the `keep` best states per level): value 1 = the fastest way to
        to_level (an upgrade must pay for itself in leveling time); higher values count being stronger more (dungeons,
        bosses, groups), so the plan invests more. A small gain bought just before a big one never pays off, so it is
        left out. Returns {"hours", "fight", "farm", "steps": [{"level", "get": [(label, item, hours)], "build",
        "strength", ...}], "timeline": [(level, strength)], "build"}."""
        from dataclasses import replace

        def items(b: Build) -> dict:
            return {k: o.item for k, o in b.picks.items() if o.item}

        def key(picks: dict) -> frozenset:
            return frozenset((k, v["prefab"]) for k, v in picks.items())

        first = self.menu_cached(p, 0.02)
        start = items(first[0]) if first and first[0].hours == 0 else {}
        # state: (objective so far, farming hours, build, items you have by then, steps, timeline)
        states = [(0.0, 0.0, start, frozenset(p.owned), [], [])]
        for level in range(p.level, max(p.level, to_level)):
            q = replace(p, level=level)
            cands = [items(b) for b in self.menu_cached(q, 0.02)]
            nxt: dict = {}
            for total, farm, picks, have, steps, line in states:
                for cand in [picks] + cands:
                    new = dict(cand)
                    if cand is not picks:  # keep a piece you already have where it is better
                        base = self.evaluate(new, q)["strength"]
                        for slot, it in picks.items():
                            if new.get(slot) is not it:
                                trial = new | {slot: it}
                                s = self.evaluate(trial, q)["strength"]
                                if s >= base:  # as good: keep the piece you already have (it costs nothing)
                                    new, base = trial, s
                    get = [(slot, it, self.hours(it, q) or 0.0) for slot, it in new.items() if it["prefab"] not in have]
                    if any(self.hours(it, q) is None for _, it, _ in get):
                        continue
                    cost = sum(h for _, _, h in get)
                    ev = self.evaluate(new, q)
                    fight = self.level_hours(level, ev["strength"], q)
                    t = total + cost + value * fight
                    k = key(new)
                    if k not in nxt or t < nxt[k][0]:
                        before = self.evaluate(picks, q)["strength"] if get else 0
                        st = steps + ([{"level": level, "get": get, "build": new, "strength": ev["strength"], "before": before,
                                        "tribe": ev["tribe"], "kill_time": ev["kill_time"],
                                        "damage_taken": ev["damage_taken"]}] if get else [])
                        nxt[k] = (t, farm + cost, new, have | {it["prefab"] for _, it, _ in get}, st,
                                  line + [{"level": level, "strength": ev["strength"], "kill_time": ev["kill_time"],
                                           "damage_taken": ev["damage_taken"], "fight": fight, "farm": cost}])
            # keep the fastest states that are also strong (a slow state is only kept if it is stronger)
            ranked = sorted(nxt.values(), key=lambda s: s[0])
            states, best_s = [], -1.0
            for s in ranked:
                strength_now = s[5][-1]["strength"] if s[5] else 0
                if strength_now > best_s + EPS or len(states) < 3:
                    states.append(s)
                    best_s = max(best_s, strength_now)
                if len(states) >= keep:
                    break
        _, farm, picks, _, steps, line = min(states, key=lambda s: s[0])
        fight = sum(d["fight"] for d in line)
        return {"hours": farm + fight, "farm": farm, "fight": fight, "steps": steps, "build": picks, "value": value,
                "timeline": [(d["level"], d["strength"]) for d in line], "series": line}

    ROUTES = (("Efficient", 1.0, "only upgrades that pay for themselves in leveling time"),
              ("Balanced", 3.0, "being stronger counts three times: more upgrades, a bit more farming"),
              ("Strong", 10.0, "being strong matters most (dungeons, bosses, groups): the most farming"))

    def routes(self, p: Profile, to_level: int) -> list[dict]:
        """The three route styles (ROUTES), dropping one that came out the same as the one before it."""
        out = []
        for name, value, about in self.ROUTES:
            r = self.route(p, to_level, value) | {"name": name, "about": about}
            sig = [(s["level"], tuple(it["prefab"] for _, it, _ in s["get"])) for s in r["steps"]]
            if out and out[-1]["sig"] == sig:
                out[-1]["name"] += f" = {name}"
                continue
            out.append(r | {"sig": sig})
        return out

    def slot_upgrades(self, p: Profile, picks: dict[str, dict], ahead: int = 10) -> dict[str, list[dict]]:
        """Per slot of your template: the useful upgrades over your current build (picks), now and up to `ahead`
        levels later: [{"item", "level", "gain" (strength ratio − 1 at that level), "hours"}], only the ones no other
        beats on level, hours and gain together, cheapest first."""
        from dataclasses import replace
        labels = [c.capitalize() for c in p.weapons] + list(SLOT_NAMES.values())
        sub = {SLOT_NAMES[s]: s for s in SLOT_NAMES}
        out: dict[str, list[dict]] = {}
        base_at: dict[int, float] = {}
        for label in labels:
            rows = []
            for it in self.opt.items:
                if not it["scaled_sum"] or not it["name"] or (picks.get(label) or {}).get("prefab") == it["prefab"]:
                    continue
                if label in ("Melee", "Ranged"):
                    if not it["is_weapon"] or weapon_class(it) != label.lower():
                        continue
                elif it["subcategory"] != sub[label]:
                    continue
                lvl = max(p.level, it["level_req"] or 0)
                if lvl > p.level + ahead:
                    continue
                q = replace(p, level=lvl)
                h = 0.0 if p.owned.get(it["prefab"]) else self.hours(it, q)
                if h is None:
                    continue
                if lvl not in base_at:
                    base_at[lvl] = self.evaluate(picks, q)["strength"]
                gain = self.evaluate(picks | {label: it}, q)["strength"] / base_at[lvl] - 1
                if gain > 0.005:
                    rows.append({"item": it, "level": lvl, "gain": gain, "hours": h})
            keep = [r for r in rows if not any(o is not r and o["level"] <= r["level"] and o["hours"] <= r["hours"]
                                               and o["gain"] >= r["gain"] and (o["level"], o["hours"], -o["gain"])
                                               < (r["level"], r["hours"], -r["gain"]) for o in rows)]
            out[label] = sorted(keep, key=lambda r: (r["level"], r["hours"]))
        return out

    # ------------------------------------------------------------------ the shop list
    TRIBES = ("Shadow", "Bone", "Outlaw", "Wild", "Grease", "Crossroads")
    ARMOUR_GROUPS = tuple(ELEMENTS) + (None, "any")  # resist element, blunt attackers (every resist counts), defence only

    def taken_by(self, armour: list[dict], p: Profile, badge_def: int) -> dict:
        """Damage taken a hit at p's level per attack element (None = blunt), plus "mix": where you fight (the
        attack mix of the profile)."""
        _, _, enemy_ap = self.enemy(p)
        base = self.opt.stat("Defence", "Player", p.level) + badge_def
        out = {el: max(DAMAGE_FLOOR * enemy_ap, enemy_ap - base - sum(self.opt.armour_score(a, el) for a in armour))
               for el in ELEMENTS + [None]}
        out["mix"] = sum(share * out[el] for el, share in self.attack_mix(p).items())
        return out

    def shortlist(self, cands: list[dict], value: Callable[[dict], float], floor: float, p: Profile, ahead: int,
                  limit: int) -> tuple[list[dict], list[dict]]:
        """The items of one slot and group worth looking at: better than `floor` (what you have), with a known way
        (or owned), usable now or within `ahead` levels; when fewer than three are, the next ones above are added
        as "later". Each: {"item", "from" (level requirement), "level" (when you can use it), "hours", "owned",
        "value", "pick"} (pick: no other is cheaper, stronger and usable sooner at once). Strongest first, at most
        `limit` (the picks come first when there are more). Second: the better items within reach that have no
        known way to get them (with the sources chosen)."""
        rows, missing = [], []
        for it in cands:
            if not it["name"] or not it["scaled_sum"]:
                continue
            v = value(it)
            if v <= floor + EPS:
                continue
            owned = bool(p.owned.get(it["prefab"]))
            h = 0.0 if owned else self.hours(it, p)
            if h is None and self.unknown:
                h = math.inf
            if h is None:
                if (it["level_req"] or 1) <= p.level + ahead:
                    missing.append(it)
                continue
            rows.append({"item": it, "from": it["level_req"] or 1, "level": max(p.level, it["level_req"] or 0),
                         "hours": h, "owned": owned, "value": v, "later": False})
        missing.sort(key=lambda it: (-value(it), it["level_req"] or 0))
        near = [r for r in rows if r["from"] <= p.level + ahead]
        later = sorted((r for r in rows if r["from"] > p.level + ahead), key=lambda r: (r["from"], -r["value"]))
        for r in later[:max(0, 3 - len(near))]:
            r["later"] = True
            near.append(r)
        for r in near:
            r["pick"] = not any(o is not r and o["level"] <= r["level"] and o["hours"] <= r["hours"] + EPS
                                and o["value"] >= r["value"] - EPS
                                and (o["level"], o["hours"], -o["value"]) < (r["level"], r["hours"], -r["value"])
                                for o in near)
        near.sort(key=lambda r: (-r["value"], r["hours"], r["level"]))
        picks = [r for r in near if r["pick"]]
        rest = [r for r in near if not r["pick"]]
        out = picks[:limit] + rest[:max(0, limit - len(picks))]
        return sorted(out, key=lambda r: (-r["value"], r["hours"], r["level"])), missing

    def recommend(self, p: Profile, picks: dict[str, dict], ahead: int = 5, limit: int = 10) -> dict:
        """The shop list: what is worth looking for now and up to `ahead` levels above, broadly, from your build
        (picks: slot label -> item) at p's level (every number is against enemies of your level, "if you had it now").

        "tribes": per tribe (TRIBES; its element, Crossroads = blunt): "badge" (damage, defence) from your skill
          points in it; "weapons" per hotbar weapon slot: the weapons of the tribe's element (they get the badge
          damage), ranked by damage a second of cooldown in your build and this tribe, with "hit", "hits",
          "kill_time";
          "accessories" per slot (Ears, Wrist, Tail): accessories ranked by what they add to a weapon of that
          element, "kill_time" and "hits_by" with the tribe's best weapons; "missing" per slot: better items in
          reach with no known way; "now": your build in this tribe (evaluate()); "with_weapons": the same with the
          tribe's best weapons; "build": the strongest set from the lists (picks, hours to get, kill_time, hits).
        "armour": per group (ARMOUR_GROUPS: a resist element, None = blunt attackers where every resist counts,
          "any" = defence only): "slots" per armour slot: pieces ranked by defence plus the resist that counts, each
          with "taken_by" (damage taken per attack element with it in your build), "missing" per slot, and "set":
          the strongest piece per slot (picks, hours, taken_by). "now": your damage taken per element, "tribe": your
          build's tribe."""
        now_ev = self.evaluate(picks, p) if picks else None
        my_tribe = now_ev["tribe"] if now_ev else None
        tribes = {}
        for tribe in self.TRIBES:
            el = TRIBE_ELEMENT.get(tribe)
            badge = self.opt.badge_bonus(el, p.skill_points)
            now = self.evaluate(picks, p, tribe=tribe)
            ref = dict(picks)
            weapons, missing, hours = {}, {}, 0.0
            for c in p.weapons:
                label = c.capitalize()
                have = picks.get(label)

                def speed(it: dict, c=c, label=label) -> float:  # damage a second of cooldown, in your build
                    return self.evaluate(picks | {label: it}, p, tribe=tribe)["hits"][c]["hit"] / max(it["cooldown"] or 0, 0.5)
                floor = now["hits"][c]["hit"] / max((have["cooldown"] or 0) if have else REFERENCE_COOLDOWN, 0.5)
                cands = [it for it in self.opt.items if it["is_weapon"] and weapon_class(it) == c and it["element"] == el]
                rows, missing[label] = self.shortlist(cands, speed, floor, p, ahead, limit)
                for r in rows:
                    ev = self.evaluate(picks | {label: r["item"]}, p, tribe=tribe)
                    r["hit"], r["hits"], r["kill_time"] = ev["hits"][c]["hit"], ev["hits"][c]["hits"], ev["kill_time"]
                    r["hits_by"] = ev["hits"]
                weapons[label] = rows
                best = next((r for r in rows if not r["later"] and not math.isinf(r["hours"])), None)
                if best:
                    ref[label] = best["item"]
                    hours += best["hours"]
            with_weapons = self.evaluate(ref, p, tribe=tribe)
            accessories = {}
            for s in DAMAGE_SLOTS:
                label = SLOT_NAMES[s]
                have = picks.get(label)
                val = lambda it, el=el: self.opt.acc_score(it, el)  # noqa: E731
                cands = [it for it in self.opt.items if it["subcategory"] == s]
                rows, missing[label] = self.shortlist(cands, val, val(have) if have else 0.0, p, ahead, limit)
                for r in rows:
                    ev = self.evaluate(ref | {label: r["item"]}, p, tribe=tribe)
                    r["kill_time"], r["hits_by"] = ev["kill_time"], ev["hits"]
                accessories[label] = rows
            build = dict(ref)
            for label, rows in accessories.items():
                best = next((r for r in rows if not r["later"] and not math.isinf(r["hours"])), None)
                if best:
                    build[label] = best["item"]
                    hours += best["hours"]
            build_ev = self.evaluate(build, p, tribe=tribe)
            tribes[tribe] = {"element": el, "badge": badge, "weapons": weapons, "accessories": accessories,
                             "missing": missing, "now": now, "with_weapons": with_weapons,
                             "build": {"picks": build, "hours": hours, "kill_time": build_ev["kill_time"],
                                       "hits": build_ev["hits"], "damage_taken": build_ev["damage_taken"]}}
        _, bdef = self.opt.badge_bonus(TRIBE_ELEMENT.get(my_tribe), p.skill_points)
        worn = [picks[SLOT_NAMES[s]] for s in DEFENCE_SLOTS if picks.get(SLOT_NAMES[s])]
        armour = {}
        for grp in self.ARMOUR_GROUPS:
            if grp == "any":
                val = lambda it: it["scaled_defence"] or 0  # noqa: E731
            else:
                val = lambda it, g=grp: self.opt.armour_score(it, g)  # noqa: E731
            slots, missing, chosen, hours = {}, {}, dict(picks), 0.0
            for s in DEFENCE_SLOTS:
                label = SLOT_NAMES[s]
                have = picks.get(label)
                cands = [it for it in self.opt.items if it["subcategory"] == s
                         and (grp in (None, "any") or it["element"] in (grp, None))]
                rows, missing[label] = self.shortlist(cands, val, val(have) if have else 0.0, p, ahead, limit)
                others = [a for a in worn if a is not have]
                for r in rows:
                    r["taken_by"] = self.taken_by(others + [r["item"]], p, bdef)
                slots[label] = rows
                best = next((r for r in rows if not r["later"] and not math.isinf(r["hours"])), None)
                if best:
                    chosen[label] = best["item"]
                    hours += best["hours"]
            on = [chosen[SLOT_NAMES[s]] for s in DEFENCE_SLOTS if chosen.get(SLOT_NAMES[s])]
            armour[grp] = {"slots": slots, "missing": missing,
                           "set": {"picks": {SLOT_NAMES[s]: chosen.get(SLOT_NAMES[s]) for s in DEFENCE_SLOTS},
                                   "hours": hours, "taken_by": self.taken_by(on, p, bdef)}}
        return {"tribes": tribes, "armour": armour, "tribe": my_tribe, "ahead": ahead,
                "now": {"taken_by": self.taken_by(worn, p, bdef), "kill_time": now_ev["kill_time"] if now_ev else None}}

    # ------------------------------------------------------------------ progression: the best set at every level
    def points_at(self, p: Profile, level: int) -> int:
        """Skill points at another level: one per level (the user's character: level 27 with 27 points, 2026-10-05;
        knowledge/OPEN_QUESTIONS.md M13), counted from what you have now."""
        return max(0, p.skill_points + (level - p.level))

    def at_level(self, p: Profile, level: int) -> Profile:
        return replace(p, level=level, skill_points=self.points_at(p, level))

    def price_table(self, p: Profile) -> dict[str, float | None]:
        """Hours to get every item of the model (0 if owned, None: no known way), each priced at the level you can
        first use it, never below yours (bananas come faster at higher levels)."""
        out: dict[str, float | None] = {}
        profiles: dict[int, Profile] = {}
        for it in sorted(self.opt.items, key=lambda it: it["level_req"] or 0):
            if p.owned.get(it["prefab"]):
                out[it["prefab"]] = 0.0
                continue
            lv = max(p.level, it["level_req"] or 0)
            if lv not in profiles:
                profiles[lv] = replace(p, level=lv)
            out[it["prefab"]] = self.hours(it, profiles[lv])
        return out

    @staticmethod
    def slot_label(it: dict) -> str | None:
        """The build slot an item goes into: "Melee", "Ranged" or the gear slot's name."""
        if it["is_weapon"]:
            return weapon_class(it).capitalize() if it["action_type"] in ATTACK_ACTIONS else None
        return SLOT_NAMES.get(it["subcategory"])

    def slot_labels(self, p: Profile) -> list[str]:
        return [c.capitalize() for c in p.weapons] + [SLOT_NAMES[s] for s in DAMAGE_SLOTS + DEFENCE_SLOTS]

    def smooth_kill(self, picks: dict[str, dict], p: Profile, tribe: str, only: str | None = None) -> float:
        """Kill time of a set summed over the hotbar weapons (weighted by the build style, weapon_weights()), without
        rounding the hits up (at least one hit): the measure the progression ranks by, so the best set doesn't flip
        back and forth where one more hit is needed (enemies of a level differ in hit points anyway). only: one
        weapon class ("melee", "ranged") on its own, unweighted (stage(): a weapon slot's rows are compared by that
        weapon, not by the build style's weights, or every ranged weapon of a melee build looks "as fast")."""
        el = TRIBE_ELEMENT.get(tribe)
        badge_dmg, _ = self.opt.badge_bonus(el, p.skill_points)
        _, hp, _ = self.enemy(p)
        ap = self.opt.stat("AbilityPower", "Player", p.level)
        accs = [picks[SLOT_NAMES[s]] for s in DAMAGE_SLOTS if picks.get(SLOT_NAMES[s])]
        total = 0.0
        for c, weight in weapon_weights(p).items():
            if only:
                if c != only:
                    continue
                weight = 1.0
            w = picks.get(c.capitalize())
            if w:
                base = ap + sum(self.opt.acc_score(a, w["element"]) for a in accs) + (badge_dmg if el and w["element"] == el else 0)
                total += weight * max(1.0, hp / max(self.weapon_hit(w, base), 1)) * max(w["cooldown"] or 0, 0.5)
            else:
                total += weight * max(1.0, hp / max(ap + sum(self.opt.acc_score(a, None) for a in accs), 1)) * REFERENCE_COOLDOWN
        return total

    def best_set(self, p: Profile, tribe: str, pool: dict[str, list[tuple[dict, float]]], prev: dict | None = None,
                 min_gain: float = 0.05) -> dict:
        """The strongest full set at p's level with the badge in `tribe` (TRIBES), all slots together, from `pool`
        (slot label -> [(item, hours)], only what is usable and allowed). Weapons and accessories: for each element
        the accessories could back, the accessories that add most to a weapon of it, then per hotbar weapon the
        fastest kill with them and the badge damage (smooth_kill()); the element with the fastest kills wins.
        Armour: the best piece per slot against each attack element of where you fight (and for plain defence, and
        weighted by the mix); the set that takes least wins. Ties go to fewer hours. Then every slot goes back to
        what the level before had (`prev`) as long as the set stays within min_gain of the best (the most expensive
        new pieces first), so an item is only replaced when that pays. Returns evaluate()'s numbers plus "picks",
        "hours" (per slot label) and "ideal" (the picks before going back to prev)."""
        prev = prev or {}
        _, badge_def = self.opt.badge_bonus(TRIBE_ELEMENT.get(tribe), p.skill_points)
        score = self.opt.acc_score
        hours_of = {id(it): h for rows in pool.values() for it, h in rows}
        best = None
        for focus in ELEMENTS + [None]:
            picks = {}
            for s in DAMAGE_SLOTS:
                label = SLOT_NAMES[s]
                rows = [r for r in pool.get(label, ()) if score(r[0], focus) > 0]
                if rows:
                    picks[label] = min(rows, key=lambda r: (-score(r[0], focus), r[1], r[0]["name"]))[0]
            for c in p.weapons:
                label = c.capitalize()
                rows = [(self.smooth_kill(picks | {label: it}, p, tribe), h, it["name"], it) for it, h in pool.get(label, ())]
                if rows:
                    picks[label] = min(rows, key=lambda r: r[:3])[3]
            key = (round(self.smooth_kill(picks, p, tribe), 6), sum(hours_of[id(it)] for it in picks.values()))
            if best is None or key < best[0]:
                best = (key, picks)
        damage = best[1]
        mix = self.attack_mix(p)
        weights = self.opt.resist_weights(mix)
        best = None
        for mode in list(mix) + ["any"] + ([MIX] if len(mix) > 1 else []):
            def val(it: dict, mode=mode) -> float:
                return (it["scaled_defence"] or 0) if mode == "any" else self.opt.armour_score(it, mode, weights)
            picks = {}
            for s in DEFENCE_SLOTS:
                rows = [r for r in pool.get(SLOT_NAMES[s], ()) if val(r[0]) > 0]
                if rows:
                    picks[SLOT_NAMES[s]] = min(rows, key=lambda r: (-val(r[0]), r[1], r[0]["name"]))[0]
            key = (round(self.taken(list(picks.values()), p, badge_def), 6), sum(hours_of[id(it)] for it in picks.values()))
            if best is None or key < best[0]:
                best = (key, picks)
        armour = best[1]
        ideal = damage | armour

        def settle(picks: dict, measure: Callable[[dict], float]) -> dict:
            limit = measure(picks) * (1 + min_gain) + EPS
            for label in sorted(picks, key=lambda k: -hours_of[id(picks[k])]):
                old = prev.get(label)
                if old is not None and old is not picks[label] and id(old) in hours_of:
                    trial = picks | {label: old}
                    if measure(trial) <= limit:
                        picks = trial
            return picks
        if prev and min_gain > 0:
            damage = settle(damage, lambda d: self.smooth_kill(d, p, tribe))
            armour = settle(armour, lambda d: self.taken(list(d.values()), p, badge_def))
        picks = damage | armour
        return self.evaluate(picks, p, tribe=tribe) | {
            "picks": picks, "hours": {k: hours_of[id(it)] for k, it in picks.items()}, "ideal": ideal, "level": p.level,
            "points": p.skill_points, "badge": self.opt.badge_bonus(TRIBE_ELEMENT.get(tribe), p.skill_points)}

    def pool(self, p: Profile, prices: dict[str, float | None], max_hours: float | None = None,
             unknown: bool = False) -> dict[str, list]:
        """Slot label -> [(item, hours)]: everything with a known way that takes at most max_hours (what you own
        always counts). unknown: also the items nobody knows how to get (hours: infinite)."""
        out: dict[str, list] = {}
        for it in self.opt.items:
            h = prices.get(it["prefab"])
            label = self.slot_label(it)
            if not label or not it["name"] or not it["scaled_sum"] or (h is None and not unknown):
                continue
            if h is not None and max_hours is not None and h > max_hours + EPS:
                continue
            out.setdefault(label, []).append((it, math.inf if h is None else h))
        return out

    AUTO = "Auto"  # progression(): the badge goes to whichever tribe kills fastest at each level

    def progression(self, p: Profile, tribe: str, max_hours: float | None = None,
                    prices: dict[str, float | None] | None = None, lo: int = 1, hi: int = 60,
                    switch_cost: float = 5.0, hour_cost: float = 0.0, unknown: bool = False,
                    utility: tuple[str, ...] = ()) -> dict:
        """What to wear at every level from lo to hi with the badge in `tribe`, searched over all levels at once (no
        model of how fast you level; skill points grow one per level, points_at()).

        First the strongest set of every level on its own (best_set(); tribe AUTO: at every level the tribe whose
        set kills fastest, switching is free; ties: less damage taken, then the tribe of the level before). Then
        smooth(): the lanes that lose the least against those sets, where every change of an item costs
        `switch_cost` (in percent of strength times levels: 5 = a new item must make you 5 % better for one level,
        or 1 % for five) and, only if you want time to count, `hour_cost` for every hour it takes to get (the same
        unit; 0 = time is irrelevant). With both 0 you get the strongest set of every level. Level 60 always gets
        its strongest set: it is the last level, so you keep that set for good and any cost pays. max_hours: leave out
        items that take longer to get; unknown: include items with no known way. utility: the utility slots of
        your hotbar ("Stun", "Heal", "Poison", "Buff"): per level the item that does most together with that level's
        set (utility(): a stun counts by the free hits of your main weapon while it holds), kept until another is
        5 % better (when switch_cost > 0; at the last level the best one); they get lanes of their own and sit in
        each level's "utility".

        Returns "levels" (per level evaluate()'s numbers plus "picks", "hours", "ideal" (that level's strongest
        set), "badge_tribe", "badge", "points"; lo first), "lanes" (slot label -> [{"from", "to", "item",
        "hours"}]), "badges" ([{"from", "to", "tribe"}]) and "changes" (the levels where the set changes)."""
        prices = self.price_table(p) if prices is None else prices
        pool = self.pool(p, prices, max_hours, unknown)
        profs = [self.at_level(p, lv) for lv in range(lo, hi + 1)]
        ideal, last = [], None
        for pl in profs:
            usable = {k: [r for r in rows if (r[0]["level_req"] or 0) <= pl.level] for k, rows in pool.items()}
            best = None
            for i, t in enumerate(self.TRIBES if tribe == self.AUTO else [tribe]):
                row = self.best_set(pl, t, usable)
                key = (round(self.smooth_kill(row["picks"], pl, t), 6), round(row["damage_taken"], 6), t != last, i)
                if best is None or key < best[0]:
                    best = (key, row, t)
            _, row, last = best
            row["badge_tribe"] = last
            ideal.append(row)
        picks = [dict(r["picks"]) for r in ideal]
        if switch_cost > 0 or hour_cost > 0:
            self.smooth(picks, ideal, profs, pool, switch_cost, hour_cost)
        levels = []
        for pl, row, d in zip(profs, ideal, picks):
            t = row["badge_tribe"]
            hours = {k: 0.0 if p.owned.get(it["prefab"]) else math.inf if prices.get(it["prefab"]) is None
                     else prices[it["prefab"]] for k, it in d.items()}
            levels.append(self.evaluate(d, pl, tribe=t) | {
                "picks": d, "hours": hours, "ideal": row["picks"], "level": pl.level, "points": pl.skill_points,
                "badge_tribe": t, "badge": row["badge"]})
        prices_u: dict[str, float | None] = {}

        def price(it: dict) -> float | None:  # utility items, priced once at your level
            if it["prefab"] not in prices_u:
                prices_u[it["prefab"]] = self.hours(it, p)
            return prices_u[it["prefab"]]
        held: dict[str, dict] = {}
        for pl, row in zip(profs, levels):
            row["utility"] = {}
            if not utility:
                continue
            for slot, rows in self.utility(pl, row["picks"], utility, price, row["badge_tribe"]).items():
                rows = [r for r in rows if max_hours is None or r["hours"] <= max_hours + EPS]
                if not rows:
                    continue
                best = rows[-1]
                old = next((r for r in rows if r["item"] is held.get(slot)), None)
                if old and switch_cost > 0 and old["value"] >= best["value"] * 0.95 and pl.level < LEVEL_CAP:
                    best = old
                held[slot] = best["item"]
                row["utility"][slot] = best
        lanes: dict[str, list] = {label: [] for label in self.slot_labels(p)}
        for slot in utility:
            lane = lanes.setdefault(slot, [])
            for row in levels:
                r = row["utility"].get(slot)
                if not r:
                    continue
                if lane and lane[-1]["item"] is r["item"] and lane[-1]["to"] == row["level"] - 1:
                    lane[-1]["to"] = row["level"]
                else:
                    lane.append({"from": row["level"], "to": row["level"], "item": r["item"], "hours": r["hours"]})
        gear = self.slot_labels(p)
        changes, badges = [], []
        for i, row in enumerate(levels):
            if i and any(row["picks"].get(k) is not levels[i - 1]["picks"].get(k) for k in gear):
                changes.append(row["level"])
            if badges and badges[-1]["tribe"] == row["badge_tribe"]:
                badges[-1]["to"] = row["level"]
            else:
                badges.append({"from": row["level"], "to": row["level"], "tribe": row["badge_tribe"]})
            for label in gear:
                lane = lanes[label]
                it = row["picks"].get(label)
                if not it:
                    continue
                if lane and lane[-1]["item"] is it and lane[-1]["to"] == row["level"] - 1:
                    lane[-1]["to"] = row["level"]
                else:
                    lane.append({"from": row["level"], "to": row["level"], "item": it, "hours": row["hours"][label]})
        return {"levels": levels, "lanes": lanes, "badges": badges, "changes": changes, "tribe": tribe, "lo": lo, "hi": hi,
                "max_hours": max_hours, "switch_cost": switch_cost, "hour_cost": hour_cost, "unknown": unknown}

    def smooth(self, picks: list[dict], ideal: list[dict], profs: list[Profile], pool: dict[str, list],
               switch_cost: float, hour_cost: float) -> None:
        """The lanes that lose the least over all levels (changes `picks`, one dict per level, in place).

        What is minimised: per level the percent you kill slower than that level's strongest set (smooth_kill())
        plus the percent more damage you take, plus switch_cost for every change of an item and hour_cost for every
        hour a newly worn item takes to get (an item you come back to is charged again; rare). The last level of
        the game (LEVEL_CAP) counts as forever (CAP_WEIGHT): what you wear there you keep, so there the strongest
        item wins whatever a change or its hours cost. Weapons and
        accessories only meet in the kill time and armour only in the damage taken, so the two groups are solved
        apart. Inside a group one lane at a time is solved exactly (lane(): a shortest path over the levels, every
        candidate item a state) with the other lanes as they are, round after round until nothing changes. The
        start is the strongest set of every level, so the element the weapons and accessories share is already the
        right one per level; a change of several slots at once that only pays together can still be missed."""
        p = profs[0]
        tribes = [r["badge_tribe"] for r in ideal]
        hours_of = {id(it): (0.0 if math.isinf(h) else h) for rows in pool.values() for it, h in rows}
        armour = [SLOT_NAMES[s] for s in DEFENCE_SLOTS]
        damage = [c.capitalize() for c in p.weapons] + [SLOT_NAMES[s] for s in DAMAGE_SLOTS]
        bdefs = [self.opt.badge_bonus(TRIBE_ELEMENT.get(t), pl.skill_points)[1] for t, pl in zip(tribes, profs)]
        ref_kill = [max(self.smooth_kill(r["picks"], pl, t), EPS) for r, pl, t in zip(ideal, profs, tribes)]
        ref_taken = [max(self.taken([r["picks"][k] for k in armour if k in r["picks"]], pl, b), EPS)
                     for r, pl, b in zip(ideal, profs, bdefs)]

        weight = [CAP_WEIGHT if pl.level >= LEVEL_CAP else 1.0 for pl in profs]

        def kill_loss(i: int, d: dict) -> float:
            return weight[i] * 100 * (self.smooth_kill(d, profs[i], tribes[i]) / ref_kill[i] - 1)

        def taken_loss(i: int, d: dict) -> float:
            return weight[i] * 100 * (self.taken([d[k] for k in armour if k in d], profs[i], bdefs[i]) / ref_taken[i] - 1)
        for group, loss in ((damage, kill_loss), (armour, taken_loss)):
            cands = {label: self.candidates(label, pool, picks, profs, hour_cost > 0) for label in group}
            for _ in range(4):
                changed = [self.lane(picks, label, cands[label], profs, loss, switch_cost, hour_cost, hours_of)
                           for label in group]
                if not any(changed):
                    break

    def candidates(self, label: str, pool: dict[str, list], picks: list[dict], profs: list[Profile],
                   cheap: bool) -> list[dict]:
        """The items of a slot worth a state in lane(): every weapon; for the other slots, per level and per way
        of counting (each element, blunt, plain defence) the three that add most among what is usable then, and
        with `cheap` (hours count) also the three that add most among those you get within half an hour, two and
        eight hours. Plus whatever the lanes hold now."""
        rows = pool.get(label, [])
        keep = {id(d[label]): d[label] for d in picks if label in d}
        if label in ("Melee", "Ranged"):
            keep.update((id(it), it) for it, _ in rows)
            return list(keep.values())
        if label in {SLOT_NAMES[s] for s in DEFENCE_SLOTS}:
            scores = [lambda it, el=el: self.opt.armour_score(it, el) for el in ELEMENTS + [None]]
            scores.append(lambda it: it["scaled_defence"] or 0)
        else:
            scores = [lambda it, el=el: self.opt.acc_score(it, el) for el in ELEMENTS + [None]]
        limits = [math.inf] + ([0.5, 2.0, 8.0] if cheap else [])
        for score in scores:
            ranked = sorted(((score(it), h, it) for it, h in rows), key=lambda r: (-r[0], r[1], r[2]["name"]))
            ranked = [r for r in ranked if r[0] > 0]
            for pl in profs:
                for limit in limits:
                    found = 0
                    for _, h, it in ranked:
                        if (it["level_req"] or 0) <= pl.level and (h <= limit or math.isinf(limit)):
                            keep[id(it)] = it
                            found += 1
                            if found == 3:
                                break
        return list(keep.values())

    def lane(self, picks: list[dict], label: str, cands: list[dict], profs: list[Profile],
             loss: Callable[[int, dict], float], switch_cost: float, hour_cost: float, hours_of: dict) -> bool:
        """One slot over all levels, the other slots as they are: the cheapest path, where a state is what the slot
        holds (a candidate, or nothing), a level costs loss(level index, the set with it) and going to another
        item costs switch_cost + hour_cost x its hours (the first item of the lane: only the hours). An item is
        no state below its level requirement. Writes the path into picks; True if anything changed."""
        states: list[dict | None] = [None] + cands
        enter = [switch_cost] + [switch_cost + hour_cost * hours_of.get(id(it), 0.0) for it in cands]
        dp: list[float] = []
        back: list[list[int]] = []
        for i, pl in enumerate(profs):
            base = picks[i]
            costs = []
            for it in states:
                if it is None:
                    d = {k: v for k, v in base.items() if k != label}
                elif (it["level_req"] or 0) > pl.level:
                    costs.append(math.inf)
                    continue
                else:
                    d = base | {label: it}
                # of two that do the same, the one you own
                costs.append(loss(i, d) - (0.01 if it is not None and pl.owned.get(it["prefab"]) else 0.0))
            if not dp:
                dp = [c + e - switch_cost for c, e in zip(costs, enter)]
                dp[0] = costs[0]
                back.append([-1] * len(states))
                continue
            m = min(range(len(dp)), key=dp.__getitem__)
            new, bk = [], []
            for s_, c in enumerate(costs):
                move = dp[m] + enter[s_]
                if dp[s_] <= move:
                    new.append(c + dp[s_])
                    bk.append(s_)
                else:
                    new.append(c + move)
                    bk.append(m)
            dp = new
            back.append(bk)
        s_ = min(range(len(dp)), key=dp.__getitem__)
        changed = False
        for i in range(len(profs) - 1, -1, -1):
            it = states[s_]
            if picks[i].get(label) is not it:
                changed = True
                if it is None:
                    picks[i].pop(label, None)
                else:
                    picks[i][label] = it
            s_ = back[i][s_]
        return changed

    def stage(self, p: Profile, tribe: str, level: int, picks: dict[str, dict], prices: dict[str, float | None],
              max_hours: float | None = None) -> dict:
        """Everything you could wear in each slot at `level`, put into the best set (picks) one at a time: slot
        label -> rows {"item", "hours" (None: no known way), "owned", "best", "over" (takes longer than max_hours),
        "kill_time", "hits", "damage_taken", "smooth"}, the best set's item first, then by kill time (weapons,
        accessories: smooth_kill()) or damage taken (armour; ties: more stats), then fewer hours. "set": the best set's
        own numbers."""
        pl = self.at_level(p, level)
        armour = {SLOT_NAMES[s] for s in DEFENCE_SLOTS}
        slots: dict[str, list] = {label: [] for label in self.slot_labels(p)}
        for it in self.opt.items:
            label = self.slot_label(it)
            if label not in slots or (it["level_req"] or 0) > level or not it["name"] or not it["scaled_sum"]:
                continue
            h = prices.get(it["prefab"])
            ev = self.evaluate(picks | {label: it}, pl, tribe=tribe)
            slots[label].append({"item": it, "hours": h, "owned": bool(p.owned.get(it["prefab"])),
                                 "best": picks.get(label) is it,
                                 "over": max_hours is not None and h is not None and h > max_hours + EPS,
                                 "kill_time": ev["kill_time"], "hits": ev["hits"], "damage_taken": ev["damage_taken"],
                                 "smooth": self.smooth_kill(picks | {label: it}, pl, tribe,
                                                            only=label.lower() if label in ("Melee", "Ranged") else None)})
        for label, rows in slots.items():
            far = math.inf
            if label in armour:
                rows.sort(key=lambda r: (not r["best"], round(r["damage_taken"], 6), -(r["item"]["scaled_sum"] or 0),
                                         far if r["hours"] is None else r["hours"]))
            else:
                rows.sort(key=lambda r: (not r["best"], round(r["smooth"], 6), far if r["hours"] is None else r["hours"]))
        return {"slots": slots, "set": self.evaluate(picks, pl, tribe=tribe), "level": level}

    # ------------------------------------------------------------------ options to choose from
    def tradeoffs(self, p: Profile, budget: float, min_step: float = 0.05) -> list[Build]:
        """Within `budget` hours: every build that no other beats on both kill time and damage taken, from "hit
        harder" to "take less" (a slider's weighted score only ever finds the two ends of this). Each gets w_lo/w_hi:
        the defence weights for which it is the strongest (None if it never is), and w_pick: the weight where it comes
        closest to the best (what the planner uses when you pick it). Neighbours closer than min_step in both numbers
        are merged."""
        damage = self.damage_frontier(p)
        armour = self.armour_frontier(p)
        builds = [b for b in self.combine(damage, armour, p) if b.hours <= budget + EPS]
        front, best_taken = [], math.inf
        for b in sorted(builds, key=lambda b: (round(b.kill_time, 6), b.damage_taken, b.hours)):
            if b.damage_taken < best_taken - EPS:
                front.append(b)
                best_taken = b.damage_taken
        thin = []
        for b in front:
            if not thin or (b.kill_time > thin[-1].kill_time * (1 + min_step) or b.damage_taken < thin[-1].damage_taken * (1 - min_step)):
                thin.append(b)
        weights = [i / 100 for i in range(101)]
        score = lambda b, w: self.strength(b.kill_time, b.damage_taken, p, w)  # noqa: E731
        best_at = {w: max(score(b, w) for b in thin) for w in weights}
        for b in thin:
            wins = [w for w in weights if score(b, w) >= best_at[w] - EPS]
            b.w_lo, b.w_hi = (min(wins), max(wins)) if wins else (None, None)
            b.w_pick = min(weights, key=lambda w: (best_at[w] - score(b, w)) / best_at[w])
        return thin

    def budgets(self, p: Profile, drop: float = 2.0, spread: float = 1.8, max_budgets: int = 7) -> list[dict]:
        """Time budgets worth looking at: Now, the points of the hours-vs-strength menu (balanced weighting) where the
        curve bends most (the gain per hour before a point over the gain per hour after it, at least `drop` times),
        at least `spread` times apart, and everything. Each: {"hours", "strength", "sweet"} (sweet: the sharpest bend,
        where more time stops paying)."""
        from dataclasses import replace
        menu = self.menu(replace(p, defence_weight=0.5), min_gain=0.0)
        if not menu:
            return [{"hours": 0.0, "strength": 1.0, "sweet": True}]
        first, last = menu[0], menu[-1]

        def at(hours: float):  # the menu point with the most hours up to `hours`
            return max((b for b in menu if b.hours <= hours + EPS), key=lambda b: b.hours, default=first)

        def slope(a, b) -> float:
            return (b.strength - a.strength) / max(b.hours - a.hours, 1e-6)
        # how much each point bends the curve: the gain per hour before it (from half its hours) over the gain per
        # hour after it (to twice its hours)
        bends = []
        for b in menu[1:-1]:
            before, after = at(b.hours / 2), at(b.hours * 2)
            if after is b:
                after = menu[menu.index(b) + 1]
            bends.append((slope(before, b) / max(slope(b, after), 1e-9), b))
        chosen = []
        for bend, b in sorted(bends, key=lambda x: -x[0]):
            if bend < drop or len(chosen) >= max_budgets - 2:
                break
            if b.hours >= 0.1 and all(max(b.hours, c.hours) / max(min(b.hours, c.hours), 1e-6) >= spread for _, c in chosen):
                chosen.append((bend, b))
        sweet = max(chosen, key=lambda x: x[0])[1] if chosen else last
        cuts = [first] + sorted((b for _, b in chosen), key=lambda b: b.hours)
        if all(max(last.hours, c.hours) / max(c.hours, 1e-6) >= spread for c in cuts[1:]) or len(cuts) == 1:
            cuts.append(last)
        return [{"hours": b.hours, "strength": b.strength, "sweet": b is sweet} for b in cuts]

    def combine(self, damage: list[dict], armour: list[dict], p: Profile) -> list[Build]:
        """Every weapon/accessory set with every armour set, as builds."""
        builds = []
        for d in damage:
            _, badge_def = self.opt.badge_bonus(d["tribe"], p.skill_points)
            for a in armour:
                worn = [o.item for o in a["armour"] if o.item]
                taken = self.taken(worn, p, badge_def)
                picks = {o.slot: o for o in d["acc"]} | {o.slot: o for o in a["armour"]}
                hits = {}
                for c, (o, hit, n, t) in d["weapons"]:
                    picks[c.capitalize()] = Option(c.capitalize(), o.item, o.hours)
                    hits[c] = {"hit": hit, "hits": n, "time": t}
                builds.append(Build(d["hours"] + a["hours"], self.strength(d["kill_time"], taken, p), d["kill_time"],
                                    taken, ELEMENT_TRIBE.get(d["tribe"]), picks, hits))
        return builds

    UTILITY = ("Stun", "Heal", "Poison", "Buff")

    @staticmethod
    def utility_slot(it: dict) -> str | None:
        fx = it.get("fx") or {}
        if "StunStatusEffect" in fx:
            return "Stun"
        if "PoisonDamage" in fx:
            return "Poison"
        if any(k in fx for k in ("LifeSteal", "HealingPercent", "Healing")):
            return "Heal"
        if "Invisibility" in fx or "IncreaseAllResist" in fx or (it.get("subcategory") == "Defensive" and any(k.startswith("Resist") for k in fx)):
            return "Buff"
        return None

    def utility(self, p: Profile, picks: dict[str, dict], slots: tuple[str, ...] = UTILITY,
                hours: Callable[[dict], float | None] | None = None, tribe: str | None = None) -> dict[str, list[dict]]:
        """The best items for your utility hotbar slots, valued against your build (picks): Stun = free hits of your
        main weapon while the enemy is stunned (stuns hold bosses too, the user 2026-10-04); Heal = HP healed per
        second of cooldown (life steal: a share of the item's own hit); Poison = poison damage per use (a share of the
        hit, UNVERIFIED); Buff = resist × the share of the time it is up, or seconds invisible. Per slot only the
        items no other beats on hours and value: [{"item", "value", "text", "hours"}], best last. hours(item):
        another price list than the planner's (the progression prices them once); tribe: where the badge is (else the
        best one for the build)."""
        ev = self.evaluate(picks, p, tribe=tribe)
        main = max(ev["hits"].values(), key=lambda h: h["hit"] / max(h["time"] / max(h["hits"], 1), 0.5), default=None)
        main_cd = max(main["time"] / max(main["hits"], 1), 0.5) if main else 1.0
        ap = self.opt.stat("AbilityPower", "Player", p.level)
        hp = self.opt.stat("IncreaseHitPoints", "Player", p.level)
        out: dict[str, list[dict]] = {s: [] for s in slots}
        for it in self.opt.item.values():
            slot = self.utility_slot(it)
            if slot not in out or not it["name"] or it["action_type"] == "Relic" or (it["level_req"] or 0) > p.level:
                continue
            if it["prefab"] in self.opt.exclude:
                continue
            if not (it["is_weapon"] or it["subcategory"] in ("Defensive", "Bomb")):
                continue
            h = 0.0 if p.owned.get(it["prefab"]) else hours(it) if hours else self.hours(it, p)
            if h is None:
                continue
            fx, cd = it["fx"], max(it["cooldown"] or 0, 0.5)
            own_hit = ap + (it["scaled_sum"] or 0) if it["is_weapon"] else 0
            if slot == "Stun":
                secs = fx["StunStatusEffect"][1]
                free = math.floor(secs / main_cd) if main else 0
                value = free * (main["hit"] if main else 0)
                _, enemy_hp, _ = self.enemy(p)
                text = (f"stuns {secs:g} s: {free} free hits of your main weapon ({value:,.0f} damage, "
                        f"{min(value / max(enemy_hp, 1), 9.99) * 100:.0f} % of an enemy's hit points, before it hits back)")
            elif slot == "Poison":
                pct, secs = fx["PoisonDamage"]
                value = pct / 100 * own_hit if own_hit else pct
                text = f"poison {value:,.0f} over {secs:g} s"
            elif slot == "Heal":
                if "HealingPercent" in fx:
                    healed, how = fx["HealingPercent"][0] / 100 * hp, f"heals {fx['HealingPercent'][0]:g} % of your HP"
                elif "LifeSteal" in fx:
                    healed, how = fx["LifeSteal"][0] / 100 * own_hit, f"steals {fx['LifeSteal'][0]:g} % of its hit"
                else:
                    healed, how = fx["Healing"][0], f"heals {fx['Healing'][0]:g} HP"
                value, text = healed / cd, f"{how}: {healed / cd:,.0f} HP a second"
            else:
                if "Invisibility" in fx:
                    secs = fx["Invisibility"][1]
                    value, text = secs, f"invisible {secs:g} s"
                else:
                    v, secs = max(((val, d) for k, (val, d) in fx.items() if k.startswith("Resist") or k == "IncreaseAllResist"),
                                  key=lambda x: x[0])
                    up = min(1.0, secs / cd)
                    value, text = v * up, f"+{v:g} resist for {secs:g} s (up {up * 100:.0f} % of the time)"
            out[slot].append({"item": it, "value": value, "text": text, "hours": h})
        for slot, rows in out.items():
            out[slot] = pareto(rows, lambda r: r["hours"], lambda r: r["value"])
        return out
