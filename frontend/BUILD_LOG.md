# Frontend build log

Running record of what I built in `frontend/` and why. Newest day at the bottom. I build with Claude Code, review every diff, and do all git branching and pushing myself.

---

## Day 1 (Mon 16 Nov 2026)

Goal: scaffold the app, PRD-based theme, app shell with left nav for both copilots, dashboard and case list.

### Decisions
- Both pillars (Loan Processing and Loss Mitigation) are shown at the v0.5 review on Fri 20 Nov.
- Using the PRD styling for now. I'll swap it once the Claude Design system is ready.
- I do the git branches, commits and pushes myself. Work goes on a feature branch and the manager merges after review.

### What I did
1. **Read the plan, both PRDs and the technical design.** Worked out that I own everything the user sees and never call a model or touch the database from the frontend.
2. **Cloned the monorepo** into `loan-lossmit-copilot/`. Arindam's D1 setup was already on `main`: `CLAUDE.md`, `contracts/openapi.yaml`, CI, PR template, empty `frontend/`.
3. **Read `CLAUDE.md` and the API contract.** Rules that matter for the UI: no "approve", "deny", "offer", "eligible" or "qualifies" wording, no arithmetic on money in the UI, corrections keep the original value, no model calls from the frontend. The contract covers login, cases, documents, field review, completeness and jobs. The income, hardship, assets, guideline, agent and audit endpoints are still TODO, so those screens will use mocks.
4. **Scaffolded Next.js** (15.5, React 19, Tailwind v4, ESLint, TypeScript) in `frontend/`. Had to delete the empty `.gitkeep` first because `create-next-app` refuses a non-empty folder.
5. **Set up shadcn/ui** and added card, table, badge, tabs, sheet, input, dialog, dropdown-menu, separator, skeleton and select.
6. **Fixed a shadcn problem.** The generated components imported `cn` from an unrelated third-party npm package. I replaced it with the standard local helper (`clsx` + `tailwind-merge`) in `src/lib/utils.ts`.
7. **Applied the PRD theme** in `globals.css`: navy, teal and gold palette, serif headings, grey panels, status colours. Also fixed a circular font variable shadcn generated.
8. **Generated API types** from the contract with `npm run gen:types` (output in `src/lib/api-types.ts`). Re-run it whenever the contract changes. `src/lib/types.ts` has the friendly names.
9. **Nav config** (`src/lib/nav.ts`) for both pillars in the PRD menu order. I added a "Cases" item to each menu so both demo cases are reachable.
10. **Mock data and API layer.** `src/mocks/data.ts` has two cases (Daniel Reyes, Angela Whitfield) and nine documents typed from the contract, including the pay-stub mismatch flag. `src/lib/api.ts` reads mocks unless `NEXT_PUBLIC_USE_MOCKS=false`. Added `.env.example` and un-ignored it in `frontend/.gitignore`.
11. **Shared components** in `src/components/shared/`: FlagChip, StatCard, SignOffNote, ShowWorkingDrawer, EvidencePanel, DocStatusChip.
12. **App shell and screens.** Left sidebar with copilot switcher, dashboard and case list for each pillar at `/underwriting` and `/loss-mitigation`, and a placeholder page for menu items that aren't built yet.

13. **Fixed fonts after looking at the screens.** Body text was showing in the browser's default serif because the font variables were on `<body>` while the base font rule sits on `<html>`. Moved the variables to `<html>` in `layout.tsx`. Now only headings are serif.

### Checks
- `eslint`, `tsc --noEmit` and `npm run build` all pass.
- Routes behave: `/` redirects to `/underwriting`, both dashboards and case lists load, unbuilt menu items show the placeholder, unknown paths return 404.
- No banned decision wording anywhere in `src/`.
- Port 3000 was already in use on my machine, so I ran the dev server on 3100.
- I haven't looked at the screens in a browser with screenshots yet.

### Tests (added after the first PR)
`CLAUDE.md` says every change adds tests, so I added Vitest to the same branch.
- Installed `vitest@3`, `jsdom`, `@testing-library/react` and `@testing-library/jest-dom`. Vitest 5 needs `@types/node` 26 but Next pins 20, and `@vitejs/plugin-react` 6 has heavy peer dependencies that clash with the shadcn CLI, so I used Vitest 3 and no React plugin instead of forcing the install.
- `npm test` runs 29 tests in 5 files: nav config (slugs, menus stay in their own pillar, no decision wording), date and text formatting, flag chip tones, evidence box position as a percentage of the page, and the mock data (matches the case/document counts, keeps the pay-stub flag, no decision wording).
- Checked the tests can fail: I broke the evidence box maths on purpose, the test caught it, then I restored it.
- CI only runs eslint, tsc and build for `frontend/`. Asking Arindam to add `npm test`.

### Open items
- To raise with Arindam on the call: ask him to add `npm test` to the CI frontend job, and ask about the two `npm audit` warnings (dev-only `minimatch`, `postcss` bundled in Next 15). The only fix is a forced jump to Next 16, which I didn't take.
- Staying on mocks until the backend sends real data: case references like `LP-0001`, the "Cases" menu item, and every screen whose endpoint isn't in the contract yet. Mocks are easy to edit and good for design review.
- Sidebar is desktop-only for now.

---

## Day 2 (Tue 17 Nov 2026)

Goal: Document Intelligence screens. An upload screen and a review screen with the page image beside the extracted fields. Both pillars use them (Document intelligence for Loan Processing, Document intake for Loss Mitigation).

### Decisions
- Built on mocks. The contract has the upload, job, extraction, field review and document type endpoints, so `src/lib/api.ts` has a function for each and flips to the real API with `NEXT_PUBLIC_USE_MOCKS=false`.
- The contract has no page image endpoint yet (marked TODO D3+), so the page image is a mock pay stub drawn as an SVG in `public/mock/`, lined up with the mock evidence boxes.
- The review screen lives under each menu item (`/underwriting/document-intelligence/<case>/<document>`), so the menu stays highlighted while reviewing.
- Used plain `<select>` for the type pickers. They are accessible and easy to test.
- No "Show working" drawer on this screen. The contract returns the check as a flag message ("Gross 3,070.50 minus deductions 1,036.89 is 2,033.61, not 2,083.61"), so I show that text as is. The UI does no arithmetic.

### What I did
1. **Mock backend for documents** in `src/mocks/store.ts`. It follows the contract rules: a stale `expected_version` gives 409, a missing reason gives 422, a correction keeps `original_value`, and a processing job moves queued, running, succeeded over a few seconds. Fixtures in `src/mocks/extraction.ts` include the pay stub net pay mismatch (DI-CHK-02, line p1-L31).
2. **API layer**: `uploadDocuments`, `getJob`, `getExtraction`, `reviewField`, `setDocumentType`, `getPageImageUrl`. Added `ApiError` so screens can react to 409 and 422. Job polling is a small hook, `useJobPoll`.
3. **Upload screen**: case picker, drop zone, document type (Auto-detect or a type), file checks (PDF, PNG, JPEG only), progress bar while the job runs, and a document table. Documents whose type could not be told show a type picker. There is a filter for documents with flagged fields.
4. **Review screen**: page image with the cited box on the left, fields on the right with flagged ones first. Picking a field moves the box. Each field can be confirmed, corrected (value and reason needed) or rejected (reason needed). A correction shows the original value struck through. The "Records a review. Not a decision." note sits next to the controls.
5. **Edit conflict**: if the value changed since the screen loaded, the review is refused and the screen asks for a reload instead of overwriting.
6. Switched both menu items from "soon" to live.

### Tests
- Went from 29 to 87 tests in 14 files. New ones cover the review payload rules, file checks, field ordering, the mock store (409, 422, original kept, job timing, type change), the upload panel, field list and form, job progress, the document table, and the whole review screen (box position, correction, conflict and reload).
- `eslint`, `tsc --noEmit`, `npm run build` and `npm test` all pass. Banned decision wording scan is clean.
- Running `npm run build` while the dev server is up breaks the dev server's cache (500 errors). Fix is to stop it, delete `.next` and start again.

### Open items
- Ask Arindam: the contract takes a multipart upload while the technical design describes a presigned upload to S3, so which one should the screen follow? And when will the page image endpoint land?
- The type picker has no reason box yet (the contract allows an optional reason).
- Pages with more than one image are not switchable yet. The panel shows the page cited by the selected field.

## Day 3 (Wed 18 Nov 2026)

Goal: finish the upload and review screens against the Day 3 brief: zoom and several pages, a box for every field with hover and click, a type dialog, and 2-second polling. Day 2 already built most of the screens, so Day 3 fills the gaps. I log after each group.

### Group 1: page viewer
Decisions:
- A new `PageViewer` instead of changing the shared `EvidencePanel`, which later screens (income, hardship) will reuse.
- Boxes stay as 0 to 1 fractions and are drawn as percentages of the page canvas. Zoom only resizes the canvas, so boxes stay on their text.
- The review screen holds `selectedName`, `hoveredName` and `viewPage`. The viewer and the field list both read them, so they always agree.

What I did:
1. `src/lib/viewer.ts`: zoom steps (50% to 300%), page limits, box to CSS, which fields get a box.
2. `page-viewer.tsx`: page arrows, zoom buttons, a box for every field (selected gold, hovered teal). Clicking a box selects its field. Picking a field on another page jumps to that page.
3. Field rows light up when their box is hovered, and the other way round.
4. Mock: a 3-page bank statement (`public/mock/bank-p1..p3.svg`) with boxes lined up to its text.

Tests: 87 to 118. New tests cover the zoom limits, boxes at any zoom, hover both ways, box click, and page jumping.

Open: I assume the box origin is the top left of the page. Confirm with Abhay before going live. (The Day 2 open item "pages not switchable" is now done.)

### Group 2: type dialog and polling
Decisions:
- Job polling is every 2 seconds against the real backend (as the brief says) and 0.7 seconds on mocks, so the demo stays lively. One constant per mode in `use-job.ts`.
- The reason on a type change is optional, as in the contract (max 500 characters). A blank reason is left out of the request.
- The dialog does not know about the API. It calls `onConfirm` and shows any error it throws, so it can be reused anywhere.
- While a re-read is running on the review screen, reviewing is paused. The values on screen belong to the old type, so editing them would be wrong.

What I did:
1. `use-job.ts`: poll interval picked by mode.
2. `setDocumentType` sends the trimmed reason. The mock refuses a reason over 500 characters (422) and records each type change (from, to, reason, time), standing in for the audit store.
3. `type-dialog.tsx`: type dropdown (never "unrecognized"), optional reason box with a character counter, Confirm disabled until a type is chosen, error shown inside the dialog.
4. The document table's "Choose type" now opens the dialog. The review screen has a "Change type" button; after a change it shows re-reading progress, then reloads the new fields.
5. Removed the old inline `TypePicker`, which nothing uses any more.

Tests: 118 to 151. New tests cover the poll timing, the reason limit and audit record, the real PUT request body, the dialog, the table flow and the review screen type change (including the paused state and the reload).

Open (Group 2): the reason is only stored, nothing shows it back yet. A type change on a reviewed document drops the old extraction in the mock. Check with Abhay that the real backend does the same, so old corrections are not lost silently.

### Group 3: page image link and the full flow
Decisions:
- The page image is now an async call, `getPageImage`, not a sync helper. Presigned links expire after about 5 minutes, so the screen always asks for the link and never keeps one for long.
- If an image fails to load, I ask for one fresh link and try again. If the fresh link fails too, I stop and show the blank page. No retry loop. Boxes and review still work without the picture.
- The contract has no page-image endpoint yet (TODO D3+), so in real mode `getPageImage` answers "none". When Arindam adds the endpoint, only that one function changes.
- In the mock, an uploaded pay stub now gets the demo story's reading (net pay flagged) and the mock pay stub picture. Before, it got an empty reading, so the demo flow could not be tried.

What I did:
1. `getPageImage` in `api.ts`, and a `usePageImage` hook that loads the link per page and handles the expired-link retry.
2. `PageViewer` reports image load and error to the screen, which passes them to the hook.
3. Mock: uploaded pay stubs get a copy of the demo reading, with their own document ID, plus the picture.
4. One end-to-end test: upload a pay stub, wait for the job, open it, see the box on the picture, try to save a correction without a reason (refused), correct it with a reason, see the original struck through and the flag cleared.

Tests: 151 to 167. A test bug cost me some time: a `beforeEach` that returned the mock made Vitest call it as a cleanup step.

Open:
- Real mode: no picture until the endpoint exists, and the login screen and CORS are still missing, so real mode cannot be switched on yet.
- Ask Arindam what the page-image response will look like (just a URL, or URL plus expiry).

Day 3 done-when: Daniel's pay stub can be uploaded, reviewed and corrected in the browser, on mocks.

## Day 4 (Thu 19 Nov 2026)

Goal: build the Income analysis screen (run, figures table, Show working, flag cards, include or exclude with a reason, copy document requests) and the Completeness screen, and prepare the Hardship and budget screen (the brief said a design prompt; I built it directly in Group 5). I log after each group, in plain words.

### Group 1: the income data and its mock
In one line: before drawing any screen, I decided what an income analysis looks like as data, and made a mock backend that returns Daniel's real numbers.

Why this comes first: the income endpoints are not in the API contract yet (only a TODO line, and the contract is Arindam's to change). So I wrote down the shape the screen needs, based on Feature Design section 2 and Arindam's `income-explain` schema, and I will send it to him as a proposal. Writing the screen against a clear shape also means that when the real endpoint arrives, only the API layer changes.

Decisions:
- Every figure arrives as text with its working and its evidence, for example `"5980.00"` plus the steps that produced it and the pay stub line it came from. The screen never calculates anything (project rule 1) and every number can be traced (rule 2).
- The AI explanations come with the backend's own label, "possible — to be confirmed", and a flag for "unverified figure". The screen will show the label as given, never as a finding.
- Overtime and bonus start out left out of the candidate figure, because Daniel's documented history covers 2026 only and the method needs 24 months. Including them later is a person's decision, with a reason.
- The mock uses the exact figures from the scenario file the backend tests check: base pay 5,980.00 a month, overtime 444.41, bonus 228.34, candidate 5,980.00 (6,424.41 if overtime is counted). The mock repeats those answers. It does not calculate income.
- The one sum the mock does is the candidate total (add up the components that are counted). It uses whole cents, so there is no rounding error. It stands in for the backend re-adding after someone includes or excludes a component.

What I did:
1. `src/lib/income-types.ts`: the proposed shape (components, figures with working, flags with both values and explanations, cross-checks, trend sentences, document requests).
2. `src/mocks/income.ts`: Daniel's analysis. Three components, the candidate total, one flag (short overtime and bonus history) with two suggested documents, four cross-document checks that all pass (wages, employer, deferrals, trend), and the two trend sentences. Line IDs on the pay stub are the real ones from Arindam's sample file.
3. `src/mocks/store.ts`: the mock job system now handles two kinds of job. An income run goes queued, then running through the stages gather, calculate, explain and checks, then done. Only when it is done does the result appear. Before the first run, asking for the latest result gives a 404.
4. `src/lib/api.ts`: `runIncomeAnalysis` and `getLatestIncome`. In real mode they call `POST /cases/{id}/income/analysis` and `GET .../analysis/latest`, the paths I am proposing.

Tests: 167 to 188. New tests check the whole analysis against the scenario numbers, that every figure has working and evidence, that figures are text and never numbers, the cents arithmetic (5,980.00 + 444.41 = 6,424.41, everything counted = 6,652.75), the job flow and 404-before-first-run, that a screen cannot change the stored result, that a case with no income documents is refused, and the real-mode requests.

Open:
- Send Arindam the proposed shape and the two paths. Ask Abhay when his income calculation lands.
- Daniel's flags: the scenario has only one real income flag. The other four checks pass. If the real backend flags more, the screen already handles any number of flags.
- Only Daniel's case can be run. Angela's loss mitigation case has no income run, and the mock says so (422).
- W-2 and tax return line IDs are not in the sample data yet, so those checks cite the document by name only.

### Group 2: the Income analysis screen
In one line: the Income analysis menu item is now a real screen. Press Run, watch the progress, then read the figures, the working behind each one, the flag, the cross-checks and the document requests.

What the screen shows, top to bottom:
1. Case picker and a **Run analysis** button (it becomes **Run again** once a result exists). Pressing it starts the job and shows a progress bar with the stage ("Gathering figures", "Calculating income", "Suggesting possible explanations", "Running checks"). The button is disabled while it runs. If the run cannot start or the job fails, the message from the backend is shown and the button works again.
2. A chip saying which method was used ("Illustrative method", `income-method@1`) and when it was run.
3. **Income components** table: current period, year to date and monthly, with a Working button next to every figure. Each drawer shows the formula, the result and a "Read from" list that links to the document. A "Counted" or "Left out" chip sits on each row, with the reason when something is left out.
4. A **Candidate monthly income** row at the bottom, labelled exactly "candidate - qualifying income is determined by the underwriter". For Daniel it shows 5,980.00 and its own working.
5. **Flags** as cards: what was found, both values side by side with where each came from, then the AI suggestion marked "possible — to be confirmed" (plus "unverified figure" if a number in it did not match). The documents that would settle the flag are listed.
6. **Suggested document requests** with a **Copy document requests** button (it tells you if the clipboard is not available).
7. **Cross-document checks** (each "Consistent" or "Flagged") and the trend sentences.

Decisions:
- The screen only displays. Money is shown by adding thousands separators to the text the backend sent (`formatMoney`). It never turns it into a number, so nothing can be rounded or changed.
- "No analysis yet" is a normal state, not an error. The backend's 404 before the first run is turned into a friendly message.
- The Show working drawer is shared with later screens, so I extended it instead of building a second one: it now lists the documents the inputs came from, and can carry its own accessible name, so a screen with many drawers stays readable to a screen reader.
- The evidence links open the document's review screen. They do not jump to the exact page and line yet (see Open).
- Only the Loan Processing menu has this screen. `/loss-mitigation/income-analysis` is a 404, as intended.
- The menu item "Income analysis" is now marked live.

What I did:
1. `src/components/income/`: `income-workspace.tsx` (the screen), `income-table.tsx`, `income-flag-card.tsx`, `income-checks.tsx`, `income-screen.tsx` (server shell), and the route `src/app/[pillar]/income-analysis/page.tsx`.
2. `src/lib/income.ts` (small display helpers: evidence text, document links, the copy text, the candidate wording) and `formatMoney` in `src/lib/format.ts`.
3. `show-working-drawer.tsx` extended (evidence list and accessible name). `job-progress.tsx` knows the three income stages. `nav.ts` marks the screen live.

Tests: 188 to 228. New tests cover the table (formatted amounts, counted and left out, the candidate row and its label, a drawer for every figure), the drawer, the flag card (both values and sources, the possible label, the unverified chip), the helpers, `formatMoney`, and the whole screen: empty state, Daniel's 5,980.00 with working, a full run on the real clock (progress, then the result), the 422 message for a case with no income documents, copy success and failure, a 404 before the first run, a load error, a start error, and a failed job.

Checked: the page serves (HTTP 200 on the dev server), the Loss Mitigation URL is a 404, and the banned-wording scan is clean. I could not look at it in a browser because the browser extension was not connected, so the layout still needs your eyes.

Open:
- Evidence links go to the document's review screen. The review screen does not yet open on a given page and line, so a link cannot jump straight to the cited line. That would be a small addition to the review screen.
- The include or exclude buttons come in Group 3. For now the table shows what is counted and why, nothing can be changed. (Done in Group 3.)
- "Done when" says the 5,980.00 comes from the real API. It comes from the mock today, because there is no income endpoint on `main` yet. See the checklist.

### Group 3: include or exclude a component, with a reason
In one line: a person can now change what counts toward the candidate monthly income. Every row has an Include or Exclude button. It asks for a reason, then the figures update at once.

How it works, step by step (Daniel as the example):
1. Next to "Left out" on the Overtime row there is an **Include** button. Base pay, which is counted, has **Exclude**.
2. It opens a small window: what will change ("Overtime (1.5x), 444.41 a month, will be added to the candidate monthly income"), what the method said and why, and a reason box marked required.
3. The confirm button stays disabled until there is a reason (blank spaces do not count). The reason can be up to 500 characters, with a counter.
4. On confirm, the candidate row changes from 5,980.00 to **6,424.41**, and its Show working drawer now reads "5,980.00 + 444.41" with "Left out: Bonus (228.34)". Excluding it again brings 5,980.00 back.
5. The row keeps a record: "Included by demo.reviewer, 20 Nov 2026", the reason, and "The method said: left out. Documented history covers 2026 only." The method's own answer is never overwritten (project rule 6). The button now offers the opposite, so a decision can be undone, and the undo is recorded too.
6. If the server refuses (for example the reason is missing), the window stays open, shows the server's message and keeps what was typed.

Decisions:
- The screen still never calculates. It sends `{included, reason}` and shows whatever analysis comes back. In the mock, the "backend" re-adds the counted components in whole cents. In real life that is the backend's plain Python, with no AI.
- The reason is checked twice: the button is disabled without one, and the mock answers 422 without one, like the contract rule for other corrections. Anyone calling it without the screen is still stopped.
- Each component carries `rule_included` (what the method decided) next to `included` (what counts now) and `override` (who, when, why). So the original answer stays visible after a change.
- The flag and the suggested document requests stay as they were. The short-history flag is a fact about the documents, not about the decision, so it still shows after someone includes overtime.
- The change comes back as the whole new analysis, so every figure and its working refresh in one go and no part of the screen can show an old total.

What I did:
1. `income-types.ts`: `rule_included` on each component and the `IncomeDecision` body.
2. `mocks/income.ts`: `applyIncomeDecision`, which checks the reason and the component, records the decision, re-adds the candidate and returns a new analysis without touching the old one. `mocks/store.ts`: `setIncomeComponentMock`, which keeps the result as the latest, so the decision is still there when the screen is opened again.
3. `lib/api.ts`: `setIncomeComponent`. In real mode it calls `PATCH /cases/{id}/income/analysis/components/{component_id}`, the path I am proposing.
4. `income-decision-dialog.tsx` (new), plus the Include or Exclude button and the decision note in `income-table.tsx`, and the wiring in `income-workspace.tsx`.

Tests: 228 to 256. New tests cover: the candidate becoming 6,424.41, 6,652.75 with everything counted and 0.00 with nothing; who, when and why being recorded while the method's answer stays; other rows and the old analysis staying untouched; reason refused when missing, blank or over 500 (and exactly 500 allowed); unknown component 404; the store keeping the decision and refusing before a run; the real-mode PATCH request (trimmed reason); the dialog (wording for include and for exclude, disabled until a reason, trimmed reason sent, counter, failure keeps it open, cancel sends nothing); the table (buttons only when a decision is possible, the decision note); and the whole screen (include overtime and see 6,424.41 with new working, the decision surviving a reopen, exclude base pay and bring it back, no decision without a reason, a refused decision changing nothing).

Checked: type check, lint and the full test suite pass. The banned-wording scan is clean. I did not look at it in a browser this time. Please try it on http://localhost:3100/underwriting/income-analysis.

Open:
- The mock records the person as "demo.reviewer". Once login exists, the real name comes from the token and the backend should set it, not the screen.
- Only the latest decision per component shows on the screen. The backend should keep every decision as history (rule 6). Ask Arindam and Abhay that the PATCH writes an audit record and that the response includes it.
- The PATCH path and body are my proposal. Same message to Arindam as for the run and latest paths.

### Group 4: the Completeness check
In one line: under the document list there is now a Completeness section. Press Run checklist, see each checklist item with a status, override one with a written reason, and copy what is still outstanding.

Where it lives: I put it at the bottom of the Document intelligence screen (Loan Processing) and the Document intake screen (Loss Mitigation), under the documents it compares. It is the same screen code for both, so Angela gets it too, with her own checklist. There is no separate menu item for it in the design.

What the screen shows, top to bottom:
1. A heading ("Completeness for Daniel Reyes — purchase"), a one-line note that code decides every status and it is never a loan decision, and a **Run checklist** button (it becomes **Run again** once a result exists).
2. A summary: **Incomplete** (or "Complete for this checklist", the wording from the spec), an "Illustrative checklist" chip, and the checklist name, version and run date.
3. One row per checklist item: a status chip (**Satisfied**, **Partially satisfied**, **Missing**, **Overridden**), the item, the reason ("14 of 30 days of pay stubs found") and the documents used, as links to their review screens.
4. An **Override** button on items that are partly met or missing. It opens a window with what the checklist found and a required reason. After confirming, the item is Overridden, and the summary and outstanding list update at once.
5. **Outstanding items** with a **Copy outstanding items** button.

What Daniel shows (from the scenario file and the spec): Incomplete. Pay stubs 14 of 30 days, the 2024 W-2 and 2024 tax return missing, the August bank statement a page short, and the credit report satisfied. Outstanding: four lines to ask the borrower for. What Angela shows: Incomplete, because the August 2026 bank statement is missing. Outstanding: "August 2026 bank statement".

Decisions:
- The panel never decides a status. It shows what the backend returned. The mock only repeats the scenario's answers. The one thing the mock does is what the backend does after an override: it works out the overall status and the outstanding list again (overrides count as satisfied, per the spec).
- An override keeps the checklist's own answer. The item's reason is unchanged, and the item also carries what the checklist found, who overrode it and when (project rule 6). Those three fields are my proposal, because the contract only has `status` and `override_reason`.
- Only items that are partly met or missing can be overridden. A satisfied item has nothing to override, and one already overridden is not overridden twice. The mock answers 422 for those, as I propose the backend should.
- The checklist is not chosen on screen. Each menu section runs its own (`pillar1-wage-earner@1` is the contract's example). The spec says the user "picks a checklist", but there is only one per pillar for now.
- I shared the required-reason window. A new `reason-dialog.tsx` is used for both the income include or exclude (Group 3, now rebuilt on it) and the checklist override, so they behave the same. The income tests all passed unchanged.
- The run answers at once (the contract returns the result, not a job), so there is no progress bar.
- "No result yet" is a normal state, the same as on the income screen.

What I did:
1. `lib/completeness.ts` (types, checklist ids per section, labels, copy text) and `mocks/completeness.ts` (Daniel's and Angela's results, the override and the recalculation). `mocks/store.ts` keeps the latest result per case, so it is still there when the screen is opened again.
2. `lib/api.ts`: `runCompleteness` and `getLatestCompleteness` (both in the contract) and `overrideCompletenessItem` (my proposal: `PATCH /cases/{id}/completeness/items/{item_id}` with `{reason}`, answering with the whole recalculated result).
3. `components/completeness/`: `completeness-panel.tsx`, `completeness-list.tsx`. `components/shared/reason-dialog.tsx`. The panel is added to `documents-workspace.tsx`.

Tests: 256 to 319. New tests cover: Daniel's and Angela's results against the scenarios; unknown case, unknown checklist and wrong checklist refused; 404 until a run; copies not changes; overrides (status, who, when, why, the checklist's answer kept, overall status and outstanding recalculated, other items untouched); refused for a blank, missing or too long reason, a satisfied item, an item already overridden and an unknown item; the real-mode requests (run, latest, the override PATCH with a trimmed reason); the shared window; the list (chips, reasons, document links by file name, Override only where allowed, overrides shown with who, when and why); the whole panel (empty state, a run for Daniel and for Angela, copy success and failure, overriding Angela's missing statement to reach Complete, the override surviving a reopen, cancel); the error cases (404 is normal, load error, run failure with a retry, a refused override keeps the window and changes nothing); and the panel on both document screens, starting afresh when another case is picked.

Checked: type check, lint and the full test suite pass. The banned-wording scan is clean. The three pages (Document intelligence, Document intake, Income analysis) load on the dev server. I did not look at it in a browser, so please try it on http://localhost:3100/underwriting/document-intelligence and http://localhost:3100/loss-mitigation/document-intake.

Open:
- Override is not in the contract. Ask Arindam for the endpoint, the three extra item fields, and the rule that only partly met or missing items can be overridden.
- The Loss Mitigation checklist id `pillar2-loss-mitigation@1` was my guess. (Day 5: the real one is `pillar2-hardship@1`, fixed.)
- The spec has a third item status, "Needs review" (a future-dated pay stub, an uncertain owner), and an overall "Needs review". The contract has only satisfied, partial, missing and overridden, and only complete or incomplete. If the backend adds them, the chips and the summary need one more case each.
- The mock document list on this screen has 4 documents for Daniel, while the scenario's full case has more (credit report, tax return). The checklist follows the scenario, so a "Documents used" link only appears where the mock list has the document.
- Daniel's scenario says the 2024 W-2 and tax return are missing on purpose, yet the income cross-checks (Group 1) quote 2024 figures from them. The scenario's own expected figures do both, so I kept them. Worth asking Abhay whether the income service reads 2024 from those documents.
- An override can be seen but not undone yet. The brief only asks for an override with a reason.

### Group 5: the Hardship and budget screen
In one line: the Hardship and budget menu item (Loss Mitigation) is now a real screen with two tabs, built for Angela Whitfield. It reads the hardship letter, checks it against the documents, and compares what she stated with what the documents show.

A change of plan, on purpose: the Day 4 brief said to write a Claude Design prompt for this screen and build it on Days 5 and 6. I built it directly in code instead, from the design system we already use and Feature Design section 7. So the prompt is not needed, and the Hardship and Budget builds that were planned for later are done now. What is left for those days is polish and the real backend.

What the screen shows, top to bottom:
1. Case picker and **Run analysis** (it becomes **Run again**), with the same progress bar as Income analysis (stages: reading the letter, comparing, building the budget, checks). A chip says the settings are "Illustrative" and when it was run.
2. **Hardship tab**, left: the letter, line by line with line IDs (p1-L6 and so on). The text each item was read from is highlighted in place. Right: the profile as four cards, **Primary reason** (Reduction in income), **Onset** (July 2026), **Duration** (Unknown) and **Intent** (Keep the home). Each card shows its quote, the line it came from, and a **✓ Quote verified** tick (or "Quote not verified" if the check failed). Each has **Show in letter** (makes that quote stand out on the left), **Confirm** and **Correct**.
3. **Hardship tab**, below: the **Consistency checks** table, Stated against Documented with a source under each value. The hours cut from 40 to 30 against a 25.00% drop in pay (2,800.00 to 2,100.00 a half-month) is the first row. Reason, intent, income and arrears agree. The spending row is flagged.
4. **Budget tab**: a **Measures** strip, each with Show working. Monthly surplus: observed **-280.00** flagged, with stated -70.00 beside it. Housing ratio **40.95%** (before the cut 30.71%). Arrears **5,160.00**. Liquid assets **640.25** (12.41% of arrears). Change in pay -25.00%.
5. **Budget tab**: the **Monthly budget** table, stated beside observed by category. "Other" is highlighted (200.00 against 410.00, +210.00, with the sentence "Observed 'other' spending 410.00 against 200.00 stated — ask the borrower"). Totals 3,420.00 and 3,630.00, and a line saying where the observed amounts come from. Each row has **Adjust**.

How the two actions work:
- **Confirm or Correct** a profile item. Confirm marks it "Reviewer-confirmed" with who and when. Correct opens a window with the allowed values (a list for reason, duration and intent; typed text for the onset) and a required reason. The card then shows the new value, your reason and "Read from the letter: Unknown", so the original reading is kept (rule 6). Confirmed values are what Feature 8 will use for the investor rules.
- **Adjust** a budget item, for example marking a spend as one-off. The window asks for the amount to count each month (a plain amount like 200.00) and a required reason. After confirming, the measures update at once: setting "Other" to 200.00 turns the surplus to -70.00, clears every flag, makes the spending check on the Hardship tab Consistent, and the row keeps "Documents showed 410.00" and your reason.

Decisions:
- The screen never calculates. Money and ratios are shown by adding separators to the backend's text. The mock repeats Angela's scenario answers. The one thing it works out is what the backend does after an adjustment, in plain code with no AI call (Feature Design 7.4): the difference, the flag (above 10% or 25.00, whichever is larger, illustrative), the totals, the surplus and the spending check, in whole cents.
- Every judgement is a person's. Nothing says approve, deny or offer. The letter reading is shown as what was read, with its quote, and a person confirms or corrects it.
- The endpoints are the four in Feature Design 7.8 (`POST /cases/{id}/hardship-assessment`, `GET .../latest`, `PUT .../latest/confirmations`, `PATCH .../latest/budget-items/{item}`). They are not in the contract yet, so the shapes (`src/lib/hardship-types.ts`) are my proposal. Each change answers with the whole updated assessment, so no part of the screen can show an old figure.
- The shared required-reason window got an optional extra field (a list or a typed value) next to the reason. It is used for the correction and the adjustment, and the income and completeness windows are unchanged.
- Document links now go to the right section for each pillar (Document intake for Loss Mitigation).
- "Hardship and budget" is marked live in the menu. Loan Processing has no such screen (404), as intended.

What I did:
1. `lib/hardship-types.ts` (the proposed shapes), `lib/hardship.ts` (display helpers, including the code that finds each quote inside its line).
2. `mocks/hardship.ts` (Angela's assessment, confirmations, adjustments) and `mocks/store.ts` (a third job kind, so a run goes queued, running, done, and the result is kept so it is still there when the screen is opened again).
3. `lib/api.ts`: `runHardshipAssessment`, `getLatestHardship`, `confirmProfileItem`, `adjustBudgetItem`.
4. `components/hardship/`: `hardship-workspace.tsx` (the screen and its two tabs), `letter-panel.tsx`, `profile-panel.tsx`, `checks-table.tsx`, `measures-strip.tsx`, `budget-table.tsx`, `source-line.tsx`, `hardship-screen.tsx`, and the route `src/app/[pillar]/hardship-budget/page.tsx`.

Tests: 319 to 444. New tests cover: Angela's figures against the scenario (profile, six checks, budget, five measures with working); every quote being an exact piece of its cited lines; confirm and correct (who, when, why, the letter reading kept even after two corrections, refused without a value, a reason or an allowed value); adjustments (clearing the flag at 200.00, still flagged at 300.00 with a deficit of 170.00, the 25.00 tolerance edge, the first observed amount kept after two adjustments, refused for a blank or too long reason or a bad amount, the other measures untouched); the job flow and 404 before a run; the real-mode requests (POST, GET, PUT with a trimmed value and reason, PATCH with a trimmed amount and reason); the helpers; the letter highlighting; each panel and table; the extended window; and the whole screen (empty state, a full run on the real clock, both tabs, confirm, correct, adjust with every figure updating, the decision surviving a reopen, a case with no letter, and every failure: a 404 is normal, a load error, a start error, a failed job, a refused confirm, correction and adjustment each leaving things as they were).

Checked: type check, lint and the full test suite pass. The banned-wording scan is clean. `/loss-mitigation/hardship-budget` loads (HTTP 200) and `/underwriting/hardship-budget` is a 404. I did not look at it in a browser, so please try it on http://localhost:3100/loss-mitigation/hardship-budget and press Run analysis.

Open:
- Nothing from the real backend yet: no hardship endpoints on `main`, so the figures come from the mock. See the checklist.
- A confirmed profile is not passed on to anything yet. Feature 8 (Recommendation) will read it; its screen is not part of this build.
- Only the latest correction or adjustment per item shows on the screen. The backend should keep every one as audit history (rule 6).
- The letter is shown as text with line IDs from the assessment, not as the page image with a box. The page picture comes with the page image endpoint (Day 3 question).
- The documents behind the evidence links are the mock list's (for example the October bank statement stands in for the July one the scenario uses), so a link may open a nearby document rather than the exact one.

### Group 6: the end-to-end income test and the final checks
In one line: one test now walks the whole Income analysis flow for Daniel Reyes in order, and every final check for Day 4 passes. No screen changed in this group.

The new test (`components/income/income-flow.test.tsx`) uses the real mock backend with nothing stubbed, and does what a person would:
1. Opens Daniel's income screen: "No income analysis yet".
2. Presses **Run analysis**: the progress bar shows, then the result replaces it.
3. Sees the candidate monthly income **5,980.00** with its label "candidate - qualifying income is determined by the underwriter".
4. Opens the working behind base pay: the formula (34.50 × 80.00 hours × 26 periods ÷ 12), the pay stub it was read from, and a link to that document.
5. Sees the flag (income.short_history) with its explanation marked "possible — to be confirmed".
6. Counts overtime: the button stays disabled until a reason is typed, then the candidate becomes **6,424.41** and the row shows the reason.
7. Leaves overtime out again with another reason: **5,980.00** returns and overtime shows "Left out".
The earlier tests check each piece on its own. This one checks that the pieces work together, in this order.

Final checks, all run after the last change:
- Type check: clean. Lint: clean.
- Tests: 445 pass (444 plus this one), in 46 files.
- Production build (`npm run build`, with the dev server stopped first): passes, and lists the income-analysis and hardship-budget routes. I restarted the dev server afterwards on a clean `.next`.
- Banned-wording scan of `src` and `public`: clean. It found the word "offers" in one code comment, which is not screen text; I reworded it so the scan is empty.

What "done" means for Day 4: the brief's "done when" (Daniel's income tab shows 5,980.00 with working from the real API) is met on the mock backend. It cannot be met on the real API yet, because the backend has no income service, the contract has no income endpoints, and the frontend has no login or CORS. Each is on the checklist below.

Open:
- Nothing is committed yet. Day 4 is on branch `feat/amogh/doc-review-viewer` as uncommitted files. The plan is a new branch on top of it, then a rebase onto `main` once PR #8 is merged.
- Not looked at in a browser by me. Please click through the three screens (Income analysis, Documents with Completeness, Hardship and budget) before the PR.

## Day 5 (Fri 20 Nov 2026 in the plan, built Mon 23 Nov)
Goal from the brief: build the Hardship tab against the real `GET .../hardship-assessment/latest` and `PUT .../confirmations`, light up a quote's lines in the letter when its profile item is hovered, then polish only the four demo screens (upload, review, income, hardship): loading skeletons, empty states, error messages with retry, and numbers with two decimals and thousands separators.

A note on the design: no Claude Design prompt came with this day, and the Hardship screen was already built on Day 4. So I built from the design system we already use, and this day is the hover, the real backend's shapes and the polish.

### Group 1: the Hardship tab, the hover, and the real backend's shapes
In one line: pointing at a profile item now lights its lines in the letter, and the screen can read the real backend's hardship answers, not only the mock.

What I found first: on 23 Nov PRs #8 and #10 merged, so Abhay's income and completeness endpoints are on `main`. His branch `feat/abhay/frontend-unblock` had the real hardship endpoints; it merged as #12 the same evening, and I checked that the hardship shape on `main` is the one I translated. They differ from what I proposed on Day 4:
- Running it answers `{ job }`, not a bare job.
- Confirming is a `PUT .../latest/confirmations` whose body names the item: `{ duration: { value, reason } }`, or `{ duration: {} }` to confirm. Mine sent `{ key, action, value, reason }`.
- Adjusting a budget line is `PATCH .../latest/budget/{line_id}` with `{ adjusted_amount, reason }`. Mine was `.../budget-items/{item}` with `{ amount, reason }`.
- The answer has a different shape (profile objects, measures as calculations with a one-line working text, checks with a `values` list), and ratios come as six-place decimals ("0.409524").
- It has no letter text, only each quote and the line IDs it sits on.
- A corrected onset must be a month written `YYYY-MM`.

What I did:
1. **Hover.** Pointing at a profile card, or putting the keyboard focus on one of its buttons, lights the lines that quote came from in the letter (a soft gold band) and shows the quote strongly. It wins over the item picked with "Show in letter" until the pointer leaves, then the picked item shows again. A quote over several lines lights every line.
2. **The real shapes.** A new file `src/lib/hardship-real.ts` reads the backend's answer into the shape the screen already uses, so the screens did not change for it. In real mode `api.ts` now uses the real paths and bodies. In mock mode nothing changed. It calculates nothing: it renames, picks labels and cuts the backend's working text into steps.
3. **Onset.** The onset is now a month written `YYYY-MM` (shown as "July 2026"), checked as you type, in the mock too, so both behave like the real backend.
4. **Checklist id.** The Loss Mitigation checklist id is `pillar2-hardship@1` (read from Abhay's config). I had guessed another one; it is fixed.

Decisions:
- The screen never sees the backend's shape. If it changes, only `hardship-real.ts` changes.
- A percentage is shown from the end of the backend's own working text ("... = 40.95%"). The screen never multiplies a ratio by 100. If that text is missing, the ratio is shown as it came.
- The backend sends the gap on a budget line without a sign. The screen shows it as it came ("210.00") and does not add a plus sign it cannot be sure of.
- The backend does not send the letter's text, so in real mode the letter shows the quoted lines only, with a note saying so. A quote over several lines shows on its first line.
- The backend does not send the lists a correction chooses from, so the reason, duration and intent lists are repeated in `hardship-real.ts` (the reasons mirror `backend/config/hardship.yaml`).
- The backend flags budget lines and checks, not measures. So in real mode the surplus card has no "Flagged" chip; the flagged "Other" line carries the backend's sentence.
- The reviewer shows as the backend's user id until it sends a name.

### Group 2: polish on the four demo screens
In one line: the same loading, empty and error behaviour on upload, review, income and hardship, and one way of writing numbers.
- **Loading.** Each screen shows a skeleton shaped like what is coming (a table, cards, or a page beside a list) instead of one grey block. Each is announced to screen readers as loading.
- **Empty states.** One shared panel with a title and what to do next: "No documents yet", "No documents with flagged fields", "Nothing to review yet" (with Check again), "Not run yet" (income and hardship).
- **Errors.** Two kinds, on purpose:
  - A failure that stops a screen showing what it should (it could not load, the run could not start, or the run failed) shows a notice in place with **Try again**, which repeats that step.
  - A failure of one action while the screen is fine (an upload, saving a field review, confirming a profile item) shows a message at the bottom right with **Try again**, which does the same action again. It stays until dismissed or retried. What was typed or chosen is kept.
  - A failure inside a window (correction, adjustment, type) stays in the window, as before.
  - An edit conflict still shows the Reload message on the review screen.
- **Numbers.** Values read from documents now show like every other figure: `2083.61` becomes `2,083.61`. Only text with exactly two decimals is changed, so a year, an account number or a name is never given commas. Nothing is parsed or rounded.
- An upload that finishes with a file-type problem still lists the problem under the drop zone.

What I did: new shared pieces `toast.tsx` (provider mounted once in the pillar layout), `error-notice.tsx`, `empty-state.tsx`, `skeletons.tsx`, and `formatFieldValue` in `lib/format.ts`; then used them in the documents screen, document table, field list and rows, review screen, upload panel, income screen and hardship screen.

### Group 3: tests and checks
Tests: 445 to 538. New tests cover: the translation of the real hardship answer from a sample written from Abhay's schema (profile, corrections, the letter's quoted lines, five measures with the backend's percentage text, the budget and an adjustment, the checks, and what a person sends); the real paths and bodies in `api.test.ts`; the hover on the letter, the cards (pointer and keyboard) and the whole screen; the toasts (a failure stays, a confirmation goes away, no stacking, a failing retry); the notice, empty and skeleton pieces; the field value formatting and the onset month; the review, documents, income and hardship screens loading, failing, retrying and being empty; and the unsigned gap. I also made four drawer assertions wait for the side panel, because they failed now and then when the whole suite ran at once.

Checked: type check, lint and all 538 tests pass; the production build passes (dev server stopped first, then restarted clean); the banned-wording scan of `src` and `public` is clean; `/loss-mitigation/hardship-budget` loads, `/underwriting/hardship-budget` is a 404. I have not looked at it in a browser: please open the Hardship tab, point at each profile card, and watch the letter on the left.

Open:
- Income and completeness still use my own shapes. The real ones on `main` differ (see the checklist), so they need the same kind of translation file. That is the next piece of work.
- Real mode still needs a login screen and CORS before anything can run against the real backend. The hardship translation is tested on a sample written from the schema, not on a real answer.
- Only the Hardship tab's letter is partial in real mode, until the backend can return the letter's text.

## Going live checklist (real backend instead of mocks)
Everything runs on mocks today. Flipping `NEXT_PUBLIC_USE_MOCKS=false` needs the items below. I update this list after every group or day, and tick items when the other side delivers them.

Needed before real mode works at all:
- [ ] Login screen and token handling. The backend has `/auth/login` (seeded users `underwriter` and `lm_specialist`), but the frontend has no sign-in page, so no request carries a token yet. Mine to build next.
- [x] CORS on the backend, so the browser on port 3000 may call the API on port 8000. On `main` since #12 (23 Nov). It reads its allowed origins from the backend settings, so the frontend's address (port 3000) has to be in that list when the backend runs.
- [x] Document, income and completeness endpoints on `main`: merged in #10 on 23 Nov. Still to do on my side: check my Day 2 and 3 screens against the real document answers once login and CORS exist.
- [x] Hardship endpoints on `main`: merged in #12 (23 Nov). The frontend reads them through `hardship-real.ts`; not yet tried against a running backend.

Real shapes on `main` that my screens do not read yet (from Abhay's #10, found 23 Nov). Each needs a translation file like `hardship-real.ts`:
- [ ] Income analysis. Paths: `POST /cases/{id}/income-analysis` (answers `{ job, analysis_id }`), `GET .../latest`, `PATCH .../latest/components/{component_id}` with `{ included, reason }` (component ids are UUIDs). Mine are `/income/analysis...`. The answer differs: `ytd` and `monthly` are plain text, each component's working is one text string inside `calculation`, an override is `{ included, reason, by, at }` beside `system_included`, flags carry `refs`, and there is a `candidate_label`. The AI explanations are empty ("explanations not generated") until `income-explain@1` is wired in, so the flag cards need an honest empty state for them. (Day 4, Groups 1 to 3)
- [ ] Completeness override. The real one is `PATCH /cases/{id}/completeness/latest/items/{item_id}` with `{ action: "override" | "clear", reason }`. Mine is `.../items/{item_id}` with `{ reason }`. An overridden item comes as status `overridden` with `override_reason`, but with no who and when, which the project's rule on corrections needs. "Needs review" arrives as `partial` with a "Needs review:" prefix. The Loss Mitigation checklist id is `pillar2-hardship@1` (done). (Day 4, Group 4)

Contract gaps (Arindam owns `contracts/`; I only ask):
- [ ] Income, completeness override and hardship endpoints are in Abhay's code and in `docs/contract-proposal-d4.md`, but not in `contracts/openapi.yaml`. Ask Arindam to add them, so the contract and not only the code says what they are. (Day 4)
- [ ] Page image endpoint: now on `main` (#12) as `GET /documents/{id}/pages/{page}` (`getPageImage`). I have not connected it yet: `getPageImage` in `api.ts` still answers "none" in real mode. (Day 3)

Questions for Abhay and Arindam:
- [ ] Bounding boxes: is the origin the top left of the page, as I assume? (Day 3)
- [ ] Upload: multipart through the API (the contract) or a presigned S3 upload (the tech design)? (Day 2)
- [ ] When a document's type changes, does the real backend drop the old extraction, as the mock does? (Day 3)
- [ ] Hardship: can the answer include the letter's text with its line IDs (or a lines endpoint)? Today it has only the quoted lines, so the letter is partial. (Day 5)
- [ ] Hardship: can `confirmation.by` be a name and not a user id? And can the answer include the allowed values for the reason, so I do not repeat the list from `hardship.yaml`? (Day 5)
- [ ] Hardship: the checks carry no document references, so each side's source shows only "Application", "Pay stubs" or "Hardship letter". Can each check say which document and line it used? (Day 5)
- [ ] Hardship: measures are never flagged, only budget lines and checks. Is that meant? (Day 5)
- [ ] Completeness and income: can an override or a decision say who and when (a name, not an id)? Today the mock shows "demo.reviewer". After login the backend should fill it from the token. (Day 4)
- [ ] Income: when I connect the real answer, do the figures and working match the scenario numbers (5,980.00 base, 444.41 overtime, 228.34 bonus)? (Day 4)
- [x] Hardship: is the letter reading a job? Yes, it answers `{ job }`. Does it return `quote_verified`? Yes, as `verified`. (Day 5)
- [x] Hardship: the stated-against-observed tolerance. It is in `thresholds.yaml` (`stated_vs_observed_tolerance`) and the backend sets the flags. (Day 5)
- [x] Completeness: the Loss Mitigation checklist id is `pillar2-hardship@1`. (Day 5)

Housekeeping:
- [ ] Add `npm test` to the CI frontend job (it runs typecheck, lint and build today).
- [ ] Evidence links on the Income screen open the document's review screen. Make the review screen open on a given page and line (mine, small). (Day 4, Group 2)
- [ ] The Hardship and budget screen is built on the mock and on a sample of the real answer. Once the endpoints, login and CORS exist, flip `NEXT_PUBLIC_USE_MOCKS=false`, run Angela's case, and check the profile (reduction in income, July 2026, unknown, keep), the 40 to 30 hours against a 25.00% pay drop, surplus -70.00 stated and -280.00 observed, housing ratio 40.95% from 30.71%, arrears 5,160.00 and liquid assets 640.25 = 12.41%. (Day 4 and 5)
- [ ] The Completeness panel is built on the mock. After it reads the real answer, run Daniel's case and check it shows Incomplete with pay stubs 14 of 30 days and the 2024 W-2 and tax return missing, then Angela's with the August bank statement missing. (Day 4, Group 4)
- [ ] The income screen is built on the mock. After it reads the real answer, run Daniel's case and check it shows 5,980.00 with the backend's working. That is the Day 4 "done when", met on the mock (the end-to-end test `income-flow.test.tsx` walks it). (Day 4, Group 6)
