"""
BSP dungeon generator.
Produces a tile grid (FLOOR / WALL), a list of rooms, and a starting position.
All coordinates are in tile units; multiply by TILE to get pixels.
"""
import random
from dataclasses import dataclass

FLOOR = 0
WALL  = 1
TILE  = 64   # pixels per tile — must match world.TILE_SIZE


@dataclass
class Room:
    tx: int   # tile x (left)
    ty: int   # tile y (top)
    tw: int   # tile width
    th: int   # tile height

    @property
    def cx(self) -> int:
        return self.tx + self.tw // 2

    @property
    def cy(self) -> int:
        return self.ty + self.th // 2

    def center_px(self):
        return self.cx * TILE + TILE // 2, self.cy * TILE + TILE // 2

    def random_floor_px(self):
        rx = random.randint(self.tx + 1, self.tx + self.tw - 2)
        ry = random.randint(self.ty + 1, self.ty + self.th - 2)
        return rx * TILE + TILE // 2, ry * TILE + TILE // 2

    def overlaps(self, other: "Room", padding: int = 2) -> bool:
        return (self.tx < other.tx + other.tw + padding and
                self.tx + self.tw + padding > other.tx and
                self.ty < other.ty + other.th + padding and
                self.ty + self.th + padding > other.ty)


class Dungeon:
    def __init__(self, cols: int = 40, rows: int = 40,
                 room_count: int = 14,
                 min_room: tuple = (5, 4),
                 max_room: tuple = (11, 9)):
        self.cols = cols
        self.rows = rows
        self.grid: list[list[int]] = [[WALL] * cols for _ in range(rows)]
        self.rooms: list[Room] = []
        self._generate(room_count, min_room, max_room)

    # ── generation ────────────────────────────────────────────────────
    def _generate(self, count, min_r, max_r):
        attempts = 0
        while len(self.rooms) < count and attempts < count * 20:
            attempts += 1
            tw = random.randint(min_r[0], max_r[0])
            th = random.randint(min_r[1], max_r[1])
            tx = random.randint(1, self.cols - tw - 2)
            ty = random.randint(1, self.rows - th - 2)
            candidate = Room(tx, ty, tw, th)
            if any(candidate.overlaps(r) for r in self.rooms):
                continue
            self._carve_room(candidate)
            self.rooms.append(candidate)

        # Connect rooms in sorted order (nearest-neighbour walk)
        ordered = self._sort_rooms()
        for i in range(1, len(ordered)):
            self._connect(ordered[i - 1], ordered[i])

        # Boss room: largest room, kept last
        self.rooms.sort(key=lambda r: r.tw * r.th)
        self.boss_room = self.rooms[-1]
        self.start_room = self.rooms[0]

    def _carve_room(self, room: Room):
        for ry in range(room.ty, room.ty + room.th):
            for rx in range(room.tx, room.tx + room.tw):
                self.grid[ry][rx] = FLOOR

    def _connect(self, a: Room, b: Room):
        # L-shaped corridor between centres
        x1, y1 = a.cx, a.cy
        x2, y2 = b.cx, b.cy
        corridor_w = random.randint(2, 3)   # 2-3 tiles wide feels more natural

        if random.random() < 0.5:
            # horizontal first, then vertical
            for x in range(min(x1, x2), max(x1, x2) + 1):
                for dy in range(corridor_w):
                    self._set_floor(x, y1 + dy)
            for y in range(min(y1, y2), max(y1, y2) + 1):
                for dx in range(corridor_w):
                    self._set_floor(x2 + dx, y)
        else:
            # vertical first, then horizontal
            for y in range(min(y1, y2), max(y1, y2) + 1):
                for dx in range(corridor_w):
                    self._set_floor(x1 + dx, y)
            for x in range(min(x1, x2), max(x1, x2) + 1):
                for dy in range(corridor_w):
                    self._set_floor(x, y2 + dy)

    def _set_floor(self, tx: int, ty: int):
        if 1 <= tx < self.cols - 1 and 1 <= ty < self.rows - 1:
            self.grid[ty][tx] = FLOOR

    def _sort_rooms(self) -> list[Room]:
        if not self.rooms:
            return []
        remaining = list(self.rooms)
        ordered = [remaining.pop(0)]
        while remaining:
            last = ordered[-1]
            nearest = min(remaining,
                          key=lambda r: abs(r.cx - last.cx) + abs(r.cy - last.cy))
            ordered.append(nearest)
            remaining.remove(nearest)
        return ordered

    # ── queries ───────────────────────────────────────────────────────
    def is_floor(self, tx: int, ty: int) -> bool:
        if 0 <= tx < self.cols and 0 <= ty < self.rows:
            return self.grid[ty][tx] == FLOOR
        return False

    def is_floor_px(self, px: float, py: float) -> bool:
        return self.is_floor(int(px) // TILE, int(py) // TILE)

    def is_floor_rect_px(self, px: float, py: float, radius: int) -> bool:
        """True only if all four corners of the entity's bounding box are on floor."""
        r = radius - 2   # shrink slightly so edges don't clip
        for dx, dy in ((-r, -r), (r, -r), (-r, r), (r, r)):
            if not self.is_floor_px(px + dx, py + dy):
                return False
        return True
