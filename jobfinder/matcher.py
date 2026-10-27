"""Score jobs against resume skills."""
import re
from .resume import SKILLS, detect_skills, has_term


def _terms(skill):
    return SKILLS.get(skill, []) + [skill]


NATIONWIDE = {"united states", "usa", "us", "remote", "remote - usa", "remote-friendly (travel-required)"}


def location_ok(location, include=(), exclude=(), nationwide=True):
    """A job passes if any ';'-separated location segment matches include and no exclude term."""
    segs = [x.strip().lower() for x in re.split(r"[;|]", location)] or [""]
    def ok(seg):
        if include and nationwide and seg in NATIONWIDE:
            return True
        if include and not any(i.lower() in seg for i in include):
            return False
        return not any(e.lower() in seg for e in exclude)
    return any(ok(x) for x in segs)


def score_job(job, skills, target_titles=(), include_locations=(), exclude_locations=(), nationwide=True,
              skill_weights=None):
    if not location_ok(job["location"], include_locations, exclude_locations, nationwide):
        return None
    title, body = job["title"].lower(), job["text"].lower()
    weights = skill_weights or {}
    matched = []
    for s in skills:
        terms = _terms(s)
        if any(has_term(title, t) for t in terms) or any(has_term(body, t) for t in terms):
            matched.append(s)
    weighted_matched = sum(weights.get(s, 1.0) for s in matched)
    skill_part = 60 * min(weighted_matched / max(min(8, len(skills)), 1), 1)  # 8 matched skills = full marks
    title_hit = any(t.lower() in title for t in target_titles)
    score = skill_part + (40 if title_hit else 0)
    # ATS view: of the skills this job mentions, how many does the resume cover?
    job_skills = detect_skills(title) | detect_skills(body)
    covered = job_skills & set(skills)
    coverage = len(covered) / max(len(job_skills), 5)  # floor: a job naming 1 skill is thin evidence, not a 100% fit
    ats = round(70 * coverage + (30 if title_hit else 0))
    return {**job, "score": round(score, 1), "matched": sorted(matched), "title_match": title_hit,
            "job_skills": sorted(job_skills), "missing": sorted(job_skills - set(skills)), "ats": ats}


def rank(jobs, skills, min_score=0, **kw):
    scored = (score_job(j, skills, **kw) for j in jobs)
    return sorted((s for s in scored if s and s["score"] >= min_score),
                  key=lambda s: -s["score"])
