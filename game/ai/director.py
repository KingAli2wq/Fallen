"""
AI Director — all AI-driven game decisions happen here.
Runs heavy calls in daemon threads so the game loop never blocks.
"""
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .client import AIClient

if TYPE_CHECKING:
    from engine.metrics import GameMetrics

logger = logging.getLogger(__name__)

_SYS_DIRECTOR = """You are the AI Game Director for "Fallen", a 2D dark-fantasy ARPG.
Analyse player performance metrics and output enemy difficulty multipliers as JSON.
Be fair but challenging — if the player is dying a lot, ease off; if they're dominating, increase pressure.
Always respond with valid JSON only."""

_SYS_BOSS = """You are a creative game designer for the dark-fantasy ARPG "Fallen".
Design unique, memorable boss encounters. Respond with valid JSON only."""

_SYS_IMPROVE = """You are a senior Pygame / Python game developer.
Review gameplay metrics and game code to suggest concrete balance and code improvements.
Be specific: name functions, values, and files."""


class AIDirector:
    def __init__(self, client: AIClient):
        self.client = client
        self._lock = threading.Lock()
        self._pending: dict = {}        # next diff adjustment to apply
        self._last_update = 0.0
        self._update_interval = 120.0  # seconds between director updates (reasoning model is slow)
        self._busy = False

    # ── public API ────────────────────────────────────────────────────
    def pop_adjustments(self) -> dict:
        with self._lock:
            adj = dict(self._pending)
            self._pending.clear()
        return adj

    def maybe_update_difficulty(self, metrics: "GameMetrics", zone_level: int):
        """Non-blocking — spawns background thread if interval has passed."""
        if not self.client.available:
            return
        if self._busy:
            return
        if time.time() - self._last_update < self._update_interval:
            return
        self._last_update = time.time()
        self._busy = True
        threading.Thread(
            target=self._run_difficulty,
            args=(metrics.to_summary(), zone_level),
            daemon=True,
        ).start()

    def generate_boss_profile(self, zone_level: int) -> dict:
        """Blocking call — do this before the zone loads, not in the game loop."""
        if not self.client.available:
            return self._fallback_boss(zone_level)

        names_by_level = {1: "desolate", 2: "ancient", 3: "corrupted", 4: "abyssal"}
        theme = names_by_level.get(zone_level, "primordial")

        result = self.client.complete_json(
            _SYS_BOSS,
            f"""Design a {theme} boss for zone level {zone_level}.
Return JSON with exactly these keys:
{{
  "name": "Unique boss name (2-3 words, dark theme)",
  "lore": "One atmospheric sentence of lore.",
  "abilities": ["charge", "projectile_burst"],
  "personality": "aggressive"
}}
Available abilities (pick 2-4): charge, projectile_burst, summon, poison_nova
personality options: aggressive, cunning, defensive""",
            max_tokens=900,  # reasoning model needs ~600 tokens to think, then ~100 for JSON
        )
        if result and "name" in result and "abilities" in result:
            return result
        return self._fallback_boss(zone_level)

    def generate_npc_line(self, npc_type: str, player_level: int, context: str) -> str:
        """Short NPC dialogue — called lazily, result may be cached by caller."""
        if not self.client.available:
            return "..."
        raw = self.client.complete(
            "Write 1-2 sentences of dark fantasy NPC dialogue. Be terse and atmospheric.",
            f"NPC: {npc_type}. Player level: {player_level}. Situation: {context}",
            max_tokens=70,
        )
        return (raw or "...").strip().strip('"\'')

    def request_code_improvement(self, metrics: "GameMetrics", code_snippets: dict):
        """Non-blocking — saves suggestions to improvements/ folder."""
        if not self.client.available:
            return
        threading.Thread(
            target=self._run_improvement,
            args=(metrics.to_summary(), code_snippets),
            daemon=True,
        ).start()

    # ── background workers ────────────────────────────────────────────
    def _run_difficulty(self, summary: str, zone_level: int):
        try:
            result = self.client.complete_json(
                _SYS_DIRECTOR,
                f"""Player stats: {summary}
Zone level: {zone_level}

Output multipliers for the NEXT zone's enemies (range 0.6 – 2.0).
JSON format:
{{
  "hp": 1.0,
  "damage": 1.0,
  "speed": 1.0,
  "reason": "short explanation for the player"
}}""",
                max_tokens=800,
            )
            if result and "hp" in result:
                adj = {
                    "hp":     max(0.6, min(2.0, float(result.get("hp",     1.0)))),
                    "damage": max(0.6, min(2.0, float(result.get("damage", 1.0)))),
                    "speed":  max(0.6, min(1.5, float(result.get("speed",  1.0)))),
                    "reason": str(result.get("reason", "")),
                }
                with self._lock:
                    self._pending = adj
                logger.info(f"Director adjustment queued: {adj}")
        except Exception as e:
            logger.error(f"Director update error: {e}")
        finally:
            self._busy = False

    def _run_improvement(self, summary: str, snippets: dict):
        try:
            code_block = "\n\n".join(
                f"# === {name} ===\n{code[:900]}"
                for name, code in list(snippets.items())[:4]
            )
            suggestion = self.client.complete(
                _SYS_IMPROVE,
                f"Metrics: {summary}\n\nCode:\n{code_block}\n\n"
                "List 1-3 specific improvements (balance OR code quality). Number each one.",
                max_tokens=480,
            )
            if suggestion:
                p = Path("improvements")
                p.mkdir(exist_ok=True)
                ts = int(time.time())
                (p / f"suggestion_{ts}.txt").write_text(
                    f"Metrics snapshot:\n{summary}\n\nAI suggestions:\n{suggestion}\n",
                    encoding="utf-8",
                )
                logger.info(f"AI improvement saved → improvements/suggestion_{ts}.txt")
        except Exception as e:
            logger.error(f"Improvement task error: {e}")

    # ── fallback data ─────────────────────────────────────────────────
    _FALLBACK_BOSSES = [
        {"name": "The Ashen Warden",    "lore": "Guardian of the first threshold, dead yet watchful.",
         "abilities": ["charge", "projectile_burst"], "personality": "aggressive"},
        {"name": "Vel'thara the Unbound","lore": "A spirit shattered across a thousand deaths.",
         "abilities": ["summon", "poison_nova"],      "personality": "cunning"},
        {"name": "The Hollow King",     "lore": "He gave his soul to win the final war.",
         "abilities": ["charge", "summon", "projectile_burst"], "personality": "defensive"},
        {"name": "Malachar the Abyssal","lore": "Dragged from the void to serve a forgotten god.",
         "abilities": ["projectile_burst", "poison_nova", "summon"], "personality": "cunning"},
    ]

    def _fallback_boss(self, zone_level: int) -> dict:
        return self._FALLBACK_BOSSES[(zone_level - 1) % len(self._FALLBACK_BOSSES)]
