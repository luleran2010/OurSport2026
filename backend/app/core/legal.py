"""Legal pages (docs/13-compliance-finland.md): privacy notice, cookies, accessibility
statement, how AI is used, and the contact point for reports (DSA). Drafts in fi/en/bn,
marked for legal review until a lawyer has signed them off."""

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from app.core.errors import NotFound
from app.core.http_cache import cached

TEXTS = Path(__file__).parent / "legal_texts"
VERSION = "2026-10-draft"
Document = Literal["privacy", "cookies", "accessibility", "ai", "contact"]

router = APIRouter(prefix="/legal", tags=["legal"])


class LegalDocument(BaseModel):
    document: str
    language: str
    version: str
    markdown: str
    needs_legal_review: bool = True


def load(document: str, language: str) -> LegalDocument:
    path = TEXTS / f"{document}.{language}.md"
    if not path.exists():
        path = TEXTS / f"{document}.en.md"
        language = "en"
    if not path.exists():
        raise NotFound()
    return LegalDocument(
        document=document, language=language, version=VERSION, markdown=path.read_text("utf-8")
    )


@router.get("/{document}", response_model=LegalDocument, operation_id="getLegalDocument")
async def legal_document(
    document: Document,
    request: Request,
    lang: Annotated[Literal["fi", "en", "bn"], Query()] = "en",
) -> Response:
    """A legal page in fi, en or bn (Markdown)."""
    return cached(request, load(document, lang), max_age=3600)
