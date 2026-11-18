"""Scenario file models. Money is ``Decimal`` (never float) and is stored as a string in JSON."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

CENT = Decimal("0.01")
SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"


def _money(value: Decimal) -> Decimal:
    if value != value.quantize(CENT):
        raise ValueError(f"money needs at most 2 decimal places, got {value}")
    return value.quantize(CENT)


Money = Annotated[Decimal, AfterValidator(_money)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- shared pieces -----------------------------------------------------------------------


class Employer(Model):
    name: str
    address: str
    ein: str


class Borrower(Model):
    name: str
    address: str
    ssn_last4: str
    case_title: str
    pillar: Literal["underwriting", "loss_mitigation"]
    reference_date: date


class LoanScenario(Model):
    purpose: str
    occupancy: str
    property_value: Money
    loan_amount: Money
    proposed_housing_payment: Money
    funds_needed_to_close: Money


class LoanRecord(Model):
    loan_id: str
    investor: str
    servicer: str
    borrower: str
    property_address: str
    unpaid_principal_balance: Money
    interest_rate_pct: Decimal
    principal_and_interest: Money
    escrow: Money
    monthly_payment: Money
    next_due_date: date
    missed_payment_due_dates: list[date]
    past_due_amount: Money
    total_due: Money
    delinquency_status: str
    months_delinquent: int


# --- document facts ----------------------------------------------------------------------


class Earning(Model):
    description: str
    hours: Decimal | None
    rate: Decimal | None
    current: Money
    ytd: Money


class Deduction(Model):
    description: str
    current: Money
    ytd: Money


class PayStubFacts(Model):
    employer: Employer
    employee: str
    employee_id: str
    address: str
    pay_frequency: str
    period_start: date
    period_end: date
    pay_date: date
    period_number: int
    periods_per_year: int
    earnings: list[Earning]
    deductions: list[Deduction]
    gross_current: Money
    gross_ytd: Money
    deductions_current: Money
    deductions_ytd: Money
    net_current: Money
    net_ytd: Money
    # A deliberate defect: the amount the stub prints when it differs from the true net pay.
    printed_net_current: Money | None
    direct_deposit_last4: str
    pages: int


class Transaction(Model):
    date: date
    description: str
    amount: Money  # credits positive, debits negative
    category: str  # what a correct labelling returns (never printed on the statement)
    counterparty: str


class BankStatementFacts(Model):
    bank: str
    bank_address: str
    account_holder: str
    account_type: str
    account_last4: str
    period_start: date
    period_end: date
    opening_balance: Money
    closing_balance: Money
    total_pages_printed: int
    pages_rendered: int
    first_page_rows: int
    other_page_rows: int
    transactions: list[Transaction]


class W2Box12(Model):
    code: str
    amount: Money


class W2Facts(Model):
    tax_year: int
    employer: Employer
    employee: str
    ssn_last4: str
    address: str
    box1: Money
    box2: Money
    box3: Money
    box4: Money
    box5: Money
    box6: Money
    box12: list[W2Box12]


class Form1040Facts(Model):
    tax_year: int
    filing_status: str
    taxpayer: str
    ssn_last4: str
    address: str
    wages: Money
    taxable_interest: Money
    total_income: Money
    adjustments: Money
    adjusted_gross_income: Money


class Score(Model):
    bureau: str
    score: int


class Tradeline(Model):
    creditor: str
    account_type: str
    ownership: str
    open_date: date
    status: str
    balance: Money
    credit_limit: Money | None
    monthly_payment: Money
    past_due: Money
    late_30: int
    late_60: int
    late_90: int
    most_recent_late: date | None
    remarks: str


class Inquiry(Model):
    creditor: str
    date: date


class CreditReportFacts(Model):
    report_date: date
    consumer: str
    address: str
    ssn_last4: str
    report_type: str
    scores: list[Score]
    tradelines: list[Tradeline]
    inquiries: list[Inquiry]
    collections: list[str]
    public_records: list[str]
    alerts: list[str]


class MortgageStatementFacts(Model):
    servicer: str
    servicer_address: str
    statement_date: date
    loan_number: str
    borrower: str
    property_address: str
    unpaid_principal_balance: Money
    interest_rate_pct: Decimal
    payment_due_date: date
    principal_and_interest: Money
    escrow: Money
    monthly_payment: Money
    past_due_amount: Money
    late_fees: Money
    total_due: Money
    payments_past_due: list[date]
    delinquency_notice: str


class HardshipReason(Model):
    reason: str
    checked: bool


class ExpenseLine(Model):
    category: str
    amount: Money


class AssetLine(Model):
    description: str
    amount: Money


class ApplicationFacts(Model):
    title: str
    borrower: str
    address: str
    phone: str
    loan_number: str
    servicer: str
    property_address: str
    occupancy: str
    hardship_reasons: list[HardshipReason]
    intent: str
    monthly_gross_income: Money
    other_income: Money
    expenses: list[ExpenseLine]
    total_expenses: Money
    assets: list[AssetLine]
    enclosed: list[str]
    signature: str
    signed_date: date


class Quote(Model):
    line: int
    quote: str


class HardshipLetterFacts(Model):
    lines: list[str]
    quotes: dict[str, Quote]


class UtilityBillFacts(Model):
    provider: str
    provider_address: str
    customer: str
    service_address: str
    account_number_last4: str
    period_start: date
    period_end: date
    statement_date: date
    due_date: date
    amount_due: Money


# --- documents and the scenario ----------------------------------------------------------


class DocBase(Model):
    id: str
    file_name: str
    role: Literal["case", "withheld"]
    declared_type: str | None = None
    notes: str | None = None


class PayStubDoc(DocBase):
    type: Literal["pay_stub"]
    facts: PayStubFacts


class BankStatementDoc(DocBase):
    type: Literal["bank_statement"]
    facts: BankStatementFacts


class W2Doc(DocBase):
    type: Literal["w2"]
    facts: W2Facts


class Form1040Doc(DocBase):
    type: Literal["tax_return_1040"]
    facts: Form1040Facts


class CreditReportDoc(DocBase):
    type: Literal["credit_report"]
    facts: CreditReportFacts


class MortgageStatementDoc(DocBase):
    type: Literal["mortgage_statement"]
    facts: MortgageStatementFacts


class ApplicationDoc(DocBase):
    type: Literal["mortgage_assistance_application"]
    facts: ApplicationFacts


class HardshipLetterDoc(DocBase):
    type: Literal["hardship_letter"]
    facts: HardshipLetterFacts


class UtilityBillDoc(DocBase):
    type: Literal["expense_bill"]
    facts: UtilityBillFacts


Document = Annotated[
    PayStubDoc
    | BankStatementDoc
    | W2Doc
    | Form1040Doc
    | CreditReportDoc
    | MortgageStatementDoc
    | ApplicationDoc
    | HardshipLetterDoc
    | UtilityBillDoc,
    Field(discriminator="type"),
]


class Scenario(Model):
    scenario_id: str
    schema_version: int
    version: str
    label: Literal["illustrative", "authoritative"]
    borrower: Borrower
    loan_scenario: LoanScenario | None = None
    loan_record: LoanRecord | None = None
    documents: list[Document]
    # The documented results (Feature Design worked examples). Never rendered; golden-test values.
    expected: dict[str, Any]
    defects: list[dict[str, Any]]
    provenance: dict[str, Any]

    def document(self, doc_id: str) -> Document:
        for doc in self.documents:
            if doc.id == doc_id:
                return doc
        raise KeyError(doc_id)


def _no_floats(text: str) -> float:
    raise ValueError(f"floats are not allowed in scenario files (got {text}); use a string")


def load_scenario(source: str | Path) -> Scenario:
    """Load by name (``daniel_reyes``) or path. Floats anywhere in the file are rejected."""
    path = Path(source)
    if not path.suffix:
        path = SCENARIO_DIR / f"{source}.json"
    raw = json.loads(path.read_text(encoding="utf-8"), parse_float=_no_floats)
    return Scenario.model_validate(raw)


def scenario_names() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


# --- helpers shared by the renderers and the tests ---------------------------------------


def money_text(value: Decimal) -> str:
    """2033.61 -> '2,033.61'; negatives keep a leading minus: '-1,425.00'."""
    return f"{value:,.2f}"


def statement_pages(facts: BankStatementFacts) -> list[list[Transaction]]:
    """Split the transactions over the printed pages, including any page that is not rendered."""
    pages: list[list[Transaction]] = []
    rest = list(facts.transactions)
    take = facts.first_page_rows
    while rest:
        pages.append(rest[:take])
        rest = rest[take:]
        take = facts.other_page_rows
    return pages


def running_balances(facts: BankStatementFacts) -> list[Decimal]:
    balance = facts.opening_balance
    out = []
    for txn in facts.transactions:
        balance += txn.amount
        out.append(balance)
    return out
