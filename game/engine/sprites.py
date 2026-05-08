"""
Sprite manager — loads assets once, provides surfaces to all entity draw() calls.
Nearest-neighbour scaling used throughout to preserve pixel-art look.
"""
import pygame
from pathlib import Path

_ASSET_ROOT = Path(__file__).parent.parent / "assets"

# ── Tiny Dungeon tile indices (16 × 16 each, 12 cols × 11 rows) ────────
# Row 0  (0 –11): stone/dirt floor variants
# Row 1  (12–23): wall tiles
# Row 6  (72–83): hero/NPC characters
# Row 7  (84–95): basic enemies
# Row 8  (96–107): monsters
FLOOR_IDS   = [0, 1, 2, 3]           # dark stone floor tiles
PLAYER_ID   = 72                     # knight (first character row)
HIT_FLASH   = (255, 80, 80, 180)     # colour used for damage flash

# ── Skeleton sheet layout (48 × 64 per frame, 3 cols × 4 rows) ─────────
# Row 0 = North  1 = East  2 = South  3 = West
SKEL_DIR_ROW = {"N": 0, "E": 1, "S": 2, "W": 3}


class SpriteManager:
    """Singleton-style manager; create once in main.py, share the reference."""

    def __init__(self):
        td   = _ASSET_ROOT / "kenney_tiny_dungeon" / "Tiles"
        sk48 = _ASSET_ROOT / "skeletons" / "PNG" / "48x64_scale"
        sk168= _ASSET_ROOT / "skeletons" / "PNG" / "168x224_scale2x"

        # ── floor tiles scaled to 64 × 64 ───────────────────────────────
        self.floor_tiles: list[pygame.Surface] = []
        for idx in FLOOR_IDS:
            raw = pygame.image.load(str(td / f"tile_{idx:04d}.png")).convert_alpha()
            self.floor_tiles.append(pygame.transform.scale(raw, (64, 64)))

        # ── wall tile: row 1 of Tiny Dungeon (dark stone block) ─────────
        raw = pygame.image.load(str(td / "tile_0014.png")).convert_alpha()
        self.wall_tile = pygame.transform.scale(raw, (64, 64))
        # top-edge cap — slightly lighter strip drawn above wall tiles
        raw_cap = pygame.image.load(str(td / "tile_0012.png")).convert_alpha()
        self.wall_cap = pygame.transform.scale(raw_cap, (64, 64))

        # ── player: 16 × 16 → 40 × 40 ───────────────────────────────────
        raw = pygame.image.load(str(td / f"tile_{PLAYER_ID:04d}.png")).convert_alpha()
        self.player = pygame.transform.scale(raw, (40, 40))

        # ── enemy walk-cycles (south-facing, 3 frames) ──────────────────
        self.enemy_frames: dict[str, list[pygame.Surface]] = {
            "melee":  self._skel_row(sk48 / "skeleton-NESW.png",        48, 64, 2),
            "ranged": self._skel_row(sk48 / "demon_skeleton-NESW.png",   48, 64, 2),
            "elite":  self._skel_row(sk48 / "warrior_skeleton-NESW.png", 48, 64, 2),
        }

        # ── boss: large demon skeleton, south row, frame 1 ───────────────
        sheet = pygame.image.load(str(sk168 / "demon_skeleton-NESW.png")).convert_alpha()
        # extract middle walk frame, south row
        raw_boss = sheet.subsurface(pygame.Rect(168, 2 * 224, 168, 224))
        self.boss = pygame.transform.scale(raw_boss, (70, 93))

        # ── damage-flash overlay cache ────────────────────────────────────
        self._flash_cache: dict[tuple, pygame.Surface] = {}

    # ── helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _skel_row(path: Path, fw: int, fh: int, row: int) -> list[pygame.Surface]:
        sheet = pygame.image.load(str(path)).convert_alpha()
        return [sheet.subsurface(pygame.Rect(col * fw, row * fh, fw, fh))
                for col in range(3)]

    def floor_tile(self, tx: int, ty: int) -> pygame.Surface:
        return self.floor_tiles[(tx + ty) % len(self.floor_tiles)]

    def enemy_frame(self, etype: str, anim_tick: int) -> pygame.Surface:
        frames = self.enemy_frames.get(etype, self.enemy_frames["melee"])
        return frames[anim_tick % len(frames)]


# Module-level singleton — set once in main.py after pygame.init()
_mgr: SpriteManager | None = None


def init() -> SpriteManager:
    global _mgr
    _mgr = SpriteManager()
    return _mgr


def get() -> SpriteManager | None:
    return _mgr
