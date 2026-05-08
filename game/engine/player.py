import math
import random
import pygame
from .constants import *


class Player:
    def __init__(self, x: float, y: float):
        self.pos = pygame.Vector2(x, y)
        self.level = 1
        self.xp = 0
        self.xp_to_next = 100

        self.max_hp = 120
        self.hp = float(self.max_hp)
        self.max_mana = 60
        self.mana = float(self.max_mana)

        self.base_damage = 18.0
        self.speed = 210.0
        self.defense = 4
        self.crit_chance = 0.07
        self.crit_mult = 1.6

        self.attack_range = 85
        self.attack_cd = 0.45
        self._attack_timer = 0.0
        self.radius = 15
        self.alive = True
        self._invuln = 0.0  # invulnerability frames after hit

    @property
    def damage(self) -> float:
        d = self.base_damage
        if random.random() < self.crit_chance:
            d *= self.crit_mult
        return d

    def take_damage(self, amount: float) -> float:
        if self._invuln > 0 or not self.alive:
            return 0.0
        actual = max(1.0, amount - self.defense)
        self.hp -= actual
        self._invuln = 0.5
        if self.hp <= 0:
            self.alive = False
        return actual

    def heal(self, amount: float):
        self.hp = min(self.max_hp, self.hp + amount)

    def gain_xp(self, amount: int):
        self.xp += amount
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self._level_up()

    def _level_up(self):
        self.level += 1
        self.xp_to_next = int(self.xp_to_next * 1.28)
        self.max_hp = int(self.max_hp * 1.1 + 12)
        self.hp = float(self.max_hp)
        self.base_damage = self.base_damage * 1.08 + 2
        self.max_mana = int(self.max_mana + 6)
        self.mana = float(self.max_mana)
        self.defense += 1

    def can_attack(self) -> bool:
        return self._attack_timer <= 0

    def do_attack(self):
        self._attack_timer = self.attack_cd

    def update(self, dt: float, keys, world_bounds: pygame.Rect, dungeon=None):
        dx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        dy = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
        if dx or dy:
            length = math.hypot(dx, dy)
            move_x = (dx / length) * self.speed * dt
            move_y = (dy / length) * self.speed * dt

            if dungeon:
                # try full move, fall back to axis-only moves to slide along walls
                nx, ny = self.pos.x + move_x, self.pos.y + move_y
                if dungeon.is_floor_rect_px(nx, ny, self.radius):
                    self.pos.x, self.pos.y = nx, ny
                elif dungeon.is_floor_rect_px(nx, self.pos.y, self.radius):
                    self.pos.x = nx
                elif dungeon.is_floor_rect_px(self.pos.x, ny, self.radius):
                    self.pos.y = ny
            else:
                self.pos.x += move_x
                self.pos.y += move_y

        self.pos.x = max(world_bounds.left + self.radius,
                         min(world_bounds.right - self.radius, self.pos.x))
        self.pos.y = max(world_bounds.top + self.radius,
                         min(world_bounds.bottom - self.radius, self.pos.y))

        if self._attack_timer > 0:
            self._attack_timer -= dt
        if self._invuln > 0:
            self._invuln -= dt
        self.mana = min(self.max_mana, self.mana + 2.5 * dt)

    def draw(self, surface: pygame.Surface, camera_offset: pygame.Vector2):
        if self._invuln > 0 and int(self._invuln * 12) % 2:
            return
        sp = self.pos - camera_offset
        sx, sy = int(sp.x), int(sp.y)

        from . import sprites as spr
        mgr = spr.get()
        if mgr:
            img = mgr.player
            w, h = img.get_size()
            # subtle blue glow behind sprite
            glow = pygame.Surface((w + 16, h + 16), pygame.SRCALPHA)
            pygame.draw.ellipse(glow, (60, 120, 255, 40), glow.get_rect())
            surface.blit(glow, (sx - w // 2 - 8, sy - h // 2 - 8))
            surface.blit(img, (sx - w // 2, sy - h // 2))
        else:
            glow = pygame.Surface((self.radius * 4, self.radius * 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (80, 140, 255, 45), (self.radius * 2, self.radius * 2), self.radius * 2)
            surface.blit(glow, (sx - self.radius * 2, sy - self.radius * 2))
            pygame.draw.circle(surface, BLUE, (sx, sy), self.radius)
            pygame.draw.circle(surface, WHITE, (sx, sy), self.radius, 2)

        # HP bar
        bw, bh = 40, 5
        bx, by = sx - bw // 2, sy - self.radius - 10
        pygame.draw.rect(surface, DARK_RED, (bx, by, bw, bh))
        pygame.draw.rect(surface, GREEN, (bx, by, max(0, int(bw * self.hp / self.max_hp)), bh))
