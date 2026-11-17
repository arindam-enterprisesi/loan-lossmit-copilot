# Document Intelligence — Functional and Design Specification (8)

_Converted from PDF (23 pages). Source: Copilots/Specs/Document Intelligence — Functional and Design Specification (8).pdf_

<!-- page 1 -->
Document Intelligence — Functional and
Design Specification
​Nov 3, 2026 · Abhay B Suvarna
This document specifies the Document Intelligence module of the AI Mortgage Copilot. It
merges the original FRD sections on document intelligence, understanding and
completeness with the later design decisions on S3, multi-tenancy, the neutral OCR
format, the pipeline and search.
1. Overview and scope
Document Intelligence takes borrower documents from the browser into S3, reads them
with OCR and an LLM, classifies and extracts them, checks the results in code, shows
them for review, indexes them for search and compares the case with a checklist. Both
pillars use it. It replaces F-DI, F-DU, F-DC and the document step of F-LDI in the original
FRD.
Item
Description
Example
Not in
scope
Fraud checks; splitting multi-
document files; handwriting;
borrower portals and email intake;
loan decisions
A pay stub with altered figures is
read as printed, not tested for
forgery. One PDF holding a W-2 and a
pay stub is not split into two
documents.
Status
To build. Documents are synthetic;
checklists and thresholds are
illustrative
Daniel Reyes and Angela Whitfield
are synthetic borrowers, and the 30-
day pay stub rule is a sample value,
not a lender requirement.
Principles
Code does arithmetic and checks;
every value points to evidence;
people decide; the tenant is the
isolation boundary
Net pay of 2,033.61 is checked in
code as 3,070.50 minus 1,036.89, and
the value links to its source line on
the page. A reviewer confirms it
before it counts.
Document Intelligence — Functional and Design Specification
Page 1 of 23

<!-- page 2 -->
2. Actors and use cases
Actors. Case users are the loan processor, underwriter and loss mitigation specialist. The
administrator manages settings. Systems: the login provider, the worker, and the OCR
engine and LLM provider. Every use case needs a valid token and access to the case.
ID
Use case
Actors
Example
UC-
01
Sign in and receive a token
All
A seeded user signs in and
receives a signed token that
carries the user, tenant and
role.
UC-
02
Create or open a case
Case users
A processor opens the
underwriting case for
borrower Daniel Reyes.
UC-
03
Upload documents
Case users
Daniel's photographed pay
stub goes straight to S3
through a one-time link.
UC-
04
Confirm or change a
document type
Case users
A bank statement uploaded
as Tax Return is switched to
Bank statement after the
mismatch question.
UC-
05
Review and correct extracted
values
Case users
A reviewer changes net pay
from 2,083.61 to 2,033.61 and
the flag clears.
UC-
06
View summaries, the
overview and persona views
Case users
A specialist opens Needs
review and sees only the
documents with flagged
fields.
UC-
07
Run and read the
completeness check
Case users
The check reports "14 of 30
days of pay stubs found", so
the case is Incomplete.
UC-
08
Override a checklist item
with a reason
Underwriter,
specialist
An underwriter marks the
August statement item as
satisfied and types a reason.
The computed status stays
visible beside it.
Document Intelligence — Functional and Design Specification
Page 2 of 23

<!-- page 3 -->
3. Functional requirements and test traceability
Each requirement maps to use cases and to a test. They replace the FR-DI, FR-DU and FR-
DC requirements of the original FRD. UC-01 to UC-13 each appear in at least one row, and
every row has a test.
ID
Use case
Actors
Example
UC-
09
Search or ask about the case
Case users
"Where does the 2,000.00
deposit appear?" returns a
cited answer that opens the
statement page.
UC-
10
Re-run a document or one
stage
Case users,
administrator
OCR timed out, so the user
re-runs only the OCR stage.
UC-
11
Delete a document or a case
Administrator
An administrator deletes the
utility bill uploaded by
mistake and receives a
deletion receipt.
UC-
12
Manage checklists,
thresholds and types; view
the audit trail
Administrator
An administrator edits the
pay stub coverage days. The
old version is kept and the
audit log records the change.
UC-
13
Process a document in the
background
Worker
After upload, the worker runs
OCR, classification,
extraction and checks, then
activates the run and indexes
it.
ID
Requirement
Use
case
Verified by
Example
FR-
DI01
Accept PDF, PNG
and JPEG through a
one-time S3 link;
reject bad files with
a reason; warn on
duplicates; keep
originals unchanged
and versioned
UC-
03
T-01 Valid, bad and
duplicate files
behave as
specified
Daniel uploads a pay stub
photo and it is stored as
original/{upload_id}.jpg.
Uploading the same file
again shows "This file is
already in the case. Keep it
anyway?"
Document Intelligence — Functional and Design Specification
Page 3 of 23

<!-- page 4 -->
ID
Requirement
Use
case
Verified by
Example
FR-
DI02
Take tenant, user
and role only from a
verified token;
tenant_id on every
row under forced
Row-Level Security;
S3 credentials
limited to the tenant
prefix; case access
checked; foreign IDs
return "not found"
UC-
01,
UC-
02
T-02 Two-tenant
and two-case
tests: nothing
crosses
A user from a second tenant
guesses a document ID from
tenant one and sees "We
couldn't find that item."
FR-
DI03
A run with a status
per stage;
idempotent jobs
retried only on
temporary errors; re-
run a document or
stage; one atomically
activated run
UC-
10,
UC-13
T-03 A killed
worker resumes
once; concurrent
re-runs leave one
active run
The worker is killed during
extraction. The stage
resumes once and exactly
one run ends up active.
FR-
DI04
Neutral OCR format
with boxes,
confidence and line
IDs; flag low-
legibility pages
UC-13
T-04 A poor scan is
flagged and
completes
A photographed pay stub
with a blurred second page
gets "Page 2 is hard to read"
and still reaches review.
FR-
DI05
Classify from
content only; apply a
type only when
certain; hold
extraction on a
strong mismatch
(4.4)
UC-
04
T-05 A statement
uploaded as Tax
Return holds
extraction
A bank statement uploaded
as Tax Return triggers "This
looks like a Bank statement,
but you chose Tax Return.
Which is right?" and
extraction waits.
FR-
DI06
Extract fields with
line IDs and
certainty; normalize
values; keep only the
last four digits of
sensitive numbers
UC-13
T-06 Clean
samples meet the
agreed rate
(proposed 95%);
logs show last four
only
An account number printed
as 000123456789 is stored
and shown as ****6789, and
logs hold no document text.
Document Intelligence — Functional and Design Specification
Page 4 of 23

<!-- page 5 -->
ID
Requirement
Use
case
Verified by
Example
FR-
DI07
Verify values against
cited lines, run the
4.3 checks, set
confidence (4.4) and
mark fields for
review
UC-
05
T-07 Net pay off by
50.00 fails DI-
CHK-02
OCR reads net pay 2,033.61
as 2,083.61. The value is in
the OCR text, but 3,070.50
minus 1,036.89 fails DI-CHK-
02, so the field is marked for
review.
FR-
DI08
Review beside the
document with
source highlight;
confirm, correct or
reject while keeping
originals; re-check
without an AI call;
template summaries;
overview and
persona views from
the index
UC-
05,
UC-
06
T-08 A correction
stores both values
and refreshes the
summary
A reviewer selects Net pay
and its box lights up on the
page image. After the
correction both values are
stored, checks re-run with
no AI call and the summary
refreshes.
FR-
DI09
Checklist per
borrower and
account with
computed statuses;
coverage, recency
and page counts in
code; template gap
messages; reviewer
overrides with a
reason
UC-
07,
UC-
08
T-09 "Page 1 of 3"
with 2 pages is
incomplete; an
override shows
the computed
status
The August statement says
"Page 1 of 3" but only 2
pages were uploaded, so the
item is Partially satisfied and
the gap message names the
missing page.
FR-
DI10
Index chunks in
pgvector after
activation; retrieve
by tenant, case and
active run; answer
only from passages
with verified
citations; semantic
cache per tenant
and case, exact-hash
cache for extraction
UC-
09
T-10 No matching
passage returns
"nothing found"
with no LLM call
A question with no matching
passage returns "Nothing
found in this case's
documents." and no LLM call
is made. A question that
contains an amount reuses a
cached answer only on an
exact match.
Document Intelligence — Functional and Design Specification
Page 5 of 23

<!-- page 6 -->
4. Document types, AI calls and validation
4.1 Document types
ID
Requirement
Use
case
Verified by
Example
FR-
DI11
Model and OCR calls
through gateways
that record provider,
model and prompt
version; schema
check with one retry;
document text is
data
UC-13
T-11 Invalid JSON is
retried once; an
injected
instruction is
ignored
The LLM returns invalid
JSON, the gateway retries
once and then fails the
stage. A line in a document
that says "ignore the rules"
is handled as text, not as an
instruction.
FR-
DI12
Append-only audit;
deletion removes
every copy with a
receipt; only
administrators
change checklists,
thresholds and
types
UC-11,
UC-12
T-12 The log
cannot be edited;
no copy remains
after deletion
An administrator deletes a
document: its S3 objects,
runs, chunks and cache
rows go and a receipt is
returned. A processor who
tries to change a checklist
threshold is rejected.
Type
Fields read
Example
Pay stub
Employee, employer, pay period
and date, gross and net pay,
year-to-date gross, earnings and
deduction lines
Daniel Reyes, pay period 2026-
09-14 to 2026-09-27, gross
3,070.50, deductions 1,036.89,
net 2,033.61.
W-2
Tax year, employee, employer,
boxes 1 to 6, Box 12
The 2025 W-2 for Daniel Reyes
with boxes 1 to 6. The 2024 W-2
is the one the case is missing.
Bank statement
Holders, institution, last four
digits, period, balances,
transactions
The August statement for Daniel
Reyes, with the account's last
four digits, its balances and a
2,000.00 deposit line.
Document Intelligence — Functional and Design Specification
Page 6 of 23

<!-- page 7 -->
4.2 AI calls
All calls go through a gateway with a provider interface (Bedrock preferred, Gemini for the
prototype). Prompts are versioned, and output is schema-checked with one retry.
Type
Fields read
Example
Form 1040
Tax year, filing status, taxpayer,
total and adjusted gross income,
wages
The 2025 return for Daniel
Reyes with filing status, total
income, adjusted gross income
and wages.
Loss mitigation
documents
Application (stated income,
expenses, hardship reasons,
intent), mortgage statement
(balance, payment parts, past
due, total due), benefits letter,
expense bill
Angela Whitfield's signed
application and her October
mortgage statement, with past
due and total due read from the
statement.
Credit report,
hardship letter
Classified here only. The credit
feature reads the report, and the
letter's text is kept for hardship
analysis
A sample credit report is
classified and handed to the
credit feature. Angela's
hardship letter is kept as text.
Call
Input to output
Rules
Example
OCR
Page images to the
neutral format
Engine chosen by bake-
off (Textract, Mistral
OCR 4.1)
A photographed pay stub
becomes blocks with
boxes, confidence and line
IDs, whichever engine
read it.
Classify
(LLM)
First pages to type,
certainty, evidence
Content only, never file
names
A file named w2.pdf that
holds a bank statement is
classified as Bank
statement, with the
evidence lines that show
it.
Extract
(LLM)
Field list and lines to
values, line IDs,
certainty
Text only; no arithmetic;
batches merged in code
Net pay comes back as
printed, with its line ID
and certainty. The LLM
does not add up the
earnings lines.
Document Intelligence — Functional and Design Specification
Page 7 of 23

<!-- page 8 -->
4.3 Validation checks
Checks run in code with configured tolerances, and a check missing a field says "cannot
check". General rules: each value is in its cited lines, evidence lines exist, the schema is
valid, and required fields are present.
Call
Input to output
Rules
Example
Embed
Chunks to vectors
One model per table,
recorded
A chunk labelled "Pay
stub, Daniel Reyes, 2026-
09-14 to 2026-09-27"
becomes a vector, and the
model name is stored with
it.
Answer
(LLM)
Question and
passages to cited
sentences
Passages only; a citation
per sentence
The question about the
2,000.00 deposit gets one
sentence that cites the
statement page.
Checks
Rule
Example
DI-CHK-01 to 04, pay
stub
Earnings add up to gross; gross
minus deductions equals net;
period start is not after end;
year-to-date is not below
current
Gross 3,070.50 minus
deductions 1,036.89 must equal
net 2,033.61, so a net pay read
as 2,083.61 fails DI-CHK-02.
DI-CHK-05 to 08,
bank statement
Balances reconcile with
transactions; printed totals and
running balances agree;
transactions fall inside the
period
A September statement that
holds a transaction dated in
August fails DI-CHK-08.
DI-CHK-09, W-2
Valid tax year; no negative
amounts
A W-2 with a negative Box 1
amount fails DI-CHK-09.
DI-CHK-10, Form 1040
Valid tax year; filing status is one
of the five options
A filing status that matches
none of the five options is
flagged for review.
Document Intelligence — Functional and Design Specification
Page 8 of 23

<!-- page 9 -->
4.4 Confidence and type decision
Confidence. High: the cited lines meet the OCR threshold, the value was found in them
and the LLM's certainty is high. Low: the value or its source was not found, certainty is
low, or OCR confidence is below the threshold. Medium: everything else. A field needs
review if it is Low, in a failed check, or required and missing.
Type decision. Auto-detect applies a type only when certain; otherwise the status is "type
needed", and Unrecognized stays out of the checklist. A chosen type that differs from the
prediction holds extraction when certainty is high, and is flagged when lower.
5. Architecture and workflow
One FastAPI backend. Files go straight to S3, a worker runs the pipeline one stage at a
time, and every row and key belongs to a tenant.
Document Intelligence — Functional and Design Specification
Page 9 of 23

<!-- page 10 -->
5.1 High-level solution architecture
The browser uploads straight to S3 through a one-time link, the API queues the job, and a
worker runs the pipeline against the OCR engine and LLM providers. Every store is
scoped to the tenant that the token carries.
high-level solution architecture · client, application, providers, storage
Document Intelligence — Functional and Design Specification
Page 10 of 23

<!-- page 11 -->
5.2 Flow
document intelligence flow · sequence, 31 steps
Document Intelligence — Functional and Design Specification
Page 11 of 23

<!-- page 12 -->
Upload (1 to 9): the API verifies the token, creates the rows and returns an upload link; the
file goes straight to S3; the API checks the hash and queues the job. Process (10 to 26): a
worker reads the original, runs OCR, classifies, extracts, verifies in code, activates the run
and indexes the chunks. Each stage keeps its own status and can be re-run alone. Review
(27 to 31): reads go through the API and Row-Level Security, and a correction is saved
beside the original.
5.3 Storage and tenancy
The token carries user, tenant and role, and the backend never trusts a tenant from the
request. The backend creates every S3 key, and the browser gets a one-time link for one
key. PostgreSQL holds the index (IDs, stage status, S3 key and version, hash, uploader and
persona, assignment), and persona views come from it, not from S3.
tenants/{tenant_id}/use-
cases/{use_case}/cases/{case_id}/documents/{document_id}/
  original/{upload_id}.{ext}
  runs/{run_id}/   raw/  pages/  ocr.json  tables/  figures/  extraction.json
Example key: tenants/tenant-1/use-cases/underwriting/cases/case-
1/documents/doc-1/original/upload-1.pdf
Isolation is enforced twice: credentials limited to the tenant prefix, and Row-Level
Security on every table. Keys hold no names or personal data.
5.4 Connectors
Connector
Use
Example
Amazon S3
Files, one prefix per tenant,
presigned links
Daniel's pay stub photo is written
under its tenant's prefix through
a presigned link that works for
that one key.
PostgreSQL with
pgvector
Index, vectors, cache; Row-Level
Security
The stage statuses of Daniel's
pay stub and the vectors of its
chunks sit in the same database,
and every row carries the tenant.
Amazon SQS
One job per run, with a dead-
letter queue
Completing an upload queues
one job. A job that keeps failing
lands in the dead-letter queue
and raises an alert.
Document Intelligence — Functional and Design Specification
Page 12 of 23

<!-- page 13 -->
5.5 Endpoints
No endpoint takes a tenant ID. It comes from the token.
Connector
Use
Example
OCR engine
Chosen by bake-off; an adapter
converts to the neutral format
If Mistral OCR 4.1 replaces
Textract, only the adapter that
converts its output to the neutral
format changes.
LLM provider
Bedrock preferred, Gemini for
the prototype
The prototype calls Gemini
through the gateway. An AWS
deployment switches the
provider to Bedrock.
Login provider and
KMS
Seeded tokens now, Amazon
Cognito later; encryption keys
A seeded user receives a signed
token today and Amazon Cognito
issues the same shape later. KMS
keys encrypt the stored files.
Endpoint
Purpose
Example
POST /cases/{id}/documents/uploads
Get an upload
link
The browser asks
for a link for a pay
stub photo and
receives a
presigned POST
for one exact S3
key.
POST
/cases/{id}/documents/{doc}/uploads/{upload}
/complete
Verify the hash
and queue the
run
After the browser
finishes the S3
upload, this call
checks the SHA-
256 and queues
the run.
GET /cases/{id}/documents
List; filters give
the persona
views
The Needs review
filter returns only
the documents
that have flagged
fields.
Document Intelligence — Functional and Design Specification
Page 13 of 23

<!-- page 14 -->
Endpoint
Purpose
Example
POST /cases/{id}/documents/{doc}/runs
Re-run a
document or
one stage
The LLM was busy
during extraction,
so the user re-
runs only that
stage.
GET /cases/{id}/documents/{doc}/extraction
Fields, flags and
summary
Returns the fields
of the active run
with their flags
and the summary
of the pay stub.
PATCH
/cases/{id}/documents/{doc}/fields/{field}
Confirm or
correct a value
A reviewer sends
net pay 2,033.61. If
someone else
changed the field
first, the call
returns an edit
conflict.
PUT /cases/{id}/documents/{doc}/type
Confirm or
change the type
The user confirms
Bank statement
for a file that was
uploaded as Tax
Return.
GET
/cases/{id}/documents/{doc}/pages/{page}
Short-lived
page link
Returns a short-
lived link to the
page image so the
source line can be
highlighted.
POST /cases/{id}/completeness
Run the
checklist; GET
.../latest reads it
POST runs the
checklist for
Daniel's case, and
GET .../latest
returns the last
result.
POST /cases/{id}/ask
Ask about the
case's
documents
The question
"Where does the
2,000.00 deposit
appear?" returns a
cited answer.
Document Intelligence — Functional and Design Specification
Page 14 of 23

<!-- page 15 -->
6. Searching the case's documents (RAG)
A person can ask a question about one case's own documents and get an answer from
that case's passages only, with a citation for every sentence. The agents use the same
search. Guideline questions use the shared sources in the guidance feature.
What the user does
1. Types a question in the case's search box, optionally limited to one document or type.
2. Reads a short answer in which each sentence cites a document and page.
3. Clicks a citation, and the page opens with the passage highlighted.
4. Sees "nothing found in this case's documents" when nothing is relevant, never a guess.
Indexing. When a run is active, the worker chunks each document along its OCR blocks (a
table stays whole, a figure keeps its caption), prefixes each chunk with a label such as
"Pay stub, Daniel Reyes, 2026-09-14 to 2026-09-27", embeds it and stores it in pgvector
with tenant, case, run, document and page.
searching the case · sequence, 16 steps
Document Intelligence — Functional and Design Specification
Page 15 of 23

<!-- page 16 -->
Answering. The token and case access are checked, and the cache is looked up for this
tenant and case (a similarity hit counts only for questions without numbers or dates). The
question is embedded with the same model. Vector plus keyword search, because
embeddings are weak at exact figures, is filtered by tenant, case and active run, with
Row-Level Security as a second guard. Passages below the threshold are dropped, and
with none left the answer is "nothing found" and the LLM is not called. Otherwise the LLM
answers from the passages with a citation per sentence, code removes any sentence
whose citation or figure fails, and a corrected value is shown beside the OCR text. A
question on one case never searches another case's chunks, and chunk IDs identify
passages but are not the access control.
7. Completeness checking
The check compares classified documents with a configurable checklist, and code
decides every status. Checklist values are illustrative samples. Real ones come from the
lender or program.
Overall. Incomplete if any required item is Missing or Partially satisfied; otherwise Needs
review if any item needs review; otherwise Complete for this checklist. Overrides count
as satisfied. It is never a loan decision.
Order
Condition
Item status
Example
1
No usable documents of the
required type for the borrower
or account
Missing
Angela Whitfield's case has no
August bank statement, so
that statement item is Missing.
2
A needed field not found, owner
uncertain, document future-
dated, or page completeness not
assessed
Needs
review
A pay stub dated after the
reference date is future-dated,
so the pay stub item needs
review.
3
Documents exist but coverage is
short, a year is absent, the latest
date is too old, or a document is
incomplete
Partially
satisfied
Daniel's pay stubs cover 14 of
30 days, so the pay stub item is
Partially satisfied. His 2024 W-
2 is absent, so the W-2 item is
Partially satisfied too.
4
Everything required is met
Satisfied
A credit report dated within
120 days of the reference date
satisfies the credit report item.
Document Intelligence — Functional and Design Specification
Page 16 of 23

<!-- page 17 -->
Rules. Days are counted inclusively, and overlapping or adjacent ranges are continuous. N
months of coverage means the end date is on or after the start plus N months minus a day.
Recency is the days from the latest document date to the reference date. Required tax
years are the reference year minus configured offsets. Bank statements are per account,
and names are matched in code. For example, stubs for 2026-09-14 to 2026-09-27 and
2026-09-28 to 2026-10-11 sit on adjacent days, so they count as one 28-day span.
Sample checklist (illustrative). Pay stubs covering 30 days, W-2s and returns for two
years, bank statements covering two months, and a credit report within 120 days. For loss
mitigation: signed application, hardship letter, pay stubs (30 days) and bank statements (2
months).
8. Non-functional requirements
Targets are proposals until measured.
Category
Requirement and
proposed target
Verified by
Example
Performance
A 5-page digital document
is ready for review within
90 s (p95, excluding queue
wait); a review page opens
within 1 s; a case search
answers within 8 s
Timed runs
A 5-page digital bank
statement is timed from
the start of its run to the
review-ready state,
leaving out the time it
waited in the queue.
Capacity and
reliability
20 documents at once; no
duplicate output; one
active run; a stage
resumes after a worker
crash; daily backup, RPO
24 h, RTO 4 h
Load test,
T-03
Twenty documents are
uploaded together and all
finish without failures.
After a restore drill, no
more than 24 hours of
data is lost.
Accuracy
At least 95% of required
fields on clean samples;
every clean sample
classified correctly
T-06
If a clean sample has 40
required fields, at least 38
must be extracted
correctly.
Security, tenancy,
privacy
TLS; KMS encryption; no
public bucket; zero cross-
tenant leaks on every
release; last four digits
only; no document text in
logs; deletion within 1 h
T-02, T-06,
T-12
The isolation suite runs
on every release and a
second tenant's user
finds nothing. A deleted
document is gone from
every store within 1 hour.
Document Intelligence — Functional and Design Specification
Page 17 of 23

<!-- page 18 -->
9. Error and message catalog
DI-E errors stop a stage, DI-W warnings appear as flags, and DI-I is information. Messages
are plain language with a reference ID, and never reveal whether another tenant's item
exists.
Category
Requirement and
proposed target
Verified by
Example
Auditability and
observability
Every action in the
append-only log; per-stage
latency, failures, retries
and cost per document;
alerts on dead-letter
depth
T-12, demo
check
A job that exhausts its
retries lands in the dead-
letter queue, an alert
fires and the log shows
each attempt.
Usability
Keyboard navigation in
review; colour never the
only signal; WCAG 2.1 AA
as the aim
Manual
check
A reviewer moves
between flagged fields
with the keyboard, and a
flag carries a label as well
as a colour.
Portability and
cost
Swapping an OCR engine
changes only its adapter;
cost per run tracked and
capped
Adapter
test
Moving from Textract to
Mistral OCR 4.1 changes
one adapter, and the cost
report shows each run's
cost against the cap.
Code and cause
Message shown
Recovery
Example
DI-E101 Token invalid
or expired
"Your session has
expired. Sign in again."
Sign in
A token expires
while a reviewer
reads a page, and
the next request
shows the sign-in
message.
DI-E102 Another
tenant's ID, or no case
access
"We couldn't find that
item."
None; same
message for both
A guessed
document ID from
another tenant and
a case the user
cannot access both
show this same
message.
Document Intelligence — Functional and Design Specification
Page 18 of 23

<!-- page 19 -->
Code and cause
Message shown
Recovery
Example
DI-E201
Unsupported,
oversized, password-
protected, corrupt or
empty file
"We couldn't use this
file: {reason}."
Fix it and upload
again
A password-
protected PDF is
rejected and the
message names the
reason.
DI-E205 Upload
incomplete; DI-W206
duplicate
"The upload didn't
finish. Please upload it
again." or "This file is
already in the case.
Keep it anyway?"
Upload again, or
keep or discard
The browser closes
before "upload
done", so the user
uploads again.
Uploading the same
pay stub twice asks
whether to keep
the copy.
DI-E301 OCR failed;
DI-W304 page hard to
read
"Reading the
document failed. We'll
retry automatically."
or "Page {n} is hard to
read. Check the
values taken from it."
Backoff retries,
then Retry
OCR times out and
is retried with
backoff. A blurred
page 2 shows "Page
2 is hard to read.
Check the values
taken from it."
DI-E401 LLM busy,
invalid, refused or cut
off
"We couldn't read this
document reliably. Re-
run it or enter the
values by hand."
Retry, fallback
provider, Re-run
The LLM returns
invalid JSON again
after its one retry,
so the user can re-
run the stage or
enter the values by
hand.
DI-W501 Type unsure;
DI-W502 chosen type
disagrees
"We couldn't tell what
this document is.
Choose its type." or
"This looks like a
{predicted}, but you
chose {selected}.
Which is right?"
Choose;
extraction held
A utility bill stays at
"type needed" and
out of the checklist.
A bank statement
chosen as Tax
Return asks which
type is right.
Document Intelligence — Functional and Design Specification
Page 19 of 23

<!-- page 20 -->
Code and cause
Message shown
Recovery
Example
DI-W601 Value not
found; DI-W603
check failed; DI-
W604 field missing
"We couldn't find this
value in the text it
came from."; the failed
rule and fields (4.3); "
{Field} wasn't found in
this document."
Check, correct or
enter by hand;
checks re-run
Net pay of 2,083.61
fails DI-CHK-02 and
the flag names the
rule and the fields.
A pay stub without
an employer shows
"Employer wasn't
found in this
document."
DI-W701 Checklist
gap or page mismatch
Template text, such as
"14 of 30 days of pay
stubs found"
Request or upload
documents
The pay stub item
shows "14 of 30
days of pay stubs
found", and the
user requests more
stubs from the
borrower.
DI-E801 Stage failed
or interrupted
"Processing stopped
at {stage}. You can re-
run this stage."
Re-run; dead-
letter alert
A worker crash
during extraction
shows that
processing stopped
at that stage, and
the user re-runs
only it.
DI-E803 Edit conflict
"Someone else
changed this value.
Review the latest and
try again."
Reload
Two reviewers edit
net pay at once. The
second one sees
the conflict
message and
reloads.
DI-I901 No passage;
DI-E902 search not
ready
"Nothing found in this
case's documents." or
"Search isn't ready for
this document yet.
You can still review it."
Rephrase, or
automatic retry
A question about
something that is
not in the case
returns "Nothing
found". Searching
before indexing
finishes says
search isn't ready,
and review still
works.
Document Intelligence — Functional and Design Specification
Page 20 of 23

<!-- page 21 -->
10. Failure modes and safeguards
Layer
What can go wrong
Safeguard
Example
Identity and
isolation
Forged or expired
token; one tenant or
case reaching another's
files, rows, search or
cache
Verified token; tenant
only from it; tenant-
scoped credentials;
forced Row-Level
Security with a non-
owner role; case
access checks; "not
found" for foreign IDs;
two-tenant and two-
case tests
A forged token is
rejected. Even with a
valid token, a case the
user cannot access
returns "We couldn't
find that item."
Upload and
storage
Partial, corrupt or
duplicate uploads; S3
and database disagree;
half-finished delete
Limits, type and hash
checks; lifecycle rule
for incomplete
uploads; reconciler;
deletion as a retried
job with a receipt
The browser closes
before "upload done".
The lifecycle rule
clears the partial file
and the reconciler
fixes any mismatch
with the database.
Worker and
queue
Crash mid-stage;
duplicate or poison
messages; racing re-
runs
Retry limits, dead-
letter queue,
idempotency keys,
atomic activation
Two users re-run the
same document at
once. Atomic
activation leaves
exactly one active run.
OCR and
LLM
Misread digits or
tables, outage, invalid
output, refusal, cut-off,
hidden instructions
Confidence flags and
arithmetic checks; a
second engine to
cross-check numbers;
schema check and one
retry; fallback provider;
batching; document
text as data; spending
caps
OCR reads 2,033.61 as
2,083.61 and the
arithmetic check flags
it. A line in a
document that says
"ignore the rules" is
treated as text.
Document Intelligence — Functional and Design Specification
Page 21 of 23

<!-- page 22 -->
11. Demo scenario
Synthetic borrowers and documents are generated from one scenario file per borrower,
so figures match across documents.
Daniel Reyes (underwriting). Six files are classified from content. A bank statement he
labelled "Tax Return" is caught, and a utility bill stays out. OCR reads net pay 2,033.61 as
2,083.61, and only the arithmetic check catches it (3,070.50 minus 1,036.89). The
completeness check finds the pay stubs 16 days short, the 2024 W-2 and return missing,
and page 3 of the August statement missing, so the status is Incomplete. A search for the
2,000.00 deposit opens the statement page with the line highlighted.
Angela Whitfield (loss mitigation). Seven documents are classified correctly, the
mortgage statement reconciles with the loan record, and the checklist shows the August
bank statement missing.
Isolation. A user from a second tenant cannot list, open, overwrite or search these
documents.
Layer
What can go wrong
Safeguard
Example
Extraction
and review
Missing or
contradictory values;
two reviewers on one
field
Missing-field flags; the
document still reaches
review; version check
per edit; corrections
survive re-runs
The employer is
missing from a pay
stub. The field is
flagged, the
document still
reaches review, and a
later re-run does not
erase a reviewer's
correction.
Search and
cache
Stale vectors; wrong
cache hit; injection
inside a chunk
Old chunks go inactive;
delete removes every
copy; exact-hash
cache for extraction;
passages as data;
search never blocks
review
A new run makes the
old chunks inactive, so
a search never returns
stale vectors.
Platform
A pooled connection
keeps another tenant's
setting; KMS key
disabled; throttling or
outage; personal data
in logs; no restore plan
Tenant set per
transaction; key-
deletion protection;
backoff; log scrubbing;
tested restore; alerts
A pooled database
connection could
carry the previous
tenant's setting, so
the tenant is set again
in every transaction.
Document Intelligence — Functional and Design Specification
Page 22 of 23

<!-- page 23 -->
12. Open decisions
OCR engine: a bake-off of Textract and Mistral OCR 4.1 on about 20 sample pages.
LLM provider: Bedrock preferred, Gemini for the prototype; one embedding model per
vector table.
Targets: the 95% accuracy figure and the section 8 numbers are proposals until
measured.
Content: real checklists and the wording of messages need review by the lender,
design and compliance.
Indexes: exact vector search first; an approximate index only after a recall test.
Keys and retention: whether to use per-tenant keys, and the retention period.
Document Intelligence — Functional and Design Specification
Page 23 of 23
