"""Local web UI: filter Greenhouse jobs and see ATS match against the resume."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
from flask import Flask, jsonify, request, send_from_directory

from .analysis import employment_type, parse_salary
from .greenhouse import fetch_board
from .matcher import rank
from .resume import extract_skills, extract_text, has_term

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "jobs_cache.json"
CACHE_TTL = 6 * 3600
MAX_ROWS = 300

JOB_TYPES = {
    "SRE / Reliability": ["site reliability", "sre", "reliability"],
    "DevOps / Platform / Infra": ["devops", "platform engineer", "infrastructure", "cloud engineer"],
    "Engineering Manager": ["engineering manager", "manager, engineering", "manager, software",
                            "director of engineering", "director, engineering", "head of engineering"],
    "Technical Program Manager": ["program manager"],
    "Database / Data": ["database", "dba", "data engineer", "data platform"],
    "Security": ["security engineer", "security"],
    "Software Engineer": ["software engineer"],
}
REMOTE_TERMS = ["remote - us", "remote, us", "remote - united states", "remote, united states",
                "remote-us", "us-remote", "remote - usa"]
EMPLOYMENT = {"full_time": "Full-time (FTE)", "part_time": "Part-time", "contract": "Contract", "intern": "Intern"}

app = Flask(__name__, static_folder=str(ROOT / "static"))
STATE = {"jobs": [], "loading": False, "done": 0, "total": 0, "fetched_at": 0, "skills": set(), "cfg": {}}


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    sources = [cfg["resume"], *cfg.get("master_resume", [])]
    STATE["cfg"] = cfg
    STATE["skills"] = extract_skills("\n".join(extract_text(p) for p in sources), cfg.get("extra_skills", []))


def enrich(job):
    sal = parse_salary(job.pop("pay", []), job["text"])
    job["salary"] = list(sal) if sal else None
    job["employment"] = employment_type(job["title"], job["text"])
    return job


def refresh(force=False):
    if STATE["loading"]:
        return
    if not force and CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_TTL:
        STATE["jobs"] = json.loads(CACHE.read_text(encoding="utf-8"))
        STATE["fetched_at"] = CACHE.stat().st_mtime
        return
    boards = STATE["cfg"]["boards"]
    STATE.update(loading=True, done=0, total=len(boards))

    def work():
        jobs = []

        def one(token):
            got = [enrich(j) for j in fetch_board(token)]
            STATE["done"] += 1
            return got

        try:
            with ThreadPoolExecutor(8) as ex:
                for got in ex.map(one, boards):
                    jobs += got
            STATE["jobs"] = jobs
            STATE["fetched_at"] = time.time()
            CACHE.parent.mkdir(exist_ok=True)
            CACHE.write_text(json.dumps(jobs), encoding="utf-8")
        finally:
            STATE["loading"] = False

    threading.Thread(target=work, daemon=True).start()


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/meta")
def meta():
    return jsonify(job_types=list(JOB_TYPES), employment=EMPLOYMENT, skills=sorted(STATE["skills"]))


@app.get("/api/status")
def status():
    return jsonify(loading=STATE["loading"], done=STATE["done"], total=STATE["total"],
                   jobs=len(STATE["jobs"]), fetched_at=STATE["fetched_at"])


@app.post("/api/refresh")
def do_refresh():
    refresh(force=True)
    return jsonify(ok=True)


def salary_ok(job, lo, hi, require):
    if not job["salary"]:
        return not require
    jlo, jhi = job["salary"]
    return (hi is None or jlo <= hi) and (lo is None or jhi >= lo)


def search(body, jobs, skills):
    kws = [k for t in body.get("job_types", []) for k in JOB_TYPES.get(t, [])]
    kws += [k.strip().lower() for k in body.get("keywords", "").split(",") if k.strip()]
    cities = [c.strip().lower() for c in body.get("cities", []) if c.strip()]
    remote = bool(body.get("remote_us"))
    include = cities + (REMOTE_TERMS if remote else [])
    emp = set(body.get("employment") or EMPLOYMENT)
    lo, hi = body.get("salary_min"), body.get("salary_max")
    jobs = [j for j in jobs
            if j["employment"] in emp
            and (not kws or any(has_term(j["title"].lower(), k) for k in kws))
            and salary_ok(j, lo, hi, body.get("require_salary"))]
    ranked = rank(jobs, skills, 0, target_titles=kws, include_locations=include, nationwide=remote)
    ranked = [r for r in ranked if r["ats"] >= body.get("min_ats", 0)]
    ranked.sort(key=lambda r: (-r["ats"], -r["score"]))
    rows = [{k: r[k] for k in ("title", "company", "location", "url", "ats", "matched", "missing",
                               "employment", "salary")} for r in ranked[:MAX_ROWS]]
    return {"total": len(ranked), "rows": rows}


@app.post("/api/search")
def do_search():
    return jsonify(search(request.get_json(force=True) or {}, STATE["jobs"], STATE["skills"]))


def main():
    load_config()
    refresh()
    app.run(host="127.0.0.1", port=5050)


if __name__ == "__main__":
    main()
