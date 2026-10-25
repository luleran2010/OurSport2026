"""Content schemas: AI drafts as the writing tasks return them, and checker results."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

type Language = Literal["fi", "en", "bn"]
type IssueKind = Literal[
    "number",
    "name",
    "hidden_name",
    "status",
    "banned",
    "fact_ref",
    "length",
    "language",
    "fiction",
]


class WrittenSentence(BaseModel):
    """One sentence and the fact ids it uses (prompt rule 2)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    facts: list[str] = []


class FictionalFlavor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    facts: list[str] = []


class WrittenText(BaseModel):
    """A draft in one language."""

    model_config = ConfigDict(extra="forbid")

    headline: WrittenSentence | None = None
    sentences: list[WrittenSentence] = Field(min_length=1)
    fictional_flavor: FictionalFlavor | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_plain_fields(cls, value: Any) -> Any:
        """Normalize plain-string fields some providers return despite the output schema."""
        if not isinstance(value, dict):
            return value
        value = value.copy()
        if isinstance(value.get("headline"), str):
            sentence_facts: list[str] = []
            sentences = value.get("sentences")
            if isinstance(sentences, list):
                for sentence in sentences:
                    if isinstance(sentence, dict) and isinstance(sentence.get("facts"), list):
                        sentence_facts.extend(
                            fact_id for fact_id in sentence["facts"] if isinstance(fact_id, str)
                        )
            value["headline"] = {
                "text": value["headline"],
                "facts": list(dict.fromkeys(sentence_facts)),
            }
        if isinstance(value.get("fictional_flavor"), str):
            value["fictional_flavor"] = {"text": value["fictional_flavor"], "facts": []}
        return value


class NameBook(BaseModel):
    """Every name the checker should recognise in a tournament's text: all team names,
    and the players a public text may not name (hidden or family-only)."""

    teams: list[str] = []
    players: list[str] = []  # public players; named only if the fact sheet names them
    private_players: list[str] = []  # hidden / family-only: never in public content


class CheckIssue(BaseModel):
    language: str
    sentence: str
    kind: IssueKind
    detail: str


class CheckResult(BaseModel):
    """`check_result` as stored on stories and commentary (docs/07, Claim checker)."""

    passed: bool
    issues: list[CheckIssue] = []


class StoryDraft(BaseModel):
    """What a writing task returns: one text per requested language."""

    model_config = ConfigDict(extra="forbid")

    en: WrittenText | None = None
    fi: WrittenText | None = None
    bn: WrittenText | None = None

    def texts(self) -> dict[str, WrittenText]:
        return {lang: text for lang in ("en", "fi", "bn") if (text := getattr(self, lang))}


class WritingInputs(BaseModel):
    """Everything a writing task sees: the fact sheet payload and how to write."""

    task: str  # "report", "preview", "team_recap", "summary", "announcement"
    length: str | None = None  # reports: "short" or "standard"
    word_range: tuple[int, int] | None = None
    sentence_range: tuple[int, int] | None = None
    tone_profile: str
    show_probabilities: bool
    facts: list[dict[str, Any]]
    fictional_team_backgrounds: dict[str, dict[str, dict[str, str]]] = Field(default_factory=dict)
    retry_issues: list[str] = Field(default_factory=list)  # checker issues of the previous attempt


class StoryFact(BaseModel):
    id: str
    claim: str


class StoryOut(BaseModel):
    """A published story as fans see it (docs/05, Key response schemas: Story)."""

    id: UUID
    tournament_id: UUID | None = None
    kind: str
    subject_type: str
    subject_id: UUID
    language: str
    headline: str
    body: str
    author_type: str
    ai_label: str | None  # localised "Written by AI from match data"; None for human text
    published_at: datetime | None
    corrected_at: datetime | None
    version: int


class StoryDetail(StoryOut):
    sentences: list[dict[str, Any]]  # [{text, facts}] — which facts each sentence uses
    facts: list[StoryFact]


class AnnouncementOut(BaseModel):
    id: UUID
    kind: str
    ref: str | None
    texts: dict[str, str]
    author_type: str
    status: str
    created_at: datetime
    sent_at: datetime | None


class CommentaryLine(BaseModel):
    language: str
    text: str
    fact_ids: list[str]


class CommentaryOut(BaseModel):
    """A live commentary item (docs/06, WebSocket `commentary`)."""

    id: UUID
    match_id: UUID
    seq: int
    kind: str
    moments: list[str]
    items: list[CommentaryLine]
    author_type: str  # "ai" or "template"
    ai_labels: dict[str, str] | None  # per language, only for AI text
    created_at: datetime


class ReviewSummary(StoryOut):
    """A story waiting for (or after) an editor's decision."""

    status: str
    review_reason: str | None
    updated_at: datetime
    reviewed_by_editor: bool = False  # approved by an editor (the label says so)
    removal_reason: str | None = None  # why an editor unpublished it


class StoryVersionOut(BaseModel):
    version: int
    headline: str
    body: str
    edited_by: UUID | None
    created_at: datetime


class ReviewItem(ReviewSummary):
    sentences: list[dict[str, Any]]
    check_result: dict[str, Any]
    facts: list[StoryFact]  # the whole fact sheet the story was written from
    versions: list[StoryVersionOut]


class StoryEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


StoryAction = Literal["approve", "reject", "unpublish"]


class ScreenPanel(BaseModel):
    kind: Literal["now_playing", "commentary", "next_up", "standings", "announcement", "story"]
    seconds: int
    data: dict[str, Any]


class ScreenRotation(BaseModel):
    """What the venue screen cycles through, in order (each panel for `seconds`)."""

    tournament_id: UUID
    generated_at: datetime
    panels: list[ScreenPanel]
