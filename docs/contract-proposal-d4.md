# Contract proposal for Day 4 (for Arindam's own contract PR)

The backend already serves these endpoints. The contract (`contracts/openapi.yaml`) names the
completeness `POST` and `GET .../latest` only; the income, page-image and hardship endpoints are TODO
comments and the completeness override has no endpoint. Abhay does not edit `contracts/`, so this is
the YAML to add (sections 1 and 2 from D4, sections 3 and 4 from D5, sections 5 to 7 from D6).
The routes use the Feature Design's paths; if you prefer `/income/analysis` (the TODO's spelling),
it is a one-line change of the router prefix.

## 1. Completeness: add the override endpoint and the "needs review" values

The contract's `CompletenessItemStatus` is `satisfied, partial, missing, overridden` and
`CompletenessResult.overall_status` is `complete, incomplete`. The FSD (section 7) also has
**needs review** (a needed field was not found, the owner is uncertain, a document is future-dated).
Today the backend sends a needs-review item as `partial` with the reason starting `Needs review:`
and a needs-review overall as `incomplete`. If you add the values, say so and the backend sends them.

```yaml
  /cases/{case_id}/completeness/latest/items/{item_id}:
    parameters:
      - $ref: "#/components/parameters/CaseId"
      - name: item_id
        in: path
        required: true
        schema: {type: string, examples: ["pay_stubs_30_days"]}
    patch:
      tags: [completeness]
      operationId: overrideCompletenessItem
      summary: Override a checklist item with a written reason, or clear the override
      description: |
        An override counts as satisfied. The status code computed stays beside it. Only the latest
        result can be changed; running the checklist again starts without overrides.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [action]
              additionalProperties: false
              properties:
                action: {type: string, enum: [override, clear]}
                reason:
                  type: string
                  maxLength: 500
                  description: Required when action is override.
      responses:
        "200":
          description: The updated result
          content:
            application/json:
              schema: {$ref: "#/components/schemas/CompletenessResult"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}
        "409":
          description: |
            code is already_overridden, nothing_to_override (the item is satisfied) or no_override
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Error"}
        "422": {$ref: "#/components/responses/ValidationFailed"}
```

`POST /cases/{case_id}/completeness` already lists 422. The backend uses these codes there:
`profile_required` (borrower names and reference date not set), `unknown_checklist`,
`wrong_checklist` (a checklist for the other pillar or another employment type).

## 2. Income analysis (Feature Design 2.7)

```yaml
  /cases/{case_id}/income-analysis:
    parameters:
      - $ref: "#/components/parameters/CaseId"
    post:
      tags: [income]
      operationId: runIncomeAnalysis
      summary: Queue an income analysis of the case's documents
      responses:
        "202":
          description: Queued. Poll the job, then read /latest.
          content:
            application/json:
              schema:
                type: object
                required: [job, analysis_id]
                properties:
                  job: {$ref: "#/components/schemas/Job"}
                  analysis_id: {type: string, format: uuid}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}
        "503": {$ref: "#/components/responses/ServiceUnavailable"}

  /cases/{case_id}/income-analysis/latest:
    parameters:
      - $ref: "#/components/parameters/CaseId"
    get:
      tags: [income]
      operationId: getLatestIncomeAnalysis
      summary: The newest income analysis
      responses:
        "200":
          description: Components, figures with their working, flags
          content:
            application/json:
              schema: {$ref: "#/components/schemas/IncomeAnalysis"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}

  /cases/{case_id}/income-analysis/latest/components/{component_id}:
    parameters:
      - $ref: "#/components/parameters/CaseId"
      - name: component_id
        in: path
        required: true
        schema: {type: string, format: uuid}
    patch:
      tags: [income]
      operationId: reviewIncomeComponent
      summary: Include or exclude a component, with a reason
      description: |
        Recalculates the candidate at once. No model is called. The reason is required either way.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [included, reason]
              additionalProperties: false
              properties:
                included: {type: boolean}
                reason: {type: string, minLength: 1, maxLength: 500}
      responses:
        "200":
          description: The updated analysis
          content:
            application/json:
              schema: {$ref: "#/components/schemas/IncomeAnalysis"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}
        "409":
          description: code is stale_analysis (a newer analysis has replaced this one)
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Error"}
        "422": {$ref: "#/components/responses/ValidationFailed"}
```

Schemas (amounts are strings, so they stay exact; the client never adds them up):

```yaml
    IncomeRef:
      type: object
      required: [document_id, field, line_ids]
      properties:
        document_id: {type: string, format: uuid}
        field: {type: string}
        line_ids: {type: array, items: {type: string}}
    IncomeCalc:
      type: object
      required: [id, name, value, unit, formula, inputs, working, config_version, evidence]
      properties:
        id: {type: string, format: uuid}
        name: {type: string}
        value: {type: string, examples: ["5980.00"]}
        unit: {type: string, enum: [usd, ratio, count, days, months, match]}
        formula: {type: string}
        inputs: {type: object, additionalProperties: {type: string}}
        working: {type: string, examples: ["34.50 x 80.00 x 26 / 12 = 5,980.00"]}
        config_version: {type: string}
        evidence: {type: array, items: {$ref: "#/components/schemas/IncomeRef"}}
    IncomeComponent:
      type: object
      required: [id, borrower, employer, component, current_period, ytd, monthly, included,
                 exclusion_reason, system_included, system_exclusion_reason, override, calculation]
      properties:
        id: {type: string, format: uuid}
        borrower: {type: string}
        employer: {type: [string, "null"]}
        component: {type: string, enum: [base, overtime, bonus, commission]}
        current_period: {type: [string, "null"]}
        ytd: {type: [string, "null"]}
        monthly: {type: string}
        included: {type: boolean}
        exclusion_reason: {type: [string, "null"]}
        system_included: {type: boolean, description: What the system decided; never overwritten.}
        system_exclusion_reason: {type: [string, "null"]}
        override:
          description: A person's include or exclude, with who, when and why.
          oneOf:
            - type: "null"
            - type: object
              required: [included, reason, by, at]
              properties:
                included: {type: boolean}
                reason: {type: string}
                by: {type: string, format: uuid}
                at: {type: string, format: date-time}
        calculation: {oneOf: [{type: "null"}, {$ref: "#/components/schemas/IncomeCalc"}]}
    IncomeFlag:
      type: object
      required: [id, code, severity, message, status, working, refs]
      properties:
        id: {type: string, format: uuid}
        code: {type: string, examples: ["INC-W101"]}
        severity: {$ref: "#/components/schemas/Severity"}
        message: {type: string}
        status: {type: string, enum: [open, resolved, overridden]}
        working: {type: [string, "null"]}
        refs: {type: array, items: {$ref: "#/components/schemas/IncomeRef"}}
    IncomeAnalysis:
      type: object
      required: [id, case_id, status, started_at, finished_at, config_versions,
                 candidate_monthly_income, candidate_label, candidate, components, flags,
                 calculations, explanations, explanations_note]
      properties:
        id: {type: string, format: uuid}
        case_id: {type: string, format: uuid}
        status: {type: string, enum: [queued, running, succeeded, failed]}
        started_at: {type: string, format: date-time}
        finished_at: {type: [string, "null"], format: date-time}
        config_versions: {type: object, description: "{kind: {name, version, label, hash}}"}
        candidate_monthly_income: {type: [string, "null"], examples: ["5980.00"]}
        candidate_label:
          type: string
          examples: ["candidate — qualifying income is determined by the underwriter"]
        candidate: {oneOf: [{type: "null"}, {$ref: "#/components/schemas/IncomeCalc"}]}
        components: {type: array, items: {$ref: "#/components/schemas/IncomeComponent"}}
        flags: {type: array, items: {$ref: "#/components/schemas/IncomeFlag"}}
        calculations: {type: array, items: {$ref: "#/components/schemas/IncomeCalc"}}
        explanations:
          type: array
          items: {type: string}
          description: Your income-explain@1 results, each "possible - to be confirmed". Empty until wired.
        explanations_note: {type: string, examples: ["explanations not generated"]}
```

## 3. Page image link (D5; replaces the `TODO(D3+)` comment)

Built and tested on D5: `GET /cases/{case_id}/documents/{document_id}/pages/{page}`. The review screen
needs the page image beside the fields. The images are private in S3, so the API hands out a presigned
link that works for 5 minutes (`PRESIGN_SECONDS` in `app/storage.py`). `width` and `height` are the
stored image's size in pixels; the `BoundingBox` values on evidence are fractions of that image
(0 to 1, origin top left), so the viewer multiplies by these to draw a box.

The route answers 404 for an unknown or hidden case, an unknown document, a document of another case,
and a page number that is not there (zero, past the last page, not a number). It answers **503
`storage_unavailable`** when the link cannot be made, which the contract's other storage-backed
endpoints already list; `ServiceUnavailable` is reused below.

```yaml
  /cases/{case_id}/documents/{document_id}/pages/{page}:
    parameters:
      - $ref: "#/components/parameters/CaseId"
      - $ref: "#/components/parameters/DocumentId"
      - name: page
        in: path
        required: true
        description: Page number, counted from 1.
        schema: {type: integer, minimum: 1}
    get:
      tags: [documents]
      operationId: getPageImage
      summary: A 5-minute link to the stored image of one page
      responses:
        "200":
          description: The link and the image size
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/PageImage"
        "401":
          $ref: "#/components/responses/Unauthorized"
        "404":
          $ref: "#/components/responses/NotFound"
        "503":
          $ref: "#/components/responses/ServiceUnavailable"
```

```yaml
    PageImage:
      type: object
      required: [page, url, expires_at, width, height]
      properties:
        page: {type: integer, minimum: 1}
        url:
          type: string
          description: Presigned link to the PNG. Fetch it with no extra headers; it expires.
        expires_at: {type: string, format: date-time}
        width: {type: integer, minimum: 1, description: Pixels of the stored image.}
        height: {type: integer, minimum: 1, description: Pixels of the stored image.}
```

If the frontend reads the image with `fetch` or a canvas (not an `<img>` tag), the S3 bucket needs its
own CORS rule in AWS; that is not in this repository.

## 4. Hardship profile, read side (D5; replaces the `TODO(F7 ...)` comment)

Built and tested on D5: `GET /cases/{case_id}/hardship-assessment/latest`. The path is the Feature
Design's (section 7.7), not the TODO's `/hardship/profile`. It returns Angela's letter read into a
profile. On D5 the profile is a **seeded sample** (`source: seeded_sample`, the Feature Design 7.8
reading stored without a model call, with every quote still checked in code against the letter's
lines), so the v0.5 screen works before a provider does. The POST that runs your `read_hardship_letter`,
the confirmations and the budget are D6 and will add to this shape; `budget` and `measures` are
reserved arrays, empty today.

Each item carries its `quote`, the `lines` it came from (rule 2) and `verified`: code found the quote
in those lines. `check_flags` holds your check's codes (`unverified_quote`, `quote_too_long`). A failed
quote also appears in `flags` (the contract's `Flag`), with evidence pointing at the cited lines of the
letter. Line IDs are only unique within a document, so `letter_document_id` names the letter (null when
none is on the case). Reason `category_label` and `sensitive` come from `hardship.yaml`.

404 for an unknown or hidden case (a Pillar 1 case is hidden from the loss-mitigation specialist and
the other way round) and for a case with no profile yet.

```yaml
  /cases/{case_id}/hardship-assessment/latest:
    parameters:
      - $ref: "#/components/parameters/CaseId"
    get:
      tags: [hardship]
      operationId: getLatestHardshipAssessment
      summary: The latest hardship profile read from the borrower's letter
      responses:
        "200":
          description: The profile, each item with its quote, lines and verified state
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/HardshipAssessment"
        "401":
          $ref: "#/components/responses/Unauthorized"
        "404":
          $ref: "#/components/responses/NotFound"
```

```yaml
    HardshipQuoted:
      type: object
      required: [quote, lines, verified, check_flags]
      properties:
        quote:
          type: [string, "null"]
          description: A short quote copied exactly from the letter; null when the letter says nothing about it.
        lines:
          type: array
          items: {type: string, examples: ["p1-L6"]}
        verified: {type: boolean, description: Code found the quote in the cited lines.}
        check_flags:
          type: array
          items: {type: string, examples: [unverified_quote, quote_too_long]}
    HardshipReason:
      allOf:
        - $ref: "#/components/schemas/HardshipQuoted"
        - type: object
          required: [category, category_label, sensitive, financial_effect]
          properties:
            category: {type: string, examples: [reduction_in_income]}
            category_label: {type: string, examples: [Reduction in income]}
            sensitive: {type: boolean}
            financial_effect: {type: string}
    HardshipProfile:
      type: object
      required: [primary_reason, other_reasons, onset, duration, intent, timeline, enclosed_documents]
      properties:
        primary_reason: {$ref: "#/components/schemas/HardshipReason"}
        other_reasons: {type: array, items: {$ref: "#/components/schemas/HardshipReason"}}
        onset:
          allOf:
            - $ref: "#/components/schemas/HardshipQuoted"
            - type: object
              required: [as_stated, month]
              properties:
                as_stated: {type: [string, "null"], examples: [July]}
                month: {type: [string, "null"], pattern: "^[0-9]{4}-[0-9]{2}$", examples: ["2026-07"]}
        duration:
          allOf:
            - $ref: "#/components/schemas/HardshipQuoted"
            - type: object
              required: [category]
              properties:
                category: {type: string, enum: [temporary, long_term, unknown]}
        intent:
          allOf:
            - $ref: "#/components/schemas/HardshipQuoted"
            - type: object
              required: [category]
              properties:
                category: {type: string, enum: [keep, sell, unsure]}
        timeline:
          type: array
          items:
            allOf:
              - $ref: "#/components/schemas/HardshipQuoted"
              - type: object
                required: [when, event]
                properties:
                  when: {type: [string, "null"]}
                  event: {type: string}
        enclosed_documents:
          type: array
          items:
            allOf:
              - $ref: "#/components/schemas/HardshipQuoted"
              - type: object
                required: [document]
                properties:
                  document: {type: string}
    HardshipAssessment:
      type: object
      required:
        [run_id, source, created_at, letter_document_id, config_version, config_label, profile, flags, budget, measures]
      properties:
        run_id: {type: string, format: uuid}
        source:
          type: string
          enum: [model, seeded_sample]
          description: seeded_sample is the Feature Design 7.8 reading stored without a model call.
        created_at: {type: string, format: date-time}
        letter_document_id: {type: [string, "null"], format: uuid}
        config_version: {type: string, examples: ["2026-11-19.1"]}
        config_label: {type: string, enum: [illustrative, authoritative]}
        profile: {$ref: "#/components/schemas/HardshipProfile"}
        flags: {type: array, items: {$ref: "#/components/schemas/Flag"}}
        budget:
          type: array
          items: {type: object}
          description: Reserved for the budget on stated and observed bases (D6). Empty today.
        measures:
          type: array
          items: {type: object}
          description: Reserved for the budget checks (D6). Empty today.
```

## 5. Asset and liability analysis (Feature Design 3.7; D6)

The Feature Design table names `POST /cases/{id}/asset-liability` and `GET .../latest`. The loan
scenario's `PUT` and the two `PATCH` routes (a line, a debt) are not in the table: they are my
proposal, following the income pattern. Amounts are strings; every figure carries `working` and
`evidence`. `evidence` entries are a document line (`document_id`, `field`, `line_ids`) or a source
(`source: "loan scenario"`, or `calculation` for the income candidate), so `AssetRef` has no
required keys.

```yaml
  /cases/{case_id}/loan-scenario:
    parameters:
      - $ref: "#/components/parameters/CaseId"
    put:
      tags: [assets]
      operationId: putLoanScenario
      summary: Enter the sample loan by hand, or replace it
      description: The values it replaces are kept in the audit event. Nothing is priced.
      requestBody:
        required: true
        content:
          application/json:
            schema: {$ref: "#/components/schemas/LoanScenarioInput"}
      responses:
        "200":
          description: The stored scenario
          content:
            application/json:
              schema: {$ref: "#/components/schemas/LoanScenario"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}
        "422": {$ref: "#/components/responses/ValidationFailed"}
    get:
      tags: [assets]
      operationId: getLoanScenario
      summary: The case's loan scenario
      responses:
        "200":
          description: The stored scenario
          content:
            application/json:
              schema: {$ref: "#/components/schemas/LoanScenario"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}

  /cases/{case_id}/asset-liability:
    parameters:
      - $ref: "#/components/parameters/CaseId"
    post:
      tags: [assets]
      operationId: runAssetLiabilityAnalysis
      summary: Queue an analysis of the case's bank statements, pay stubs and credit report
      responses:
        "202":
          description: Queued. Poll the job, then read /latest.
          content:
            application/json:
              schema:
                type: object
                required: [job, analysis_id]
                properties:
                  job: {$ref: "#/components/schemas/Job"}
                  analysis_id: {type: string, format: uuid}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}
        "503": {$ref: "#/components/responses/ServiceUnavailable"}

  /cases/{case_id}/asset-liability/latest:
    parameters:
      - $ref: "#/components/parameters/CaseId"
    get:
      tags: [assets]
      operationId: getLatestAssetLiabilityAnalysis
      summary: The newest asset and liability analysis
      responses:
        "200":
          description: Figures with working, debts, labelled statement lines, flags
          content:
            application/json:
              schema: {$ref: "#/components/schemas/AssetLiabilityAnalysis"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}

  /cases/{case_id}/asset-liability/latest/transactions/{transaction_id}:
    parameters:
      - $ref: "#/components/parameters/CaseId"
      - name: transaction_id
        in: path
        required: true
        schema: {type: string, format: uuid}
    patch:
      tags: [assets]
      operationId: reviewTransaction
      summary: Give a statement line another category, or mark a deposit as sourced
      description: |
        Send `category` or `sourced`, not both. The reason is required. Recalculates at once; no
        model is called. The system's label stays in `system_category`; `sourced` is a note that
        a person looked, not verification. 409 `analysis_not_ready` while a newer run is in progress.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [reason]
              additionalProperties: false
              properties:
                category: {$ref: "#/components/schemas/TransactionCategory"}
                sourced: {type: boolean}
                reason: {type: string, minLength: 1, maxLength: 500}
      responses:
        "200":
          description: The updated analysis
          content:
            application/json:
              schema: {$ref: "#/components/schemas/AssetLiabilityAnalysis"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}
        "409": {$ref: "#/components/responses/EditConflict"}
        "422": {$ref: "#/components/responses/ValidationFailed"}

  /cases/{case_id}/asset-liability/latest/obligations/{obligation_id}:
    parameters:
      - $ref: "#/components/parameters/CaseId"
      - name: obligation_id
        in: path
        required: true
        schema: {type: string, format: uuid}
    patch:
      tags: [assets]
      operationId: reviewObligation
      summary: Include a debt in the DTI or leave it out, with a reason
      description: |
        Recalculates the ratios at once. The system's decision stays in
        `system_counts_toward_dti`, and a later run keeps the person's choice.
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [counts_toward_dti, reason]
              additionalProperties: false
              properties:
                counts_toward_dti: {type: boolean}
                reason: {type: string, minLength: 1, maxLength: 500}
      responses:
        "200":
          description: The updated analysis
          content:
            application/json:
              schema: {$ref: "#/components/schemas/AssetLiabilityAnalysis"}
        "401": {$ref: "#/components/responses/Unauthorized"}
        "404": {$ref: "#/components/responses/NotFound"}
        "409": {$ref: "#/components/responses/EditConflict"}
        "422": {$ref: "#/components/responses/ValidationFailed"}
```

Schemas (`components/schemas`):

```yaml
    TransactionCategory:
      type: string
      enum:
        - payroll deposit
        - other income deposit
        - transfer in
        - transfer out
        - housing payment
        - loan payment
        - credit card payment
        - utility
        - insurance
        - everyday spending
        - overdraft or returned-item fee
        - other fee
        - refund
        - other
    LoanScenarioInput:
      type: object
      required: [purpose, occupancy, property_value, loan_amount, proposed_housing_payment, funds_to_close]
      additionalProperties: false
      properties:
        purpose: {type: string, minLength: 1, maxLength: 64}
        occupancy: {type: string, minLength: 1, maxLength: 64}
        property_value: {type: string, description: "Decimal, two places, above zero", examples: ["400000.00"]}
        loan_amount: {type: string, examples: ["360000.00"]}
        proposed_housing_payment: {type: string, examples: ["1980.00"]}
        funds_to_close: {type: string, examples: ["36500.00"]}
    LoanScenario:
      type: object
      required: [case_id, purpose, occupancy, property_value, loan_amount, proposed_housing_payment, funds_to_close, updated_at]
      properties:
        case_id: {type: string, format: uuid}
        purpose: {type: string}
        occupancy: {type: string}
        property_value: {type: string}
        loan_amount: {type: string}
        proposed_housing_payment: {type: string}
        funds_to_close: {type: string}
        updated_at: {type: [string, "null"], format: date-time}
    AssetRef:
      type: object
      description: A line of a document, or the loan scenario or income run the figure used.
      properties:
        document_id: {type: [string, "null"], format: uuid}
        field: {type: [string, "null"]}
        line_ids: {type: array, items: {type: string}}
        source: {type: [string, "null"], examples: ["loan scenario"]}
        calculation: {type: [string, "null"], examples: ["candidate_monthly_income"]}
    AssetCalculation:
      type: object
      required: [id, name, value, unit, formula, inputs, working, config_version, evidence]
      properties:
        id: {type: string, format: uuid}
        name: {type: string, examples: [dti]}
        value: {type: string, description: "Cents for usd, six places for a ratio", examples: ["0.446990"]}
        unit: {type: string, enum: [usd, ratio, count, days, months, match]}
        formula: {type: string}
        inputs: {type: object, additionalProperties: {type: string}}
        working: {type: string, examples: ["(1,980.00 + 693.00) / 5,980.00 = 44.70%"]}
        config_version: {type: string, examples: ["income_method@2026-11-19.1, thresholds@2026-11-23.1"]}
        evidence: {type: array, items: {$ref: "#/components/schemas/AssetRef"}}
    PersonChange:
      type: object
      required: [reason, by, at]
      properties:
        reason: {type: string}
        by: {type: string, format: uuid}
        at: {type: string, format: date-time}
    AssetTransaction:
      type: object
      required:
        [id, document_id, line_id, posted_on, description, amount, direction, category, category_source,
         system_category, needs_review, sourced]
      properties:
        id: {type: string, format: uuid}
        document_id: {type: string, format: uuid}
        line_id: {type: string, examples: ["p1-L14"]}
        account_last4: {type: [string, "null"]}
        posted_on: {type: string, format: date}
        description: {type: string}
        amount: {type: string, description: "The size; direction says which way"}
        direction: {type: string, enum: [credit, debit]}
        category: {$ref: "#/components/schemas/TransactionCategory"}
        category_source: {type: string, enum: [ai, user]}
        system_category: {$ref: "#/components/schemas/TransactionCategory"}
        counterparty: {type: [string, "null"]}
        needs_review: {type: boolean, description: "The labeller could not place it after one retry"}
        sourced: {type: boolean}
        sourced_note: {type: [string, "null"]}
        change: {oneOf: [{$ref: "#/components/schemas/PersonChange"}, {type: "null"}]}
        payroll_match: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        large_deposit: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
    AssetObligation:
      type: object
      required: [id, creditor, kind, monthly_payment, source, counts_toward_dti, reason, system_counts_toward_dti]
      properties:
        id: {type: string, format: uuid}
        creditor: {type: string}
        kind: {type: string, examples: [revolving, installment, rent]}
        monthly_payment: {type: string}
        balance: {type: [string, "null"]}
        source: {type: string, enum: [bank, credit_report, both]}
        counts_toward_dti: {type: boolean}
        reason: {type: string}
        system_counts_toward_dti: {type: boolean}
        change: {oneOf: [{$ref: "#/components/schemas/PersonChange"}, {type: "null"}]}
    AssetFlag:
      type: object
      required: [id, code, severity, message, status, refs]
      properties:
        id: {type: string, format: uuid}
        code: {type: string, examples: [AL-W101]}
        severity: {type: string, enum: [error, warning, info]}
        message: {type: string}
        status: {type: string}
        working: {type: [string, "null"]}
        refs: {type: array, items: {$ref: "#/components/schemas/AssetRef"}}
    AssetLiabilityAnalysis:
      type: object
      required:
        [id, case_id, status, started_at, config_versions, note, documented_assets, funds_to_close,
         funds_shortfall, monthly_obligations, front_end_ratio, dti, ltv, calculations, obligations,
         transactions, flags]
      properties:
        id: {type: string, format: uuid}
        case_id: {type: string, format: uuid}
        status: {type: string, enum: [queued, running, succeeded, failed]}
        started_at: {type: string, format: date-time}
        finished_at: {type: [string, "null"], format: date-time}
        config_versions: {type: object}
        note:
          type: string
          examples: ["Candidate figures for the underwriter to review. They are not a decision."]
        documented_assets: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        funds_to_close: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        funds_shortfall: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        monthly_obligations: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        front_end_ratio: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        dti: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        ltv: {oneOf: [{$ref: "#/components/schemas/AssetCalculation"}, {type: "null"}]}
        calculations:
          type: array
          description: The rest, such as dti_with_overtime.
          items: {$ref: "#/components/schemas/AssetCalculation"}
        obligations: {type: array, items: {$ref: "#/components/schemas/AssetObligation"}}
        transactions: {type: array, items: {$ref: "#/components/schemas/AssetTransaction"}}
        flags: {type: array, items: {$ref: "#/components/schemas/AssetFlag"}}
```

Notes for you:

- **A ratio is `null` when its inputs are missing** (no scenario, no income run), and an `AL-I101`
  info flag says which. The front end shows "cannot compute", not zero.
- **Flag codes AL-W101 to W107 and AL-I101 are from `backend/config/thresholds.yaml`**, with their
  message templates; the Feature Design names the messages but not the codes.
- **Credit report fields:** the obligations total 693.00 only when the credit report's tradelines
  are stored. The reader has no `credit_report` extract schema yet, so the live demo shows the four
  bank debts (658.00, DTI 44.11%) until it does. The field names I read are
  `tradeline_NNN_{creditor, account_type, balance, credit_limit, monthly_payment}`; please emit
  exactly those.

## 6. Reports, review, sign-off, audit and guidelines (Feature Design 6.7, 8.7; D6)

Built on seeded samples until your agents and the rules engine write the same tables
(`source: seeded_sample` says so in every response). The agents write through
`services/report_writer.py`; the endpoints below read and review what it stores. Only the right role
may act: the underwriter on Pillar 1, the loss mitigation specialist on Pillar 2. The administrator
makes no case decisions and gets 403; a role that cannot see the case gets 404.

Not built, because they are yours: `POST .../underwriting-report`, `POST .../lm-recommendation`
and both `.../agents/{agent}/rerun`.

```yaml
  /cases/{case_id}/underwriting-report/latest:
    get:       # operationId getLatestUnderwritingReport; 200 UnderwritingReport, 401, 404
  /cases/{case_id}/underwriting-report/latest/conditions:
    post:      # addUnderwritingCondition; body {text, priority}; 201 UnderwritingReport; 403, 404, 422
  /cases/{case_id}/underwriting-report/latest/conditions/{condition_id}:
    patch:     # reviewUnderwritingCondition; 200 UnderwritingReport; 403, 404, 409 stale_report, 422
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [decision]
              additionalProperties: false
              properties:
                decision: {type: string, enum: [accepted, edited, rejected]}
                edited_text: {type: string, maxLength: 2000, description: Required when edited}
                reason: {type: string, maxLength: 500, description: Required when edited or rejected}
  /cases/{case_id}/underwriting-report/latest/sign-off:
    post:      # signOffUnderwritingReport; body {note?}; 201 SignOffResult; 403, 404, 409 already_signed_off
  /cases/{case_id}/lm-recommendation/latest:
    get:       # getLatestLmRecommendation; 200 LmRecommendation
  /cases/{case_id}/lm-recommendation/latest/conditions/{condition_id}/override:
    put:       # overrideLmCondition; 200 LmRecommendation; 403, 404, 422 derived_condition
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [status, reason]
              additionalProperties: false
              properties:
                status: {type: string, enum: [met, not_met, not_evaluable, needs_confirmation]}
                reason: {type: string, minLength: 1, maxLength: 500}
  /cases/{case_id}/lm-recommendation/latest/sign-off:
    post:      # signOffLmRecommendation; 201 SignOffResult
  /cases/{case_id}/audit:
    get:       # listCaseAudit
      parameters:
        - {name: action, in: query, schema: {type: string}, description: Exact action name}
        - {name: entity_type, in: query, schema: {type: string}}
        - {name: limit, in: query, schema: {type: integer, minimum: 1, maximum: 200, default: 50}}
        - {name: before, in: query, schema: {type: integer, minimum: 1}, description: Id of the last event seen}
      # 200 AuditPage {items: [AuditEvent], next_before: integer|null}, newest first
  /guidelines/sources:
    get:       # listGuidelineSources; 200 {items: [{id, title, kind, label, passage_count}]}
  /guidelines/passages/{passage_id}:
    get:       # getGuidelinePassage; 200 {id, source_id, source_title, heading, text, label, notice}; 404
```

Shapes worth stating (the field lists are in `backend/app/api/schemas/reports.py` and `audit.py`):

- **Condition** keeps `text` (as the agents wrote it, never changed) beside `edited_text`, with
  `current_text` for display, `decision` (`pending`, `accepted`, `edited`, `rejected`), `reason`,
  `decided_by` and `decided_at`.
- **SignOffResult** is `{sign_off, report_status, pending_conditions}`; `sign_off.statement` is
  always "Records a review. Not a decision." and names the report `version` reviewed.
- **Waterfall option** has `status` (after overrides), `original_status` (what the rules found),
  `conditions` and the override fields. Each **condition** has `id`, `label`, `expression`, `values`,
  `passage_id` (opens at `/guidelines/passages/{id}`), `status`, `effective_status`, `derived` and
  `override {status, reason, by, at}`. Overriding to the status the rules found removes the override.
- **LmRecommendation** also carries `rule_set {name, version, label, banner}`, the lender view with
  its working, and `report` (null until there is one).
- **Passage IDs** are my provisional scheme, `sample-investor-a-v1.repayment-plan.1`, with no `#` so
  they fit a URL path. Tell me if your index uses another and I will follow it.
- **Wording:** the Feature Design's final-terms line says "the investor's approved method". Rule 3
  forbids "approved" in any text, so the response says "the investor's own method".

## 7. Hardship: read the letter, confirm it, adjust the budget (Feature Design 7.7; D6)

`GET .../hardship-assessment/latest` already exists (section 4). Its `budget` and `measures` arrays
were reserved; they now hold real shapes, and the response gains `checks`, `budget_flags`,
`budget_note`, `confirmed_by` and `confirmed_at`. Each of `primary_reason`, `onset`, `duration` and
`intent` gains `confirmation`.

```yaml
  /cases/{case_id}/hardship-assessment:
    post:      # runHardshipReading; 202 {job}; 404, 409 no_letter, 503
  /cases/{case_id}/hardship-assessment/latest/confirmations:
    put:       # confirmHardshipItems; loss mitigation specialist only (admin 403); 200 HardshipAssessment
      requestBody:
        content:
          application/json:
            schema:
              type: object
              additionalProperties: false
              description: Name each item you mean. {} confirms it as read; a value corrects it.
              properties:
                primary_reason: {$ref: "#/components/schemas/ConfirmationItem"}
                onset: {$ref: "#/components/schemas/ConfirmationItem"}
                duration: {$ref: "#/components/schemas/ConfirmationItem"}
                intent: {$ref: "#/components/schemas/ConfirmationItem"}
  /cases/{case_id}/hardship-assessment/latest/budget/{line_id}:
    patch:     # adjustBudgetLine; specialist only; 200 HardshipAssessment; 404, 422 no_observed_amount
      requestBody:
        content:
          application/json:
            schema:
              type: object
              required: [reason]
              additionalProperties: false
              properties:
                adjusted_amount: {type: [string, "null"], description: Null clears the adjustment}
                reason: {type: string, minLength: 1, maxLength: 500}
```

```yaml
    ConfirmationItem:
      type: object
      additionalProperties: false
      properties:
        value: {type: string, description: "Omit to confirm as read. duration: temporary|long_term|unknown; intent: keep|sell|unsure; onset: YYYY-MM; primary_reason: a hardship category key"}
        reason: {type: string, maxLength: 500, description: Required when value differs from the reading}
    Confirmation:
      type: object
      required: [status, value, original, by, at, label]
      properties:
        status: {type: string, enum: [confirmed, corrected]}
        value: {type: string}
        original: {type: [string, "null"], description: The value as the letter was read}
        reason: {type: [string, "null"]}
        by: {type: string, format: uuid}
        at: {type: string, format: date-time}
        label: {type: string, examples: [reviewer-confirmed]}
```

- **A confirmation is added beside the item and never replaces it** (`category` stays as read).
  Confirmed items are what the rules engine uses; an unconfirmed one makes a rule `needs_confirmation`.
- **`budget`** is one line per category: `stated`, `observed`, `observed_month`, `adjusted`,
  `adjustment_reason`, `effective_observed`, `difference`, `flagged`, `change`, and the `stated_calc`
  and `observed_calc` figures with their working and evidence.
- **`measures`** are the figures (`documented_gross_monthly_income`, `income_change`,
  `surplus_stated`, `surplus_observed`, `housing_ratio`, `arrears`, `liquid_assets`, and so on), each
  `{value, working, evidence}`. **`checks`** are the consistency checks with both values and `agrees`.
- **Fields your reader must emit** for the budget to compute: the application's
  `monthly_expenses_NNN_{description, amount}`, `monthly_income_NNN_{description, amount}`,
  `hardship_reasons_NNN_reason` (ticked reasons only) and `intent`; the mortgage statement's
  `regular_monthly_payment` and `past_due_amount`; the pay stub's `gross_pay_current`,
  `net_pay_current`, `pay_frequency` and `pay_date`. Without them the budget says what it cannot
  compute (`HB-I101`) and the demo with the rule-based reader shows exactly that.
- **Flag codes `HB-W101` to `W105` and `HB-I101`** are in `backend/config/thresholds.yaml` with their
  message templates.

## 8. Loss mitigation recommendation: apply the rules (Feature Design 8.4, 8.7; D7)

`GET .../lm-recommendation/latest`, the override and the sign-off are in section 6. This adds the
endpoint that makes the waterfall, and two fields on each condition.

```yaml
  /cases/{case_id}/lm-recommendation:
    post:      # runLmRecommendation; loss mitigation specialist only (admin and underwriter 403); 202 {job}; 404, 503
      # No body. Applies the rule set in code and calls no model. Poll GET /jobs/{id}, then read /latest.
```

- **A run exists only when it is complete**, so `/latest` is never an empty waterfall of a run still
  to be made (404 until the first one). The newest run is the one shown; earlier runs, such as the
  seeded sample, are history.
- **`report` is null** on a rules-only run. Your graph writes the report with `report_writer` into
  the same run (`run_recommendation_rules(session, case_id, user_id=..., job_id=...)` is the
  function for its step 4; it flushes and the caller commits).
- **Sign-off needs a report on the newest run:** `POST .../latest/sign-off` returns **409
  `no_report`** until one exists, so an older run's report (the seeded sample) is never signed off
  for a newer waterfall.
- **Each condition gains `note` and `evidence`:**

```yaml
    WaterfallCondition:
      properties:
        note: {type: [string, "null"], description: Why it could not be decided, or what a person must confirm}
        evidence:
          type: array
          items: {type: object, description: "A document line {document_id, field, line_ids}, a stored calculation {calculation_id, name}, a hardship item {hardship_profile_id, item, line_ids}, or the loan record {loan_record_id, field}"}
```

- **Statuses:** `needs_confirmation` means a judgement (hardship duration, intent) was read from the
  letter and nobody has confirmed it, so the rules do not use it. `not_evaluable` means something is
  missing, and `note` says what. The "no earlier option's conditions are met" condition is
  `needs_confirmation` or `not_evaluable` while an earlier option is, and `not_reached` once one is
  met.
- **Overrides carry to a new run** by condition id, with the rules' own status beside them. An
  override the rules have since caught up with is dropped.

## 9. For you, not the contract

- **Income flag codes are my labels** (the docs define none for Feature 2): `INC-CHK-01` 1040
  wages against W-2 Box 1, `02` employer, `03` Box 5 minus Box 1 against Box 12 deferrals, `04`
  trend or decline; `INC-W101` short history (excluded), `W102` year-to-date against current,
  `W103` pay frequency, `W104` pay period against year-to-date, `W105` unclassified earnings line.
  Say if you want other codes.
- **Income explanations:** the backend leaves a seam for your `income-explain@1` and `check_figures`;
  today the result carries `explanations: []`. The flags it would explain are in `flags`.
- **Gemini latency:** with a free key, `classify` took 38 to 650 s per document in testing, and 10 of
  18 calls failed with a `GatewayError` after about 37 s (the cause was not captured; free-tier rate
  limiting is the likely one). The worker now allows 1800 s a job and logs the cause chain.
- **"Hardship resolved" has no value in your profile.** Duration is `temporary`, `long_term` or
  `unknown`, so the repayment plan's and the deferral's "hardship resolved (confirmed)" condition is
  `not_met` once the duration is confirmed, with a note saying so; a reviewer who knows the hardship
  ended can override it with a reason. I did not invent a field. Tell me if you want `resolved` added
  to the duration categories (it is a change to `hardship@1`, your folder).
- **Months delinquent comes from the loan record** (the simulated servicing record), because no
  document field carries it. The mortgage statement's `payments_past_due` is in the generated
  documents but not in the schema; add it if you want it read from the document.
- **Rule set citations:** every condition cites a passage id in `sample-investor-a-v1.<topic>.<n>`
  form (my provisional scheme). The seeded guide has all ten; a test checks that each cited id
  resolves.
