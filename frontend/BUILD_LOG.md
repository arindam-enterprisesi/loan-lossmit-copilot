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
