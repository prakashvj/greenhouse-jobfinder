# Greenhouse Job Finder – Project Plan

## Goal
Pull jobs from Greenhouse-hosted boards and rank them against the skills in my resume.

## Key decision: data source
`my.greenhouse.io` is the login-gated candidate portal (no public API, ToS/bot-detection concerns,
and credentials must not be automated). Every Greenhouse customer, however, exposes a **public Job Board API**:
`https://boards-api.greenhouse.io/v1/boards/<board_token>/jobs?content=true`. We use that: stable JSON, no login, no scraping.

## Architecture
resume.pdf/docx -> `resume.py` (text + skill extraction vs. skills vocabulary)
config.yaml (board tokens, target titles, locations) -> `greenhouse.py` (fetch, polite, retries)
-> `matcher.py` (score = weighted skill overlap + title match + location filter)
-> `cli.py` (CSV + Markdown report in `output/`).

## Scoring
- Skill score: matched resume skills in job text / skills required, weighted (title hit x3, body x1).
- Title bonus for target titles (SRE, Engineering Manager, ...).
- Location filter (include/exclude substrings). Final 0-100; threshold in config.

## Milestones
1. Plan + scaffold  2. Resume parser  3. API client  4. Matcher  5. CLI/reports
6. Unit tests (offline, fixtures) + one live smoke test  7. Execute, review results, tune.

## Risks
Board tokens must be known (maintained in config.yaml); HTML in content (stripped); rate limits (sleep + retry).
