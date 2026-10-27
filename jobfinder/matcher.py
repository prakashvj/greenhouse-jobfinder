"""Score jobs against resume skills."""
import re
from .resume import SKILLS, has_term


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


def score_job(job, skills, target_titles=(), include_locations=(), exclude_locations=(), nationwide=True):
    if not location_ok(job["location"], include_locations, exclude_locations, nationwide):
        return None
    title, body = job["title"].lower(), job["text"].lower()
    matched, points = [], 0.0
    for s in skills:
        in_title = any(has_term(title, t) for t in _terms(s))
        in_body = any(has_term(body, t) for t in _terms(s))
        if in_title or in_body:
            matched.append(s)
            points += 3 if in_title else 1
    skill_part = 60 * min(len(matched) / max(min(8, len(skills)), 1), 1)  # 8 matched skills = full marks
    title_hit = any(t.lower() in title for t in target_titles)
    score = skill_part + (40 if title_hit else 0)
    # ATS view: of the skills this job mentions, how many does the resume cover?
    job_skills = {c for c in SKILLS if any(has_term(title, t) or has_term(body, t) for t in _terms(c))}
    covered = job_skills & set(skills)
    coverage = len(covered) / max(len(job_skills), 5)  # floor: a job naming 1 skill is thin evidence, not a 100% fit
    ats = round(70 * coverage + (30 if title_hit else 0))
    return {**job, "score": round(score, 1), "matched": sorted(matched), "title_match": title_hit,
            "job_skills": sorted(job_skills), "missing": sorted(job_skills - set(skills)), "ats": ats}


def rank(jobs, skills, min_score=0, **kw):
    scored = (score_job(j, skills, **kw) for j in jobs)
    return sorted((s for s in scored if s and s["score"] >= min_score),
                  key=lambda s: -s["score"])
