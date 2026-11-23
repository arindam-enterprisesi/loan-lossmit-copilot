# Contract proposal for Day 4 (for Arindam's own contract PR)

The backend already serves these endpoints. The contract (`contracts/openapi.yaml`) names the
completeness `POST` and `GET .../latest` only; the income, page-image and hardship endpoints are TODO
comments and the completeness override has no endpoint. Abhay does not edit `contracts/`, so this is
the YAML to add (sections 1 and 2 from D4, sections 3 and 4 from D5).
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

## 5. For you, not the contract

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
