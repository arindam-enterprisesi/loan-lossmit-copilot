"""Read a hardship letter into a profile, then check every quote in code (Feature Design 7.5).

    outcome = await read_hardship_letter(letter_lines, application_reasons=["Reduction in income"])
    outcome.profile.primary_reason.category   # "reduction_in_income"
    outcome.all_quotes_verified               # every quote found in its cited lines

The profile is what the borrower says, not a judgement. A person confirms or
corrects the reasons, onset, duration and intent before Feature 8 uses them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.llm.checks import QuoteCheck, iter_quoted, verify_quotes
from app.llm.gateway import Gateway, GatewayResult, get_gateway
from app.llm.tasks import DocumentLine, clean_text, format_numbered_lines
from app.prompts.schemas.hardship import (
    HardshipConfig,
    HardshipProfile,
    hardship_profile_model,
    load_hardship_config,
)


@dataclass(frozen=True)
class HardshipOutcome:
    profile: HardshipProfile
    call: GatewayResult[HardshipProfile]
    quote_checks: list[QuoteCheck]
    # Cited line IDs that are not in the letter; their items also fail the quote check.
    unknown_line_ids: list[str]
    config_version: str

    @property
    def all_quotes_verified(self) -> bool:
        return all(check.verified for check in self.quote_checks)

    @property
    def flagged(self) -> list[QuoteCheck]:
        return [check for check in self.quote_checks if not check.verified]


def describe_categories(config: HardshipConfig) -> str:
    return "\n".join(
        f"- {c.key}: {c.label}{' (sensitive)' if c.sensitive else ''}" for c in config.categories
    )


async def read_hardship_letter(
    letter_lines: Sequence[DocumentLine],
    *,
    application_reasons: Sequence[str] = (),
    config: HardshipConfig | None = None,
    provider: str | None = None,
    gateway: Gateway | None = None,
) -> HardshipOutcome:
    """One hardship@1 call on the whole letter, then ``verify_quotes`` on the result.

    ``application_reasons`` are the reasons ticked on the application, as extracted.
    """
    settings = config or load_hardship_config()
    output_model = hardship_profile_model(settings.keys)
    reasons = "\n".join(f"- {clean_text(r)}" for r in application_reasons) or "(none ticked)"
    call = await (gateway or get_gateway()).run(
        "hardship",
        "hardship@1",
        {
            "max_quote_chars": settings.max_quote_chars,
            "categories": describe_categories(settings),
            "application_reasons": reasons,
            "numbered_lines": format_numbered_lines(letter_lines),
        },
        output_model,
        provider=provider,
    )
    profile = call.output
    known = {ln.line_id for ln in letter_lines}
    cited = [lid for _, item in iter_quoted(profile) for lid in item.lines]
    return HardshipOutcome(
        profile=profile,
        call=call,
        quote_checks=verify_quotes(profile, letter_lines, max_quote_chars=settings.max_quote_chars),
        unknown_line_ids=list(dict.fromkeys(lid for lid in cited if lid not in known)),
        config_version=settings.version,
    )
