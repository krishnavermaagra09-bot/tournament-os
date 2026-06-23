"""
Tournament Rule Engine — centralized validation layer.

Checks rules BEFORE state changes are applied:
  - Transition pre-conditions (min teams, check-in complete, etc.)
  - Registration constraints (team size, region/platform, capacity)
  - Score validation (format, range)
  - Custom rules parsed from tournament.rules text (YAML/JSON or keyword-based)

Usage:
    engine = RuleEngine(tournament)
    violations = engine.validate_transition(TournamentStatus.LIVE)
    if violations:
        raise RuleViolationError(violations)
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.tournament import Tournament, TournamentStatus

logger = logging.getLogger(__name__)


class RuleViolationError(Exception):
    """Raised when one or more rule violations are found."""
    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("\n".join(f"• {v}" for v in violations))


class RuleEngine:
    """Stateless rule validator — instantiate with the tournament object."""

    def __init__(self, tournament: "Tournament"):
        self.t = tournament
        self._custom_rules: list[dict] = self._parse_custom_rules()

    # ── Transition pre-conditions ─────────────────────────────────────────────

    def validate_transition(
        self,
        new_status: "TournamentStatus",
        checked_in_count: int = 0,
        approved_count: int = 0,
    ) -> list[str]:
        """
        Return a list of violation messages (empty = no violations).
        Enforces pre-conditions before allowing a status change.
        """
        from app.database.models.tournament import TournamentStatus

        violations: list[str] = []
        t = self.t

        # REGISTRATION_OPEN requires min fields
        if new_status == TournamentStatus.REGISTRATION_OPEN:
            if not t.game:
                violations.append("Tournament must have a game set before opening registration.")
            if not t.format:
                violations.append("Tournament must have a format set before opening registration.")

        # CHECKIN_OPEN requires teams
        if new_status == TournamentStatus.CHECKIN_OPEN:
            min_teams = 2
            if approved_count < min_teams:
                violations.append(
                    f"At least {min_teams} teams must be approved before check-in can open. "
                    f"Currently: {approved_count}."
                )

        # LIVE requires checked-in teams
        if new_status == TournamentStatus.LIVE:
            min_checkin = self._custom_int("min_checkin_teams", default=2)
            if checked_in_count < min_checkin:
                violations.append(
                    f"At least {min_checkin} teams must be checked in before going live. "
                    f"Currently checked in: {checked_in_count}."
                )

        return violations

    # ── Registration constraints ──────────────────────────────────────────────

    def validate_registration(
        self,
        form_data: dict,
        current_team_count: int = 0,
    ) -> list[str]:
        """Validate a registration submission against tournament constraints."""
        violations: list[str] = []
        t = self.t

        # Capacity check
        if t.max_teams and current_team_count >= t.max_teams:
            violations.append(
                f"Tournament is full ({current_team_count}/{t.max_teams} teams). "
                "Check if a waitlist is available."
            )

        # Team size
        if t.min_team_size and t.team_size_type and t.team_size_type.value == "fixed":
            member_count = len(form_data.get("members", []))
            if member_count and member_count < t.min_team_size:
                violations.append(
                    f"Team must have at least {t.min_team_size} player(s). "
                    f"Submitted with {member_count}."
                )
            if t.max_team_size and member_count > t.max_team_size:
                violations.append(
                    f"Team exceeds max size of {t.max_team_size} players."
                )

        # Region check
        allowed_region = self._custom_str("region")
        if allowed_region and form_data.get("region") and form_data["region"].lower() != allowed_region.lower():
            violations.append(
                f"Tournament is restricted to region **{allowed_region}**. "
                f"Your region: {form_data['region']}."
            )

        # Platform check
        if t.platform and form_data.get("platform") and form_data["platform"].lower() != t.platform.lower():
            violations.append(
                f"Tournament is for **{t.platform}** players only."
            )

        return violations

    # ── Score validation ──────────────────────────────────────────────────────

    def validate_score(self, score_team1: dict, score_team2: dict) -> list[str]:
        """Validate submitted match scores."""
        violations: list[str] = []

        s1 = score_team1.get("score")
        s2 = score_team2.get("score")

        if s1 is None or s2 is None:
            violations.append("Both team scores must be provided.")
            return violations

        try:
            s1, s2 = int(s1), int(s2)
        except (TypeError, ValueError):
            violations.append("Scores must be integers.")
            return violations

        if s1 < 0 or s2 < 0:
            violations.append("Scores cannot be negative.")

        max_score = self._custom_int("max_score_value", default=99)
        if s1 > max_score or s2 > max_score:
            violations.append(f"Score values cannot exceed {max_score}.")

        if s1 == s2:
            # Check if ties are allowed
            if not self._custom_bool("allow_ties", default=False):
                violations.append("Ties are not allowed in this tournament. One team must win.")

        return violations

    # ── Feature flag shortcuts ────────────────────────────────────────────────

    def flag(self, key: str, default: bool = True) -> bool:
        """Read a feature flag from the tournament (returns default if not set)."""
        flags: dict = self.t.feature_flags or {}
        val = flags.get(key)
        return default if val is None else bool(val)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _parse_custom_rules(self) -> list[dict]:
        """
        Parse custom rules from tournament.rules text.
        Supports simple key=value lines, e.g.:
            min_checkin_teams=4
            max_score_value=3
            allow_ties=false
        """
        rules = []
        text: str = self.t.rules or ""
        for line in text.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                rules.append({"key": key.strip(), "value": value.strip()})
        return rules

    def _custom_str(self, key: str, default: str = "") -> str:
        for rule in self._custom_rules:
            if rule["key"] == key:
                return rule["value"]
        return default

    def _custom_int(self, key: str, default: int = 0) -> int:
        val = self._custom_str(key)
        try:
            return int(val) if val else default
        except ValueError:
            return default

    def _custom_bool(self, key: str, default: bool = False) -> bool:
        val = self._custom_str(key).lower()
        if val in ("true", "yes", "1"):
            return True
        if val in ("false", "no", "0"):
            return False
        return default
