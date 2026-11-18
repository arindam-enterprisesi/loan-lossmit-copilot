"""A merged credit report (simulated: no bureau is involved)."""

from __future__ import annotations

from synthetic.layout import LEFT, RIGHT, Page, Seg
from synthetic.schema import CreditReportDoc
from synthetic.schema import money_text as m


def _none_or(items: list[str]) -> str:
    return ", ".join(items) if items else "none"


def render_credit_report(doc: CreditReportDoc) -> list[Page]:
    f = doc.facts
    p = Page()
    p.line("SAMPLE MERGED CREDIT REPORT (simulated)", bold=True, size=12, rule=True)
    p.line(f"Report date: {f.report_date.isoformat()}")
    p.line(f"Consumer: {f.consumer}   SSN XXX-XX-{f.ssn_last4}")
    p.line(f"Address: {f.address}")
    p.line(f"Alerts: {_none_or(f.alerts)}", rule=True)
    p.line("SCORES", bold=True)
    for s in f.scores:
        p.cols(Seg(LEFT, f"{s.bureau} score"), Seg(RIGHT, str(s.score), "r"))
    p.line("TRADELINES", bold=True, rule=True)
    for t in f.tradelines:
        p.line(
            f"{t.creditor} | {t.account_type} | {t.ownership} | opened {t.open_date.isoformat()} "
            f"| status {t.status}",
            bold=True,
        )
        limit = f"Limit {m(t.credit_limit)}" if t.credit_limit is not None else "Limit n/a"
        p.line(
            f"Balance {m(t.balance)}  {limit}  Monthly payment {m(t.monthly_payment)}  "
            f"Past due {m(t.past_due)}"
        )
        last = t.most_recent_late.isoformat() if t.most_recent_late else "none"
        p.line(
            f"Late payments: 30-day {t.late_30}, 60-day {t.late_60}, 90-day {t.late_90}  "
            f"Most recent late: {last}"
        )
        p.line(f"Remarks: {t.remarks or 'none'}")
    p.line("INQUIRIES", bold=True, rule=True)
    for q in f.inquiries:
        p.line(f"{q.creditor}  {q.date.isoformat()}")
    p.line(f"Collections: {_none_or(f.collections)}")
    p.line(f"Public records: {_none_or(f.public_records)}")
    p.footer("Page 1 of 1")
    return [p]
