"""
Per-Project Compression Profiles

Remembers optimal compression mode for each codebase.
Tracks effectiveness and auto-suggests best mode.
"""

import json
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime
import logging

try:
    from .compression import EfficientMode
except ImportError:
    from compression import EfficientMode

logger = logging.getLogger(__name__)


@dataclass
class CompressionStats:
    """Compression statistics for a project"""
    mode: EfficientMode
    usage_count: int
    total_original_tokens: int
    total_compressed_tokens: int
    total_tokens_saved: int
    avg_savings_ratio: float
    avg_quality_score: float
    last_used: float  # timestamp


@dataclass
class ProjectProfile:
    """Compression profile for a project"""
    project_id: str
    preferred_mode: Optional[EfficientMode]
    auto_detected: bool
    stats_by_mode: Dict[str, CompressionStats]
    created_at: float
    updated_at: float


class ProjectProfileManager:
    """Manages per-project compression profiles"""

    def __init__(self, profiles_dir: Optional[Path] = None):
        """
        Args:
            profiles_dir: Directory to store profile files
                         Defaults to ~/.claude/plugins/ainl-graph-memory/profiles/
        """
        if profiles_dir is None:
            profiles_dir = (
                Path.home() / ".claude" / "plugins" / "ainl-graph-memory" / "profiles"
            )

        self.profiles_dir = profiles_dir
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache
        self.profiles: Dict[str, ProjectProfile] = {}

    def _profile_path(self, project_id: str) -> Path:
        """Get path to profile file for project"""
        return self.profiles_dir / f"{project_id}.json"

    def _load_profile(self, project_id: str) -> Optional[ProjectProfile]:
        """Load profile from disk"""
        path = self._profile_path(project_id)

        if not path.exists():
            return None

        try:
            with open(path, 'r') as f:
                data = json.load(f)

            # Parse stats by mode
            stats_by_mode = {}
            for mode_str, stats_data in data.get('stats_by_mode', {}).items():
                stats_by_mode[mode_str] = CompressionStats(
                    mode=EfficientMode.parse_config(mode_str),
                    usage_count=stats_data['usage_count'],
                    total_original_tokens=stats_data['total_original_tokens'],
                    total_compressed_tokens=stats_data['total_compressed_tokens'],
                    total_tokens_saved=stats_data['total_tokens_saved'],
                    avg_savings_ratio=stats_data['avg_savings_ratio'],
                    avg_quality_score=stats_data.get('avg_quality_score', 0.0),
                    last_used=stats_data['last_used']
                )

            preferred_mode = None
            if data.get('preferred_mode'):
                preferred_mode = EfficientMode.parse_config(data['preferred_mode'])

            return ProjectProfile(
                project_id=project_id,
                preferred_mode=preferred_mode,
                auto_detected=data.get('auto_detected', False),
                stats_by_mode=stats_by_mode,
                created_at=data['created_at'],
                updated_at=data['updated_at']
            )

        except Exception as e:
            logger.error(f"Failed to load profile for {project_id}: {e}")
            return None

    def _save_profile(self, profile: ProjectProfile):
        """Save profile to disk"""
        path = self._profile_path(profile.project_id)

        try:
            # Convert stats to dict
            stats_by_mode = {}
            for mode_str, stats in profile.stats_by_mode.items():
                stats_by_mode[mode_str] = {
                    'usage_count': stats.usage_count,
                    'total_original_tokens': stats.total_original_tokens,
                    'total_compressed_tokens': stats.total_compressed_tokens,
                    'total_tokens_saved': stats.total_tokens_saved,
                    'avg_savings_ratio': stats.avg_savings_ratio,
                    'avg_quality_score': stats.avg_quality_score,
                    'last_used': stats.last_used
                }

            data = {
                'project_id': profile.project_id,
                'preferred_mode': profile.preferred_mode.value if profile.preferred_mode else None,
                'auto_detected': profile.auto_detected,
                'stats_by_mode': stats_by_mode,
                'created_at': profile.created_at,
                'updated_at': profile.updated_at
            }

            with open(path, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved profile for {profile.project_id}")

        except Exception as e:
            logger.error(f"Failed to save profile for {profile.project_id}: {e}")

    def get_profile(self, project_id: str) -> ProjectProfile:
        """Get or create profile for project"""
        # Check cache
        if project_id in self.profiles:
            return self.profiles[project_id]

        # Try to load from disk
        profile = self._load_profile(project_id)

        if profile is None:
            # Create new profile
            profile = ProjectProfile(
                project_id=project_id,
                preferred_mode=None,
                auto_detected=False,
                stats_by_mode={},
                created_at=datetime.now().timestamp(),
                updated_at=datetime.now().timestamp()
            )

        # Cache
        self.profiles[project_id] = profile
        return profile

    def get_preferred_mode(self, project_id: str) -> Optional[EfficientMode]:
        """Get preferred compression mode for project"""
        profile = self.get_profile(project_id)
        return profile.preferred_mode

    def set_preferred_mode(self,
                          project_id: str,
                          mode: EfficientMode,
                          auto_detected: bool = False):
        """Set preferred compression mode for project"""
        profile = self.get_profile(project_id)
        profile.preferred_mode = mode
        profile.auto_detected = auto_detected
        profile.updated_at = datetime.now().timestamp()

        self._save_profile(profile)

        logger.info(
            f"Set preferred mode for {project_id}: {mode.value} "
            f"({'auto-detected' if auto_detected else 'manual'})"
        )

    def record_compression(self,
                          project_id: str,
                          mode: EfficientMode,
                          original_tokens: int,
                          compressed_tokens: int,
                          quality_score: float = 0.0):
        """Record compression usage for project"""
        profile = self.get_profile(project_id)

        mode_str = mode.value
        now = datetime.now().timestamp()

        # Get or create stats for mode
        if mode_str not in profile.stats_by_mode:
            profile.stats_by_mode[mode_str] = CompressionStats(
                mode=mode,
                usage_count=0,
                total_original_tokens=0,
                total_compressed_tokens=0,
                total_tokens_saved=0,
                avg_savings_ratio=0.0,
                avg_quality_score=0.0,
                last_used=now
            )

        stats = profile.stats_by_mode[mode_str]

        # Update stats
        tokens_saved = original_tokens - compressed_tokens
        savings_ratio = tokens_saved / max(original_tokens, 1)

        # Running averages
        n = stats.usage_count
        stats.avg_savings_ratio = (stats.avg_savings_ratio * n + savings_ratio) / (n + 1)
        stats.avg_quality_score = (stats.avg_quality_score * n + quality_score) / (n + 1)

        # Totals
        stats.usage_count += 1
        stats.total_original_tokens += original_tokens
        stats.total_compressed_tokens += compressed_tokens
        stats.total_tokens_saved += tokens_saved
        stats.last_used = now

        profile.updated_at = now

        # Save
        self._save_profile(profile)

    def auto_detect_mode(self, project_id: str) -> Optional[EfficientMode]:
        """
        Auto-detect best mode based on historical usage.

        Returns suggested mode or None if insufficient data.
        """
        profile = self.get_profile(project_id)

        if not profile.stats_by_mode:
            return None

        # Need at least 5 compressions per mode to make a recommendation
        eligible_modes = [
            (mode_str, stats) for mode_str, stats in profile.stats_by_mode.items()
            if stats.usage_count >= 5
        ]

        if not eligible_modes:
            return None

        # Score each mode: balance savings and quality
        best_mode = None
        best_score = 0.0

        for mode_str, stats in eligible_modes:
            # Score = 0.6 * savings + 0.4 * quality
            score = 0.6 * stats.avg_savings_ratio + 0.4 * stats.avg_quality_score

            if score > best_score:
                best_score = score
                best_mode = stats.mode

        if best_mode:
            logger.info(
                f"Auto-detected best mode for {project_id}: {best_mode.value} "
                f"(score: {best_score:.2f})"
            )

        return best_mode

    def suggest_mode(self, project_id: str, fallback_mode: EfficientMode) -> EfficientMode:
        """
        Suggest compression mode for project.

        Priority:
        1. Manual preferred mode
        2. Auto-detected mode (if enough data)
        3. Fallback mode
        """
        profile = self.get_profile(project_id)

        # 1. Manual preference
        if profile.preferred_mode and not profile.auto_detected:
            return profile.preferred_mode

        # 2. Auto-detect
        auto_mode = self.auto_detect_mode(project_id)
        if auto_mode:
            # Update profile if changed
            if profile.preferred_mode != auto_mode:
                self.set_preferred_mode(project_id, auto_mode, auto_detected=True)
            return auto_mode

        # 3. Fallback
        return fallback_mode

    def get_project_stats(self, project_id: str) -> Dict:
        """Get comprehensive stats for project"""
        profile = self.get_profile(project_id)

        stats = {
            'project_id': project_id,
            'preferred_mode': profile.preferred_mode.value if profile.preferred_mode else None,
            'auto_detected': profile.auto_detected,
            'modes': {}
        }

        for mode_str, mode_stats in profile.stats_by_mode.items():
            stats['modes'][mode_str] = {
                'usage_count': mode_stats.usage_count,
                'avg_savings_ratio': f"{mode_stats.avg_savings_ratio:.1%}",
                'avg_quality_score': f"{mode_stats.avg_quality_score:.2f}",
                'total_tokens_saved': mode_stats.total_tokens_saved,
                'last_used': datetime.fromtimestamp(mode_stats.last_used).isoformat()
            }

        return stats

    def get_all_projects(self) -> List[str]:
        """Get list of all projects with profiles"""
        return [
            path.stem for path in self.profiles_dir.glob("*.json")
        ]


# Global singleton
_profile_manager: Optional[ProjectProfileManager] = None


def get_profile_manager() -> ProjectProfileManager:
    """Get global profile manager instance"""
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ProjectProfileManager()
    return _profile_manager
