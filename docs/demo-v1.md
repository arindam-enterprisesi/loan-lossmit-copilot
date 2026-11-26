# Demo script, v1.0 (about 20 minutes)

Two stories, both pillars, real model calls. Everything shown is synthetic data.

## Before the demo (15 minutes ahead)

```bash
docker compose up -d --build          # api :8000, worker, postgres, redis
make migrate
make data
make reset-demo ARGS="--upload"       # reads every document with Claude (about 3 minutes)
cd frontend && npm run dev            # http://localhost:3000 (NEXT_PUBLIC_USE_MOCKS=false in .env.local)
```

Fallbacks: if no model provider works, use `ARGS="--upload --fake-reader"` (rule-based reader, same
figures, no agents). If S3 is down, `ARGS=` seeds the cases and the sample reports without documents.
Check `uv run python -m app.llm.smoke --provider anthropic` passes first.

Log in as `underwriter` (Daniel) and `lm_specialist` (Angela), password `DEMO_PASSWORD` (default `demo`).

## 1. Daniel Reyes, purchase (underwriter, 10 minutes)

1. **Documents.** Seven documents, each classified and read with line citations. Open the pay stub:
   printed net pay 2,083.61 is flagged `DI-CHK-02`, because gross 3,070.50 less deductions 1,036.89 is
   2,033.61. Open the August statement: "Page 1 of 3" with two pages received (`DI-W701`).
   *Say:* the model copies what is printed; code does the arithmetic and raises the flag.
2. **Income.** Base pay 5,980.00 a month with its working (34.50 × 80.00 × 26 / 12). Overtime 444.41
   and bonus 228.34 are excluded: 2026 is the only year documented. The W-2 Box 5 vs Box 1 gap
   carries a possible explanation citing Box 12 code D, labelled "possible — to be confirmed".
3. **Completeness.** Incomplete: pay stubs 14 of 30 days, the 2024 W-2 and return missing, a page
   missing.
4. **Assets, liabilities, credit.** Documented assets 9,226.32 against 36,500.00 to close: shortfall
   27,273.68. The 2,000.00 transfer on 2026-09-22 has no source. Debts 693.00 (the Harbor Retail card
   comes from the credit report); DTI 44.70%, or 41.61% with overtime. Score 705; Northgate Card
   utilization 36.75%.
5. **Guideline assistant.** Ask "How is overtime income evaluated?" with the case attached: Fannie
   Mae and Freddie Mac side by side, plus the lender overlay. Click a citation to open the passage
   and its "illustrative" label. Ask about jumbo loans: "no supporting passage found", and no model
   call was made.
6. **Underwriting copilot.** Run it (about a minute): watch Researcher, Writer and Critic. The
   report shows the DTI conflict openly (44.70% vs 41.61%), findings by priority each with evidence,
   and suggested conditions. Show the guardrails: what the Critic returned, and what code removed.
7. **Review.** Accept five conditions, reject one with "not required for this file", sign off.
   *Say:* the sign-off records a review. It is not a decision.

## 2. Angela Whitfield, hardship (loss mitigation specialist, 8 minutes)

1. **Hardship letter.** Reduction in income from July 2026, duration unknown, intent keep. Every
   quote is verified against the letter's lines; confirm duration and intent.
2. **Budget.** Income 4,200.00; deficits 70.00 stated and 280.00 observed; housing ratio 40.95%;
   arrears 5,160.00. The two lines where stated and observed differ are flagged.
3. **Recommendation.** Run it: the rules (in code) mark loan modification's conditions met, each
   condition with its values and cited passage; the lender view shows foreclosure loss 16,310.00
   against modification cost 13,893.00, a 2,417.00 difference, with working. The agents' report adds
   the borrower's situation, compliance points citing 12 CFR 1024.41(b) with the facts to check, and
   the items for human review. Final terms read "to be calculated under the investor's own method".
4. **Override and sign off.** Override one condition with a reason (the rules' status stays beside
   it), then sign off.

## 3. Under the hood (2 minutes)

- `backend/config/llm.yaml`: switch the agents from Claude API to Bedrock and re-run one agent.
- `docs/provider-evaluation.md`: the same checks on both providers.
- `GET /cases/{id}/audit`: every action, upload to sign-off, including each question to the assistant.

## Words to avoid

Never say approve, deny, offer, eligible or qualifies. Say "conditions met", "for the underwriter's
review", "a person decides".
