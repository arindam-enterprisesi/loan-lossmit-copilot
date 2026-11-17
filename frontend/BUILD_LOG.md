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

### Open items
- Add tests (Vitest). `CLAUDE.md` requires them and there's no frontend test setup yet.
- Ask Arindam whether `Case` in the contract should have a display reference like `LP-0001`. The PRD screens show one; for now it comes from a mock-only lookup.
- Ask Arindam about the two `npm audit` warnings (dev-only `minimatch`, `postcss` bundled in Next 15). The only fix is a forced jump to Next 16, which I didn't take.
- Sidebar is desktop-only for now.
