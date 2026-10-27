"""Local web UI: filter Greenhouse jobs and see ATS match against the resume."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import yaml
from flask import Flask, jsonify, request, send_from_directory

from . import db, profiles
from .analysis import employment_type, parse_salary
from .greenhouse import fetch_board
from .job_types import JOB_TYPES
from .matcher import rank
from .resume import has_term

ROOT = db.ROOT
CACHE = ROOT / "data" / "jobs_cache.json"
CACHE_TTL = 6 * 3600
MAX_ROWS = 300

REMOTE_TERMS = ["remote - us", "remote, us", "remote - united states", "remote, united states",
                "remote-us", "us-remote", "remote - usa"]
EMPLOYMENT = {"full_time": "Full-time (FTE)", "part_time": "Part-time", "contract": "Contract", "intern": "Intern"}

app = Flask(__name__, static_folder=str(ROOT / "static"))
STATE = {"jobs": [], "loading": False, "done": 0, "total": 0, "fetched_at": 0, "cfg": {}}


def load_config():
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    STATE["cfg"] = cfg
    db.init_db()
    profiles.seed_from_config(cfg)


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
    return jsonify(job_types=list(JOB_TYPES), employment=EMPLOYMENT)


@app.get("/api/profiles")
def list_profiles():
    return jsonify(profiles=profiles.list_profiles())


@app.post("/api/profiles")
def create_profile():
    name = (request.get_json(force=True) or {}).get("name", "").strip()
    if not name:
        return jsonify(error="name is required"), 400
    return jsonify(profiles.get_or_create_profile(name))


@app.get("/api/profiles/<int:profile_id>")
def get_profile(profile_id):
    profile = profiles.get_profile(profile_id)
    if not profile:
        return jsonify(error="not found"), 404
    return jsonify(profile)


@app.delete("/api/profiles/<int:profile_id>")
def delete_profile(profile_id):
    if not profiles.delete_profile(profile_id):
        return jsonify(error="not found"), 404
    return jsonify(ok=True)


@app.post("/api/profiles/<int:profile_id>/documents")
def add_profile_document(profile_id):
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="file is required"), 400
    kind = request.form.get("kind", "document")
    profile = profiles.add_document(profile_id, kind, file.filename, file.read())
    if not profile:
        return jsonify(error="not found"), 404
    return jsonify(profile)


@app.post("/api/profiles/<int:profile_id>/notes")
def add_profile_note(profile_id):
    text = (request.get_json(force=True) or {}).get("text", "").strip()
    if not text:
        return jsonify(error="text is required"), 400
    profile = profiles.add_note(profile_id, text)
    if not profile:
        return jsonify(error="not found"), 404
    return jsonify(profile)


@app.post("/api/profiles/<int:profile_id>/skills")
def add_profile_skill(profile_id):
    skill = (request.get_json(force=True) or {}).get("skill", "").strip()
    if not skill:
        return jsonify(error="skill is required"), 400
    profile = profiles.add_manual_skill(profile_id, skill)
    if not profile:
        return jsonify(error="not found"), 404
    return jsonify(profile)


@app.post("/api/profiles/<int:profile_id>/skills/remove")
def remove_profile_skill(profile_id):
    skill = (request.get_json(force=True) or {}).get("skill", "").strip()
    if not skill:
        return jsonify(error="skill is required"), 400
    profile = profiles.remove_skill(profile_id, skill)
    if not profile:
        return jsonify(error="not found"), 404
    return jsonify(profile)


@app.post("/api/profiles/<int:profile_id>/job_types")
def add_profile_job_type(profile_id):
    label = (request.get_json(force=True) or {}).get("label", "").strip()
    if not label:
        return jsonify(error="label is required"), 400
    return jsonify(job_types=profiles.add_custom_job_type(profile_id, label))


@app.post("/api/profiles/<int:profile_id>/desired")
def set_profile_desired(profile_id):
    labels = (request.get_json(force=True) or {}).get("labels", [])
    return jsonify(job_types=profiles.set_desired_job_types(profile_id, labels))


@app.post("/api/profiles/<int:profile_id>/job_types/dismiss")
def dismiss_profile_job_type(profile_id):
    body = request.get_json(force=True) or {}
    label = body.get("label", "").strip()
    if not label:
        return jsonify(error="label is required"), 400
    return jsonify(job_types=profiles.set_job_type_dismissed(profile_id, label, bool(body.get("dismissed", True))))


@app.get("/api/profiles/<int:profile_id>/documents/<int:doc_id>/download")
def download_profile_document(profile_id, doc_id):
    path = profiles.get_document_file(profile_id, doc_id)
    if not path or not path.exists():
        return jsonify(error="not found"), 404
    return send_from_directory(path.parent, path.name, as_attachment=True)


@app.get("/api/status")
def status():
    return jsonify(loading=STATE["loading"], done=STATE["done"], total=STATE["total"],
                   jobs=len(STATE["jobs"]), fetched_at=STATE["fetched_at"])


@app.post("/api/refresh")
def do_refresh():
    refresh(force=True)
    return jsonify(ok=True)


def days_since_posted(updated):
    """Days since a job's updated_at, or None if the timestamp is missing/unparsable."""
    try:
        dt = datetime.fromisoformat(updated)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def salary_ok(job, lo, hi, require):
    if not job["salary"]:
        return not require
    jlo, jhi = job["salary"]
    return (hi is None or jlo <= hi) and (lo is None or jhi >= lo)


def search(body, jobs, skills, skill_weights=None, feedback=None):
    kws = [k for t in body.get("job_types", []) for k in JOB_TYPES.get(t, [])]
    kws += [k.strip().lower() for k in body.get("keywords", "").split(",") if k.strip()]
    cities = [c.strip().lower() for c in body.get("cities", []) if c.strip()]
    remote = bool(body.get("remote_us"))
    include = cities + (REMOTE_TERMS if remote else [])
    emp = set(body.get("employment") or EMPLOYMENT)
    lo, hi = body.get("salary_min"), body.get("salary_max")
    days = body.get("days")
    jobs = [j for j in jobs
            if j["employment"] in emp
            and (not kws or any(has_term(j["title"].lower(), k) for k in kws))
            and salary_ok(j, lo, hi, body.get("require_salary"))
            and (not days or (days_since_posted(j.get("updated")) or 0) <= days)]
    ranked = rank(jobs, skills, 0, target_titles=kws, include_locations=include, nationwide=remote,
                  skill_weights=skill_weights)
    ranked = [r for r in ranked if r["ats"] >= body.get("min_ats", 0)]
    ranked.sort(key=lambda r: (-r["ats"], -r["score"]))
    feedback = feedback or {}
    rows = [{**{k: r[k] for k in ("title", "company", "location", "url", "ats", "matched", "missing",
                                  "employment", "salary")}, "posted_days_ago": days_since_posted(r.get("updated")),
             "feedback": feedback.get(r["url"])}
            for r in ranked[:MAX_ROWS]]
    return {"total": len(ranked), "rows": rows}


@app.post("/api/search")
def do_search():
    body = request.get_json(force=True) or {}
    profile_id = body.get("profile_id")
    skills = profiles.get_skills(profile_id) if profile_id else set()
    weights = profiles.get_skill_weights(profile_id) if profile_id else None
    feedback = profiles.get_feedback(profile_id) if profile_id else None
    return jsonify(search(body, STATE["jobs"], skills, skill_weights=weights, feedback=feedback))


@app.post("/api/profiles/<int:profile_id>/feedback")
def add_job_feedback(profile_id):
    body = request.get_json(force=True) or {}
    url = body.get("url", "").strip()
    decision = body.get("decision")
    if not url or decision not in ("picked", "passed"):
        return jsonify(error="url and a valid decision are required"), 400
    job = next((j for j in STATE["jobs"] if j.get("url") == url), None)
    if not job:
        return jsonify(error="job not found"), 404
    return jsonify(profiles.set_job_feedback(profile_id, url, job["title"], job["company"], job["text"], decision))


@app.post("/api/profiles/<int:profile_id>/applied_jobs")
def add_applied_job(profile_id):
    body = request.get_json(force=True) or {}
    title = body.get("title", "").strip()
    text = body.get("text", "").strip()
    company = body.get("company", "").strip()
    if not title or not text:
        return jsonify(error="title and text are required"), 400
    profile = profiles.add_applied_job(profile_id, title, company, text)
    if not profile:
        return jsonify(error="not found"), 404
    return jsonify(profile)


def main():
    load_config()
    refresh()
    app.run(host="127.0.0.1", port=5050)


if __name__ == "__main__":
    main()
