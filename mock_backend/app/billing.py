"""Club portal C6: billing.

Mock of a hosted payment provider (in production e.g. Stripe Billing). Our app never sees card details:
- the payment method is a summary the provider returns (brand, last 4, expiry),
- "Manage payment method" asks the backend for a short-lived provider session URL and redirects there,
- invoices are issued by the provider; we list them and offer the PDF.

Pricing: price per Premium seat per month (VAT 0 %), Finnish VAT added on invoices. Adding seats mid-month
charges the rest of the month on the next invoice; removing seats applies from the next invoice.
"""

from __future__ import annotations

import calendar
import html
import secrets
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException

from . import club_members as CM
from .club_portal import subscription
from .mock_data import CLUBS, VAT_RATE
from .models import BillingSummary, Invoice, PaymentMethod, SeatChangeResult

if TYPE_CHECKING:
    from .store import FeedStore, Session

MAX_SEATS = 1000
PORTAL_MINUTES = 15


def _today(ts_ms: int) -> date:
    """Calendar day for billing (the server runs on Finnish time)."""
    return datetime.fromtimestamp(ts_ms / 1000).astimezone().date()


def _month_start(day: date, months: int = 0) -> date:
    y, m = day.year, day.month + months
    return date(y + (m - 1) // 12, (m - 1) % 12 + 1, 1)


def vat(net: int) -> int:
    return round(net * VAT_RATE / 100)


def _invoices(store: FeedStore, club_id: str, sub: dict) -> list[dict]:
    """Seeded monthly invoices (paid), newest first. Kept in the subscription so they stay the same."""
    if sub["invoices"] is None:
        rows = []
        for k in range(1, min(sub["since_months"], 6) + 1):
            start = _month_start(_today(store.now), -k)
            seats = max(sub["seats_total"] - 2 * (k - 1), 0) if sub["seats_total"] else 0
            net = seats * sub["price_cents"]
            rows.append({"id": f"inv-{club_id}-{start:%Y%m}", "number": f"LP-{start:%Y%m}-{club_id.upper()}",
                         "period_start": start.isoformat(),
                         "period_end": (_month_start(start, 1) - timedelta(days=1)).isoformat(),
                         "issued_on": start.isoformat(), "seats": seats, "net_cents": net, "vat_cents": vat(net),
                         "total_cents": net + vat(net), "status": "paid"})
        sub["invoices"] = rows
        sub.setdefault("pending_cents", 0)
    return sub["invoices"]


def summary(store: FeedStore, club_id: str) -> BillingSummary:
    sub = subscription(store, club_id)
    invoices = _invoices(store, club_id, sub)
    used = CM.seats(store, club_id).used
    monthly = sub["seats_total"] * sub["price_cents"]
    pending = sub.get("pending_cents", 0)
    card = sub.get("card")
    return BillingSummary(
        club=CLUBS[club_id], plan=sub["plan"], price_per_seat_cents=sub["price_cents"], vat_rate=VAT_RATE,
        seats_total=sub["seats_total"], seats_used=used, min_seats=used, max_seats=MAX_SEATS,
        monthly_net_cents=monthly, next_invoice_date=_month_start(_today(store.now), 1).isoformat(),
        next_invoice_estimate_cents=monthly + pending + vat(monthly + pending), pending_charge_cents=pending,
        payment_method=PaymentMethod(brand=card[0], last4=card[1], expires=card[2]) if card else None,
        invoices=[Invoice(**inv, pdf_url=f"/clubs/{club_id}/billing/invoices/{inv['id']}.pdf") for inv in invoices],
        updated_at=store.now,
    )


def change_seats(store: FeedStore, club_id: str, seats: int, preview: bool) -> SeatChangeResult:
    sub = subscription(store, club_id)
    _invoices(store, club_id, sub)
    used = CM.seats(store, club_id).used
    before = sub["seats_total"]
    if seats < used:
        raise HTTPException(409, {"code": "seats_in_use", "min": used,
                                  "message": f"{used} seats are in use. Remove Premium from members first to go below {used}."})
    if seats == before:
        raise HTTPException(409, {"code": "no_change", "message": "That is the current seat count."})
    if seats > 0 and not sub.get("card"):
        raise HTTPException(402, {"code": "payment_method_required", "message": "Add a payment method first."})
    now = _today(store.now)
    days = calendar.monthrange(now.year, now.month)[1]
    days_left = days - now.day + 1
    added = max(seats - before, 0)
    prorated = round(added * sub["price_cents"] * days_left / days)
    new_monthly = seats * sub["price_cents"]
    eur = lambda c: f"{c / 100:.2f} €".replace(".", ",")  # noqa: E731
    if added:
        msg = (f"{added} more seat{'s' if added > 1 else ''} now. {eur(prorated)} (VAT 0 %) for the rest of this month "
               f"is added to the next invoice; from then on {eur(new_monthly)} a month.")
    else:
        msg = f"{before - seats} seat{'s' if before - seats > 1 else ''} fewer. From the next invoice {eur(new_monthly)} a month."
    if preview:
        return SeatChangeResult(seats_from=before, seats_to=seats, prorated_net_cents=prorated,
                                new_monthly_net_cents=new_monthly, message=msg, applied=False)
    sub["seats_total"] = seats
    sub["pending_cents"] = sub.get("pending_cents", 0) + prorated
    if sub["plan"] == "Free" and seats > 0:
        sub["plan"] = "Club"
    return SeatChangeResult(seats_from=before, seats_to=seats, prorated_net_cents=prorated, new_monthly_net_cents=new_monthly,
                            message=msg, applied=True, billing=summary(store, club_id))


# ---- hosted provider page (mock) ---------------------------------------------------------

def portal_session(store: FeedStore, club_id: str, return_path: str, session: Session) -> tuple[str, int]:
    if not return_path.startswith("/club/") or "//" in return_path or "\\" in return_path:
        return_path = f"/club/{club_id}/billing"
    token = secrets.token_urlsafe(18)
    expires = store.now + PORTAL_MINUTES * 60_000
    store.portal_sessions[token] = {"club_id": club_id, "return_path": return_path, "expires_at": expires, "by": session}
    return f"/billing-provider/session/{token}", expires


def _session(store: FeedStore, token: str) -> dict:
    s = store.portal_sessions.get(token)
    if s is None or s["expires_at"] < store.now:
        raise HTTPException(410, "This payment page link has expired. Open it again from the club portal.")
    return s


def provider_page(store: FeedStore, token: str) -> str:
    s = _session(store, token)
    club = CLUBS[s["club_id"]]
    card = subscription(store, s["club_id"]).get("card")
    now_card = f"{card[0]} ending {card[1]}, expires {card[2]}" if card else "No payment method yet"
    back = html.escape(f"{s['return_path']}?portal=return")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Demo payment provider</title><style>
body{{margin:0;font:15px/1.5 system-ui,sans-serif;background:#f4f5f7;color:#1c2330;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}}
.card{{background:#fff;border-radius:14px;padding:28px;max-width:440px;width:100%;box-shadow:0 8px 30px rgb(0 0 0/.08)}}
.demo{{background:#fff4cc;color:#6b5200;border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:16px}}
h1{{font-size:20px;margin:0 0 4px}}p{{margin:6px 0}}form{{display:inline}}button,a.btn{{display:inline-block;margin:14px 8px 0 0;padding:10px 16px;border-radius:9px;
border:1px solid #c9ced6;background:#fff;color:#1c2330;font:inherit;text-decoration:none;cursor:pointer}}button.primary{{background:#1c2330;color:#fff;border-color:#1c2330}}
</style></head><body><main class="card">
<div class="demo">Demo only: this page stands in for the payment provider’s hosted billing page. It doesn’t ask for card details.</div>
<h1>Billing for {html.escape(club.name)}</h1>
<p>Payment method: <strong>{html.escape(now_card)}</strong></p>
<p>On the real provider page the club admin adds or replaces the card and downloads receipts.</p>
<form method="post" action="/billing-provider/session/{token}/simulate-update"><button class="primary">Simulate: card replaced</button></form>
<a class="btn" href="{back}">Return to OurSport</a>
</main></body></html>"""


def simulate_update(store: FeedStore, token: str) -> str:
    s = _session(store, token)
    sub = subscription(store, s["club_id"])
    sub["card"] = ("Visa", f"{secrets.randbelow(9000) + 1000}", "12/29")
    store.portal_sessions.pop(token, None)
    return f"{s['return_path']}?portal=updated"


# ---- invoice PDF -------------------------------------------------------------------------

def invoice_pdf(store: FeedStore, club_id: str, invoice_id: str) -> tuple[str, bytes]:
    inv = next((i for i in summary(store, club_id).invoices if i.id == invoice_id), None)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    club = CLUBS[club_id]
    sub = subscription(store, club_id)
    d = lambda iso: date.fromisoformat(iso).strftime("%d.%m.%Y")  # noqa: E731
    eur = lambda c: f"{c / 100:,.2f}".replace(",", " ").replace(".", ",") + " EUR"  # noqa: E731
    lines = [
        (20, "OurSport AI - Invoice"), (11, ""), (11, f"Invoice number: {inv.number}"), (11, f"Date: {d(inv.issued_on)}"),
        (11, f"Billed to: {club.name}, {club.city}"), (11, f"Period: {d(inv.period_start)} - {d(inv.period_end)}"), (11, ""),
        (11, f"Premium seats: {inv.seats} x {eur(sub['price_cents'])} / month"), (11, f"Net amount: {eur(inv.net_cents)}"),
        (11, f"VAT {str(VAT_RATE).replace('.', ',')} %: {eur(inv.vat_cents)}"), (13, f"Total: {eur(inv.total_cents)}"),
        (11, ""), (11, f"Status: {'Paid' if inv.status == 'paid' else 'Open'}"), (9, ""),
        (9, "Demo invoice generated by the OurSport AI mock billing. Not a real tax document."),
    ]
    return f"{inv.number}.pdf", _pdf(lines)


def _pdf(lines: list[tuple[int, str]]) -> bytes:
    """A one-page PDF with plain text lines (no PDF library needed)."""
    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    y, ops = 790, ["BT"]
    for size, text in lines:
        ops.append(f"/F1 {size} Tf 1 0 0 1 56 {y} Tm ({esc(text)}) Tj")
        y -= size + 9
    ops.append("ET")
    stream = "\n".join(ops).encode("cp1252", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)
