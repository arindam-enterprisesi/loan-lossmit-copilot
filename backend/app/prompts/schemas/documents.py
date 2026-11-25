"""Field schemas per document type (Feature Design 1.3, "Document types and what is read").

One model per extractable type. Hardship letters are classified only here (read
by hardship@1 in Feature 7), so they have no field schema. The credit report's
fields feed the code in Feature 4 (scores, tradelines, inquiries).

Every value is copied exactly as printed (``"2,083.61"``, ``"09/14/2026"``); code
normalises amounts and dates, cuts account numbers to the last four digits and
runs the arithmetic checks. A repeating group (earnings lines, transactions) is a
list with one entry per printed row.

No ``from __future__ import annotations`` here: the ``Annotated`` metadata must be
real objects so the field list can read it.
"""

from typing import Annotated

from app.prompts.schemas.fields import Describe, ExtractedField, Schema

# --- pay stub --------------------------------------------------------------------------------


class EarningsLine(Schema):
    description: Annotated[
        ExtractedField, Describe("The earnings type as printed, e.g. Regular, Overtime, Bonus.")
    ]
    hours: Annotated[ExtractedField, Describe("Hours for the current period, if printed.")]
    rate: Annotated[ExtractedField, Describe("Hourly rate, if printed.")]
    current: Annotated[ExtractedField, Describe("Amount for the current period.")]
    ytd: Annotated[ExtractedField, Describe("Year-to-date amount.")]


class DeductionLine(Schema):
    description: Annotated[
        ExtractedField, Describe("The deduction as printed, e.g. Federal income tax, 401(k).")
    ]
    current: Annotated[ExtractedField, Describe("Amount for the current period.")]
    ytd: Annotated[ExtractedField, Describe("Year-to-date amount.")]


class PayStubFields(Schema):
    employer_name: Annotated[ExtractedField, Describe("The employer's name.")]
    employee_name: Annotated[ExtractedField, Describe("The employee's name.")]
    pay_frequency: Annotated[
        ExtractedField, Describe("Pay frequency as printed, e.g. Weekly, Biweekly, Semi-monthly.")
    ]
    pay_period_start: Annotated[ExtractedField, Describe("First day of the pay period.")]
    pay_period_end: Annotated[ExtractedField, Describe("Last day of the pay period.")]
    pay_date: Annotated[ExtractedField, Describe("The pay date or check date.")]
    earnings: Annotated[list[EarningsLine], Describe("Every earnings line in the earnings table.")]
    deductions: Annotated[
        list[DeductionLine], Describe("Every deduction line in the deductions table.")
    ]
    gross_pay_current: Annotated[ExtractedField, Describe("Gross pay for the current period.")]
    gross_pay_ytd: Annotated[ExtractedField, Describe("Gross pay year to date.")]
    total_deductions_current: Annotated[
        ExtractedField, Describe("Total deductions for the current period, as printed.")
    ]
    total_deductions_ytd: Annotated[
        ExtractedField, Describe("Total deductions year to date, as printed.")
    ]
    net_pay_current: Annotated[ExtractedField, Describe("Net pay for the current period.")]
    net_pay_ytd: Annotated[ExtractedField, Describe("Net pay year to date.")]


# --- bank statement --------------------------------------------------------------------------


class Transaction(Schema):
    date: Annotated[ExtractedField, Describe("The transaction date as printed.")]
    description: Annotated[ExtractedField, Describe("The description exactly as printed.")]
    amount: Annotated[
        ExtractedField,
        Describe(
            "The amount exactly as printed, keeping any minus sign, parentheses or CR/DR marker."
        ),
    ]
    column: Annotated[
        ExtractedField,
        Describe(
            "Only when the statement has separate deposit and withdrawal columns: the heading "
            "of the column the amount is printed in. Null when there is one amount column."
        ),
    ]
    balance: Annotated[ExtractedField, Describe("The running balance after it, if printed.")]


class BankStatementFields(Schema):
    institution: Annotated[ExtractedField, Describe("The bank or credit union name.")]
    account_holder: Annotated[ExtractedField, Describe("The account holder name(s).")]
    account_number: Annotated[
        ExtractedField,
        Describe("The account number as printed, usually masked (e.g. 'ending 6032')."),
    ]
    statement_period_start: Annotated[ExtractedField, Describe("First day of the period.")]
    statement_period_end: Annotated[ExtractedField, Describe("Last day of the period.")]
    opening_balance: Annotated[ExtractedField, Describe("Opening or beginning balance.")]
    closing_balance: Annotated[ExtractedField, Describe("Closing or ending balance.")]
    total_deposits: Annotated[
        ExtractedField, Describe("Printed total of deposits and credits, if shown.")
    ]
    total_withdrawals: Annotated[
        ExtractedField, Describe("Printed total of withdrawals and debits, if shown.")
    ]
    transactions: Annotated[
        list[Transaction], Describe("Every transaction row, on every page, in order.")
    ]


# --- tax forms -------------------------------------------------------------------------------


class TaxReturn1040Fields(Schema):
    tax_year: Annotated[ExtractedField, Describe("The tax year of the return.")]
    taxpayer_names: Annotated[
        ExtractedField, Describe("Taxpayer name, and spouse name on a joint return.")
    ]
    filing_status: Annotated[ExtractedField, Describe("The filing status that is checked.")]
    wages: Annotated[ExtractedField, Describe("Wages, salaries and tips (line 1z or line 1).")]
    total_income: Annotated[ExtractedField, Describe("Total income (line 9).")]
    adjusted_gross_income: Annotated[ExtractedField, Describe("Adjusted gross income (line 11).")]


class Box12Entry(Schema):
    code: Annotated[ExtractedField, Describe("The Box 12 letter code, e.g. D, DD, W.")]
    amount: Annotated[ExtractedField, Describe("The amount next to that code.")]


class W2Fields(Schema):
    tax_year: Annotated[ExtractedField, Describe("The tax year of the form.")]
    employer_name: Annotated[ExtractedField, Describe("The employer's name (box c).")]
    employee_name: Annotated[ExtractedField, Describe("The employee's name (box e).")]
    box1_wages: Annotated[ExtractedField, Describe("Box 1, wages, tips, other compensation.")]
    box2_federal_tax_withheld: Annotated[
        ExtractedField, Describe("Box 2, federal income tax withheld.")
    ]
    box3_social_security_wages: Annotated[ExtractedField, Describe("Box 3.")]
    box4_social_security_tax: Annotated[ExtractedField, Describe("Box 4.")]
    box5_medicare_wages: Annotated[ExtractedField, Describe("Box 5.")]
    box6_medicare_tax: Annotated[ExtractedField, Describe("Box 6.")]
    box12: Annotated[list[Box12Entry], Describe("Every Box 12 code and amount.")]


# --- loss mitigation documents ---------------------------------------------------------------


class AmountLine(Schema):
    description: Annotated[ExtractedField, Describe("The label printed for this row.")]
    amount: Annotated[ExtractedField, Describe("The amount on this row.")]


class HardshipReason(Schema):
    reason: Annotated[ExtractedField, Describe("A hardship reason that is checked or written.")]


class MortgageAssistanceApplicationFields(Schema):
    borrower_names: Annotated[ExtractedField, Describe("Borrower and co-borrower names.")]
    loan_number: Annotated[ExtractedField, Describe("The loan or account number as printed.")]
    property_address: Annotated[ExtractedField, Describe("The property address.")]
    occupancy: Annotated[ExtractedField, Describe("How the property is occupied, as stated.")]
    hardship_reasons: Annotated[
        list[HardshipReason],
        Describe("Only the reasons the borrower checked or wrote, not unchecked options."),
    ]
    intent: Annotated[
        ExtractedField, Describe("What the borrower wants to do with the home, as stated.")
    ]
    monthly_income: Annotated[
        list[AmountLine], Describe("Each stated monthly income line (gross wages, other).")
    ]
    monthly_expenses: Annotated[list[AmountLine], Describe("Each stated monthly expense line.")]
    total_monthly_expenses: Annotated[
        ExtractedField, Describe("The printed total of monthly expenses, if shown.")
    ]
    assets: Annotated[list[AmountLine], Describe("Each stated asset and its value.")]
    signed_date: Annotated[ExtractedField, Describe("The date next to the signature.")]


class MortgageStatementFields(Schema):
    servicer: Annotated[ExtractedField, Describe("The loan servicer's name.")]
    borrower_names: Annotated[ExtractedField, Describe("The borrower name(s).")]
    loan_number: Annotated[ExtractedField, Describe("The loan number as printed.")]
    statement_date: Annotated[ExtractedField, Describe("The statement date.")]
    payment_due_date: Annotated[ExtractedField, Describe("The payment due date.")]
    unpaid_principal_balance: Annotated[
        ExtractedField, Describe("Unpaid or outstanding principal balance.")
    ]
    interest_rate: Annotated[ExtractedField, Describe("The interest rate as printed.")]
    principal_and_interest: Annotated[
        ExtractedField, Describe("The principal and interest part of the monthly payment.")
    ]
    escrow: Annotated[ExtractedField, Describe("The escrow part of the monthly payment.")]
    regular_monthly_payment: Annotated[
        ExtractedField, Describe("The regular monthly payment amount.")
    ]
    past_due_amount: Annotated[ExtractedField, Describe("The past-due or overdue amount.")]
    fees: Annotated[ExtractedField, Describe("Late charges and fees, as printed.")]
    total_amount_due: Annotated[ExtractedField, Describe("The total amount due.")]


class BenefitsLetterFields(Schema):
    issuer: Annotated[ExtractedField, Describe("The agency or plan that issued the letter.")]
    payee: Annotated[ExtractedField, Describe("The person receiving the benefit.")]
    benefit_type: Annotated[
        ExtractedField, Describe("The kind of benefit, e.g. unemployment, pension.")
    ]
    amount: Annotated[ExtractedField, Describe("The benefit amount per payment.")]
    frequency: Annotated[ExtractedField, Describe("How often it is paid, as stated.")]
    start_date: Annotated[ExtractedField, Describe("When payments start or started.")]
    end_date: Annotated[ExtractedField, Describe("When payments end, if stated.")]
    letter_date: Annotated[ExtractedField, Describe("The date of the letter.")]


class ExpenseBillFields(Schema):
    payee: Annotated[ExtractedField, Describe("The company or provider the bill is from.")]
    customer: Annotated[ExtractedField, Describe("The customer or account holder name.")]
    expense_type: Annotated[
        ExtractedField, Describe("What the bill is for, e.g. electricity, insurance.")
    ]
    amount_due: Annotated[ExtractedField, Describe("The amount due.")]
    frequency: Annotated[ExtractedField, Describe("The billing frequency, if stated.")]
    billing_period_start: Annotated[ExtractedField, Describe("First day of the billing period.")]
    billing_period_end: Annotated[ExtractedField, Describe("Last day of the billing period.")]
    statement_date: Annotated[ExtractedField, Describe("The bill or statement date.")]
    due_date: Annotated[ExtractedField, Describe("The payment due date.")]


# --- credit report (Feature Design 4.3) -------------------------------------------------------


class CreditScore(Schema):
    bureau: Annotated[ExtractedField, Describe("The bureau or score name as printed.")]
    value: Annotated[ExtractedField, Describe("The score as printed.")]


class Tradeline(Schema):
    creditor: Annotated[ExtractedField, Describe("The creditor or account name.")]
    account_type: Annotated[
        ExtractedField, Describe("Revolving, installment, mortgage or open, as printed.")
    ]
    ownership: Annotated[ExtractedField, Describe("Individual, joint or authorized user.")]
    open_date: Annotated[ExtractedField, Describe("The date the account was opened.")]
    status: Annotated[ExtractedField, Describe("The account status, e.g. open or closed.")]
    balance: Annotated[ExtractedField, Describe("The current balance.")]
    credit_limit: Annotated[
        ExtractedField, Describe("The credit limit or high credit; null when printed as n/a.")
    ]
    monthly_payment: Annotated[ExtractedField, Describe("The scheduled monthly payment.")]
    past_due: Annotated[ExtractedField, Describe("The past-due amount.")]
    late_30: Annotated[ExtractedField, Describe("The count of 30-day late payments.")]
    late_60: Annotated[ExtractedField, Describe("The count of 60-day late payments.")]
    late_90: Annotated[ExtractedField, Describe("The count of 90-day late payments.")]
    most_recent_late: Annotated[
        ExtractedField, Describe("The date of the most recent late payment; null when none.")
    ]
    remarks: Annotated[ExtractedField, Describe("Remarks printed for the account; null if none.")]


class Inquiry(Schema):
    creditor: Annotated[ExtractedField, Describe("Who made the inquiry.")]
    date: Annotated[ExtractedField, Describe("The inquiry date.")]


class CreditReportFields(Schema):
    consumer_name: Annotated[ExtractedField, Describe("The consumer's name.")]
    report_date: Annotated[ExtractedField, Describe("The date of the report.")]
    alerts: Annotated[
        ExtractedField,
        Describe("Fraud alerts, freezes or consumer statements as printed; null if none."),
    ]
    scores: Annotated[list[CreditScore], Describe("Every credit score printed, one per bureau.")]
    tradelines: Annotated[list[Tradeline], Describe("Every trade account, in printed order.")]
    inquiries: Annotated[list[Inquiry], Describe("Every inquiry listed.")]
