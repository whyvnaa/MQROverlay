"""Your character from the game's own messages, for the Build tab: level, XP, bananas, NickCash, badge points and
tribe, inventory, hotbar, worn gear and learned patterns. Formats from the upstream server (MQReawakened; MQReborn may
differ, so everything is parsed defensively and failures are only counted):

- in  %xt%ci%<room>%<user>%<info>%<object>%<level name>%   character info. When you pick your character the server
      sends your own "Detailed" info (CharacterDataModel.ToString, sections split by "["): [0] fields split by "<"
      (3 bananas, 4 NickCash, 9 level, 11 XP, 17 badge points, 18 tribe, 21+ "tribe|points|unlocked"), [2] inventory
      ("id{count{binding{delay" split by ">"), [5] hotbar, [8] worn gear ("slot=id=binding" split by ":"), and later
      the learned recipes ("recipe,item,n,..." split by "|"). Other players' info (Lite) has far fewer sections.
      Zone changes send only your position, so the full picture comes at login.
- in  %xt%ip%<room>%<items>%<flag>%     inventory: "id{count{binding{delay|id{..." (CharacterInventoryExtensions)
- in  %xt%ca%<room>%<bananas>%<nc>%     bananas and NickCash (PlayerExtensions.SendCashUpdate)
- in  %xt%cp%<room>%<xp>%<xp for next level>%   (PlayerExtensions.SendRepPoints)
- in  %xt%ce%<room>%<level<...>%<user>%  level up (LevelUpDataModel; yours when the user is you)
- in  %xt%cA%<room>%<type|points|unlocked<...>%<tribe>%<auto>%   badge points per tribe (AssignBadges)
- in  %xt%cz%<room>%<recipe,item,n,...>%  a pattern learned (UseItem)
- in  %xt%hs|hu%<room>%<slot|item|slot|item...>%  hotbar (UseItem, UseItemFromHotBar)
- out %xt%<ext>%ie%<room>%<slot=id=binding:...>%   your new equipment (EquipItem; worn items leave the inventory)
- in  %xt%iq%<room>%<user>%<slot=id=binding:...>%  someone's equipment (yours when the user is you)

What was parsed (numbers only, never a raw message: the login message holds the password in plain text) is saved to
the overlay's settings folder (character.json), so a restarted overlay still knows you until the next login."""

import json
import threading
import time
from pathlib import Path

TRIBES = {2: "Crossroads", 3: "Bone", 4: "Shadow", 5: "Wild", 6: "Outlaw", 7: "Grease"}  # A2m.Server.TribeType
FIELDS = ("inventory", "worn", "hotbar", "recipes", "bananas", "nick_cash", "xp", "level", "badges", "tribe")


def num(text: str) -> int:
    return int(float(text.replace(",", ".")))


def lead_int(text: str) -> int | None:
    """The number at the start of "12{1{0" or "12"."""
    head = text.split("{")[0].split(",")[0].strip()
    return int(head) if head.lstrip("-").isdigit() else None


def parse_items(text: str) -> dict[int, int]:
    """Inventory items "id{count{binding{delay", split by "|" (ip) or ">" (login info)."""
    out: dict[int, int] = {}
    for entry in text.replace(">", "|").split("|"):
        f = entry.split("{")
        if len(f) >= 2 and f[0].lstrip("-").isdigit() and f[1].lstrip("-").isdigit():
            if int(f[1]) > 0:
                out[int(f[0])] = out.get(int(f[0]), 0) + int(f[1])
    return out


def parse_equipment(text: str) -> dict[int, int]:
    """slot (ItemSubCategory) -> item id."""
    out = {}
    for entry in text.split(":"):
        f = entry.split("=")
        if len(f) == 3 and f[0].isdigit() and f[1].isdigit():
            out[int(f[0])] = int(f[1])
    return out


def parse_hotbar(text: str) -> dict[int, int]:
    """hotbar slot -> item id, from "slot|item|slot|item" (an item may come as "id{count...")."""
    f = text.split("|")
    out = {}
    for i in range(0, len(f) - 1, 2):
        slot, item = lead_int(f[i]), lead_int(f[i + 1])
        if slot is not None and item and item > 0:
            out[slot] = item
    return out


def parse_recipes(text: str) -> set[int]:
    """Learned recipes "recipe,item,n,ingredients..." split by "|": the item ids they make."""
    out = set()
    for entry in text.split("|"):
        f = entry.split(",")
        if len(f) >= 3 and f[0].isdigit() and f[1].isdigit():
            out.add(int(f[1]))
    return out


def parse_tribes(entries: list[str]) -> dict[str, int]:
    badges = {}
    for entry in entries:
        f = entry.split("|")
        if len(f) >= 2 and f[0].isdigit() and int(f[0]) in TRIBES and f[1].lstrip("-").isdigit():
            badges[TRIBES[int(f[0])]] = int(f[1])
    return badges


def parse_login(info: str) -> dict | None:
    """Your own detailed character info (None if this is another player's short info)."""
    sec = info.split("[")
    if len(sec) < 9:
        return None
    head = sec[0].split("<")
    if len(head) < 21:
        return None
    out = {"bananas": num(head[3]), "nick_cash": num(head[4]), "level": num(head[9]), "xp": num(head[11]),
           "tribe": TRIBES.get(num(head[18])), "badges": parse_tribes(head[21:]),
           "inventory": parse_items(sec[2]), "hotbar": parse_hotbar(sec[5]), "worn": parse_equipment(sec[8])}
    for s in sec[9:]:  # the recipe list: entries like "12,345,3,..."; the resistances are plain numbers
        if "," in s and parse_recipes(s):
            out["recipes"] = parse_recipes(s)
            break
    else:
        out["recipes"] = set()
    return out


class PlayerState:
    """Latest known character data (None = not seen yet), written by the capture thread."""

    def __init__(self, cache: Path | None = None):
        self.lock = threading.Lock()
        self.cache = cache
        self.inventory: dict[int, int] | None = None  # item id -> count (without worn gear)
        self.worn: dict[int, int] | None = None  # slot -> item id
        self.hotbar: dict[int, int] | None = None  # hotbar slot -> item id
        self.recipes: set[int] | None = None  # item ids you have learned to craft
        self.bananas: int | None = None
        self.nick_cash: int | None = None
        self.xp: int | None = None
        self.level: int | None = None
        self.badges: dict[str, int] | None = None  # tribe -> badge points
        self.tribe: str | None = None
        self.user: str | None = None  # your user id (from your login info)
        self.source = "none"  # login, live (changes only), saved (from character.json)
        self.saved_at: float | None = None
        self.seen: dict[str, int] = {}  # message code -> count (parsed ones)
        self.errors = 0
        self.version = 0  # bumps on every change, so the Build tab knows when to plan again
        self.load()

    # ---------------------------------------------------------------- messages

    def handle(self, direction: str, msg: str) -> None:
        if not msg.startswith("%xt%"):
            return
        parts = msg.split("%")
        try:
            if direction == "in" and len(parts) > 4:
                self.incoming(parts[2], parts[4:-1])
            elif direction == "out" and len(parts) > 5 and parts[3] == "ie":
                worn = parse_equipment(parts[5])
                with self.lock:
                    self.worn = worn
                    self.bump("ie")
        except (ValueError, IndexError):
            with self.lock:
                self.errors += 1

    def incoming(self, code: str, args: list[str]) -> None:
        if code == "ci" and len(args) >= 2:
            data = parse_login(args[1])
            if data:
                with self.lock:
                    for k, v in data.items():
                        setattr(self, k, v)
                    self.user, self.source = args[0], "login"
                    self.bump(code)
        elif code == "ip" and args:
            items = parse_items(args[0])
            with self.lock:
                self.inventory = items
                self.bump(code)
        elif code == "ca" and len(args) >= 2:
            bananas, nc = num(args[0]), num(args[1])
            with self.lock:
                self.bananas, self.nick_cash = bananas, nc
                self.bump(code)
        elif code == "cp" and args:
            xp = num(args[0])
            with self.lock:
                self.xp = xp
                self.bump(code)
        elif code == "ce" and len(args) >= 2:
            level = num(args[0].split("<")[0])
            with self.lock:
                if self.user is None or args[1] == self.user:
                    self.level = level
                    self.bump(code)
        elif code == "cA" and args:
            badges = parse_tribes(args[0].split("<"))
            with self.lock:
                self.badges = badges
                if len(args) >= 2 and args[1].isdigit():
                    self.tribe = TRIBES.get(int(args[1]), self.tribe)
                self.bump(code)
        elif code == "cz" and args:
            learned = parse_recipes(args[0])
            with self.lock:
                self.recipes = (self.recipes or set()) | learned
                self.bump(code)
        elif code in ("hs", "hu") and args:
            bar = parse_hotbar(args[0])
            with self.lock:
                self.hotbar = bar
                self.bump(code)
        elif code == "iq" and len(args) >= 2:
            worn = parse_equipment(args[1])
            with self.lock:
                # someone's gear: yours if the user is you, or (before a login was seen) if it holds what you wore
                mine = args[0] == self.user if self.user else (
                    self.worn is not None and worn and set(worn.items()) & set(self.worn.items()))
                if mine:
                    self.worn = worn
                    self.bump(code)

    def bump(self, code: str) -> None:
        self.seen[code] = self.seen.get(code, 0) + 1
        self.version += 1
        if self.source == "saved" and code != "ci":
            self.source = "live"
        self.save()

    # ---------------------------------------------------------------- saved copy

    def load(self) -> None:
        if not self.cache:
            return
        try:
            d = json.loads(self.cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        conv = {"inventory": lambda v: {int(k): n for k, n in v.items()}, "worn": lambda v: {int(k): n for k, n in v.items()},
                "hotbar": lambda v: {int(k): n for k, n in v.items()}, "recipes": set}
        for k in FIELDS:
            if d.get(k) is not None:
                setattr(self, k, conv.get(k, lambda v: v)(d[k]))
        self.source, self.saved_at = "saved", d.get("time")
        self.version = 1

    def save(self) -> None:
        """Write the parsed values (called under the lock)."""
        if not self.cache:
            return
        d = {k: getattr(self, k) for k in FIELDS}
        d["recipes"] = sorted(self.recipes) if self.recipes is not None else None
        d["time"] = time.time()
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            with self.cache.open("w", encoding="utf-8", newline="\n") as fh:
                json.dump(d, fh)
                fh.write("\n")
        except OSError:
            pass

    # ---------------------------------------------------------------- reading

    def level_from_xp(self, level_xp: list[int]) -> int | None:
        """Your level from your XP and the XP table (cumulative XP to reach each next level)."""
        with self.lock:
            xp = self.xp
        if xp is None:
            return None
        return 1 + sum(1 for t in level_xp if t and xp >= t)

    def snapshot(self) -> dict:
        with self.lock:
            return {"inventory": dict(self.inventory or {}), "worn": dict(self.worn or {}),
                    "hotbar": dict(self.hotbar or {}), "recipes": set(self.recipes or ()),
                    "bananas": self.bananas, "nick_cash": self.nick_cash, "xp": self.xp, "level": self.level,
                    "badges": dict(self.badges or {}), "tribe": self.tribe, "source": self.source,
                    "saved_at": self.saved_at, "known": self.inventory is not None, "version": self.version}
