"""Per-person profiles: accumulated skills, uploaded documents, and job-type suggestions.

A profile's skills and "possible" job types only ever grow as documents/notes are added -
returning with the same name adds to the existing profile; a different name starts a fresh one.
"""
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.utils import secure_filename

from . import db
from .job_types import JOB_TYPES
from .resume import detect_skills, extract_skills, extract_text, has_term


def _profiles_dir(db_path):
    """Uploaded files live next to the DB file (data/profiles/ in production, tmp_path in tests)."""
    return Path(db_path).parent / "profiles"


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_or_create_profile(name, db_path=db.DB_PATH):
    name = name.strip()
    conn = db.connect(db_path)
    try:
        row = conn.execute("SELECT id, name FROM profiles WHERE lower(name) = lower(?)", (name,)).fetchone()
        if row:
            return {"id": row["id"], "name": row["name"]}
        cur = conn.execute("INSERT INTO profiles (name, created_at) VALUES (?, ?)", (name, _now()))
        conn.commit()
        return {"id": cur.lastrowid, "name": name}
    finally:
        conn.close()


def list_profiles(db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        rows = conn.execute("SELECT id, name FROM profiles ORDER BY name").fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    finally:
        conn.close()


def delete_profile(profile_id, db_path=db.DB_PATH):
    """Permanently remove a profile and everything tied to it. Not reversible, unlike dismiss."""
    conn = db.connect(db_path)
    try:
        conn.execute("DELETE FROM profile_skills WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM profile_documents WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM profile_job_types WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM job_feedback WHERE profile_id = ?", (profile_id,))
        cur = conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        conn.commit()
        deleted = cur.rowcount > 0
    finally:
        conn.close()
    if deleted:
        shutil.rmtree(_profiles_dir(db_path) / str(profile_id), ignore_errors=True)
    return deleted


def get_skills(profile_id, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        rows = conn.execute("SELECT skill FROM profile_skills WHERE profile_id = ?", (profile_id,)).fetchall()
        return {r["skill"] for r in rows}
    finally:
        conn.close()


def _accumulate_skills(conn, profile_id, text, extra=()):
    found = extract_skills(text, extra)
    now = _now()
    for skill in found:
        conn.execute("INSERT OR IGNORE INTO profile_skills (profile_id, skill, added_at) VALUES (?, ?, ?)",
                     (profile_id, skill, now))
    return found


def add_manual_skill(profile_id, skill, db_path=db.DB_PATH):
    skill = skill.strip().lower()
    conn = db.connect(db_path)
    try:
        conn.execute("INSERT OR IGNORE INTO profile_skills (profile_id, skill, added_at) VALUES (?, ?, ?)",
                     (profile_id, skill, _now()))
        conn.commit()
    finally:
        conn.close()
    return get_profile(profile_id, db_path)


def remove_skill(profile_id, skill, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        conn.execute("DELETE FROM profile_skills WHERE profile_id = ? AND skill = ?", (profile_id, skill))
        conn.commit()
    finally:
        conn.close()
    return get_profile(profile_id, db_path)


def _recompute_possible_job_types(conn, profile_id):
    rows = conn.execute("SELECT extracted_text FROM profile_documents WHERE profile_id = ?", (profile_id,)).fetchall()
    combined = "\n".join(r["extracted_text"] for r in rows)
    now = _now()
    for label, keywords in JOB_TYPES.items():
        if any(has_term(combined, kw) for kw in keywords):
            conn.execute(
                "INSERT INTO profile_job_types (profile_id, label, is_custom, possible, desired, updated_at) "
                "VALUES (?, ?, 0, 1, 0, ?) "
                "ON CONFLICT(profile_id, label) DO UPDATE SET possible = 1, updated_at = excluded.updated_at",
                (profile_id, label, now))


def get_job_types(profile_id, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT label, is_custom, possible, desired, dismissed FROM profile_job_types WHERE profile_id = ?",
            (profile_id,)).fetchall()
    finally:
        conn.close()
    by_label = {r["label"]: {"label": r["label"], "is_custom": bool(r["is_custom"]), "possible": bool(r["possible"]),
                              "desired": bool(r["desired"]), "dismissed": bool(r["dismissed"])} for r in rows}
    for label in JOB_TYPES:
        by_label.setdefault(label, {"label": label, "is_custom": False, "possible": False, "desired": False,
                                     "dismissed": False})
    order = list(JOB_TYPES)
    return sorted(by_label.values(), key=lambda jt: (order.index(jt["label"]) if jt["label"] in order else len(order),
                                                      jt["label"]))


def set_job_type_dismissed(profile_id, label, dismissed, db_path=db.DB_PATH):
    """Dismiss (strike through) or restore a job type - reversible, unlike removing a skill."""
    now = _now()
    conn = db.connect(db_path)
    try:
        existing = conn.execute("SELECT id FROM profile_job_types WHERE profile_id = ? AND label = ?",
                                 (profile_id, label)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO profile_job_types (profile_id, label, is_custom, possible, desired, dismissed, updated_at) "
                "VALUES (?, ?, ?, 0, 0, 0, ?)",
                (profile_id, label, 0 if label in JOB_TYPES else 1, now))
        conn.execute("UPDATE profile_job_types SET dismissed = ?, updated_at = ? WHERE profile_id = ? AND label = ?",
                     (1 if dismissed else 0, now, profile_id, label))
        if dismissed:
            conn.execute("UPDATE profile_job_types SET desired = 0, updated_at = ? WHERE profile_id = ? AND label = ?",
                         (now, profile_id, label))
        conn.commit()
    finally:
        conn.close()
    return get_job_types(profile_id, db_path)


def add_custom_job_type(profile_id, label, db_path=db.DB_PATH):
    label = label.strip()
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO profile_job_types (profile_id, label, is_custom, possible, desired, updated_at) "
            "VALUES (?, ?, 1, 0, 0, ?) ON CONFLICT(profile_id, label) DO NOTHING",
            (profile_id, label, _now()))
        conn.commit()
    finally:
        conn.close()
    return get_job_types(profile_id, db_path)


def set_desired_job_types(profile_id, labels, db_path=db.DB_PATH):
    """Overwrite which job types are marked desired - the one place this isn't additive."""
    labels = set(labels)
    now = _now()
    conn = db.connect(db_path)
    try:
        existing = {r["label"] for r in conn.execute(
            "SELECT label FROM profile_job_types WHERE profile_id = ?", (profile_id,)).fetchall()}
        for label in labels - existing:
            conn.execute(
                "INSERT INTO profile_job_types (profile_id, label, is_custom, possible, desired, updated_at) "
                "VALUES (?, ?, ?, 0, 0, ?)",
                (profile_id, label, 0 if label in JOB_TYPES else 1, now))
        conn.execute("UPDATE profile_job_types SET desired = 0, updated_at = ? WHERE profile_id = ?",
                     (now, profile_id))
        for label in labels:
            conn.execute("UPDATE profile_job_types SET desired = 1, updated_at = ? WHERE profile_id = ? AND label = ?",
                         (now, profile_id, label))
        conn.commit()
    finally:
        conn.close()
    return get_job_types(profile_id, db_path)


def add_document(profile_id, kind, filename, file_bytes, db_path=db.DB_PATH):
    safe_name = secure_filename(filename) or "upload"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    folder = _profiles_dir(db_path) / str(profile_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{ts}_{safe_name}"
    dest.write_bytes(file_bytes)
    text = extract_text(dest)
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO profile_documents (profile_id, kind, label, file_path, extracted_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profile_id, kind, filename, str(dest), text, _now()))
        _accumulate_skills(conn, profile_id, text)
        _recompute_possible_job_types(conn, profile_id)
        conn.commit()
    finally:
        conn.close()
    return get_profile(profile_id, db_path)


def add_note(profile_id, text, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO profile_documents (profile_id, kind, label, file_path, extracted_text, created_at) "
            "VALUES (?, 'note', NULL, NULL, ?, ?)",
            (profile_id, text, _now()))
        _accumulate_skills(conn, profile_id, text)
        _recompute_possible_job_types(conn, profile_id)
        conn.commit()
    finally:
        conn.close()
    return get_profile(profile_id, db_path)


def add_applied_job(profile_id, title, company, text, db_path=db.DB_PATH):
    """Record a job already applied to, as immediate positive ("picked") signal.

    Stored alongside resumes/notes (kind='applied_job') for transparency in the Documents
    list, but deliberately skips skill/job-type accumulation - a job's requirements are not
    the candidate's own skills.
    """
    label = f"{title.strip()} — {company.strip()}" if company.strip() else title.strip()
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO profile_documents (profile_id, kind, label, file_path, extracted_text, created_at) "
            "VALUES (?, 'applied_job', ?, NULL, ?, ?)",
            (profile_id, label, text, _now()))
        conn.commit()
    finally:
        conn.close()
    return get_profile(profile_id, db_path)


def set_job_feedback(profile_id, job_url, title, company, text, decision, db_path=db.DB_PATH):
    """Record/overwrite a pick-or-pass decision for one job, keyed by (profile_id, job_url)."""
    conn = db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO job_feedback (profile_id, job_url, title, company, text, decision, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(profile_id, job_url) DO UPDATE SET decision = excluded.decision, "
            "title = excluded.title, company = excluded.company, text = excluded.text, "
            "created_at = excluded.created_at",
            (profile_id, job_url, title, company, text, decision, _now()))
        conn.commit()
    finally:
        conn.close()
    return {"url": job_url, "decision": decision}


def get_feedback(profile_id, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        rows = conn.execute("SELECT job_url, decision FROM job_feedback WHERE profile_id = ?",
                             (profile_id,)).fetchall()
        return {r["job_url"]: r["decision"] for r in rows}
    finally:
        conn.close()


def _skill_evidence_counts(profile_id, db_path):
    """Picked/passed Counters of canonical skills, from live feedback + applied-job bootstrap."""
    conn = db.connect(db_path)
    try:
        fb_rows = conn.execute("SELECT text, decision FROM job_feedback WHERE profile_id = ?",
                               (profile_id,)).fetchall()
        applied_rows = conn.execute(
            "SELECT extracted_text FROM profile_documents WHERE profile_id = ? AND kind = 'applied_job'",
            (profile_id,)).fetchall()
    finally:
        conn.close()
    picked, passed = Counter(), Counter()
    for r in fb_rows:
        bucket = picked if r["decision"] == "picked" else passed
        for s in detect_skills(r["text"]):
            bucket[s] += 1
    for r in applied_rows:  # bootstrap data: always a positive signal
        for s in detect_skills(r["extracted_text"]):
            picked[s] += 1
    return picked, passed, len(fb_rows) + len(applied_rows)


def _weights_from_counts(picked, passed):
    """Laplace-smoothed pick rate, scaled so no evidence -> 1.0 (neutral)."""
    return {s: (picked[s] + 1) / (picked[s] + passed[s] + 2) * 2 for s in set(picked) | set(passed)}


def get_skill_weights(profile_id, db_path=db.DB_PATH):
    """Per-skill weight from pick/pass feedback + applied-job bootstrap.
    No evidence -> 1.0 (neutral, matches today's unweighted matcher exactly)."""
    picked, passed, _ = _skill_evidence_counts(profile_id, db_path)
    return _weights_from_counts(picked, passed)


def get_weight_insight(profile_id, db_path=db.DB_PATH, min_sources=3, top_n=5):
    """Compact up/down-weighted skill lists for the Profile tab's transparency panel.
    Returns None until there are at least min_sources feedback/applied-job rows."""
    picked, passed, n_sources = _skill_evidence_counts(profile_id, db_path)
    if n_sources < min_sources:
        return None
    weights = _weights_from_counts(picked, passed)
    ranked = sorted(weights.items(), key=lambda kv: -kv[1])
    up = [{"skill": s, "weight": round(w, 2)} for s, w in ranked if w > 1.0][:top_n]
    down = [{"skill": s, "weight": round(w, 2)} for s, w in reversed(ranked) if w < 1.0][:top_n]
    return {"up": up, "down": down}


def list_documents(profile_id, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, kind, label, file_path, created_at FROM profile_documents "
            "WHERE profile_id = ? ORDER BY created_at", (profile_id,)).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "label": r["label"],
                 "has_file": r["file_path"] is not None, "created_at": r["created_at"]} for r in rows]
    finally:
        conn.close()


def get_document_file(profile_id, doc_id, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        row = conn.execute("SELECT file_path FROM profile_documents WHERE id = ? AND profile_id = ?",
                           (doc_id, profile_id)).fetchone()
    finally:
        conn.close()
    if not row or not row["file_path"]:
        return None
    return Path(row["file_path"])


def get_profile(profile_id, db_path=db.DB_PATH):
    conn = db.connect(db_path)
    try:
        row = conn.execute("SELECT id, name FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "skills": sorted(get_skills(profile_id, db_path)),
            "job_types": get_job_types(profile_id, db_path), "documents": list_documents(profile_id, db_path),
            "weight_insight": get_weight_insight(profile_id, db_path)}


def seed_from_config(cfg, name="Default", db_path=db.DB_PATH):
    """One-time migration: if no profiles exist yet, build one from config.yaml's resume path(s)."""
    if list_profiles(db_path) or not cfg.get("resume"):
        return None
    profile = get_or_create_profile(name, db_path)
    for path in [cfg["resume"], *cfg.get("master_resume", [])]:
        text = extract_text(path)
        conn = db.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO profile_documents (profile_id, kind, label, file_path, extracted_text, created_at) "
                "VALUES (?, 'resume', ?, ?, ?, ?)",
                (profile["id"], Path(path).name, str(path), text, _now()))
            _accumulate_skills(conn, profile["id"], text, cfg.get("extra_skills", []))
            _recompute_possible_job_types(conn, profile["id"])
            conn.commit()
        finally:
            conn.close()
    return profile
