import math
import random
import pygame
from .constants import *


class Boss:
    def __init__(self, x: float, y: float, zone_level: int, profile: dict = None):
        p = profile or {}
        self.pos = pygame.Vector2(x, y)
        self.name = p.get("name", "The Fallen King")
        self.lore = p.get("lore", "A darkness from beyond the veil.")
        self.abilities: list[str] = p.get("abilities", ["charge", "projectile_burst"])[:4]

        scale = 1.0 + (zone_level - 1) * 0.2
        self.max_hp = int(600 * scale)
        self.hp = float(self.max_hp)
        self.damage = 32.0 * scale
        self.speed = 78.0
        self.radius = 34
        self.alive = True
        self.enraged = False

        self._atk_timer = 0.0
        self._ability_timer = 3.0   # first ability after 3s
        self._atk_cd = 1.5
        self._ability_cd = 5.0

        self._charging = False
        self._charge_vel = pygame.Vector2(0, 0)
        self._charge_t = 0.0

        self.announce = ""
        self._announce_t = 0.0

    # ── phases ────────────────────────────────────────────────────────
    def _check_enrage(self):
        if not self.enraged and self.hp <= self.max_hp * 0.3:
            self.enraged = True
            self.speed *= 1.45
            self.damage *= 1.35
            self._ability_cd = 3.0
            self.announce = f"⚡ {self.name} ENRAGES!"
            self._announce_t = 3.5

    # ── public update ──────────────────────────────────────────────────
    def update(self, dt: float, player_pos: pygame.Vector2) -> list:
        if not self.alive:
            return []
        self._check_enrage()

        events = []
        if self._announce_t > 0:
            self._announce_t -= dt
        if self._atk_timer > 0:
            self._atk_timer -= dt
        if self._ability_timer > 0:
            self._ability_timer -= dt

        if self._charging:
            self.pos += self._charge_vel * 340 * dt
            self._charge_t -= dt
            if self._charge_t <= 0:
                self._charging = False
        else:
            dist = self.pos.distance_to(player_pos)
            if dist > self.radius + 30:
                self.pos += (player_pos - self.pos).normalize() * self.speed * dt

            # basic melee
            if dist <= self.radius + 40 and self._atk_timer <= 0:
                self._atk_timer = self._atk_cd
                events.append({"type": "melee", "damage": self.damage, "owner": "boss",
                                "pos": pygame.Vector2(self.pos)})

            # ability
            if self._ability_timer <= 0:
                self._ability_timer = self._ability_cd
                ability = random.choice(self.abilities) if self.abilities else "projectile_burst"
                events += self._use_ability(ability, player_pos)

        return events

    def _use_ability(self, ability: str, player_pos: pygame.Vector2) -> list:
        events = []
        if ability == "charge":
            d = player_pos - self.pos
            if d.length() > 0:
                self._charge_vel = d.normalize()
                self._charging = True
                self._charge_t = 0.22
                self.announce = "CHARGE!"
                self._announce_t = 1.2

        elif ability == "projectile_burst":
            self.announce = "BURST!"
            self._announce_t = 1.0
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                events.append({
                    "type": "projectile",
                    "pos": pygame.Vector2(self.pos),
                    "dir": pygame.Vector2(math.cos(rad), math.sin(rad)),
                    "damage": self.damage * 0.55,
                    "speed": 155, "color": DARK_RED, "owner": "boss", "lifetime": 3.0,
                })

        elif ability == "summon":
            self.announce = "SUMMONING!"
            self._announce_t = 1.8
            for _ in range(3):
                off = pygame.Vector2(random.uniform(-120, 120), random.uniform(-120, 120))
                events.append({"type": "spawn_enemy", "pos": self.pos + off, "owner": "boss"})

        elif ability == "poison_nova":
            self.announce = "POISON NOVA!"
            self._announce_t = 1.6
            for angle in range(0, 360, 30):
                rad = math.radians(angle)
                events.append({
                    "type": "projectile",
                    "pos": pygame.Vector2(self.pos),
                    "dir": pygame.Vector2(math.cos(rad), math.sin(rad)),
                    "damage": self.damage * 0.38,
                    "speed": 110, "color": GREEN, "owner": "boss", "lifetime": 4.0,
                })
        return events

    def take_damage(self, amount: float):
        self.hp -= amount
        if self.hp <= 0:
            self.alive = False

    def draw(self, surface: pygame.Surface, camera_offset: pygame.Vector2):
        sp = self.pos - camera_offset
        sx, sy, r = int(sp.x), int(sp.y), self.radius

        from . import sprites as spr
        mgr = spr.get()

        # glow behind boss
        gc = (220, 30, 30, 60) if self.enraged else (160, 32, 240, 60)
        glow = pygame.Surface((r * 5, r * 5), pygame.SRCALPHA)
        pygame.draw.circle(glow, gc, (r * 5 // 2, r * 5 // 2), r * 5 // 2)
        surface.blit(glow, (sx - r * 5 // 2, sy - r * 5 // 2))

        if mgr:
            img = mgr.boss
            if self.enraged:
                # red tint when enraged
                img = img.copy()
                img.fill((120, 0, 0, 0), special_flags=pygame.BLEND_RGBA_ADD)
            bw_img, bh_img = img.get_size()
            surface.blit(img, (sx - bw_img // 2, sy - bh_img // 2))
            bar_top = sy - bh_img // 2 - 14
        else:
            pts = [(sx + r * math.cos(math.radians(60 * i - 30)),
                    sy + r * math.sin(math.radians(60 * i - 30))) for i in range(6)]
            pygame.draw.polygon(surface, DARK_RED if self.enraged else PURPLE, pts)
            pygame.draw.polygon(surface, WHITE, pts, 3)
            bar_top = sy - r - 16

        # boss HP bar
        bw, bh = 80, 9
        bx = sx - bw // 2
        pygame.draw.rect(surface, DARK_GRAY, (bx - 1, bar_top - 1, bw + 2, bh + 2))
        pygame.draw.rect(surface, DARK_RED, (bx, bar_top, bw, bh))
        fc = RED if self.enraged else PURPLE
        pygame.draw.rect(surface, fc, (bx, bar_top, max(0, int(bw * self.hp / self.max_hp)), bh))

        # announce
        if self._announce_t > 0:
            font = pygame.font.SysFont("Arial", 17, bold=True)
            txt = font.render(self.announce, True, YELLOW)
            surface.blit(txt, (sx - txt.get_width() // 2, bar_top - 22))
