import pygame
from .constants import *


class HUD:
    def __init__(self):
        self.f_med  = pygame.font.SysFont("Arial", 18, bold=True)
        self.f_sm   = pygame.font.SysFont("Arial", 14)
        self.f_tiny = pygame.font.SysFont("Arial", 12)
        self._msgs: list[list] = []   # [text, ttl, color]
        self.ai_status = "AI: Offline"
        self.zone_label = ""
        self.show_boss_bar = False

    def msg(self, text: str, color: tuple = WHITE, duration: float = 2.8):
        self._msgs.append([text, duration, color])

    def update(self, dt: float):
        self._msgs = [[t, d - dt, c] for t, d, c in self._msgs if d > dt]

    def draw(self, surface: pygame.Surface, player, zone):
        W, H = surface.get_size()

        # ── HP bar ───────────────────────────────────────────────────────
        self._bar(surface, 10, H - 68, 200, 20,
                  player.hp / player.max_hp, DARK_RED, GREEN,
                  f"HP  {int(player.hp)}/{player.max_hp}")

        # ── Mana bar ──────────────────────────────────────────────────────
        self._bar(surface, 10, H - 44, 200, 18,
                  player.mana / player.max_mana, (15, 15, 70), BLUE,
                  f"MP  {int(player.mana)}/{player.max_mana}")

        # ── XP bar ───────────────────────────────────────────────────────
        xp_ratio = player.xp / player.xp_to_next
        pygame.draw.rect(surface, DARK_GRAY, (10, H - 14, W - 20, 7))
        pygame.draw.rect(surface, YELLOW,    (10, H - 14, int((W - 20) * xp_ratio), 7))

        # ── Level / zone label ───────────────────────────────────────────
        lbl = self.f_sm.render(f"Lv.{player.level}  ·  {self.zone_label}", True, WHITE)
        surface.blit(lbl, (10, H - 88))

        # ── Kill progress ─────────────────────────────────────────────────
        if not zone.boss_spawned:
            kills = zone.kill_count
            need  = zone.kills_for_boss
            kt = self.f_sm.render(f"Kills {kills}/{need}  →  Boss", True, GRAY)
            surface.blit(kt, (W - kt.get_width() - 10, 10))
        else:
            kt = self.f_sm.render("BOSS ACTIVE", True, RED)
            surface.blit(kt, (W - kt.get_width() - 10, 10))

        # ── Boss HP bar (top center) ──────────────────────────────────────
        if self.show_boss_bar and zone.boss and zone.boss.alive:
            bw, bh = 420, 26
            bx = W // 2 - bw // 2
            by = 8
            pygame.draw.rect(surface, DARK_GRAY, (bx - 2, by - 2, bw + 4, bh + 4))
            pygame.draw.rect(surface, DARK_RED,  (bx, by, bw, bh))
            fc = RED if zone.boss.enraged else PURPLE
            ratio = max(0, zone.boss.hp / zone.boss.max_hp)
            pygame.draw.rect(surface, fc, (bx, by, int(bw * ratio), bh))
            name_txt = self.f_med.render(zone.boss.name, True, WHITE)
            surface.blit(name_txt, (W // 2 - name_txt.get_width() // 2, by + 4))

        # ── AI status ─────────────────────────────────────────────────────
        ai_color = CYAN if "Online" in self.ai_status or "Active" in self.ai_status else GRAY
        at = self.f_tiny.render(self.ai_status, True, ai_color)
        surface.blit(at, (W - at.get_width() - 8, H - 20))

        # ── Floating messages (center screen) ─────────────────────────────
        for i, (text, _, color) in enumerate(reversed(self._msgs[-7:])):
            t = self.f_sm.render(text, True, color)
            surface.blit(t, (W // 2 - t.get_width() // 2, H // 2 - 120 - i * 24))

        # ── Controls hint (top-left, subtle) ─────────────────────────────
        hint = self.f_tiny.render("WASD move  |  SPACE attack  |  ESC quit", True, (55, 55, 65))
        surface.blit(hint, (10, 10))

    # ── helpers ──────────────────────────────────────────────────────────
    def _bar(self, surface, x, y, w, h, ratio, bg, fg, label):
        pygame.draw.rect(surface, DARK_GRAY, (x - 1, y - 1, w + 2, h + 2))
        pygame.draw.rect(surface, bg, (x, y, w, h))
        pygame.draw.rect(surface, fg, (x, y, max(0, int(w * ratio)), h))
        t = self.f_tiny.render(label, True, WHITE)
        surface.blit(t, (x + 4, y + (h - t.get_height()) // 2))
