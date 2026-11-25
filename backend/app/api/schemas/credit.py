"""Credit report analysis responses (Feature Design 4.8).

Every score, tradeline, inquiry and flag carries the report lines it came from, and every figure its
working. The report is simulated, so every response says so. Nothing here decides anything: the
summary says what the report shows (rule 3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.api.schemas.assets import AssetFlagOut, CalcOut, calc_from_row
from app.api.schemas.assets import flag_from_row as asset_flag_from_row
from app.api.schemas.income import exact
from app.api.schemas.jobs import JobOut
from app.db.enums import AnalysisStatus
from app.db.models import CreditInquiry, CreditScore, Tradeline
from app.services.credit import slug
from app.services.credit_runs import CreditView, summary_from_view

SAMPLE_TAG = "Sample credit report (simulated). No credit bureau was contacted."
SUMMARY_NOTE = (
    "Says what the report shows and flags it for a person to look at. It makes no credit decision."
)
# Alerts always come first (Feature Design 4.3).
ALERT_CODE = "CR-W105"


class CreditRunAccepted(BaseModel):
    job: JobOut
    analysis_id: uuid.UUID


class ScoreOut(BaseModel):
    bureau: str
    score: int
    is_representative: bool
    line_ids: list[str]


class TradelineOut(BaseModel):
    id: uuid.UUID
    position: int
    creditor: str
    account_type: str
    ownership: str | None
    opened_on: date | None
    status: str | None
    balance: str | None
    credit_limit: str | None
    monthly_payment: str | None
    past_due: str | None
    late_30: int
    late_60: int
    late_90: int
    last_late_on: date | None
    remarks: str
    line_ids: list[str]
    # Revolving accounts only: balance over limit, and whether it is above the review level.
    utilization: CalcOut | None
    utilization_over_review_level: bool
    months_since_last_late: CalcOut | None
    late_in_lookback: bool
    derogatory: bool


class InquiryOut(BaseModel):
    id: uuid.UUID
    position: int
    creditor: str
    inquired_on: date | None
    in_window: bool
    matched_tradeline_id: uuid.UUID | None
    # "no new account found" is a null match, shown as such.
    matched_account: str | None
    line_ids: list[str]


class RepresentativeScoreOut(BaseModel):
    score: int
    bureau: str | None
    method: str
    calculation: CalcOut


class CreditAnalysisOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: AnalysisStatus
    started_at: datetime
    finished_at: datetime | None
    config_versions: dict[str, object]
    tag: str = SAMPLE_TAG
    note: str = SUMMARY_NOTE
    # Fraud alerts, freezes and consumer statements come first.
    alerts: list[AssetFlagOut]
    scores: list[ScoreOut]
    representative: RepresentativeScoreOut | None
    tradelines: list[TradelineOut]
    total_revolving_utilization: CalcOut | None
    monthly_payments: list[CalcOut]
    inquiries: list[InquiryOut]
    derogatory: list[TradelineOut]
    flags: list[AssetFlagOut]
    summary: list[str]
    calculations: list[CalcOut]


def _score(row: CreditScore) -> ScoreOut:
    return ScoreOut(
        bureau=row.bureau,
        score=row.score,
        is_representative=row.is_representative,
        line_ids=list(row.line_refs),
    )


def _tradeline(row: Tradeline, view: CreditView, version: str) -> TradelineOut:
    key = slug(row.creditor)
    utilization = view.calc(f"utilization_{key}")
    months = view.calc(f"months_since_last_late_{key}")
    return TradelineOut(
        id=row.id,
        position=row.position,
        creditor=row.creditor,
        account_type=row.account_type,
        ownership=row.ownership,
        opened_on=row.opened_on,
        status=row.status,
        balance=exact(row.balance),
        credit_limit=exact(row.credit_limit),
        monthly_payment=exact(row.monthly_payment),
        past_due=exact(row.past_due),
        late_30=row.late_30,
        late_60=row.late_60,
        late_90=row.late_90,
        last_late_on=row.last_late_on,
        remarks=row.remarks,
        line_ids=list(row.line_refs),
        utilization=calc_from_row(utilization, version) if utilization else None,
        utilization_over_review_level=row.utilization_over_review_level,
        months_since_last_late=calc_from_row(months, version) if months else None,
        late_in_lookback=row.late_in_lookback,
        derogatory=row.derogatory,
    )


def _inquiry(row: CreditInquiry, by_id: dict[uuid.UUID, Tradeline]) -> InquiryOut:
    matched = by_id.get(row.matched_tradeline_id) if row.matched_tradeline_id else None
    return InquiryOut(
        id=row.id,
        position=row.position,
        creditor=row.creditor,
        inquired_on=row.inquired_on,
        in_window=row.in_window,
        matched_tradeline_id=row.matched_tradeline_id,
        matched_account=matched.creditor if matched else None,
        line_ids=list(row.line_refs),
    )


def analysis_from_view(view: CreditView, method: str) -> CreditAnalysisOut:
    version = view.version_string()
    flags = [asset_flag_from_row(f) for f in view.flags]
    representative = view.calc("representative_score")
    chosen = next((s for s in view.scores if s.is_representative), None)
    tradelines = [_tradeline(t, view, version) for t in view.tradelines]
    by_id = {t.id: t for t in view.tradelines}
    return CreditAnalysisOut(
        id=view.run.id,
        case_id=view.run.case_id,
        status=view.run.status,
        started_at=view.run.started_at,
        finished_at=view.run.finished_at,
        config_versions=view.run.config_versions,
        alerts=[f for f in flags if f.code == ALERT_CODE],
        scores=[_score(s) for s in view.scores],
        representative=(
            RepresentativeScoreOut(
                score=int(representative.value),
                bureau=chosen.bureau if chosen else None,
                method=method,
                calculation=calc_from_row(representative, version),
            )
            if representative
            else None
        ),
        tradelines=tradelines,
        total_revolving_utilization=(
            calc_from_row(c, version) if (c := view.calc("total_revolving_utilization")) else None
        ),
        monthly_payments=[
            calc_from_row(c, version)
            for c in view.calculations
            if c.name.startswith("monthly_payments_")
        ],
        inquiries=[_inquiry(i, by_id) for i in view.inquiries],
        derogatory=[t for t in tradelines if t.derogatory],
        flags=[f for f in flags if f.code != ALERT_CODE],
        summary=summary_from_view(view),
        calculations=[calc_from_row(c, version) for c in view.calculations],
    )
