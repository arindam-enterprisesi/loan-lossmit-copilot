# Provider evaluation (2026-11-25)

Same checks on each provider, on the synthetic samples (`python -m app.llm.evaluate`).
A pass means the output matched the known answer and passed the code checks.

| Check | anthropic (claude-opus-5-5) | bedrock (global.anthropic.claude-sonnet-4-6) |
| --- | --- | --- |
| classify | pass, 10.9 s | pass, 4.8 s |
| extract | pass, 16.3 s | pass, 22.8 s |
| label | pass, 8.0 s | pass, 4.4 s |
| hardship | pass, 7.6 s | pass, 11.7 s |
| explain | pass, 6.0 s | pass, 5.0 s |
| guideline | pass, 6.0 s | pass, 5.5 s |

Details:

- anthropic / classify: type=pay_stub certainty=high lines=['p1-L4', 'p1-L9', 'p1-L10', 'p1-L17', 'p1-L31'] model=claude-opus-5-5 attempts=1 in=2854 out=64 3590ms
- anthropic / extract: net pay 2,083.61 @ p1-L31 model=claude-opus-5-5 calls=1 attempts=1 in=4448 out=1683 16314ms
- anthropic / label: 24 labelled, needs review=[], unknown=[] model=claude-opus-5-5 calls=1 in=2283 out=918 7967ms
- anthropic / hardship: reduction_in_income/2026-07/unknown/keep quotes=11 flagged=[] model=claude-opus-5-5 attempts=1 in=3641 out=609 7536ms
- anthropic / explain: 2 explanation(s), cites Box 12=True, flags=[] model=claude-opus-5-5 attempts=1 in=1454 out=510 5943ms
- anthropic / guideline: 9 sentences, 1 removed, cites fhlmc-guide.5303.1, fnma-sg.B3-3.1-01.variable, lender-overlay.LO-1
- bedrock / classify: type=pay_stub certainty=high lines=['p1-L4', 'p1-L13', 'p1-L17', 'p1-L25', 'p1-L31'] model=global.anthropic.claude-sonnet-4-6 attempts=1 in=2238 out=56 4748ms
- bedrock / extract: net pay 2,083.61 @ p1-L31 model=global.anthropic.claude-sonnet-4-6 calls=1 attempts=1 in=3626 out=1246 22788ms
- bedrock / label: 24 labelled, needs review=[], unknown=[] model=global.anthropic.claude-sonnet-4-6 calls=1 in=1782 out=611 4423ms
- bedrock / hardship: reduction_in_income/2026-07/unknown/keep quotes=11 flagged=[] model=global.anthropic.claude-sonnet-4-6 attempts=1 in=3001 out=446 11701ms
- bedrock / explain: 1 explanation(s), cites Box 12=True, flags=[] model=global.anthropic.claude-sonnet-4-6 attempts=1 in=1138 out=220 4997ms
- bedrock / guideline: 3 sentences, 1 removed, cites fhlmc-guide.5303.1, fnma-sg.B3-3.1-01.variable
