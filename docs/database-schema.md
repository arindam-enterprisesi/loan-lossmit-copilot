# Database schema

The copilot needs 34 tables in PostgreSQL, in five groups (plus two deferred). They are added migration by migration on the day each feature needs them. Abhay owns all of them except the guideline search tables, which Arindam owns. Settings stay in versioned YAML files in `backend/config`, and the database records which version each run used.

## Conventions for every table

- Primary keys are UUIDs; every row has `created_at`, and rows people change have `created_by` or `updated_by`.
- Money is `NUMERIC(14,2)` and ratios `NUMERIC(9,6)`; never floats.
- Nothing is overwritten: a correction keeps `original_value`, and every change also writes a row to `audit_events`.
- Every analysis is stored as an `analysis_runs` row; "latest" means the newest run for that case and feature.
- `cases.tenant_id` is present now so Row-Level Security can be switched on in phase 2 without a migration of every table.
- Files live in S3; tables store only the S3 key.

## 1. Identity, settings, platform

| Table | Purpose | Key columns | Feature | Owner | Due |
|---|---|---|---|---|---|
| `users` | Demo users and roles | id, name, email, role (processor, underwriter, lm_specialist, compliance, admin) | All | Abhay | D1 |
| `config_versions` | Which settings version a run used | id, kind (checklist, income_method, thresholds, rule_set, llm, templates), name, version, label (illustrative, authoritative), source, content_hash, active | All | Abhay | D4 |
| `jobs` | Background job status for the UI to poll | id, kind, case_id, document_id, status, progress, attempts, error, updated_at | All | Abhay | D1 |
| `llm_calls` | One row per model call, no document text | id, job_id, task, prompt_id, provider, model, tokens_in, tokens_out, latency_ms, retried, success | All | Arindam (written by the gateway) | D2 |
| `audit_events` | Append-only record of every upload, AI call, calculation and review action | id, at, actor_id, role, case_id, action, entity_type, entity_id, before (jsonb), after (jsonb), reason | All | Abhay | D1 |

## 2. Cases and documents

| Table | Purpose | Key columns | Feature | Owner | Due |
|---|---|---|---|---|---|
| `cases` | One borrower scenario | id, tenant_id, case_ref (LP-0001, LM-0001), pillar (loan_processing, loss_mitigation), borrower_names (jsonb), employment_type, reference_date, status, created_by | 1 | Abhay | D1 |
| `loan_scenarios` | Sample loan entered by hand (Pillar 1) | case_id (PK, FK), purpose, occupancy, property_value, loan_amount, proposed_housing_payment, funds_to_close | 3 | Abhay | D6 |
| `loan_records` | Simulated servicing record (Pillar 2) | case_id (FK), loan_id, investor, unpaid_balance, monthly_payment, principal_interest, escrow, next_due_date, months_delinquent, arrears_amount, source = synthetic | 7, 8 | Abhay | D6 |
| `documents` | One uploaded file | id, case_id, s3_key, sha256, mime, size_bytes, page_count, doc_type, doc_type_certainty, doc_type_source (ai, user), borrower, period_start, period_end, status, summary | 1 | Abhay | D1 |
| `pages` | One page image | id, document_id, page_no, image_s3_key, width, height, read_by (text_layer, tesseract), printed_page_label | 1 | Abhay | D1 |
| `lines` | Numbered text lines, the anchor for all evidence | id, document_id, page_id, line_ref (p1-L31), text, bbox (jsonb), confidence | 1 | Abhay | D1 |
| `fields` | Extracted values with evidence and review state | id, document_id, name, value, normalized_value, original_value, line_refs (text[]), certainty, review_status (pending, confirmed, corrected, rejected), reviewed_by, review_reason | 1 | Abhay | D1 |
| `flags` | Every warning from every feature, in one place | id, case_id, feature, entity_type, entity_id, code, severity, message, evidence (jsonb), status (open, resolved, overridden), resolved_by, reason | All | Abhay | D3 |
| `completeness_results` | Checklist result per run | id, run_id, case_id, items (jsonb: item, status satisfied/partial/missing, reason, override), overall_status | 1 | Abhay | D4 |

## 3. Analysis results

| Table | Purpose | Key columns | Feature | Owner | Due |
|---|---|---|---|---|---|
| `analysis_runs` | Parent row for every run of a feature | id, case_id, feature (income, assets, credit, hardship, underwriting, lm_recommendation, completeness), status, job_id, config_versions (jsonb), started_at, finished_at | 2 to 8 | Abhay | D4 |
| `calculations` | Every computed figure with its working ("Show working") | id, run_id, case_id, name, value, unit, formula, inputs (jsonb), working, evidence (jsonb) | 2, 3, 4, 7, 8 | Abhay | D4 |
| `income_components` | Income by borrower, employer and component | id, run_id, borrower, employer, component (base, overtime, bonus, commission), current_period, ytd, monthly, included, exclusion_reason, calculation_id | 2 | Abhay | D4 |
| `transactions` | Bank statement lines with labels | id, document_id, line_ref, account_last4, posted_on, description, amount, direction, category, counterparty, category_source (ai, user), payroll_match_field_id, sourced_note | 3 | Abhay | D6 |
| `obligations` | Recurring debts and whether they count toward DTI | id, run_id, case_id, creditor, kind, monthly_payment, balance, source (bank, credit_report, both), counts_toward_dti, reason | 3 | Abhay | D6 |
| `hardship_profiles` | Letter read into reason, onset, duration, intent | id, run_id, case_id, primary_reason, reasons (jsonb with quote, line_refs, verified), onset, duration, intent, timeline (jsonb), confirmed_by, confirmed_at | 7 | Abhay (prompt output from Arindam) | D6 |
| `budget_lines` | Budget by category on stated and observed bases | id, run_id, category, stated_amount, observed_amount, adjusted_amount, adjustment_reason, flagged | 7 | Abhay | D6 |
| `credit_scores` | Bureau scores from the sample report | id, run_id, bureau, score, is_representative | 4 (P1) | Abhay | D7 |
| `tradelines` | Accounts on the sample credit report | id, run_id, document_id, creditor, account_type, ownership, opened_on, status, balance, credit_limit, monthly_payment, past_due, late_30, late_60, late_90, last_late_on, remarks, line_refs | 4 (P1) | Abhay | D7 |
| `credit_inquiries` | Inquiries and their matched new account | id, run_id, creditor, inquired_on, matched_tradeline_id | 4 (P1) | Abhay | D7 |

## 4. Rules, agents and reports

| Table | Purpose | Key columns | Feature | Owner | Due |
|---|---|---|---|---|---|
| `waterfall_results` | Each loss mitigation option and its status | id, run_id, rule_set_version, order_no, option, status (met, not_met, not_evaluable, not_reached, needs_confirmation), conditions (jsonb: values used, passage ids), overridden, override_reason, overridden_by | 8 | Abhay | D6 |
| `lender_views` | Option cost against foreclosure | id, run_id, foreclosure_loss, modification_cost, advantage, settings (jsonb), calculation_ids | 8 | Abhay | D6 |
| `agent_runs` | One row per Researcher, Writer or Critic attempt | id, run_id, agent, attempt, status, provider, model, prompt_id, output (jsonb), error, started_at, finished_at | 6, 8 | Arindam (shape), Abhay (migration) | D6 |
| `reports` | Draft underwriting or recommendation report | id, run_id, case_id, kind (underwriting, lm_recommendation), version, sections (jsonb), guardrail_results (jsonb), status (draft, in_review, signed_off) | 6, 8 | Arindam (shape), Abhay (migration) | D6 |
| `findings` | Findings in a report, each with evidence | id, report_id, priority (significant, attention, information), title, detail, evidence (jsonb), flag_id | 6 | Abhay | D6 |
| `conditions` | Suggested conditions and the reviewer's decision | id, report_id, text, priority, source (agent, user), decision (pending, accepted, edited, rejected), edited_text, reason, decided_by, decided_at | 6 | Abhay | D6 |
| `sign_offs` | Record that a person reviewed a report; never a decision | id, report_id, case_id, signed_by, role, signed_at, note | 6, 8 | Abhay | D6 |

## 5. Guideline search (RAG)

| Table | Purpose | Key columns | Feature | Owner | Due |
|---|---|---|---|---|---|
| `guideline_sources` | Loaded source documents | id, collection (fannie_mae, freddie_mac, lender_overlay, reg_x, investor_guide), title, version, as_of, label, s3_key, loaded_at | 5 | Arindam | D6 |
| `rag_chunks` | Passages with embeddings and full-text index | id, source_id, section_path, page, paragraph_ref, text, tsv (tsvector), embedding (vector(1024)), embedding_model | 5 | Arindam | D6 |
| `guideline_questions` | Questions, answers, citations and feedback | id, user_id, case_id (nullable), question, source_set, answer (jsonb), retrieved_chunk_ids, removed_sentences, feedback (helpful, not_helpful, wrongly_cited) | 5 | Arindam | D6 |

## 6. Deferred to phase 2

- `drafts` and `draft_versions` for Feature 9 letters (template version, sections, check results, approval).
- Row-Level Security policies on every case-scoped table, keyed on `cases.tenant_id`.

## How the PRD master tables map here

The PRDs list master data tables (checklists, income_methods, settings, guideline_sources, rule_sets, rule_options, hardship_categories, checklist_items). All except `guideline_sources` are versioned YAML files in `backend/config`, so they are reviewed in PRs like code; `config_versions` records which version each run used. `guideline_sources` is a table because sources are loaded at runtime.
