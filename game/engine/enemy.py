import pygame
from .constants import *

_TYPES = {
    "melee": {
        "name": "Wraith",         "hp": 60,  "damage": 12, "speed": 115,
        "xp": 20,  "radius": 14, "color": RED,    "shape": "circle",
        "atk_range": 30,  "atk_cd": 1.2, "detect": 300,
    },
    "ranged": {
        "name": "Shade Archer",   "hp": 40,  "damage": 18, "speed": 75,
        "xp": 25,  "radius": 12, "color": ORANGE, "shape": "triangle",
        "atk_range": 240, "atk_cd": 2.0, "detect": 360,
    },
    "elite": {
        "name": "Elite Revenant", "hp": 160, "damage": 26, "speed": 95,
        "xp": 65,  "radius": 18, "color": PURPLE, "shape": "diamond",
        "atk_range": 40,  "atk_cd": 1.4, "detect": 340,
    },
}


class Enemy:
    def __init__(self, x: float, y: float, etype: str = "melee",
                 zone_level: int = 1, mults: dict = None):
        s = dict(_TYPES.get(etype, _TYPES["melee"]))
        mults = mults or {}
        scale = 1.0 + (zone_level - 1) * 0.15

        self.type = etype
        self.name = s["name"]
        self.pos = pygame.Vector2(x, y)
        self.max_hp = int(s["hp"] * scale * mults.get("hp", 1.0))
        self.hp = float(self.max_hp)
        self.damage = s["damage"] * scale * mults.get("damage", 1.0)
        self.speed = s["speed"] * mults.get("speed", 1.0)
        self.xp = int(s["xp"] * scale)
        self.radius = s["radius"]
        self.color = s["color"]
        self.shape = s["shape"]
        self.atk_range = s["atk_range"]
        self.atk_cd = s["atk_cd"]
        self.detect = s["detect"]
        self._atk_timer = 0.0
        self.alive = True
        self._anim_timer = 0.0
        self._anim_tick = 0

    def take_damage(self, amount: float):
        self.hp -= amount
        if self.hp <= 0:
            self.alive = False

    def update(self, dt: float, player_pos: pygame.Vector2, dungeon=None) -> list:
        """Returns list of attack event dicts."""
        if not self.alive:
            return []
        events = []
        if self._atk_timer > 0:
            self._atk_timer -= dt
        # walk animation at ~6 fps
        self._anim_timer += dt
        if self._anim_timer >= 1 / 6:
            self._anim_timer = 0.0
            self._anim_tick += 1

        dist = self.pos.distance_to(player_pos)
        if dist <= self.detect:
            if dist > self.atk_range:
                d = (player_pos - self.pos).normalize()
                nx = self.pos.x + d.x * self.speed * dt
                ny = self.pos.y + d.y * self.speed * dt
                if dungeon:
                    if dungeon.is_floor_rect_px(nx, ny, self.radius):
                        self.pos.x, self.pos.y = nx, ny
                    elif dungeon.is_floor_rect_px(nx, self.pos.y, self.radius):
                        self.pos.x = nx
                    elif dungeon.is_floor_rect_px(self.pos.x, ny, self.radius):
                        self.pos.y = ny
                else:
                    self.pos.x, self.pos.y = nx, ny
            elif self._atk_timer <= 0:
                self._atk_timer = self.atk_cd
                if self.type == "ranged":
                    events.append({
                        "type": "projectile",
                        "pos": pygame.Vector2(self.pos),
                        "dir": player_pos - self.pos,
                        "damage": self.damage,
                        "speed": 195,
                        "color": ORANGE,
                        "owner": "enemy",
                    })
                else:
                    events.append({"type": "melee", "damage": self.damage,
                                   "pos": pygame.Vector2(self.pos), "owner": "enemy"})
        return events

    def draw(self, surface: pygame.Surface, camera_offset: pygame.Vector2):
        sp = self.pos - camera_offset
        sx, sy = int(sp.x), int(sp.y)

        from . import sprites as spr
        mgr = spr.get()
        if mgr:
            frame = mgr.enemy_frame(self.type, self._anim_tick)
            fw, fh = frame.get_size()
            # colour tint for elites — create a tinted copy
            if self.type == "elite":
                tinted = frame.copy()
                tinted.fill((80, 0, 120, 0), special_flags=pygame.BLEND_RGBA_ADD)
                surface.blit(tinted, (sx - fw // 2, sy - fh // 2))
            else:
                surface.blit(frame, (sx - fw // 2, sy - fh // 2))
            bar_ref_y = sy - fh // 2 - 6
        else:
            r = self.radius
            pygame.draw.circle(surface, self.color, (sx, sy), r)
            pygame.draw.circle(surface, WHITE, (sx, sy), r, 2)
            bar_ref_y = sy - r - 8

        # HP bar
        bw, bh = 34, 4
        bx = sx - bw // 2
        pygame.draw.rect(surface, DARK_RED, (bx, bar_ref_y, bw, bh))
        pygame.draw.rect(surface, RED, (bx, bar_ref_y, max(0, int(bw * self.hp / self.max_hp)), bh))
