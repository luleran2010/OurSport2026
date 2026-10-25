"""Competitions: tournament defaults, contacts for staff only, junior visibility."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.time import FrozenClock
from app.core.viewer import Viewer
from app.modules.accounts import service as accounts
from app.modules.competitions import service
from app.modules.competitions.schemas import (
    ConsentCreate,
    OrganisationCreate,
    PlayerCreate,
    TeamCreate,
    TournamentCreate,
)

MakeUser = Callable[[], Awaitable[UUID]]
ANONYMOUS = Viewer()


async def organisation(db: AsyncSession, clock: FrozenClock, user: UUID) -> UUID:
    data = OrganisationCreate(
        kind="community", name="Test Community", sports=["football"], accept_processing_terms=True
    )
    return (await service.create_organisation(db, clock, Viewer(user_id=user), data)).id


async def tournament(
    db: AsyncSession, clock: FrozenClock, owner: UUID, age_group: Any = "adult"
) -> UUID:
    org = await organisation(db, clock, owner)
    data = TournamentCreate(
        organisation_id=org, name="Test Cup", sport="football", age_group=age_group
    )
    return (await service.create_tournament(db, clock, owner, data)).id


async def junior_team(db: AsyncSession, clock: FrozenClock, tournament_id: UUID) -> UUID:
    team = await service.create_team(
        db,
        clock,
        TeamCreate(
            name="Test Juniors",
            age_group="u12",
            contact_name="Coach",
            contact_email="coach@example.com",
            contact_phone="+358 40 000 0000",
        ),
    )
    await service.enter_team(db, tournament_id, team.id)
    return team.id


# --- tournaments -----------------------------------------------------------------------------


async def test_u12_tournaments_hide_probabilities_by_default(
    db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner = await make_user()
    org = await organisation(db, clock, owner)

    junior = await service.create_tournament(
        db,
        clock,
        owner,
        TournamentCreate(organisation_id=org, name="Mini Cup", sport="football", age_group="u12"),
    )
    adult = await service.create_tournament(
        db, clock, owner, TournamentCreate(organisation_id=org, name="Mini Cup", sport="football")
    )

    assert junior.settings.show_probabilities is False
    assert junior.is_junior
    assert junior.settings.filming_policy == "consent_required"
    assert adult.settings.show_probabilities is True
    assert adult.status == "draft"
    assert adult.slug != junior.slug


# --- teams -----------------------------------------------------------------------------------


async def test_team_contacts_are_for_tournament_staff_only(
    db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner, stranger = await make_user(), await make_user()
    cup = await tournament(db, clock, owner, "u12")
    team = await junior_team(db, clock, cup)

    as_owner = await service.get_team(db, Viewer(user_id=owner), team)
    as_stranger = await service.get_team(db, Viewer(user_id=stranger), team)
    as_anonymous = await service.get_team(db, ANONYMOUS, team)

    assert as_owner.contacts is not None and as_owner.contacts.contact_email == "coach@example.com"
    assert as_stranger.contacts is None
    assert as_anonymous.contacts is None


def test_alias_normalisation_ignores_case_accents_and_punctuation() -> None:
    assert service.normalise_alias("  Dhaka  Stars F.C. ") == service.normalise_alias(
        "dhaka stars fc"
    )
    assert service.normalise_alias("Kärpät") == "karpat"


# --- junior players --------------------------------------------------------------------------


async def test_junior_players_default_to_hidden_and_adults_to_public(
    db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner = await make_user()
    team = await junior_team(db, clock, await tournament(db, clock, owner, "u12"))
    adults = await service.create_team(db, clock, TeamCreate(name="Test Adults"))

    junior = await service.create_player(db, clock, team, PlayerCreate(display_name="Junior One"))
    by_year = await service.create_player(
        db,
        clock,
        adults.id,
        PlayerCreate(display_name="Young One", birth_year=clock.now().year - 15),
    )
    adult = await service.create_player(
        db, clock, adults.id, PlayerCreate(display_name="Adult One")
    )

    assert junior.visibility == "hidden"
    assert by_year.visibility == "hidden"
    assert adult.visibility == "public"


async def test_showing_a_junior_needs_guardian_consent(
    db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner = await make_user()
    team = await junior_team(db, clock, await tournament(db, clock, owner, "u12"))
    player = await service.create_player(db, clock, team, PlayerCreate(display_name="Junior Two"))

    with pytest.raises(ValidationFailed):
        await service.create_player(
            db, clock, team, PlayerCreate(display_name="Junior Three", visibility="public")
        )
    with pytest.raises(ValidationFailed):
        await service.set_player_visibility(db, clock, player.id, "family_only")
    profile = await service.record_consent(
        db, clock, player.id, ConsentCreate(scope="profile", guardian_contact="guardian")
    )
    family = await service.set_player_visibility(db, clock, player.id, "family_only")
    with pytest.raises(ValidationFailed):
        await service.set_player_visibility(db, clock, player.id, "public")
    await service.record_consent(
        db, clock, player.id, ConsentCreate(scope="stats", guardian_contact="guardian")
    )
    public = await service.set_player_visibility(db, clock, player.id, "public")
    withdrawn = await service.withdraw_consent(db, clock, profile)

    assert family.visibility == "family_only"
    assert public.visibility == "public"
    assert withdrawn.visibility == "hidden"  # stats alone allows nothing more


async def test_visibility_filter_per_viewer(
    db: AsyncSession, clock: FrozenClock, make_user: MakeUser
) -> None:
    owner, guardian, stranger = await make_user(), await make_user(), await make_user()
    team = await junior_team(db, clock, await tournament(db, clock, owner, "u12"))
    hidden = await service.create_player(db, clock, team, PlayerCreate(display_name="Hidden One"))
    family = await service.create_player(db, clock, team, PlayerCreate(display_name="Family One"))
    shown = await service.create_player(db, clock, team, PlayerCreate(display_name="Public One"))
    for scope in ("profile", "stats"):
        for player in (family, shown):
            await service.record_consent(
                db, clock, player.id, ConsentCreate(scope=scope, guardian_contact="guardian")
            )
    await service.set_player_visibility(db, clock, family.id, "family_only")
    await service.set_player_visibility(db, clock, shown.id, "public")
    await accounts.link_family(db, clock, guardian, family.id, owner)

    def names(players: list[Any]) -> set[str]:
        return {p.display_name for p in players}

    assert names(await service.list_players(db, ANONYMOUS, team)) == {"Public One"}
    assert names(await service.list_players(db, Viewer(user_id=stranger), team)) == {"Public One"}
    assert names(await service.list_players(db, Viewer(user_id=guardian), team)) == {
        "Public One",
        "Family One",
    }
    assert names(await service.list_players(db, Viewer(user_id=owner), team)) == {
        "Public One",
        "Family One",
        "Hidden One",
    }
    with pytest.raises(NotFound):
        await service.get_player(db, ANONYMOUS, hidden.id)


# --- endpoint --------------------------------------------------------------------------------

ORGANISATION = {
    "kind": "community",
    "name": "Test Association",
    "sports": ["football"],
    "accept_processing_terms": True,
}


def test_create_organisation_needs_an_account(api: TestClient) -> None:
    response = api.post("/api/v1/organisations", json=ORGANISATION)

    assert response.status_code == 401


def test_create_organisation_requires_the_processing_terms(
    api: TestClient, signed_in: dict[str, str]
) -> None:
    headers = {"X-CSRF-Token": signed_in["csrf_token"]}

    created = api.post("/api/v1/organisations", json=ORGANISATION, headers=headers)
    refused = api.post(
        "/api/v1/organisations",
        json={**ORGANISATION, "accept_processing_terms": False},
        headers=headers,
    )

    assert created.status_code == 201
    assert created.json()["slug"].startswith("test-association")
    assert refused.status_code == 422
