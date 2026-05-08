import random
import pygame
from .constants import *
from .dungeon   import Dungeon, FLOOR, WALL, TILE
from .enemy     import Enemy
from .boss      import Boss
from .loot      import LootOrb
from .projectile import Projectile

GRID_COLS = 40
GRID_ROWS = 40
WORLD_W   = GRID_COLS * TILE
WORLD_H   = GRID_ROWS * TILE


class Zone:
    def __init__(self, level: int, mults: dict = None, boss_profile: dict = None):
        self.level        = level
        self.mults        = mults or {}
        self.boss_profile = boss_profile
        self.bounds       = pygame.Rect(0, 0, WORLD_W, WORLD_H)

        self.dungeon = Dungeon(GRID_COLS, GRID_ROWS, room_count=12)

        self.enemies:     list[Enemy]     = []
        self.boss:        Boss | None     = None
        self.loot:        list[LootOrb]   = []
        self.projectiles: list[Projectile]= []

        self.boss_spawned  = False
        self.boss_defeated = False
        self.cleared       = False

        self._spawn_enemies()

    # ── player start position (centre of start room) ──────────────────
    @property
    def player_start(self) -> tuple[float, float]:
        return self.dungeon.start_room.center_px()

    # ── setup ──────────────────────────────────────────────────────────
    def _spawn_enemies(self):
        count = 12 + self.level * 3
        self.kills_for_boss = max(6, count // 2)
        pool  = ["melee"] * 6 + ["ranged"] * 3 + ["elite"] * 1

        # collect all floor rooms except boss room & start room
        spawn_rooms = [r for r in self.dungeon.rooms
                       if r is not self.dungeon.boss_room
                       and r is not self.dungeon.start_room]
        if not spawn_rooms:
            spawn_rooms = self.dungeon.rooms[:]

        for _ in range(count):
            room = random.choice(spawn_rooms)
            x, y = room.random_floor_px()
            self.enemies.append(Enemy(x, y, random.choice(pool), self.level, self.mults))

    def _spawn_boss(self):
        bx, by = self.dungeon.boss_room.center_px()
        self.boss = Boss(bx, by, self.level, self.boss_profile)
        self.boss_spawned = True

    # ── queries ────────────────────────────────────────────────────────
    @property
    def kill_count(self) -> int:
        return sum(1 for e in self.enemies if not e.alive)

    @property
    def alive_enemies(self):
        return [e for e in self.enemies if e.alive]

    def is_walkable(self, px: float, py: float, radius: int = 14) -> bool:
        return self.dungeon.is_floor_rect_px(px, py, radius)

    # ── main update ────────────────────────────────────────────────────
    def update(self, dt: float, player, metrics) -> list[tuple]:
        events = []

        # Boss spawn trigger
        if not self.boss_spawned and self.kill_count >= self.kills_for_boss:
            self._spawn_boss()
            metrics.boss_attempts += 1
            events.append(("boss_spawn", self.boss))

        # Enemies
        for enemy in self.alive_enemies:
            for ev in enemy.update(dt, player.pos, self.dungeon):
                events += self._handle_attack_event(ev, player, metrics)

        # Boss
        if self.boss and self.boss.alive:
            for ev in self.boss.update(dt, player.pos):
                events += self._handle_attack_event(ev, player, metrics)
            if not self.boss.alive:
                bx, by = self.boss.pos.x, self.boss.pos.y
                self.loot.append(LootOrb(bx, by, self.boss.max_hp // 2, boss_drop=True))
                metrics.boss_kills += 1
                events.append(("boss_kill", self.boss))

        # Projectiles
        for p in self.projectiles:
            p.update(dt, self.bounds, self.dungeon)
            if p.alive and p.owner in ("enemy", "boss"):
                if p.pos.distance_to(player.pos) < player.radius + p.radius:
                    dmg = player.take_damage(p.damage)
                    if dmg > 0:
                        metrics.total_damage_taken += dmg
                        events.append(("player_hit", dmg))
                    p.alive = False

        # Loot pickup
        for orb in self.loot:
            orb.update(dt)
            if orb.alive and orb.pos.distance_to(player.pos) < player.radius + orb.radius + 14:
                player.gain_xp(orb.xp)
                orb.alive = False
                events.append(("xp", orb.xp))

        self.projectiles = [p for p in self.projectiles if p.alive]
        self.loot        = [o for o in self.loot if o.alive]

        # Zone clear
        if self.boss_spawned and self.boss and not self.boss.alive and not self.cleared:
            self.cleared = True
            events.append(("zone_cleared", self.level))

        return events

    def _handle_attack_event(self, ev: dict, player, metrics) -> list[tuple]:
        events = []
        etype = ev.get("type")
        if etype == "melee":
            if ev["pos"].distance_to(player.pos) < player.radius + 50:
                dmg = player.take_damage(ev["damage"])
                if dmg > 0:
                    metrics.total_damage_taken += dmg
                    events.append(("player_hit", dmg))
        elif etype == "projectile":
            self.projectiles.append(Projectile(
                ev["pos"], ev["dir"], ev["damage"],
                ev["speed"], ev["color"], ev["owner"],
                ev.get("lifetime", 5.0),
            ))
        elif etype == "spawn_enemy":
            # only spawn on floor tiles
            px, py = ev["pos"].x, ev["pos"].y
            if self.dungeon.is_floor_px(px, py):
                self.enemies.append(Enemy(px, py, "melee", self.level))
        return events

    # ── player attack (called from main on SPACE) ──────────────────────
    def player_attack(self, player, metrics) -> float:
        if not player.can_attack():
            return 0.0
        player.do_attack()
        total = 0.0
        for e in self.alive_enemies:
            if player.pos.distance_to(e.pos) <= player.attack_range + e.radius:
                dmg = player.damage
                e.take_damage(dmg)
                total += dmg
                if not e.alive:
                    metrics.total_kills += 1
                    self.loot.append(LootOrb(e.pos.x, e.pos.y, e.xp))
        if self.boss and self.boss.alive:
            if player.pos.distance_to(self.boss.pos) <= player.attack_range + self.boss.radius:
                dmg = player.damage
                self.boss.take_damage(dmg)
                total += dmg
        if total > 0:
            metrics.total_damage_dealt += total
        return total

    # ── draw ───────────────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface, cam: pygame.Vector2):
        from . import sprites as spr
        mgr = spr.get()

        t = TILE
        cam_ix, cam_iy = int(cam.x), int(cam.y)
        tx_start = cam_ix // t
        ty_start = cam_iy // t
        tx_end   = tx_start + surface.get_width()  // t + 2
        ty_end   = ty_start + surface.get_height() // t + 2

        for ty in range(max(0, ty_start), min(GRID_ROWS, ty_end)):
            for tx in range(max(0, tx_start), min(GRID_COLS, tx_end)):
                sx = tx * t - cam_ix
                sy = ty * t - cam_iy
                cell = self.dungeon.grid[ty][tx]

                if cell == FLOOR:
                    if mgr:
                        surface.blit(mgr.floor_tile(tx, ty), (sx, sy))
                    else:
                        pygame.draw.rect(surface, (30, 30, 40), (sx, sy, t, t))
                else:  # WALL
                    if mgr:
                        surface.blit(mgr.wall_tile, (sx, sy))
                        # shadow strip at bottom of wall for depth illusion
                        shadow = pygame.Surface((t, 8), pygame.SRCALPHA)
                        shadow.fill((0, 0, 0, 90))
                        surface.blit(shadow, (sx, sy + t - 8))
                    else:
                        pygame.draw.rect(surface, (18, 18, 26), (sx, sy, t, t))

        # Entities
        for orb in self.loot:
            orb.draw(surface, cam)
        for p in self.projectiles:
            p.draw(surface, cam)
        for e in self.enemies:
            if e.alive:
                e.draw(surface, cam)
        if self.boss and self.boss.alive:
            self.boss.draw(surface, cam)
