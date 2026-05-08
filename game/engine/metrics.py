import time
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class GameMetrics:
    session_start: float = field(default_factory=time.time)
    player_deaths: int = 0
    total_kills: int = 0
    boss_kills: int = 0
    boss_attempts: int = 0
    total_damage_dealt: float = 0.0
    total_damage_taken: float = 0.0
    zones_cleared: int = 0
    current_zone_level: int = 1
    player_level: int = 1
    session_time: float = 0.0

    def elapsed(self) -> float:
        return time.time() - self.session_start

    def avg_dps(self) -> float:
        t = self.elapsed()
        return self.total_damage_dealt / t if t > 0 else 0.0

    def boss_success_rate(self) -> float:
        return self.boss_kills / self.boss_attempts if self.boss_attempts > 0 else 0.0

    def to_summary(self) -> str:
        return (
            f"time={self.elapsed():.0f}s deaths={self.player_deaths} "
            f"kills={self.total_kills} boss={self.boss_kills}/{self.boss_attempts} "
            f"avg_dps={self.avg_dps():.1f} dmg_taken={self.total_damage_taken:.0f} "
            f"zones_cleared={self.zones_cleared} zone_lvl={self.current_zone_level} "
            f"player_lvl={self.player_level}"
        )

    def save(self, path: str = "improvements/metrics.json"):
        self.session_time = self.elapsed()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
