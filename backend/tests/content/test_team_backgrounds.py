import datetime as dt
import json
import uuid
from pathlib import Path

import pytest

from app.modules.analysis.schemas import Fact, FactContext, FactSheetOut
from app.modules.content import checker, service, team_backgrounds
from app.modules.content.schemas import FictionalFlavor, NameBook, WrittenSentence, WrittenText


def _sheet() -> FactSheetOut:
    return FactSheetOut(
        id=uuid.uuid4(),
        subject_type="match",
        subject_id=uuid.uuid4(),
        kind="report",
        facts=[
            Fact(
                id="fixture",
                kind="fixture",
                claim="Alpha United play Beta City.",
                source="match",
            )
        ],
        context=FactContext(
            tournament_id=uuid.uuid4(),
            is_junior=True,
            show_probabilities=False,
            languages=["en"],
            tone_profile="junior",
        ),
        inputs_hash="test",
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )


def _write_corpus(path: Path, teams: dict[str, dict[str, str]]) -> None:
    path.write_text(
        json.dumps({"version": 1, "teams": teams}),
        encoding="utf-8",
    )


def test_team_background_lookup_is_normalized_and_exact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "team_backgrounds.json"
    _write_corpus(
        path,
        {
            "Alpha United": {
                "en": "A fictional tale of bright scarves.",
                "fi": "Kuvitteellinen tarina kirkkaista huiveista.",
                "bn": "উজ্জ্বল স্কার্ফের একটি কাল্পনিক গল্প।",
            }
        },
    )
    monkeypatch.setattr(team_backgrounds, "CORPUS_PATH", path)

    found = team_backgrounds.find_team_backgrounds(["  ALPHA   UNITED ", "Alpha"])

    assert found == {
        "  ALPHA   UNITED ": {
            "en": "A fictional tale of bright scarves.",
            "fi": "Kuvitteellinen tarina kirkkaista huiveista.",
            "bn": "উজ্জ্বল স্কার্ফের একটি কাল্পনিক গল্প।",
        }
    }


def test_report_inputs_only_include_teams_in_the_fact_sheet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "team_backgrounds.json"
    _write_corpus(
        path,
        {
            name: {"en": name, "fi": name, "bn": name}
            for name in ("Alpha United", "Beta City", "Other Town")
        },
    )
    monkeypatch.setattr(team_backgrounds, "CORPUS_PATH", path)
    names = NameBook(teams=["Alpha United", "Beta City", "Other Town"])

    report = service._inputs(_sheet(), "report", "short", [], names)
    preview = service._inputs(_sheet(), "preview", None, [], names)

    assert set(report.fictional_team_backgrounds) == {"Alpha United", "Beta City"}
    assert report.fictional_team_backgrounds["Alpha United"]["en"]["id"].startswith("lore_")
    assert preview.fictional_team_backgrounds == {}


@pytest.mark.parametrize(
    ("language", "label"),
    [
        ("en", "Fictional team flavor (not a match fact):"),
        ("fi", "Kuvitteellinen joukkuekuvaus (ei ottelufakta):"),
        ("bn", "কাল্পনিক দলের পরিচিতি (ম্যাচের তথ্য নয়):"),
    ],
)
def test_story_body_separates_labeled_flavor_from_fact_sentences(
    language: str, label: str
) -> None:
    text = WrittenText(
        sentences=[WrittenSentence(text="The match finished 2-1.", facts=["score"])],
        fictional_flavor=FictionalFlavor(
            text="A wholly fictional club legend.",
            facts=["lore_alpha_en"],
        ),
    )

    body = service._story_body(text, language)

    assert body == (
        f"The match finished 2-1.\n\n**{label}** A wholly fictional club legend."
    )
    assert [sentence.text for sentence in text.sentences] == ["The match finished 2-1."]


def test_editorial_fact_check_excludes_only_labeled_flavor() -> None:
    body = (
        "The match finished 2-1.\n\n"
        "**Fictional team flavor (not a match fact):** A wholly fictional club legend."
    )

    assert service._fact_body(body) == "The match finished 2-1."
    assert service._fact_body("An ordinary factual paragraph.") == "An ordinary factual paragraph."


def test_checker_accepts_flavor_cited_to_external_lore_not_match_facts() -> None:
    text = WrittenText(
        sentences=[WrittenSentence(text="Alpha United play Beta City.", facts=["fixture"])],
        fictional_flavor=FictionalFlavor(
            text="A wholly imagined breeze follows the teams.",
            facts=["lore_alpha_en"],
        ),
    )

    result = checker.check(
        {"en": text},
        _sheet(),
        NameBook(teams=["Alpha United", "Beta City"]),
        task="commentary",
        additional_facts={"lore_alpha_en": "A fictional motif of bright scarves."},
    )

    assert result.passed, result.issues


def test_checker_rejects_fictional_flavor_without_background() -> None:
    text = WrittenText(
        sentences=[WrittenSentence(text="Alpha United play Beta City.", facts=["fixture"])],
        fictional_flavor=FictionalFlavor(
            text="A wholly imagined breeze follows the teams.",
            facts=["lore_alpha_en"],
        ),
    )

    result = checker.check(
        {"en": text},
        _sheet(),
        NameBook(teams=["Alpha United", "Beta City"]),
        task="commentary",
    )

    assert not result.passed
    assert any(issue.kind == "fiction" for issue in result.issues)


def test_checker_rejects_multisentence_fictional_flavor() -> None:
    text = WrittenText(
        sentences=[WrittenSentence(text="Alpha United play Beta City.", facts=["fixture"])],
        fictional_flavor=FictionalFlavor(
            text="A fictional breeze follows. The colors are imagined.",
            facts=["lore_alpha_en"],
        ),
    )

    result = checker.check(
        {"en": text},
        _sheet(),
        NameBook(teams=["Alpha United", "Beta City"]),
        task="commentary",
        additional_facts={"lore_alpha_en": "A fictional motif."},
    )

    assert not result.passed
    assert any(issue.kind == "fiction" for issue in result.issues)


def test_invalid_team_background_corpus_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "team_backgrounds.json"
    _write_corpus(path, {"Alpha United": {"en": "Only one language"}})
    monkeypatch.setattr(team_backgrounds, "CORPUS_PATH", path)

    with pytest.raises(ValueError, match="invalid background for team"):
        team_backgrounds.find_team_backgrounds(["Alpha United"])
