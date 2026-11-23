"""The validation and document-field settings, and every flag message template."""

from __future__ import annotations

import re
import string
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.services.document_config import (
    DEFAULT_FIELDS_PATH,
    DEFAULT_VALIDATION_PATH,
    get_document_fields,
    get_validation_config,
    load_document_fields,
    load_validation_config,
)

RULES = get_validation_config()
CFG = get_document_fields()
SERVICES = Path(__file__).resolve().parents[2] / "app" / "services"
BLOCKED = ("approve", "deny", "denied", "offer", "eligible", "qualif")


def test_the_shipped_settings_are_versioned_and_labelled() -> None:
    for config in (RULES, CFG):
        assert config.version and config.label in {"illustrative", "authoritative"}
    assert DEFAULT_VALIDATION_PATH.name == "validation.yaml"
    assert DEFAULT_FIELDS_PATH.name == "document_fields.yaml"
    assert RULES.arithmetic_tolerance == Decimal("0.01")
    assert RULES.min_line_confidence == Decimal("0.80")


def _written(tmp_path: Path, name: str, data: dict[str, Any]) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _shipped(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "change",
    [
        {"label": "approved"},
        {"arithmetic_tolerance": "0"},
        {"min_line_confidence": "1.5"},
        {"surprise": True},
    ],
)
def test_bad_validation_settings_are_rejected(tmp_path: Path, change: dict[str, Any]) -> None:
    data = {**_shipped(DEFAULT_VALIDATION_PATH), **change}
    with pytest.raises(ValidationError):
        load_validation_config(_written(tmp_path, "v.yaml", data))


def test_validation_settings_must_define_the_cannot_check_message(tmp_path: Path) -> None:
    data = _shipped(DEFAULT_VALIDATION_PATH)
    del data["flags"]["cannot_check"]
    with pytest.raises(ValidationError, match="cannot_check"):
        load_validation_config(_written(tmp_path, "v.yaml", data))


def test_bad_field_settings_are_rejected(tmp_path: Path) -> None:
    data = _shipped(DEFAULT_FIELDS_PATH)
    data["types"]["pay_stub"]["fields"][0]["kind"] = "currency"
    with pytest.raises(ValidationError):
        load_document_fields(_written(tmp_path, "f.yaml", data))


def test_every_flag_code_the_services_use_has_a_message() -> None:
    used: set[str] = set()
    for source in SERVICES.glob("*.py"):
        used |= set(
            re.findall(r"""["'](DI-[A-Z]+-?\d+(?::\w+)?)["']""", source.read_text(encoding="utf-8"))
        )
    assert {"DI-CHK-02", "DI-W701"} <= used
    assert used <= set(RULES.flags), used - set(RULES.flags)


def test_every_template_fills_in_and_uses_no_blocked_word() -> None:
    for code, template in RULES.flags.items():
        names = {f for _, f, _, _ in string.Formatter().parse(template.message) if f}
        filled = template.message.format(**{n: "x" for n in names})
        assert "{" not in filled, code
        assert not any(word in template.message.lower() for word in BLOCKED), code
    for spec in CFG.types.values():
        assert not any(word in (spec.summary or "").lower() for word in BLOCKED)


def test_the_net_pay_message_matches_the_contracts_example() -> None:
    _, message = RULES.flag(
        "DI-CHK-02",
        gross="3,070.50",
        deductions="1,036.89",
        expected="2,033.61",
        printed="2,083.61",
    )
    # contracts/openapi.yaml's Flag example, with a final full stop
    assert message == "Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,083.61."


@pytest.mark.parametrize(
    "code",
    ["DI-CHK-0" + str(n) for n in range(1, 9)] + ["DI-W601", "DI-W604", "DI-W605", "DI-W701"],
)
def test_check_and_warning_messages_are_warnings(code: str) -> None:
    assert RULES.severity(code) == "warning"


def test_failures_are_errors_and_cannot_check_is_info() -> None:
    assert {RULES.severity(c) for c in ("DI-E201", "DI-E301", "DI-E401", "DI-E801")} == {"error"}
    assert RULES.severity("cannot_check") == "info"


def test_pay_stub_and_bank_statement_have_fields_and_roles() -> None:
    assert CFG.has_fields("pay_stub") and CFG.has_fields("bank_statement")
    assert CFG.has_fields("w2") and CFG.has_fields("tax_return_1040")
    # The credit report has no extract schema yet, but its tradeline fields are defined ahead of it
    # (see test_loss_mitigation_fields.py). A type the config does not know has none.
    assert CFG.has_fields("credit_report") and not CFG.has_fields("nonsense")
    assert CFG.role("pay_stub", "net") == "net_pay_current"
    assert CFG.role("bank_statement", "closing") == "closing_balance"
    assert CFG.role("pay_stub", "nope") is None and CFG.role("nonsense", "net") is None
    assert {f.name for f in CFG.required_fields("pay_stub")} >= {
        "net_pay_current",
        "gross_pay_current",
    }


def test_every_role_points_at_a_real_field() -> None:
    for doc_type, spec in CFG.types.items():
        names = {f.name for f in spec.fields}
        for role, name in spec.roles.items():
            assert name in names, (doc_type, role, name)
        for name in spec.period_fields + ([spec.borrower_field] if spec.borrower_field else []):
            assert name in names, (doc_type, name)


def test_every_summary_placeholder_is_a_field() -> None:
    for doc_type, spec in CFG.types.items():
        if spec.summary:
            names = {f.name for f in spec.fields}
            used = {f for _, f, _, _ in string.Formatter().parse(spec.summary) if f}
            assert used <= names, (doc_type, used - names)


def test_field_kinds_come_from_the_list_the_transactions_and_the_earnings_pattern() -> None:
    assert CFG.kind_of("pay_stub", "net_pay_current") == "amount"
    assert CFG.kind_of("pay_stub", "pay_period_start") == "date"
    assert CFG.kind_of("pay_stub", "account_last4") == "id_last4"
    assert CFG.kind_of("pay_stub", "earnings_holiday_current") == "amount"  # a new earnings line
    assert CFG.kind_of("bank_statement", "txn_007_date") == "date"
    assert CFG.kind_of("bank_statement", "txn_007_description") == "text"
    assert CFG.kind_of("bank_statement", "txn_007_amount") == "amount"
    assert CFG.kind_of("bank_statement", "txn_007_balance") == "amount"
    assert CFG.kind_of("pay_stub", "something_else") == "text"


def test_transaction_field_names_round_trip() -> None:
    assert CFG.transaction_field("bank_statement", 7, "amount") == "txn_007_amount"
    assert CFG.transaction_match("bank_statement", "txn_007_amount") == ("007", "amount")
    assert CFG.transaction_match("bank_statement", "opening_balance") is None
    assert CFG.transaction_match("pay_stub", "txn_007_amount") is None
    assert CFG.transaction_field("pay_stub", 1, "amount") is None


def test_labels_for_messages() -> None:
    assert CFG.field_label("pay_stub", "net_pay_current") == "Net pay"
    assert CFG.field_label("bank_statement", "txn_003_amount") == "Transaction 3 amount"
    assert CFG.type_label("bank_statement") == "bank statement"
    assert CFG.type_label("tax_return_1040") == "tax return (Form 1040)"
    assert CFG.type_label("something_new") == "something new"


def test_earnings_fields_need_a_kind_between_the_prefix_and_suffix() -> None:
    assert CFG.is_earnings_field("pay_stub", "earnings_bonus_current")
    assert not CFG.is_earnings_field("pay_stub", "earnings__current")
    assert not CFG.is_earnings_field("pay_stub", "gross_pay_current")
    assert not CFG.is_earnings_field("bank_statement", "earnings_bonus_current")


# --- repeating rows, renamed fields and column signs (the real reader's shapes) -------------------


def test_row_columns_have_their_own_kinds() -> None:
    assert CFG.kind_of("pay_stub", "earnings_001_hours") == "number"
    assert CFG.kind_of("pay_stub", "earnings_002_rate") == "number"
    assert CFG.kind_of("pay_stub", "earnings_001_current") == "amount"
    assert CFG.kind_of("pay_stub", "earnings_001_ytd") == "amount"
    assert CFG.kind_of("pay_stub", "earnings_001_description") == "text"
    assert CFG.kind_of("pay_stub", "deduction_003_current") == "amount"
    assert CFG.kind_of("w2", "box12_001_amount") == "amount"
    assert CFG.kind_of("w2", "box12_001_code") == "text"
    assert CFG.kind_of("bank_statement", "txn_004_column") == "text"


def test_row_match_gives_the_row_its_index_and_part() -> None:
    row, index, part = CFG.row_match("pay_stub", "earnings_012_hours") or (None, 0, "")
    assert row is not None and (row.source, index, part) == ("earnings", 12, "hours")
    assert row.field_name(12, "hours") == "earnings_012_hours"
    assert CFG.row_match("pay_stub", "earnings_regular_current") is None  # the fake's name
    assert CFG.row_match("pay_stub", "earnings_001_nonsense") is None
    assert CFG.row_match("credit_report", "earnings_001_hours") is None


def test_renames_map_the_extract_schemas_names_to_ours() -> None:
    assert CFG.rename("bank_statement", "institution") == "institution_name"
    assert CFG.rename("bank_statement", "account_number") == "account_last4"
    assert CFG.rename("bank_statement", "closing_balance") == "closing_balance"
    assert CFG.rename("nonsense", "institution") == "institution"


def test_only_the_amount_of_a_signed_column_row_is_column_signed() -> None:
    assert CFG.is_column_signed("bank_statement", "txn_001_amount")
    assert not CFG.is_column_signed("bank_statement", "txn_001_balance")
    assert not CFG.is_column_signed("pay_stub", "earnings_001_current")
    assert not CFG.is_column_signed("bank_statement", "closing_balance")


@pytest.mark.parametrize(
    ("heading", "sign"),
    [
        ("Withdrawals", "-"),
        ("Withdrawals and debits", "-"),
        ("DEBIT", "-"),
        ("Deposits", "+"),
        ("Deposits and credits", "+"),
        ("Memo", None),
        (None, None),
        ("", None),
    ],
)
def test_a_column_heading_decides_the_sign(heading: str | None, sign: str | None) -> None:
    assert CFG.sign_for_column("bank_statement", heading) == sign
    assert CFG.sign_for_column("pay_stub", heading) is None  # no column signs for this type


def test_a_row_may_not_name_an_unknown_kind() -> None:
    text = DEFAULT_FIELDS_PATH.read_text(encoding="utf-8").replace("hours: number", "hours: money")
    with pytest.raises(ValidationError):
        load_document_fields(_write(text))


def _write(text: str) -> Path:
    import tempfile

    path = Path(tempfile.mkdtemp()) / "document_fields.yaml"
    path.write_text(text, encoding="utf-8")
    return path
