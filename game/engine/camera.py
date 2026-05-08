import pygame
from .constants import SCREEN_W, SCREEN_H


class Camera:
    def __init__(self, world_w: int, world_h: int):
        self.world_w = world_w
        self.world_h = world_h
        self.offset = pygame.Vector2(0, 0)

    def follow(self, target: pygame.Vector2):
        self.offset.x = max(0, min(self.world_w - SCREEN_W, target.x - SCREEN_W // 2))
        self.offset.y = max(0, min(self.world_h - SCREEN_H, target.y - SCREEN_H // 2))
