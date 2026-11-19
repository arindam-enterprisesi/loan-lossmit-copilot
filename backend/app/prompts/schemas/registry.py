"""Schema Registry (CPS-03): one entry per document type.

Each type has a one-paragraph description that the classify prompt shows the
model, and the field schema extract@1 reads (``None`` for types that are only
classified here: credit reports and hardship letters are analysed in Features 4
and 7). Adding a type means adding it here. The type names must match
``DocumentType`` in contracts/openapi.yaml; a test checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.prompts.schemas import documents as d
from app.prompts.schemas.fields import Schema


class DocumentType(StrEnum):
    PAY_STUB = "pay_stub"
    BANK_STATEMENT = "bank_statement"
    TAX_RETURN_1040 = "tax_return_1040"
    W2 = "w2"
    CREDIT_REPORT = "credit_report"
    MORTGAGE_ASSISTANCE_APPLICATION = "mortgage_assistance_application"
    MORTGAGE_STATEMENT = "mortgage_statement"
    BENEFITS_LETTER = "benefits_letter"
    EXPENSE_BILL = "expense_bill"
    HARDSHIP_LETTER = "hardship_letter"
    UNRECOGNIZED = "unrecognized"


@dataclass(frozen=True)
class DocumentTypeSpec:
    doc_type: DocumentType
    label: str
    pillars: tuple[int, ...]
    description: str
    fields_model: type[Schema] | None


REGISTRY: dict[DocumentType, DocumentTypeSpec] = {
    spec.doc_type: spec
    for spec in [
        DocumentTypeSpec(
            DocumentType.PAY_STUB,
            "Pay stub",
            (1, 2),
            "An employer's earnings statement for one pay period: employer and employee names, "
            "pay period and pay date, earnings lines (regular, overtime, bonus) with hours and "
            "rates, deductions (taxes, benefits, retirement), gross pay, net pay and "
            "year-to-date totals.",
            d.PayStubFields,
        ),
        DocumentTypeSpec(
            DocumentType.BANK_STATEMENT,
            "Bank statement",
            (1, 2),
            "A statement from a bank or credit union for one account and period: institution "
            "name, account holder, masked account number, statement period, opening and closing "
            "balances, and a list of dated deposits and withdrawals.",
            d.BankStatementFields,
        ),
        DocumentTypeSpec(
            DocumentType.TAX_RETURN_1040,
            "Tax return (Form 1040)",
            (1, 2),
            "A US individual income tax return on IRS Form 1040 for one tax year: filing status, "
            "taxpayer names, wages, total income, adjusted gross income, and numbered form lines.",
            d.TaxReturn1040Fields,
        ),
        DocumentTypeSpec(
            DocumentType.W2,
            "W-2",
            (1,),
            "An IRS Form W-2 Wage and Tax Statement for one tax year: employer and employee, "
            "numbered boxes 1 to 6 for wages and withheld taxes, and Box 12 codes.",
            d.W2Fields,
        ),
        DocumentTypeSpec(
            DocumentType.CREDIT_REPORT,
            "Credit report",
            (1,),
            "A consumer credit report: personal identification, credit scores, a list of "
            "trade accounts with creditor, balance, payment and status history, inquiries and "
            "public records.",
            None,
        ),
        DocumentTypeSpec(
            DocumentType.MORTGAGE_ASSISTANCE_APPLICATION,
            "Mortgage assistance application",
            (2,),
            "A servicer's mortgage assistance or loss mitigation application form completed by a "
            "borrower: stated monthly income, expenses and assets, hardship reasons checked, and "
            "whether the borrower intends to keep or sell the property.",
            d.MortgageAssistanceApplicationFields,
        ),
        DocumentTypeSpec(
            DocumentType.MORTGAGE_STATEMENT,
            "Mortgage statement",
            (2,),
            "A periodic mortgage billing statement from a loan servicer: loan number, principal "
            "balance, payment breakdown (principal, interest, escrow), past-due amount, fees and "
            "total amount due.",
            d.MortgageStatementFields,
        ),
        DocumentTypeSpec(
            DocumentType.BENEFITS_LETTER,
            "Benefits letter",
            (2,),
            "A letter from an agency or plan confirming benefit payments, such as unemployment, "
            "Social Security, disability or pension: payee, amount, frequency and start or end "
            "dates.",
            d.BenefitsLetterFields,
        ),
        DocumentTypeSpec(
            DocumentType.EXPENSE_BILL,
            "Expense bill",
            (2,),
            "A bill or invoice for a household expense such as a utility, insurance premium, "
            "medical or childcare cost: payee, amount due, billing period and due date.",
            d.ExpenseBillFields,
        ),
        DocumentTypeSpec(
            DocumentType.HARDSHIP_LETTER,
            "Hardship letter",
            (2,),
            "A letter written by a borrower to their mortgage servicer explaining a financial "
            "hardship: what happened, when it started, how it affects their ability to pay, and "
            "what they hope to do with the home.",
            None,
        ),
    ]
}


def describe_types() -> str:
    """The type list shown to the classify prompt, one bullet per registered type."""
    return "\n".join(f"- {spec.doc_type.value}: {spec.description}" for spec in REGISTRY.values())
