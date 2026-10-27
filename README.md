# Greenhouse Job Finder

Pulls open roles from Greenhouse-hosted job boards and ranks them against the skills in your
resume, using Greenhouse's public Job Board API (no login, no scraping — see [PLAN.md](PLAN.md)
for the design rationale).

## Project layout

```
jobfinder/
  greenhouse.py   # fetches + normalizes postings from the public Greenhouse Job Board API
  resume.py       # extracts text/skills from a resume (PDF or DOCX)
  matcher.py      # scores a job against a skill set + title/location filters
  analysis.py     # salary and employment-type inference from job text
  cli.py          # batch run: resume + boards -> output/matches.{csv,md}
  web.py          # local Flask UI for interactively filtering/searching jobs
static/
  index.html      # the web UI's front end
tests/
  test_jobfinder.py
config.example.yaml  # template — copy to config.yaml and fill in your resume path
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"         # installs the package + pytest, with console entry points
copy config.example.yaml config.yaml   # then edit config.yaml: resume path, boards, filters
```

`config.yaml` is gitignored — it holds your personal resume path and tuning, so it never gets
committed. `config.example.yaml` is the tracked template.

## Usage

Batch CLI — scans every board in `config.yaml`, writes `output/matches.csv` and
`output/matches.md`:

```bash
jobfinder --config config.yaml
```

Web UI — fetches boards once (cached for 6h), then lets you filter/search interactively at
`http://127.0.0.1:5050`:

```bash
jobfinder-web
```

(or double-click `run_ui.bat` on Windows, which opens the page for you).

## Tests

```bash
pytest
```
