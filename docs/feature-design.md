# AI Mortgage Copilot — Feature Design (2)

_Converted from PDF (48 pages). Source: Copilots/Specs/AI Mortgage Copilot — Feature Design (2).pdf_

<!-- page 1 -->
AI Mortgage Copilot — Feature Design
Nov 2, 2026 · ​@Abhay B Suvarna
About the project
The AI Mortgage Copilot is a demo prototype that shows how LLMs, retrieval-augmented
generation (RAG) and multi-agent workflows can help US mortgage professionals. It is not
a mortgage platform. It has no borrower onboarding, no real credit bureau or bank
connections and no production systems, and it uses synthetic borrowers and documents
throughout.
It covers two areas:
Loan processing and underwriting (Pillar 1). For a borrower applying for a new loan,
the copilot reads their documents, analyzes income, assets, debts and credit, answers
guideline questions and drafts an underwriting analysis for the underwriter.
Loss mitigation (Pillar 2). For a borrower who has fallen behind on an existing loan, it
reads the hardship application, assesses their finances, checks the options against
investor rules and Regulation X, and drafts a recommendation and letters for the
servicer. Loss mitigation mainly protects the lender and the investor, so the report
shows the lender's view first.
Four rules apply throughout. Code, not the AI, does all arithmetic. Every finding links to its
evidence. People make every decision, and the system never approves, denies or offers
anything. And no mortgage rule or threshold is invented: every setting is configuration,
labelled illustrative unless it has a stated source.
It is built with a Next.js web app, one FastAPI backend, the Gemini API, Google Document
AI, LangGraph, ChromaDB or FAISS, and PostgreSQL.
How this document is organized
Every feature follows the same eight parts: overview, user interaction, input
requirements, workflow diagram, LLM inference, services used, API and connectors, and
output. Nine features follow, then shared pages on the agents, backend services, demo
data and storage, and security.
AI Mortgage Copilot — Feature Design
Page 1 of 48

<!-- page 2 -->
1. Document Intelligence
Turns uploaded borrower documents into checked, structured data with a link from every
value back to its place on the page. It works out what each document is, reads it,
summarizes it and shows what is missing from the case. Both pillars use it.
1.1 Feature overview
1.2 User interaction
1. Upload. The user drops in files. The document type is set to Auto-detect, or picked by
hand.
2. Confirm only if needed. If the AI is unsure of a type, or strongly disagrees with the
type the user picked, a small dialog asks which is right. Otherwise nothing is asked.
3. Review. The document opens beside its extracted fields. Flagged fields come first, and
clicking a field highlights its place on the page. The user confirms or corrects each one,
and the original value is always kept.
4. Case overview. One table lists every document with its type, owner, period and flags,
plus a summary for each.
What it does
Reads documents with OCR and an LLM; classifies
and extracts them; checks the result in Python;
compares the case with a required-document
checklist
What it shows off
OCR plus an LLM reading messy documents; every
value traceable to the page; plain Python catching
errors the AI missed
Users
Loan processor or underwriter (Pillar 1); loss
mitigation specialist (Pillar 2)
Replaces
Document intelligence, document understanding
and completeness analysis in the original plan, plus
the loss mitigation document step
Not included
Fraud or authenticity checks; splitting one file that
holds several documents; handwriting
AI Mortgage Copilot — Feature Design
Page 2 of 48

<!-- page 3 -->
5. Completeness. The user enters the borrower names and picks a checklist. The screen
shows what is satisfied, partial or missing, with the reason. The user can override an
item with a written reason, or copy the list of outstanding items.
1.3 Input requirements
Files. PDF, PNG or JPEG. All documents are synthetic samples.
Document types and what is read from them.
For the completeness check. Borrower names, an employment type, a reference date,
and a checklist. The checklists are configuration. The demo versions are illustrative
samples: pay stubs covering 30 days, W-2s and tax returns for two years, bank statements
covering two months, a credit report. Real requirements must come from the lender or
program.
Pillar
Document
Key fields
1 and
2
Pay stub
Employer, pay period, pay date, earnings lines,
deductions, gross and net pay, year to date
1 and
2
Bank statement
Account holder, institution, last four digits,
period, balances, every transaction
1 and
2
Tax return (Form 1040)
Tax year, filing status, wages, total income,
adjusted gross income
1
W-2
Tax year, employer, boxes 1 to 6, Box 12 codes
1
Credit report (sample)
Classified here; analyzed in Feature 4
2
Mortgage assistance
application
Stated income, expenses, assets, hardship
reasons, intent
2
Mortgage statement
Balance, payment parts, past due amount, total
due
2
Benefits letter, expense bill
Amount, frequency, dates, payee
2
Hardship letter
Classified here; analyzed in Feature 7
AI Mortgage Copilot — Feature Design
Page 3 of 48

<!-- page 4 -->
1.4 Workflow diagram
Steps 4 to 7 are the only AI calls, and every step marked as a loop on the backend is plain
Python. Step 11 re-runs whenever a document is added or a value is corrected, with no
new AI call for documents that have not changed.
1.5 LLM inference
Three AI calls, and no others in this feature.
Document Intelligence flow · sequence, 12 steps
AI Mortgage Copilot — Feature Design
Page 4 of 48

<!-- page 5 -->
An abridged extraction result:
{"fields": {"net_pay_current": {"value": "2,083.61", "lines": ["p1-L31"], 
"certainty": "medium"}}, "signals": []}
Checked in code, never by the AI.
Every value really appears in the line it cites.
Amounts and dates are converted to standard forms, and Social Security and account
numbers are cut to their last four digits.
Arithmetic: earnings add up to gross pay, gross minus deductions equals net pay, bank
balances reconcile with the transactions, dates are in order.
Printed page counts ("Page 1 of 3") against the pages uploaded.
Matching names to borrowers, merging date ranges, and measuring coverage, recency
and missing tax years against the checklist.
Call
Input
Output
Note
Classify
Numbered lines of the
first pages, plus a short
description of each
document type
The type (or
"Unrecognized"), a
certainty rating, and the
lines that justify it
The type is applied
automatically only
when certain;
otherwise the user is
asked. File names are
never sent
Extract
The type's field list,
plus the numbered
lines of every page
Each field's value, the line
IDs it came from and a
certainty rating; also any
signs the document is
incomplete, such as a
"continued" notice or a
cut-off table
One call per document.
Long statements are
split by pages and
merged in code
Describe
The first pages of an
unrecognized
document
A one-line description
Only for unrecognized
documents. For known
types the summary is
built from the extracted
fields by a template,
with no AI call
AI Mortgage Copilot — Feature Design
Page 5 of 48

<!-- page 6 -->
Gap messages are templates filled from those results, such as "14 of 30 days of pay
stubs found".
Safeguards. Output must match the schema, with one automatic retry. Document text is
treated as data and never as instructions. Low-confidence and flagged values are shown
to a person first.
1.6 Services used
The features are modules of one Python application, not separately deployed services.
1.7 API and connectors
Service
Role here
Ingestion and OCR
Stores originals unchanged, runs OCR, numbers
every line and records where it sits on the page
LLM Gateway
The only route to Gemini: versioned prompts,
schema checks, retry
Schema Registry
One field list per document type; adding a type
means adding a schema and a description
Rules and Config
Checklists, tolerances and thresholds, each
labelled authoritative or illustrative
Human Review
Confirm, correct or reject any value; the original is
kept
Evidence Model
Links each value to its line and page
Audit Store
Records every upload, AI call and correction
Connector
Use
Document AI
OCR text, layout and confidence (external)
Gemini API
Classification and extraction (external)
PostgreSQL and local file storage
Results, history, originals (internal)
AI Mortgage Copilot — Feature Design
Page 6 of 48

<!-- page 7 -->
1.8 Output
Per document: its type and certainty; each field with its value, position on the page,
confidence and flags; a summary; and a review status.
Per case: the overview table, and the completeness result with each item's status, an
outstanding items list and an overall status.
For the other features: the same data as JSON, using corrected values.
Example. For Daniel Reyes, OCR misreads net pay 2,033.61 as 2,083.61. The value is
genuinely in the OCR text, so only the arithmetic check (gross 3,070.50 minus deductions
1,036.89 should be 2,033.61) catches it, and the reviewer corrects it. A bank statement
uploaded as a tax return is recognized from its content and switched. An August
statement whose footer says "Page 1 of 3" but has only two pages is reported as
incomplete.
2. Income Analysis
Reconciles income across pay stubs, W-2s and tax returns and shows candidate monthly
income by component, with the working. Python does every calculation. The LLM only
suggests explanations for differences. The underwriter decides what counts as qualifying
Endpoint
Purpose
POST /cases/{id}/documents
Upload files
GET /cases/{id}/documents
List with type, status and flags
GET /cases/{id}/documents/{doc}/extraction
Fields, flags and summary
PATCH
/cases/{id}/documents/{doc}/fields/{field}
Confirm or correct a value
PUT /cases/{id}/documents/{doc}/type
Confirm or change the type
PUT /cases/{id}/profile
Borrower names, employment type,
reference date
POST /cases/{id}/completeness
Run the checklist; GET .../latest returns
the result
GET /cases/{id}/overview
The case overview
AI Mortgage Copilot — Feature Design
Page 7 of 48

<!-- page 8 -->
income.
2.1 Feature overview
2.2 User interaction
1. Open the Income tab and run the analysis.
2. See each income component with its current-period, year-to-date and monthly figure.
"Show working" opens the formula and its inputs.
3. Read the flags. Each shows both values side by side with their sources, and possible
explanations marked "to be confirmed".
4. Include or exclude a component, with a reason. The figures update at once.
5. Copy the suggested document requests.
2.3 Input requirements
From Feature 1: pay stubs (earnings lines, hours, rate, pay period, year to date), W-2s
(boxes 1 and 5, Box 12 codes), tax returns (wages, total income) and the borrower names.
An income method. Configuration, with illustrative sample settings. Real methods
depend on the program and lender and must come from their documented requirements.
What it does
Groups earnings by type, calculates monthly,
annual and year-over-year income, cross-checks
the documents, flags discrepancies and suggests
explanations
What it shows off
Calculations with visible working, and an LLM used
only where judgement is needed
Users
Underwriter
Replaces
Income analysis in the original plan
Not included
Deciding qualifying income; self-employment,
rental and other income; employment verification
Setting
Illustrative sample
Base pay, hourly
Rate × regular hours × pay periods per year ÷ 12
AI Mortgage Copilot — Feature Design
Page 8 of 48

<!-- page 9 -->
2.4 Workflow diagram
Setting
Illustrative sample
Overtime, bonus, commission
Counted only if documented history is 24 months
or more; otherwise excluded and flagged
Year-to-date average
Year-to-date amount × periods per year ÷ (periods
elapsed × 12)
Declining income
A year-over-year drop above 5% is flagged
Tolerance
Cross-document comparisons within 1.00 or 0.5%,
whichever is larger
Income Analysis flow · sequence, 10 steps
AI Mortgage Copilot — Feature Design
Page 9 of 48

<!-- page 10 -->
Steps 4, 7 and 10 are plain Python. Including or excluding a component recalculates at
once, with no AI call.
2.5 LLM inference
One AI call per run. For each flag, it proposes possible explanations from the evidence it is
given (earnings descriptions, W-2 Box 12 codes, employer names) and lists documents
that would settle the question. Every explanation is labelled "possible — to be confirmed"
and cites its evidence. The AI sees computed figures only, never the documents, and
never calculates or rounds.
Checked in code.
The trend sentence ("Gross pay rose 5.49% in 2025") is built from the numbers by a
template, with no AI. Any figure in an AI explanation is checked against its input, and a
failure is marked "unverified figure".
Check
Comparison
Wages
Form 1040 wages against W-2 Box 1 for the same
year
Employer
Employer on the latest pay stub against the latest
W-2
Deferrals
W-2 Box 5 minus Box 1 against the Box 12 deferral
codes (configured; sample: D)
Trend
Latest full-year W-2 against the current year
annualized, using the decline threshold
History
Documented history of overtime, bonus and
commission against the requirement
Year to date
Year-to-date pay divided by periods elapsed,
against current-period pay
Frequency
Printed pay frequency against the frequency
implied by the period length
AI Mortgage Copilot — Feature Design
Page 10 of 48

<!-- page 11 -->
2.6 Services used
2.7 API and connectors
Connector: Gemini API, through the LLM Gateway. Nothing else external.
2.8 Output
The income profile for each borrower and employer, and a table of components with
current, year-to-date and monthly figures and their working.
A candidate monthly income, labelled "candidate — qualifying income is determined by
the underwriter".
Annual history from W-2s and returns, with the current year marked as a projection.
Service
Role here
Calculations
Every formula, returning its working
Rules and Config
The income method and thresholds
LLM Gateway
The explanation call: versioned prompt, schema
check, retry
Evidence Model
Links each figure to its document lines
Human Review
Include or exclude with a reason; original kept
Audit Store
Inputs, method version, results and review actions
Endpoint
Purpose
POST /cases/{id}/income-analysis
Run the analysis
GET /cases/{id}/income-analysis/latest
Components, figures, flags,
explanations
PATCH /cases/{id}/income-
analysis/latest/components/{component}
Include or exclude, with a reason
POST /cases/{id}/income-
analysis/latest/explanations
Regenerate explanations
AI Mortgage Copilot — Feature Design
Page 11 of 48

<!-- page 12 -->
Flags with both values and sources, possible explanations, and suggested document
requests.
The same data as JSON for Features 3 and 6.
Example. For Daniel Reyes, base pay gives 5,980.00 a month. Overtime (444.41) and bonus
(228.34) are excluded because their history covers 2026 only. W-2 Box 5 rose from
70,431.80 in 2024 to 74,298.60 in 2025 (+5.49%), and the 2026 pace is 79,833.00 (+7.45%).
The AI explains the gap between Box 5 and Box 1 as 401(k) deferrals, citing Box 12.
Including overtime would make the candidate total 6,424.41, which the underwriter can
test and reverse.
3. Asset and Liability Analysis
Shows the borrower's documented assets, recurring obligations and candidate ratios
(front-end ratio, DTI and LTV). The LLM labels each bank transaction. Python finds
patterns, totals balances, flags large deposits and computes the ratios. The underwriter
decides which obligations count.
3.1 Feature overview
What it does
Labels bank transactions, matches payroll to pay
stubs, flags large deposits and fees, finds recurring
debts, reconciles them with the credit report, and
computes funds to close, DTI and LTV
What it shows off
An LLM used for the one task rules cannot do well,
reading free-text transaction descriptions, and
exact figures from code
Users
Underwriter
Replaces
Asset and liability analysis in the original plan
Not included
Live bank data; verifying where a deposit came
from; gift documentation; retirement and
investment statements; pricing; appraisal
AI Mortgage Copilot — Feature Design
Page 12 of 48

<!-- page 13 -->
3.2 User interaction
1. Enter the sample loan scenario (purpose, property value, loan amount, proposed
housing payment, funds needed to close), then run the analysis.
2. Read the summary strip: documented assets, funds to close, and the three candidate
ratios, each with its working.
3. Browse each account's transactions with category chips and flags. Reclassify a
transaction, or mark a deposit as sourced with a note.
4. Review the obligations table, including each debt's source (bank, credit report or
both). Include or exclude one from DTI, with a reason.
5. Ratios update at once after any change.
3.3 Input requirements
From other features: bank statement transactions (Feature 1), liabilities from the credit
report (Feature 4, when run), and candidate monthly income (Feature 2).
Sample loan scenario. Entered by hand: loan purpose, occupancy, property value, loan
amount, proposed monthly housing payment and estimated funds to close. Nothing is
calculated by a pricing engine.
Settings (configuration, illustrative samples).
Setting
Sample
Large deposit
A credit of 1,000.00 or more that is not payroll or a
transfer between the borrower's own accounts
Recurring debit
Same payee in 2 or more statement months, with
amounts within 1.00
Payroll match
Employer name in the description, amount within
1.00, date within 3 days of a pay date
DTI defaults
Include credit report liabilities with a payment
above zero; exclude current rent on a purchase of a
primary residence
DTI review level
43%
AI Mortgage Copilot — Feature Design
Page 13 of 48

<!-- page 14 -->
3.4 Workflow diagram
Only steps 4 and 5 use the AI. Reclassifying a transaction or changing an obligation
recomputes everything in step 9, with no AI call.
3.5 LLM inference
One AI call per statement. It receives each transaction's line, date, description and
amount, plus the fixed category list and the names of the borrower and employer. It
returns one category and a cleaned-up counterparty name for every transaction, citing
the line.
Categories: payroll deposit, other income deposit, transfer in, transfer out, housing
payment, loan payment, credit card payment, utility, insurance, everyday spending,
overdraft or returned-item fee, other fee, refund, other.
Asset and Liability Analysis flow · sequence, 9 steps
AI Mortgage Copilot — Feature Design
Page 14 of 48

<!-- page 15 -->
The AI never decides whether a deposit is acceptable, never adds amounts and never
compares figures. If it returns an unknown line or misses one, the call is retried once, and
any transaction still unlabelled shows as "other, needs review".
Done in code: matching deposits to pay stubs, finding recurring debits, flagging large
deposits and overdraft fees, reconciling debts with the credit report, documented
balances, funds to close against funds needed, and every ratio. Flag messages are
templates, such as "Large deposit of 2,000.00 on 2026-09-22 — source may need
documenting under program rules".
3.6 Services used
3.7 API and connectors
Connector: Gemini API, through the LLM Gateway.
Service
Role here
LLM Gateway
The labelling call: versioned prompt, schema check,
retry
Calculations
Balances, funds to close, ratios, with working
Rules and Config
The settings above, each labelled illustrative or
authoritative
Evidence Model
Links each figure to a statement line, credit report
tradeline or scenario value
Human Review
Reclassify, mark sourced, include or exclude;
original kept
Audit Store
Scenario values, labels, decisions and results
Endpoint
Purpose
PUT /cases/{id}/loan-scenario
Enter the sample loan scenario
POST /cases/{id}/asset-liability
Run the analysis
GET /cases/{id}/asset-liability/latest
Accounts, transactions, flags,
obligations, ratios
AI Mortgage Copilot — Feature Design
Page 15 of 48

<!-- page 16 -->
3.8 Output
Accounts with documented balances, and every transaction with its category,
counterparty, payroll match and flags.
Flags for large deposits, overdraft or returned-item fees, and recurring debts that are
not on the credit report.
An obligations table with each debt's source and whether it counts toward DTI.
Documented liquid assets against funds needed, with any shortfall.
Candidate front-end ratio, DTI and LTV, each labelled "candidate — for underwriter
review".
The same data as JSON for Feature 6.
Example. For Daniel Reyes, both September paychecks of 2,033.61 match his pay stubs,
and a 2,000.00 transfer from an individual is flagged. Documented assets of 9,226.32 fall
27,273.68 short of the 36,500.00 needed. Obligations total 693.00 a month. With candidate
income of 5,980.00, the front-end ratio is 33.11%, DTI is 44.70% (above the illustrative 43%
level) and LTV is 90.00%. If the underwriter counts overtime, DTI falls to 41.61%.
4. Credit Report Analysis
Reads a sample credit report through the Feature 1 pipeline, computes credit metrics in
code, and flags credit-related risks with evidence. The report is simulated; no credit
bureau is contacted, and no credit decision is made.
4.1 Feature overview
Endpoint
Purpose
PATCH /cases/{id}/transactions/{transaction}
Reclassify, or mark a deposit sourced
PATCH /cases/{id}/asset-
liability/latest/obligations/{obligation}
Include or exclude, with a reason
What it does
Extracts scores, tradelines, inquiries and
derogatory items; computes utilization, late-
payment history and inquiry matches; flags risks;
passes monthly payments to Feature 3
AI Mortgage Copilot — Feature Design
Page 16 of 48

<!-- page 17 -->
4.2 User interaction
1. Upload the sample credit report in Feature 1 (it is recognized as a credit report) and
open the Credit tab.
2. See every score, the representative score and the method used, with a "sample credit
report" tag.
3. Browse the tradelines, with utilization bars for revolving accounts, and the late-
payment summary.
4. Read the inquiries list; each inquiry shows its matched new account or "no new
account found".
5. Open a flag to jump to the report line it describes. Add an annotation, such as
"explanation received".
4.3 Input requirements
The sample report. One merged credit report as a PDF, with up to three bureau scores.
Fraud alerts, freezes and consumer statements, when present, always appear at the top
of the results.
What is read from it. Report date and consumer names; scores with bureau labels; for
each tradeline the creditor, account type, ownership, open date, status, balance, credit
limit, monthly payment, past-due amount, late-payment counts, most recent late date and
remarks; inquiries with creditor and date; collections and public records.
Settings (configuration, illustrative samples).
What it shows off
The same extraction pipeline reused for a new
document type, with every credit metric calculated
in code
Users
Underwriter
Replaces
Credit report analysis in the original plan
Not included
Bureau connections; credit decisions or score
cutoffs; rescoring; dispute handling
Setting
Sample
Representative score
Middle of three, lower of two
AI Mortgage Copilot — Feature Design
Page 17 of 48

<!-- page 18 -->
4.4 Workflow diagram
Only step 2 uses the AI, through the same extraction call as Feature 1.
4.5 LLM inference
The only AI use is the extraction in Feature 1, which reads the report into its fields with an
evidence line for each. Nothing else in this feature uses the AI.
Setting
Sample
Late-payment lookback
24 months
Inquiry window
120 days
Inquiry to new-account match
Account opened within 30 days
Utilization review level
30% per account
Credit Report Analysis flow · sequence, 7 steps
AI Mortgage Copilot — Feature Design
Page 18 of 48

<!-- page 19 -->
Tradeline remarks such as "in dispute" or "closed by consumer" are classified by keyword
rules. An optional fallback asks the AI to classify a remark the rules do not recognize,
citing the remark.
Done in code: the representative score, utilization per account and in total, late payments
by severity within the lookback, months since the last late payment, inquiry-to-account
matching, the derogatory list, monthly payment totals by account type, and all flags. The
credit summary is a template filled from those results, such as "One 30-day late payment
on Northgate Card, 19 months before the report date".
4.6 Services used
4.7 API and connectors
Connectors: Gemini API and Document AI through Feature 1. A credit bureau connection
is simulated by the sample file.
Service
Role here
Ingestion and OCR, LLM Gateway, Schema
Registry
Read the report (credit report schema
registered here)
Calculations
All metrics, with working
Rules and Config
The settings above, labelled illustrative
Evidence Model
Links every figure and flag to its report line
Human Review
Corrections and annotations; original kept
Audit Store
Inputs, metrics and annotations
Endpoint
Purpose
POST /cases/{id}/credit-analysis
Run the analysis
GET /cases/{id}/credit-analysis/latest
Scores, tradelines, metrics, flags,
summary
PATCH /cases/{id}/credit-
analysis/latest/items/{item}
Add an annotation
AI Mortgage Copilot — Feature Design
Page 19 of 48

<!-- page 20 -->
4.8 Output
All scores, the representative score and the method used.
Tradelines, utilization per account and in total, late-payment summary, inquiries with
their matches, derogatory items, and alerts.
Flags and a template summary, each linked to its report line, plus annotations.
Monthly payments by account type, passed to Feature 3, and the same data as JSON
for Feature 6.
Example. The sample report for Daniel Reyes, dated 2026-10-12, shows scores 712, 698 and
705, so the representative score under the illustrative method is 705. Northgate Card
utilization is 36.75%, above the illustrative 30% level, and total revolving utilization is
28.00%. There is one 30-day late payment, 19 months ago. Monthly payments total 693.00.
A new Harbor Retail card was opened the day of an inquiry, and an Orion Mortgage inquiry
has no matching account.
5. Guideline and Regulation Assistant
Answers questions from loaded source documents, using only retrieved passages and
citing every sentence. It is one retrieval-augmented generation (RAG) engine with two
source sets: agency and lender guidelines (Fannie Mae, Freddie Mac, a lender overlay)
and Regulation X. The same engine serves the investor guide in Feature 8 and the
Researcher agent in Features 6 and 8.
5.1 Feature overview
What it does
Loads source documents, retrieves the relevant
passages and writes short cited answers. In case-
aware mode it lists the provisions that may apply to
a case, with the facts to check
What it shows off
RAG done carefully: citations that are verified, and
silence when the sources are silent
Users
Underwriter, loss mitigation specialist, compliance
reviewer; also the agents
Replaces
The guideline assistant and the Regulation X
assistant in the original plan
AI Mortgage Copilot — Feature Design
Page 20 of 48

<!-- page 21 -->
5.2 User interaction
1. Ask a question and choose the source set (guidelines, Regulation X, or all). "Attach
case" adds the case's facts.
2. Read the answer: short sentences, each with a citation marker.
3. Click a citation to open the passage, with its document, section, page, version and an
"authoritative" or "illustrative" label.
4. Where sources differ, such as an agency guide and a lender overlay, see them side by
side.
5. If no passage supports an answer, see "no supporting passage found" instead of a
guess.
6. Mark an answer helpful, not helpful or wrongly cited. Regulation X answers always
carry the notice "Not legal advice; confirm with your compliance team."
5.3 Input requirements
Not included
Automatic updates from publishers; state law; legal
advice; deciding whether a borrower meets a
requirement or whether a servicer complied
Collection
Source
Label
Fannie Mae
Selling Guide, the parts on income, assets,
liabilities and credit, downloaded from the
publisher
Authoritative, with version
date
Freddie Mac
Single-Family Seller/Servicer Guide, same
topics
Authoritative, with version
date
Lender
overlay
A short document written for the demo
Illustrative
Regulation X
12 CFR Part 1024, Subpart C, and its official
interpretations, from the eCFR
Authoritative, with the "as of"
date
Investor
guide
A short "Sample Investor A" guide written
for the demo (used in Feature 8)
Illustrative
AI Mortgage Copilot — Feature Design
Page 21 of 48

<!-- page 22 -->
Also needed: the question, and in case-aware mode the case's facts (application date,
checklist result, delinquency status). Settings: chunk size, number of passages, similarity
threshold, embedding model, maximum quotation length, and any Regulation X timing
rules, which the team configures from the regulation text with their citations. The
prototype may ship with none.
5.4 Workflow diagram
Step 2 first turns the question into an embedding, using the same model that loaded the
sources. Step 4 drops weak matches before the AI sees anything, and step 7 removes any
sentence that fails its checks.
Guideline and Regulation Assistant flow · sequence, 10 steps
AI Mortgage Copilot — Feature Design
Page 22 of 48

<!-- page 23 -->
5.5 LLM inference
Two uses of AI models.
1. Embeddings, to find passages. When a source is loaded, it is split along its own
section structure, and each chunk is turned into an embedding by an embedding model
(a Gemini embedding model or an equivalent, chosen once). Each question is
embedded with the same model. The model name is stored with each collection, and
changing it means reloading the collection. Calls go through the LLM Gateway.
2. The answer. Gemini receives the question, the last few turns and only the retrieved
passages, each with its ID, source, section and version. It must cite a passage for every
sentence, keep quotations short, show disagreement side by side, and say when the
passages do not answer the question.
Checked in code.
Passages below the similarity threshold are dropped. If none remain, the answer is "no
supporting passage found" and the AI is not called.
A question that names a section is looked up directly.
Every citation must be one of the retrieved passages, and every quotation must be an
exact piece of its passage. A sentence that fails is removed, and the removal is shown.
Regulation X only: any time period, date or amount in an answer must appear in a cited
paragraph. Dates are computed only by Python, from a configured timing rule, and
labelled with the rule and its paragraph.
5.6 Services used
Service
Role here
RAG Service
Loads and chunks sources, embeds, retrieves, runs
the citation checks
LLM Gateway
The embedding and answer calls
Rules and Config
Source labels, timing rules, thresholds
Evidence Model
Turns citations into links that open the passage
Audit Store
Question, retrieved passages and scores, answer,
removed sentences, feedback
AI Mortgage Copilot — Feature Design
Page 23 of 48

<!-- page 24 -->
5.7 API and connectors
Connectors: Gemini API (answers, and embeddings if a Gemini embedding model is
chosen); a vector store (ChromaDB or FAISS, as a local library); source files in local file
storage.
5.8 Output
A cited answer; each citation opens its passage.
"No supporting passage found" or "not covered by the loaded sources" when
appropriate, and the Regulation X notice.
In case-aware mode, a list of provisions that may apply, with the facts to check against
each, and never a statement that a borrower qualifies or a servicer complied.
Feedback records, and an evaluation report from a test set of questions with their
expected sections (retrieval hit rate and citation validity).
Example. For Daniel Reyes's file, the underwriter asks how overtime income is evaluated.
The assistant answers in a few cited sentences with the Fannie Mae and Freddie Mac
passages side by side. A question about the lender's overlay is answered from the
illustrative overlay, labelled as such. A question about jumbo loans finds nothing in the
loaded sources, so the answer is "no supporting passage found". For Angela Whitfield's
case, a question about a missing document in a received application, in case-aware mode,
cites 12 CFR 1024.41(b) and lists the facts to check, such as the date received and the
missing statement.
Endpoint
Purpose
POST /guidelines/ask
Question, source set and optional case ID; returns
the cited answer
GET /guidelines/passages/{id}
One passage with its source details
GET /guidelines/sources
Loaded sources, versions and labels
POST /guidelines/sources
Load a source (administrator)
AI Mortgage Copilot — Feature Design
Page 24 of 48

<!-- page 25 -->
6. Underwriting Copilot
Combines the results of Features 1 to 4 into a draft underwriting analysis: findings, risks,
missing information and suggested conditions, each with its evidence. Code prepares the
findings, three agents research, write and check the report, and the underwriter decides.
This completes Pillar 1.
6.1 Feature overview
6.2 User interaction
1. Run the copilot.
2. Watch the three agents' progress. If one fails, re-run it alone.
3. Read the report. Every finding links to its evidence, every guideline statement to its
passage, and conflicts between findings are shown openly.
4. Accept, edit or reject each suggested condition, with a reason, or add your own.
5. Sign off the review. The sign-off records that a person reviewed the report. It is not a
decision and is never labelled as one.
What it does
Turns every flag from Features 1 to 4 into a findings
list; a Researcher agent looks up the guidance, a
Writer agent drafts the report and a Critic agent
checks it
What it shows off
A multi-agent workflow in which each agent has a
different job and different tools, a writer-and-critic
loop, and guardrails written in code
Users
Underwriter
Replaces
The underwriting copilot, which had five agents in
the earlier plan
Not included
Approving or denying a loan; connecting to Fannie
Mae DU or Freddie Mac LPA; pricing; collateral
review such as appraisal, title and property
eligibility (the loan scenario gives a property value
only)
AI Mortgage Copilot — Feature Design
Page 25 of 48

<!-- page 26 -->
6.3 Input requirements
The results of Features 1 to 4: the completeness result, income, assets and liabilities,
and credit. Guideline search comes from Feature 5.
Optionally, a simulated input: a sample automated-underwriting findings file (a
recommendation label and a list of conditions), used only for a side-by-side
comparison.
Settings: the list of decision words to block (such as approved, denied, eligible,
qualifies) and the review-priority levels.
6.4 Workflow diagram
Underwriting Copilot agent workflow · sequence, 12 steps
AI Mortgage Copilot — Feature Design
Page 26 of 48

<!-- page 27 -->
Step 2 is code, not an agent. The Critic's check in step 10 either passes the draft or sends
it back to the Writer once.
6.5 LLM inference
Three agents, coordinated by LangGraph with a shared, typed state. Each agent's output
is checked against its schema.
Agent
Job
Tools
Output
Researcher
For each finding that
needs guidance, decides
what to search for, finds
the passages in the
guides and the lender
overlay, states what they
require, and notes what
the file already shows
and what is missing
Guideline search
(Feature 5); what-if
calculation
Cited requirements,
gaps, open questions
Writer
Drafts the report from
the findings and the
Researcher's output:
snapshot, findings by
priority, potential risks,
missing information,
suggested conditions,
guideline references
None
The report sections
Critic
Reads the draft against
the evidence. Returns it
once for correction if a
claim lacks support, a
figure does not match, a
guideline statement has
no cited passage, or the
wording sounds like a
decision
Evidence lookup; fixed
wording checks
Pass, or a list of fixes
AI Mortgage Copilot — Feature Design
Page 27 of 48

<!-- page 28 -->
Done in code, with no agent. Building the findings list from the flags; priority labels
(significant, attention, information, which describe review order and not eligibility); the
what-if numbers; and the final guardrails: every finding has evidence, every figure equals
a stored result, no decision wording, and every citation resolves to a retrieved passage. If
one agent fails, the report still completes with that section marked "not available".
6.6 Services used
6.7 API and connectors
Connectors: Gemini API; Feature 5 (internal); the optional sample automated-
underwriting file (simulated).
Service
Role here
Agent Layer
LangGraph state, run log and progress display
Guideline search (Feature 5)
The Researcher's retrieval and the citation checks
Calculations
What-if figures, such as DTI with overtime counted
LLM Gateway
Every agent call
Evidence Model
Links each finding to its source
Human Review
Accept, edit, reject, add, sign off; originals kept
Report Builder
Builds tables and figures from stored results;
agents write only the narrative
Audit Store
Inputs, prompts, tool calls, outputs and review
actions
Endpoint
Purpose
POST /cases/{id}/underwriting-report
Start the workflow
GET /cases/{id}/underwriting-report/latest
Report, agent outputs, status
POST /cases/{id}/underwriting-
report/latest/agents/{agent}/rerun
Re-run one agent
PATCH /cases/{id}/underwriting-
report/latest/conditions/{condition}
Accept, edit or reject a condition
AI Mortgage Copilot — Feature Design
Page 28 of 48

<!-- page 29 -->
6.8 Output
The report: case snapshot, findings by priority, potential risks, missing information,
suggested conditions, guideline references and an evidence index.
A list of conflicts between findings, and an optional comparison with the sample
automated findings, labelled "simulated".
The run log of each agent, and the sign-off record.
Example. For Daniel Reyes, the findings include a 27,273.68 shortfall in assets against
funds to close, an unsourced 2,000.00 transfer, overtime and bonus excluded because
their history covers 2026 only, DTI of 44.70% (above the illustrative 43% level), a 30-day
late payment 19 months ago, pay stubs 16 days short, and page 3 of the August statement
missing. The report shows the DTI conflict openly: 44.70%, or 41.61% if overtime is
counted. It ends with six suggested conditions. The underwriter accepts five, rejects one
with the reason "not required for this file", and signs off the review.
7. Hardship and Financial Assessment
Reads the hardship letter into a profile of reasons, onset, duration and intent, each
backed by a quote that code verifies. Builds the borrower's monthly budget on two bases,
what they state and what the documents show, and computes affordability. There is one
AI call, and everything else is Python. The specialist confirms the judgements that the
investor rules rely on.
7.1 Feature overview
Endpoint
Purpose
POST /cases/{id}/underwriting-report/latest/sign-
off
Record the review
What it does
Reads the letter into a profile, compares the stated
facts with the documents, builds the budget and
computes income change, surplus or deficit,
housing ratio, arrears and liquid assets
AI Mortgage Copilot — Feature Design
Page 29 of 48

<!-- page 30 -->
7.2 User interaction
1. Open the Hardship tab. The letter appears beside the profile, and each quote
highlights its lines.
2. Review the consistency checks. Each row shows both values, such as the hours cut
stated in the letter and the change in pay on the stubs.
3. Confirm or correct the reasons, onset, duration and intent. These confirmed values
drive the investor rules in Feature 8.
4. Open the Budget tab: stated figures beside observed figures, with differences
highlighted.
5. Adjust an item with a reason, for example marking a spend as one-off. The measures
update at once.
7.3 Input requirements
From Feature 1: the hardship letter (text with line IDs), the application (stated income,
expenses, assets, reasons, intent), pay stubs, bank statements, the mortgage statement
and any benefits letter. Loan record (simulated): loan ID, investor name, unpaid balance,
payment parts, due dates and delinquency status.
Settings (illustrative samples).
What it shows off
An LLM reading free text safely, with every quote
checked, and the difference between stated and
observed figures
Users
Loss mitigation specialist
Replaces
Borrower hardship analysis and financial situation
assessment
Not included
Judging credibility or sincerity; recommending an
option; extracting medical detail; credit reports for
loss mitigation cases
AI Mortgage Copilot — Feature Design
Page 30 of 48

<!-- page 31 -->
7.4 Workflow diagram
Setting
Sample
Hardship categories
Reduction in income, unemployment, increase in
housing expense, medical or disability, divorce or
separation, death in household, disaster, business
failure, other
Stated against observed
A difference above 10% or 25.00, whichever is
larger, is flagged
Quote length
A short maximum, so quotes stay quotes
Hardship and Financial Assessment flow · sequence, 10 steps
AI Mortgage Copilot — Feature Design
Page 31 of 48

<!-- page 32 -->
Only steps 4 and 5 use the AI. Steps 6, 7 and 10 are Python, so adjusting the budget never
calls the AI.
7.5 LLM inference
One AI call. It reads the letter, together with the reasons ticked on the application, and
returns: the hardship reasons from the category list (one primary), the onset as stated,
the expected duration (temporary, long-term or unknown), the stated intent (keep the
home, sell, unsure), a timeline of events, and the documents the borrower says are
enclosed. Each item carries a short quote and its line IDs. For medical, family or other
sensitive matters it records only the category and the financial effect, never a diagnosis.
It writes neutrally and does not judge credibility or recommend an option.
{"primary_reason": {"category": "reduction_in_income", "quote": "cut my hours 
from 40 to 30 a week in July", "lines": ["p1-L6"]}, "intent": {"category": 
"keep", "quote": "I want to keep my home", "lines": ["p1-L14"]}}
Checked in code. Every quote must be an exact piece of its cited lines. Facts are
compared with the documents: the change in pay on the stubs against the stated cut,
stated amounts against extracted amounts, and the letter's reasons and intent against the
application's. The budget is computed from the documents: documented gross and net
monthly income, expenses by category on both bases (observed amounts come from the
labelled bank transactions of Feature 3), surplus or deficit, housing ratio, income change,
arrears, and liquid assets as a share of arrears. Flag messages are templates, such as
"Observed 'other' spending 410.00 against 200.00 stated — ask the borrower".
7.6 Services used
Service
Role here
LLM Gateway
The letter-reading call: versioned prompt, schema
check, retry
Calculations
The budget and every measure, with working
Rules and Config
Categories and tolerances, labelled illustrative
Evidence Model
Links quotes and figures to their lines
Human Review
Confirm and correct judgements; adjust budget
items; originals kept
AI Mortgage Copilot — Feature Design
Page 32 of 48

<!-- page 33 -->
7.7 API and connectors
Connector: Gemini API. Transaction labelling reuses Feature 3.
7.8 Output
The hardship profile with its quotes, and confirmed values labelled "reviewer-
confirmed".
Consistency checks, each with both values.
The budget on both bases, the affordability measures with working, and flags.
The same data as JSON for Feature 8.
Example. Angela Whitfield writes that her hours were cut from 40 to 30 in July 2026, that
she fell behind from August, that she does not know whether her hours will return, and
that she wants to keep her home. The profile reads: reduction in income, onset July 2026,
duration unknown, intent to keep. Her stubs fall from 2,800.00 to 2,100.00 per half-month,
a 25% drop that matches the cut. Monthly income is 4,200.00 (net 3,350.00). Expenses
are 3,420.00 stated and 3,630.00 observed, the gap being "other" spending of 410.00
against 200.00. That gives a monthly deficit of 70.00 on the stated basis and 280.00 on the
observed one. The housing ratio is 40.95%, up from 30.71% before the cut. Arrears are
5,160.00, and her 640.25 of liquid assets covers 12.41% of them. The specialist confirms
the reason and intent and records the duration as long-term or unknown.
Service
Role here
Audit Store
The profile, checks, confirmations and adjustments
Endpoint
Purpose
POST /cases/{id}/hardship-assessment
Run the analysis
GET /cases/{id}/hardship-assessment/latest
Profile, checks, budget, measures
PUT /cases/{id}/hardship-
assessment/latest/confirmations
Confirm or correct reasons, onset,
duration, intent
PATCH /cases/{id}/hardship-
assessment/latest/budget-items/{item}
Adjust a budget item, with a reason
AI Mortgage Copilot — Feature Design
Page 33 of 48

<!-- page 34 -->
8. Loss Mitigation Recommendation
Code applies the investor's rule set to the case in waterfall order and computes the
lender's comparison with foreclosure. The same three agents (Researcher, Writer, Critic)
then turn the results into a recommendation report for an authorized decision-maker.
Loss mitigation exists mainly to protect the investor's and servicer's position, so the
report shows the lender's view first. The system never offers or approves an option.
8.1 Feature overview
8.2 User interaction
1. Run the recommendation. If a rule needs a judgement that is not yet confirmed, such
as hardship duration, the specialist is asked first.
2. See the waterfall: option cards in order, each with a status and expandable conditions.
Options the rules never reach are greyed.
3. Read the lender view: the expected outcome of each option whose conditions are met,
beside the foreclosure outcome.
4. Watch the agents, then read the report: lender view, the borrower's situation, options,
missing information, compliance points and items for human review.
What it does
Evaluates each loss mitigation option against
configured investor rules, computes the lender's
expected outcome against foreclosure, and has
three agents research the sources and regulation,
write the report and check it
What it shows off
Rules and AI each doing what they do best, the
same agent pattern as Feature 6, and awareness of
servicing regulation
Users
Loss mitigation specialist; administrator (maintains
the rule set)
Replaces
The investor waterfall assistant and the loss
mitigation recommendation
Not included
Real investor rules; final modification terms;
offering or approving any option; sending anything
AI Mortgage Copilot — Feature Design
Page 34 of 48

<!-- page 35 -->
5. Override a condition with a reason; the statuses recompute and the override stays
visible. Annotate sections, then sign off the review. The sign-off is not a decision.
8.3 Input requirements
From other features: the confirmed hardship profile and budget measures (Feature 7),
the loan record, the application completeness result from the loss mitigation checklist
(Feature 1), and the investor guide and Regulation X (Feature 5).
Sample rule set: Sample Investor A, version 1. Invented for the demo and labelled
"illustrative — not an actual investor's requirements". Each rule cites its passage in a short
sample guide.
Lender view settings (illustrative). Property value 265,000.00; liquidation discount 15%;
foreclosure and carrying costs 24,000.00; review horizon 36 months; chance of re-default
after a modification 30%. This is a simplified comparison, not any investor's actual model.
Order
Option
Conditions (illustrative)
1
Repayment plan
Hardship resolved (confirmed), and monthly
surplus at least arrears ÷ 6
2
Forbearance
Hardship temporary (confirmed)
3
Payment deferral
Hardship resolved (confirmed), surplus at the
contractual payment of zero or more, and 6 or
fewer months delinquent
4
Loan modification
Hardship long-term or unknown (confirmed),
intent to keep the home (confirmed), and a target
payment of 35% of documented gross monthly
income below the contractual payment
5 and 6
Short sale, deed-in-lieu
Evaluated only if no earlier option's conditions are
met
AI Mortgage Copilot — Feature Design
Page 35 of 48

<!-- page 36 -->
8.4 Workflow diagram
Step 4 is code: the rules decide every condition and compute the lender view before any
agent starts. The agents never evaluate a condition.
8.5 LLM inference
The same three agents as Feature 6, with Pillar 2 inputs and tools.
Loss Mitigation Recommendation flow · sequence, 12 steps
AI Mortgage Copilot — Feature Design
Page 36 of 48

<!-- page 37 -->
Done in code. Every rule evaluation (met, not met, not evaluable, not reached), the target
payment, the lender view, and the guardrails: an option can be called "potentially suitable"
only if the rules marked its conditions met; words such as approved, denied, guaranteed
and "you qualify" are blocked; every figure equals a stored result. Dates under Regulation
X are computed only by Python from a configured rule.
8.6 Services used
Agent
Job
Tools
Researcher
For each option the rules reached, finds
that rule's passage in the investor guide.
Finds the Regulation X provisions that may
apply to the case's facts, with citations
and the facts to check, and reports
whether the application is complete
Source search (Feature 5)
Writer
Drafts the report in this order: lender view,
the borrower's situation, options in
waterfall order with reasons, missing
information, compliance points, items for
human review
None
Critic
Checks the draft against the evidence.
Returns it once if a claim lacks support, a
figure does not match, a citation does not
resolve, or the wording promises or
decides
Evidence lookup; fixed wording
checks
Service
Role here
Rules and Config
The rule set, the lender view settings and the
checklist, each versioned and labelled
Calculations
Target payment and the lender view, with working
Agent Layer
LangGraph state, run log and progress
Source search (Feature 5)
Investor guide and Regulation X retrieval, with
citation checks
LLM Gateway
Every agent call
AI Mortgage Copilot — Feature Design
Page 37 of 48

<!-- page 38 -->
8.7 API and connectors
Connectors: Gemini API; Feature 5 (internal). The rule set is versioned configuration kept
with the code.
8.8 Output
The waterfall: each option with its status, its conditions with the values used, and its
cited rule passage.
The lender view: expected outcomes with their working.
The report, with missing information, compliance points and items for human review;
the rule set name and version with an "illustrative" banner; overrides; and the sign-off
record.
Final terms are never computed; they read "to be calculated under the investor's
approved method".
Example. For Angela Whitfield, under Sample Investor A:
Service
Role here
Evidence Model, Human Review
Links to evidence; overrides, annotations, sign-off
Report Builder, Audit Store
Tables from stored results; the full record of every
run
Endpoint
Purpose
POST /cases/{id}/lm-recommendation
Start the evaluation and the agents
GET /cases/{id}/lm-recommendation/latest
Waterfall, lender view, report, status
PUT /cases/{id}/lm-
recommendation/latest/conditions/{condition}/ove
rride
Override a condition, with a reason
POST /cases/{id}/lm-
recommendation/latest/agents/{agent}/rerun
Re-run one agent
POST /cases/{id}/lm-recommendation/latest/sign-
off
Record the review
AI Mortgage Copilot — Feature Design
Page 38 of 48

<!-- page 39 -->
Lender view. Foreclosure: a claim of 217,560.00 (balance 212,400.00 plus arrears 5,160.00)
against net recovery of 201,250.00 (265,000.00 less 15%, less 24,000.00) is a loss of
16,310.00. Modification: a payment reduction of 250.00 for 36 months (9,000.00) plus a
30% chance of the 16,310.00 loss (4,893.00) is an expected cost of 13,893.00, which is
2,417.00 lower. These figures use illustrative settings.
The report also notes the missing August bank statement, cites 12 CFR 1024.41(b) on
notifying the borrower about missing documents, and lists the facts to check, such as the
date the application was received. The specialist adds a note to request the statement
and signs off the review.
9. Case Summary and Communication
Drafts three documents from a loss mitigation case's stored results: an internal case
summary, a missing-document request and a borrower status update. Each comes from
an approved template whose fixed text, such as required disclosures, is inserted word for
word. The LLM writes only the sections the template allows, and code checks every draft
before a person sees it. Nothing is ever sent by the system.
Option
Result
Why
Repayment plan
Not met
Hardship not resolved; surplus of -70.00 is below
the 860.00 needed (5,160.00 ÷ 6)
Forbearance
Not met
Hardship not temporary
Payment deferral
Not met
Hardship not resolved, and surplus is below zero
(3 months delinquent is within the limit)
Loan modification
Conditions
met
Long-term or unknown hardship, intent to keep,
and a target payment of 1,470.00 (35% of
4,200.00) below 1,720.00
Short sale, deed-in-
lieu
Not reached
An earlier option's conditions are met
AI Mortgage Copilot — Feature Design
Page 39 of 48

<!-- page 40 -->
9.1 Feature overview
9.2 User interaction
1. Choose a draft type for the case.
2. Read the draft. Fixed sections are locked and shaded, the other sections are editable,
and any failed check shows as an inline flag.
3. Regenerate a section or edit it by hand. Edits are tracked.
4. Mark the draft reviewed, then approve it for sending. Approval is recorded with the
approver and time, and the sending happens outside the system.
5. Copy the text out. A banner reads "The system does not send this document".
9.3 Input requirements
Stored results: the checklist result and outstanding items list (Feature 1), the loan record,
the hardship profile and budget measures (Feature 7), and the recommendation report
(Feature 8).
Templates (illustrative samples; real wording and disclosures come from compliance).
What it does
Fills templates from stored results, has the LLM
write the free sections, checks the draft, and
records a person's review and approval
What it shows off
AI writing inside guardrails: fixed text kept
verbatim, promises and wrong figures caught by
code
Users
Loss mitigation specialist; compliance reviewer,
who owns the templates
Replaces
Case summary and communication in the original
plan
Not included
Sending email or letters; deciding whether a draft
satisfies a regulatory notice requirement;
languages other than English
AI Mortgage Copilot — Feature Design
Page 40 of 48

<!-- page 41 -->
Settings: the list of promise and outcome phrases to block, the internal-only fields (rule
IDs, internal flags, review priorities) that must never appear in a borrower-facing draft,
and a length limit for each free section.
Draft
Sections
Internal case summary
Snapshot, hardship, finances, lender view, option
results, open items, compliance notes (all editable
text)
Missing-document request
Greeting, purpose, the outstanding items list
(inserted by code), how to send documents,
contact details, fixed disclosures
Borrower status update
Greeting, current status, what happens next in
general terms, contact details, fixed disclosures
AI Mortgage Copilot — Feature Design
Page 41 of 48

<!-- page 42 -->
9.4 Workflow diagram
In step 4, code fills in the facts and fixed text. In step 7, code checks the LLM's wording
before the specialist sees the draft.
9.5 LLM inference
One AI call per draft. It receives facts from the stored results, not documents, plus the
instructions for each free section, and writes those sections in plain language within the
length limits. It must not promise, predict an outcome or give legal advice.
Checked in code. Every section is scanned for the blocked phrases. Every figure and date
must match a stored result. Fixed sections must be unchanged. Internal-only fields must
not appear in a borrower-facing draft. A borrower-facing draft never names an option as
Case Summary and Communication flow · sequence, 10 steps
AI Mortgage Copilot — Feature Design
Page 42 of 48

<!-- page 43 -->
available, offered or approved, and may say only that the request is under review. A
section that fails is regenerated once, then flagged for the specialist.
9.6 Services used
9.7 API and connectors
Connector: Gemini API. There is no email or messaging connector, and none is planned.
9.8 Output
The drafts, each with its version, template version, check results, edit history and
approval status.
A copyable text version; PDF export is optional.
Service
Role here
Report Builder
Fills templates, inserts fixed text and lists
LLM Gateway
The drafting call: versioned prompt, schema check,
retry
Rules and Config
Templates, phrase list, internal-only fields
Evidence Model
Traces each figure in a draft to its stored result
Human Review
Edits, review and approval, all tracked
Audit Store
Template version, facts used, AI output, checks,
edits, approvals
Endpoint
Purpose
POST /cases/{id}/drafts
Generate a draft of a given type
GET /cases/{id}/drafts/{draft}
Read a draft with its check results
PATCH /cases/{id}/drafts/{draft}
Edit a free section
POST /cases/{id}/drafts/{draft}/approve
Record the approval
AI Mortgage Copilot — Feature Design
Page 43 of 48

<!-- page 44 -->
Example. For Angela Whitfield, the missing-document request lists exactly one item
inserted by code, the August 2026 bank statement, and the LLM writes a short
explanation of why it is needed and how to send it. In the first status update the LLM
writes that she is "likely to qualify for a modification". The check flags the promise and the
section is regenerated to say only that her request is under review and which documents
are still needed. The specialist edits one sentence, marks both letters reviewed and
approves them. The system records the approval, and the letters are sent outside it.
Shared pages
These pages cover what every feature relies on, so the feature sections can stay short.
A. The three agents
Features 6 and 8 use the same three agents on different inputs. Everything else that
earlier plans called an agent is now plain code: the income, asset, credit and hardship
analyses, and the rule evaluation.
How a run works. Code builds the findings list, then the Researcher, Writer and Critic run
in turn under LangGraph, which holds a shared, typed state. Code then runs the final
guardrails, and a person reviews. Agents read stored results only, use only the tools listed
Agent
Job
In Underwriting
(Feature 6)
In Loss Mitigation
(Feature 8)
Researcher
Decides what to look
up and finds the
sources behind each
finding or option
Searches the Fannie
Mae and Freddie Mac
guides and the lender
overlay for each flag
Searches the investor
guide for each option the
rules reached, and
Regulation X for the case's
facts
Writer
Drafts the report
from the findings and
the research
The underwriting
analysis
The recommendation
report, lender view first
Critic
Checks the draft
against the evidence
and returns it once
for correction
Unsupported claims,
wrong figures, uncited
guidance, decision
wording
The same, plus a check
that an option called
potentially suitable has its
conditions met in the
rules
AI Mortgage Copilot — Feature Design
Page 44 of 48

<!-- page 45 -->
for them, and never calculate a figure. If an agent fails, the report still completes with that
section marked "not available", and the agent can be re-run alone.
Why three. Each has a different job and different tools, and the Writer and Critic loop is a
genuine multi-agent behaviour. Fewer agents would lose the loop. More would be agents
that decide nothing.
B. Backend services
The features are modules of one Python application. They call these eleven shared
services as library functions, so no service is deployed on its own.
architecture · 4 layers
AI Mortgage Copilot — Feature Design
Page 45 of 48

<!-- page 46 -->
Long jobs (OCR, extraction, agent runs) run in the background, and the frontend polls
their status. Every endpoint is scoped by a case ID, which groups one borrower scenario's
documents and results.
C. Demo data and storage
Nearly all borrower data is synthetic. The two exceptions are the public Fannie Mae,
Freddie Mac and Regulation X documents, which are real.
Service
What it does
Used by features
CPS-01 Ingestion and
OCR
Stores originals unchanged, runs OCR,
numbers every line with its position
1
CPS-02 LLM Gateway
The only route to Gemini: versioned
prompts, schema-checked output, one
retry, document text treated as data
1 to 3, 5 to 9
CPS-03 Schema
Registry
One field list and classifier description per
document type
1, 4
CPS-04 Calculations
All arithmetic, in decimal, returning its
working
2, 3, 4, 6, 7, 8
CPS-05 Rules and
Config
Checklists, methods, thresholds, rule sets
and templates, each versioned and
labelled authoritative or illustrative
1, 2, 3, 4, 5, 7, 8, 9
CPS-06 RAG Service
Loads sources, embeds, retrieves, checks
citations
5, and through it 6
and 8
CPS-07 Agent Layer
LangGraph workflows with typed state
6, 8
CPS-08 Evidence
Model
Links every finding to a document line,
passage, calculation or rule
All
CPS-09 Human Review
Confirm, correct, reject or override
anything; originals kept
All
CPS-10 Report Builder
Builds reports and drafts from stored
results; the LLM writes only narrative
6, 8, 9
CPS-11 Audit Store
Append-only record of every upload, AI
call, calculation and review action
All
AI Mortgage Copilot — Feature Design
Page 46 of 48

<!-- page 47 -->
How many files. About 20 to 25. The two demo stories use about 16 (eight for each
borrower). The rest are deliberately broken: a password-protected PDF, a corrupt PDF, an
unsupported format, a duplicate upload, and low-quality scans.
How they are made. One scenario file per borrower holds every figure. A script renders all
of that borrower's documents from it, so numbers such as 2,033.61 or 1,720.00 are
identical wherever they appear. A second script degrades some copies to look scanned or
photographed.
Storage. For the prototype everything runs on one machine, with local file storage. GCS or
S3 can replace it later. No real borrower data should be used, because document text is
sent to Document AI and Gemini.
D. Security and governance
Synthetic data only. Real borrower data would first need a data-handling review of the
OCR and LLM providers.
Data
Where it comes from
Where it lives
Borrower documents
Synthetic, created by the
team
Originals in file storage;
metadata in PostgreSQL
Extracted fields, flags,
calculations, reports,
reviews, audit log
Produced by the system
PostgreSQL
Fannie Mae and Freddie Mac
guides, Regulation X
Real public documents,
downloaded by the team
Source files in file storage;
chunks and embeddings in
the vector store (ChromaDB
or FAISS)
Lender overlay, investor
guide
Illustrative, written by the
team
Same as the real guides
Checklists, income method,
rule sets, lender view
settings, templates,
thresholds
Illustrative, written by the
team
Versioned configuration files
with the code; each run
records the version used
Loan scenario, loan record,
sample automated
underwriting findings
Small JSON files written by
the team
Loaded into PostgreSQL by a
seed script
AI Mortgage Copilot — Feature Design
Page 47 of 48

<!-- page 48 -->
Roles. Three seeded demo roles: loan processor or underwriter, loss mitigation
specialist and administrator, each with a simple login. There is no full identity system.
Sensitive values. Extracted data keeps only the last four digits of Social Security and
account numbers, and the screens mask them. Logs hold IDs, not document text.
Hardship letters are visible only to users on the case, and sensitive circumstances are
kept as a category and a financial effect, never as detail.
Audit. Every upload, AI call, calculation, review and approval is recorded in an append-
only log. Corrections never overwrite the original value.
People decide. No screen or report presents a decision. A sign-off records that a
person reviewed a report. Nothing is sent by the system.
Untrusted text. Text inside a document is treated as data and never as instructions to
the AI.
Controlled configuration. Only an administrator can change a checklist, rule set,
template or threshold. Every version is kept, and every result records the version it
used.
Retention. The retention period is configuration, and an administrator can delete a
whole case and its data, which is itself logged.
AI Mortgage Copilot — Feature Design
Page 48 of 48
