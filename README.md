# MonkeyQuest Overlay

A map and build overlay for the Monkey Quest client on MQReborn. It shows the map of the zone you are in, where
you are, an arrow to any spot you pick, and a Build tab that works out the best gear for your character at every
level from what you own.

It only reads: the client's log file (to know your zone), the game's own network messages (your position and your
character), and the map data in `data/`. It does not touch the game, its files or its memory.

## Install and run

**Download**: the zip from the [latest release](https://github.com/whyvnaa/MQROverlay/releases/latest) (about
30 MB), unzip it anywhere and run `mq-overlay.exe`. Windows SmartScreen warns once about an unsigned program:
"More info", then "Run anyway".

**Or with [uv](https://docs.astral.sh/uv/)** (it brings its own Python), in any terminal:

```bash
uvx --from git+https://github.com/whyvnaa/MQROverlay mq-overlay
```

The first start downloads the overlay and the whole Qt package (about 100 MB, once); to update, add `--refresh`.
Or clone the repository and run `uv run mq-overlay` inside it.

Windows only (the game is too). The game must run in a window or borderless window: overlays can't draw over
exclusive fullscreen (Alt+Enter in the game switches). The game's install folder doesn't matter.

### Live position (Npcap)

Where you are, the arrow, and your character in the Build tab come from the game's own connection, which the
overlay reads through [Npcap](https://npcap.com/#download). Install it once (keep "Install Npcap in WinPcap
API-compatible Mode" ticked, leave "Restrict Npcap driver's access to Administrators only" unticked). The overlay
tells you at start when Npcap is missing, with the steps and a "Check again" button, so no restart is needed; the
tray menu and the map's header open the same window later. The overlay only listens to the game's connection
(port 9339), in memory: nothing is logged or saved, and your login is never stored.

Without Npcap the maps, the search and the Build tab's planning still work; you just have no position and the
Build tab doesn't know your character.

## Keys

| Key | What it does |
|---|---|
| **F8** | corner map on/off: a small map in a corner of the game window, click-through, follows you |
| **F7** | full-screen map on/off: covers the game, takes the mouse; Esc closes it too |
| Ctrl+F | the search box on the full-screen map |
| wheel, drag, double-click | zoom, move, whole zone again |
| click a marker or spot | sets your waypoint: a banana-yellow arrow over the game points the way, zone by zone |
| right-click a marker | opens its page on the [Monkey Quest Reborn Wiki](https://whyvnaa.github.io/MQRWiki/) |
| Shift+click | tells the overlay where you are, when there is no live position |

Both hotkeys work while the game has focus. If one is taken by another program, the tray message says so; change
it in the settings file (below) or use the tray icon's menu, which has the same actions.

## The full-screen map

- **Map | Build** at the top switches between the map and the Build tab.
- **Find**: enemy and NPC names, portal targets, quest items and everything chests, gathering spots and enemies
  drop. Matches light up on the map and the list shows every zone with matches; click one to look at its map,
  "Back to …" returns to your zone.
- **Look at another zone**, **Show on the map** (each marker kind on or off, saved) and **Front path | Back path**
  (the path on show; "Find me" zooms to you on your path).
- **Waypoint**: click anywhere. In another zone the arrow points at the portal to take; where a path ends it points
  at the bridge to the other path, using the game's own route data. "Clear waypoint" in the header removes it.

## The Build tab

Your level, bananas, skill points, inventory, hotbar and worn gear come from the game when you log in with the
overlay running (a saved copy is kept, so a restarted overlay still knows you). Then:

- **Your gear** (left): what you wear per slot, and "better in your bag" when something you own would do more.
- **Progression** (middle): the best gear at every level from 1 to 60 for the badge you pick (or Auto), one lane
  per slot. Click a level for its card: the best set and every other item you could wear there, with what it costs
  you against the best, how long it takes to get and the way. 📍 jumps to the place on the map.
- **Shop list**: what is worth looking for now and a few levels above, per tribe and armour group.
- **Item cards** (right): stats, what the item adds to you, how to get it with every zone that has it, other
  upgrades for the slot, and **Exclude** for items you don't want suggested (listed on the left, where you can take
  them back).
- The strip on top: your hotbar (which slots to plan for), the build style (Hybrid, Melee build, Ranged build),
  who you fight, and where items may come from.

The same planner runs on the wiki's [build calculator](https://whyvnaa.github.io/MQRWiki/guides/calculator.html);
the overlay adds your real inventory.

## Settings and options

Settings are in `%LOCALAPPDATA%\MonkeyQuest-Overlay\MQ Overlay\settings.json` (only what differs from the defaults
is saved): `hotkey_fullmap`, `hotkey_minimap` (e.g. `"Ctrl+M"`), `minimap` (on/off), `minimap_corner`
(`top-right`, `top-left`, `bottom-right`, `bottom-left`), `minimap_width` (part of the game width, default 0.16),
`minimap_margin` (pixels from the edges), `minimap_span` (how far the corner map shows around you, in game units;
a game screen is 20), `live_prompt` (the Npcap window at start). Your character is saved next to it as
`character.json` (numbers and item ids only).

Command line: `--zone LV_CRS_Trail01` shows a zone instead of following the log, `--full` opens the full-screen
map right away (works without the game), `--log PATH` reads another log file (the default is the client's
`output_log.txt` under `%LOCALAPPDATA%Low\MQReborn Team\MQReborn`), `--no-live` turns the live position off.
`--snapshot out.png` renders the overlay into a PNG and exits (for testing; `--build LEVEL`, `--own`, `--card`,
`--shop` and more set up the Build tab for it).

Tests: `uv run pytest`. Release zip: `uv run --group build tools/build_exe.py` (PyInstaller; a tag `v*` on GitHub
builds and attaches it automatically).

## Data

`data/` is generated by the MonkeyQuest knowledge base (its `scripts/export_overlay.py`) from the level files of
the MQReborn client: terrain, invisible walls and the placed objects, joined to its database for names, drop
tables, portal targets and wiki links; the game's own route data per zone; the build planner and its item data.
Portraits are renders of the game's 3D models. Monkey Quest art © Nickelodeon.
