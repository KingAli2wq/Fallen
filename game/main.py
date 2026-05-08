"""
Fallen — AI-Driven 2D ARPG
Run:  python main.py
Requires: pygame  (pip install pygame)
AI:       start model server first — see HOW_TO_START_AI.txt
"""
import logging
import sys
import time
from pathlib import Path

import pygame

from engine.constants import *
from engine.camera  import Camera
from engine.player  import Player
from engine.world   import Zone, WORLD_W, WORLD_H
from engine.hud     import HUD
from engine.metrics import GameMetrics
from engine        import sprites
from ai.client      import AIClient
from ai.director    import AIDirector

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("main")


class FallenGame:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Fallen  ·  AI-Driven ARPG")
        sprites.init()   # must come after set_mode so convert_alpha() works
        self.clock  = pygame.time.Clock()

        self.ai      = AIClient()
        self.director = AIDirector(self.ai)
        self.metrics  = GameMetrics()
        self.hud      = HUD()

        self.zone_level = 1
        self.mults      = {}      # AI difficulty multipliers for next zone
        self.zone: Zone | None = None
        self.player: Player | None = None
        self.camera = Camera(WORLD_W, WORLD_H)

        self.state = "playing"    # playing | dead | zone_clear
        self._clear_timer = 0.0
        self._next_improve = time.time() + 300   # 5-min improvement cycle

        self._load_zone(first=True)

        status = "AI: Online" if self.ai.available else "AI: Offline (see HOW_TO_START_AI.txt)"
        self.hud.ai_status = status
        if self.ai.available:
            self.hud.msg("AI Director connected!", CYAN, 4.0)
        else:
            self.hud.msg("AI offline — running with fallback data", GRAY, 5.0)

    # ── zone management ──────────────────────────────────────────────
    def _load_zone(self, first: bool = False):
        log.info(f"Loading zone {self.zone_level} …")
        boss_profile = self.director.generate_boss_profile(self.zone_level)
        log.info(f"  Boss: {boss_profile['name']}")

        self.zone = Zone(self.zone_level, self.mults, boss_profile)
        sx, sy = self.zone.player_start
        if first or self.player is None:
            self.player = Player(sx, sy)
        else:
            self.player.pos = pygame.Vector2(sx, sy)
            self.player.heal(self.player.max_hp * 0.25)
        self.camera = Camera(WORLD_W, WORLD_H)
        self.camera.follow(self.player.pos)

        self.hud.zone_label   = f"Zone {self.zone_level}"
        self.hud.show_boss_bar = False
        self.metrics.current_zone_level = self.zone_level

        self.hud.msg(f"Entering Zone {self.zone_level}", YELLOW, 3.0)
        if self.mults:
            reason = self.mults.get("reason", "")
            if reason:
                self.hud.msg(f"AI: {reason}", CYAN, 5.0)

    # ── event handling ───────────────────────────────────────────────
    def _handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                if event.key == pygame.K_SPACE and self.state == "playing":
                    self.zone.player_attack(self.player, self.metrics)
                if event.key == pygame.K_r and self.state == "dead":
                    self._respawn()
        return True

    def _respawn(self):
        self.metrics.player_deaths += 1
        self.player = Player(WORLD_W // 2, WORLD_H // 2)
        self.state  = "playing"
        self._load_zone()

    # ── zone event dispatch ──────────────────────────────────────────
    def _on_zone_events(self, events: list):
        for kind, data in events:
            if kind == "boss_spawn":
                self.hud.show_boss_bar = True
                self.hud.msg(f"BOSS: {data.name}", RED, 6.0)
                self.hud.msg(f'"{data.lore}"', GRAY, 7.0)
            elif kind == "boss_kill":
                self.hud.show_boss_bar = False
                self.hud.msg(f"{data.name} has fallen!", YELLOW, 4.0)
            elif kind == "zone_cleared":
                self.state = "zone_clear"
                self._clear_timer = 3.5
                self.hud.msg("ZONE CLEARED!", YELLOW, 3.0)
            elif kind == "xp":
                pass   # could show floating +XP text here

    # ── AI tick ──────────────────────────────────────────────────────
    def _ai_tick(self):
        self.metrics.player_level = self.player.level
        self.director.maybe_update_difficulty(self.metrics, self.zone_level)

        # Apply queued director adjustments
        adj = self.director.pop_adjustments()
        if adj:
            reason = adj.pop("reason", "")
            self.mults = adj
            self.hud.ai_status = "AI: Active"
            if reason:
                self.hud.msg(f"AI Director: {reason}", CYAN, 5.0)

        # Periodic code-improvement request
        if time.time() > self._next_improve:
            self._next_improve = time.time() + 300
            snippets = {
                p.name: p.read_text(encoding="utf-8")
                for p in Path(".").glob("**/*.py")
                if ".venv" not in str(p) and p.stat().st_size < 30_000
            }
            self.director.request_code_improvement(self.metrics, snippets)

    # ── main loop ────────────────────────────────────────────────────
    def run(self):
        running = True
        while running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)

            if not self._handle_events():
                break

            keys = pygame.key.get_pressed()

            if self.state == "playing":
                self.player.update(dt, keys, self.zone.bounds, self.zone.dungeon)
                self.camera.follow(self.player.pos)
                events = self.zone.update(dt, self.player, self.metrics)
                self._on_zone_events(events)
                self.hud.update(dt)
                self._ai_tick()

                if not self.player.alive:
                    self.state = "dead"
                    self.hud.msg("YOU DIED — press R to respawn", RED, 9999)

            elif self.state == "zone_clear":
                self._clear_timer -= dt
                self.hud.update(dt)
                if self._clear_timer <= 0:
                    self.zone_level += 1
                    self._load_zone()
                    self.state = "playing"

            elif self.state == "dead":
                self.hud.update(dt)

            # ── draw ─────────────────────────────────────────────────
            self.screen.fill(BLACK)
            self.zone.draw(self.screen, self.camera.offset)
            self.player.draw(self.screen, self.camera.offset)
            self.hud.draw(self.screen, self.player, self.zone)
            pygame.display.flip()

        self.metrics.save()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    game = FallenGame()
    game.run()
