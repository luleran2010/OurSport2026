"""Accounts API schemas (docs/05-api.md, Sign-up, auth and session)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Language = Literal["fi", "en", "bn"]


def _valid_time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone '{value}'") from exc
    return value


class FollowTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["team", "tournament", "organisation"]
    target_id: UUID


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=80)
    language: Language
    time_zone: str
    age_13_plus: Literal[True]  # accounts are for people aged 13+
    privacy_accepted: Literal[True]
    follow: FollowTarget | None = None

    _time_zone = field_validator("time_zone")(_valid_time_zone)


class MagicLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=200)


class Accepted(BaseModel):
    status: Literal["accepted"] = "accepted"


class SessionInfo(BaseModel):
    user_id: UUID
    csrf_token: str  # send back as X-CSRF-Token on unsafe requests
    account_created: bool = False


class PlanInfo(BaseModel):
    tier: str
    granted_by_organisation_id: UUID | None = None
    valid_until: str | None = None


class Membership(BaseModel):
    organisation_id: UUID
    organisation_name: str = ""
    role: str


class StaffTournament(BaseModel):
    tournament_id: UUID
    tournament_name: str = ""
    organisation_id: UUID | None = None
    role: str


class FollowRef(BaseModel):
    """One thing the user follows (the full list with names: `listFollows`)."""

    id: UUID  # the follow id, for `unfollow`
    target_type: str
    target_id: UUID
    is_primary: bool = False


class Preferences(BaseModel):
    """Consent choices (docs/13 §6): only essential cookies without consent; marketing
    emails only after opt-in. Login and match notifications are not marketing."""

    model_config = ConfigDict(extra="forbid")

    analytics_cookies: bool = False
    marketing_emails: bool = False
    updated_at: datetime | None = None


class PreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analytics_cookies: bool | None = None
    marketing_emails: bool | None = None


class Me(BaseModel):
    """The signed-in user. Plan, memberships, staff roles, follows, family links and
    notifications are filled in by the modules that own them as they arrive."""

    id: UUID
    display_name: str
    email: str
    language: Language
    time_zone: str
    plan: PlanInfo | None = None
    memberships: list[Membership] = []
    staff_tournaments: list[StaffTournament] = []
    global_roles: list[str] = []
    primary_team_id: UUID | None = None
    family_player_ids: list[UUID] = []
    follows: list[FollowRef] = []
    unread_notifications: int = 0
    preferences: Preferences = Preferences()


class MeParts(BaseModel):
    """What another module adds to `Me` (registered with `service.contribute_to_me`)."""

    memberships: list[Membership] | None = None
    staff_tournaments: list[StaffTournament] | None = None
    primary_team_id: UUID | None = None
    follows: list[FollowRef] | None = None
    unread_notifications: int | None = None


DemoPersona = Literal["fan", "organiser", "editor"]


class DemoLoginRequest(BaseModel):
    """Development only: sign in as a demo account without the email round trip."""

    model_config = ConfigDict(extra="forbid")

    persona: DemoPersona = "fan"


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    language: Language | None = None
    time_zone: str | None = None
    preferences: PreferencesPatch | None = None

    @field_validator("time_zone")
    @classmethod
    def _time_zone(cls, value: str | None) -> str | None:
        return None if value is None else _valid_time_zone(value)


class Profile(BaseModel):
    """What other modules may know about a user to reach them (notifications)."""

    id: UUID
    email: str
    display_name: str
    language: Language
    time_zone: str


class MyData(BaseModel):
    """Everything OurSport holds about the signed-in user (GDPR Art. 15 and 20)."""

    user_id: UUID
    generated_at: datetime
    data: dict[str, Any]  # by module
