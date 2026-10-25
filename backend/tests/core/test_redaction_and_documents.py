import io
import zipfile

from openpyxl import Workbook

from app.core.documents import extract
from app.core.redaction import find_pii, redact

PLANTED = {
    "phone": "+358 40 123 4567",
    "email": "coach.person@example.com",
    "identity_code": "131052-308T",
    "date": "12.03.2012",
    "address": "Mannerheimintie 12",
}


def test_redaction_removes_every_planted_kind_and_counts_it() -> None:
    text = (
        f"Coach: call {PLANTED['phone']} or mail {PLANTED['email']}. "
        f"Player born {PLANTED['date']}, id {PLANTED['identity_code']}, "
        f"lives at {PLANTED['address']}. Final 3-1 in 2026, shirt 10."
    )

    result = redact(text)

    for value in PLANTED.values():
        assert value not in result.text
    assert set(result.counts) == set(PLANTED)
    assert "3-1" in result.text and "2026" in result.text and "shirt 10" in result.text
    assert find_pii(result.text) == []


def test_csv_with_semicolons_becomes_rows() -> None:
    data = b"Team;Club\nDhaka Stars;FinBangla\nOulu United;OU\n"

    doc = extract(data, "teams.csv", "text/csv")

    assert doc.rows == [["Team", "Club"], ["Dhaka Stars", "FinBangla"], ["Oulu United", "OU"]]


def test_xlsx_and_docx_are_read() -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["Team", "Group"])
    sheet.append(["Team One", "A"])
    xlsx = io.BytesIO()
    book.save(xlsx)
    docx = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    run = "<w:p><w:r><w:t>Rule 1: win 3 points</w:t></w:r></w:p>"
    body = f'<w:document xmlns:w="{ns}"><w:body>{run}</w:body></w:document>'
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", body)

    sheet_doc = extract(xlsx.getvalue(), "teams.xlsx")
    word_doc = extract(docx.getvalue(), "rules.docx")

    assert sheet_doc.rows == [["Team", "Group"], ["Team One", "A"]]
    assert word_doc.text == "Rule 1: win 3 points"
    assert extract(b"\x89PNG...", "photo.png", "image/png").kind == "image"
