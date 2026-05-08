import math
import random
import pygame
from .constants import YELLOW, WHITE, ORANGE


class LootOrb:
    def __init__(self, x: float, y: float, xp: int, boss_drop: bool = False):
        self.pos = pygame.Vector2(x + random.uniform(-20, 20),
                                  y + random.uniform(-20, 20))
        self.xp = xp
        self.boss_drop = boss_drop
        self.radius = 9 if boss_drop else 5
        self.color = ORANGE if boss_drop else YELLOW
        self.alive = True
        self._bob = random.uniform(0, math.pi * 2)

    def update(self, dt: float):
        self._bob += dt * 3

    def draw(self, surface: pygame.Surface, camera_offset: pygame.Vector2):
        sp = self.pos - camera_offset
        bob_y = int(sp.y + math.sin(self._bob) * 2)
        pygame.draw.circle(surface, self.color, (int(sp.x), bob_y), self.radius)
        pygame.draw.circle(surface, WHITE, (int(sp.x), bob_y), self.radius, 1)
