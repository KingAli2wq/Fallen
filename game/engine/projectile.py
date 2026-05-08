import pygame
from .constants import WHITE


class Projectile:
    def __init__(self, pos: pygame.Vector2, direction: pygame.Vector2,
                 damage: float, speed: float, color: tuple,
                 owner: str, lifetime: float = 5.0):
        self.pos = pygame.Vector2(pos)
        length = direction.length()
        self.vel = direction / length if length > 0 else pygame.Vector2(1, 0)
        self.damage = damage
        self.speed = speed
        self.color = color
        self.owner = owner  # "player" | "enemy" | "boss"
        self.lifetime = lifetime
        self.radius = 5
        self.alive = True

    def update(self, dt: float, world_bounds: pygame.Rect, dungeon=None):
        self.pos += self.vel * self.speed * dt
        self.lifetime -= dt
        if self.lifetime <= 0 or not world_bounds.collidepoint(self.pos.x, self.pos.y):
            self.alive = False
        elif dungeon and not dungeon.is_floor_px(self.pos.x, self.pos.y):
            self.alive = False   # hit a wall

    def draw(self, surface: pygame.Surface, camera_offset: pygame.Vector2):
        sp = self.pos - camera_offset
        pygame.draw.circle(surface, self.color, (int(sp.x), int(sp.y)), self.radius)
        pygame.draw.circle(surface, WHITE, (int(sp.x), int(sp.y)), self.radius, 1)
