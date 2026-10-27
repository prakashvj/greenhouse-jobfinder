import httpx

from jobfinder import db, profiles
from jobfinder.discover_boards import discover
from jobfinder.greenhouse import fetch_board, strip_html
from jobfinder.matcher import location_ok, rank, score_job
from jobfinder.resume import detect_skills, extract_skills, has_term

JOB = {"id": 1, "title": "Senior SRE Manager", "location": "Remote - US", "url": "u", "company": "x", "updated": "",
       "text": "Run Azure and Kubernetes services, on-call, observability, SQL Server."}


def test_has_term_word_boundary():
    assert has_term("We use SRE daily", "sre")
    assert not has_term("misrepresent", "sre")


def test_extract_skills():
    s = extract_skills("Sr. SRE Manager. Azure Key Vault, Azure SQL, Application Insights, SQL Server DBA")
    assert {"azure", "site reliability engineering", "sql server", "observability", "security"} <= s


def test_strip_html_escaped():
    assert strip_html("&lt;p&gt;Hi &amp;amp; bye&lt;/p&gt;") == "Hi & bye"


def test_score_and_filters():
    skills = {"azure", "kubernetes", "observability", "aws"}
    r = score_job(JOB, skills, target_titles=["sre"])
    assert r["title_match"] and set(r["matched"]) == {"azure", "kubernetes", "observability"}
    assert r["score"] > 80
    assert score_job(JOB, skills, include_locations=["london"]) is None
    assert score_job(JOB, skills, exclude_locations=["remote"]) is None


def test_rank_orders_and_thresholds():
    low = {**JOB, "id": 2, "title": "Chef", "text": "cook food"}
    out = rank([low, JOB], {"azure"}, min_score=10, target_titles=["sre"])
    assert [j["id"] for j in out] == [1]


def test_fetch_board_mock():
    def handler(req):
        if "missing" in str(req.url):
            return httpx.Response(404)
        return httpx.Response(200, json={"jobs": [{"id": 9, "title": "T", "location": {"name": "L"},
                                                   "absolute_url": "u", "content": "&lt;b&gt;Azure&lt;/b&gt;"}]})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    jobs = fetch_board("ok", client=c)
    assert jobs[0]["text"] == "Azure" and jobs[0]["location"] == "L"
    assert fetch_board("missing", client=c) == []


def test_discover_boards_skips_already_configured_and_dead_tokens():
    def handler(req):
        token = str(req.url).rsplit("/boards/", 1)[1].split("/jobs")[0]
        if token == "realcompany":
            return httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]})
        if token == "emptycompany":
            return httpx.Response(200, json={"jobs": []})
        return httpx.Response(404)
    c = httpx.Client(transport=httpx.MockTransport(handler))
    found = discover(["realcompany", "emptycompany", "fakecompany", "alreadyknown"],
                      already_configured={"alreadyknown"}, client=c)
    assert found == {"realcompany": 2}  # empty/fake/already-configured all excluded


SEA = ["seattle", "bellevue", "redmond", "kirkland", "washington state", "wa", "remote - us", "remote, united states", "remote - united states", "united states"]
EXC = ["washington, dc", "washington dc", "remote - india", "remote, canada"]


def test_location_ok_segments():
    assert location_ok("Remote, Canada; Remote, United States", SEA, EXC)
    assert location_ok("Bellevue, Washington", SEA, EXC)
    assert not location_ok("Washington, DC", SEA, EXC)
    assert not location_ok("Remote - India", SEA, EXC)
    assert not location_ok("London, UK", SEA, EXC)


def test_salary_and_employment():
    from jobfinder.analysis import employment_type, parse_salary
    assert parse_salary([{"currency_type": "USD", "min_cents": 15000000, "max_cents": 20000000}], "") == (150000, 200000)
    assert parse_salary([], "Pay range $140,000 - $190,000 per year") == (140000, 190000)
    assert parse_salary([], "$120K to $160K") == (120000, 160000)
    assert parse_salary([{"currency_type": "EUR", "min_cents": 9000000}], "") is None
    assert employment_type("SRE (Contract)", "") == "contract"
    assert employment_type("Barista", "This is a part-time role") == "part_time"
    assert employment_type("SRE", "full-time or part-time") == "full_time"


def test_detect_skills_matches_alias_and_canonical_name():
    assert "site reliability engineering" in detect_skills("Looking for an SRE")
    assert "python" in detect_skills("Python required")


def test_score_job_default_weights_match_unweighted_behavior():
    skills = {"azure", "kubernetes", "observability", "aws"}
    assert score_job(JOB, skills, target_titles=["sre"]) == score_job(JOB, skills, target_titles=["sre"],
                                                                        skill_weights={})


def test_score_job_weights_affect_score_only_not_ats_or_matched():
    skills = {"azure", "kubernetes", "observability", "aws"}
    base = score_job(JOB, skills, target_titles=["sre"])
    boosted = score_job(JOB, skills, target_titles=["sre"], skill_weights={"azure": 2.0})
    assert boosted["score"] > base["score"]
    assert boosted["ats"] == base["ats"]
    assert boosted["matched"] == base["matched"]


def test_ats_missing_skills():
    job = {**JOB, "text": "Azure, Kubernetes, Terraform, Python experience required"}
    r = score_job(job, {"azure", "kubernetes"}, target_titles=["sre"])
    assert "terraform" in r["missing"] and "python" in r["missing"] and "azure" not in r["missing"]
    assert r["ats"] == round(70 * 2 / 5 + 30)  # title "SRE" is a 5th job skill


def test_web_search_filters():
    from jobfinder.web import search
    base = {**JOB, "employment": "full_time", "salary": [150000, 200000]}
    jobs = [base, {**base, "id": 2, "location": "Seattle, WA", "salary": None},
            {**base, "id": 3, "employment": "part_time"}, {**base, "id": 4, "title": "Chef", "location": "Seattle"}]
    out = search({"job_types": ["SRE / Reliability"], "cities": ["seattle"], "remote_us": False,
                  "employment": ["full_time"]}, jobs, {"azure"})
    assert [r["location"] for r in out["rows"]] == ["Seattle, WA"]
    out = search({"job_types": ["SRE / Reliability"], "cities": [], "remote_us": True, "salary_min": 190000,
                  "require_salary": True}, jobs, {"azure"})
    assert out["total"] == 2  # ids 1 and 3 (salary ok, remote); no employment filter given


def _db(tmp_path):
    path = tmp_path / "profiles.db"
    db.init_db(path)
    return path


def test_get_or_create_profile_same_name_reuses_id(tmp_path):
    path = _db(tmp_path)
    a = profiles.get_or_create_profile("Jyothi", db_path=path)
    b = profiles.get_or_create_profile("jyothi", db_path=path)  # case-insensitive match
    c = profiles.get_or_create_profile("Someone Else", db_path=path)
    assert a["id"] == b["id"]
    assert a["id"] != c["id"]


def test_delete_profile_removes_everything(tmp_path):
    path = _db(tmp_path)
    keep = profiles.get_or_create_profile("Keep", db_path=path)
    gone = profiles.get_or_create_profile("Gone", db_path=path)
    profiles.add_document(gone["id"], "resume", "resume.txt", b"Azure and Kubernetes experience.", db_path=path)
    assert profiles.delete_profile(gone["id"], db_path=path) is True
    assert profiles.get_profile(gone["id"], db_path=path) is None
    assert {p["id"] for p in profiles.list_profiles(db_path=path)} == {keep["id"]}
    assert profiles.delete_profile(gone["id"], db_path=path) is False  # already gone


def test_skill_accumulation_is_additive(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    first = profiles.add_note(p["id"], "Azure and Kubernetes experience.", db_path=path)
    assert {"azure", "kubernetes"} <= set(first["skills"])
    second = profiles.add_note(p["id"], "Also did some Python scripting.", db_path=path)
    assert {"azure", "kubernetes", "python"} <= set(second["skills"])  # earlier skills retained


def test_possible_job_types_only_added_never_removed(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    first = profiles.add_note(p["id"], "Worked as an SRE doing on-call reliability work.", db_path=path)
    possible = {jt["label"] for jt in first["job_types"] if jt["possible"]}
    assert "SRE / Reliability" in possible
    second = profiles.add_note(p["id"], "Unrelated note about lunch.", db_path=path)
    still_possible = {jt["label"] for jt in second["job_types"] if jt["possible"]}
    assert possible <= still_possible


def test_add_manual_skill_and_remove_skill(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    profile = profiles.add_manual_skill(p["id"], "Cloud", db_path=path)
    assert "cloud" in profile["skills"]  # normalized to lowercase
    profile = profiles.add_manual_skill(p["id"], "cloud", db_path=path)  # duplicate add is a no-op
    assert profile["skills"].count("cloud") == 1
    profile = profiles.remove_skill(p["id"], "cloud", db_path=path)
    assert "cloud" not in profile["skills"]


def test_dismiss_and_restore_job_type(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    # dismissing a never-seen built-in label creates a row for it on the fly
    jt = profiles.set_job_type_dismissed(p["id"], "Security", True, db_path=path)
    sec = next(j for j in jt if j["label"] == "Security")
    assert sec["dismissed"] and not sec["desired"]
    # dismissing clears desired, if it was set
    jt = profiles.set_desired_job_types(p["id"], ["SRE / Reliability"], db_path=path)
    jt = profiles.set_job_type_dismissed(p["id"], "SRE / Reliability", True, db_path=path)
    sre = next(j for j in jt if j["label"] == "SRE / Reliability")
    assert sre["dismissed"] and not sre["desired"]
    # restoring un-dismisses without re-marking it desired
    jt = profiles.set_job_type_dismissed(p["id"], "SRE / Reliability", False, db_path=path)
    sre = next(j for j in jt if j["label"] == "SRE / Reliability")
    assert not sre["dismissed"] and not sre["desired"]


def test_set_desired_job_types_toggle(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    jt = profiles.set_desired_job_types(p["id"], ["SRE / Reliability"], db_path=path)
    assert {j["label"] for j in jt if j["desired"]} == {"SRE / Reliability"}
    jt = profiles.set_desired_job_types(p["id"], [], db_path=path)
    assert not any(j["desired"] for j in jt)  # desired is a plain overwrite, not additive
    jt = profiles.set_desired_job_types(p["id"], ["Security"], db_path=path)
    assert {j["label"] for j in jt if j["desired"]} == {"Security"}


def test_add_custom_job_type(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    jt = profiles.add_custom_job_type(p["id"], "Nurse Practitioner", db_path=path)
    custom = next(j for j in jt if j["label"] == "Nurse Practitioner")
    assert custom["is_custom"] and not custom["possible"] and not custom["desired"]


def test_add_document_round_trip(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    profile = profiles.add_document(p["id"], "resume", "resume.txt",
                                     b"Experience with Terraform and Docker containers.", db_path=path)
    assert "terraform" in profile["skills"] and "docker" in profile["skills"]
    assert len(profile["documents"]) == 1
    doc = profile["documents"][0]
    assert doc["kind"] == "resume" and doc["has_file"]
    stored = profiles.get_document_file(p["id"], doc["id"], db_path=path)
    assert stored.exists() and stored.read_text(encoding="utf-8").startswith("Experience")


def test_days_since_posted():
    from datetime import datetime, timedelta, timezone
    from jobfinder.web import days_since_posted
    assert days_since_posted(None) is None
    assert days_since_posted("not-a-date") is None
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert days_since_posted(recent) == 2


def test_web_search_days_filter():
    from jobfinder.web import search
    from datetime import datetime, timedelta, timezone
    base = {**JOB, "employment": "full_time", "salary": None}
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    jobs = [{**base, "id": 1, "updated": old}, {**base, "id": 2, "updated": fresh}]
    out = search({"employment": ["full_time"], "days": 7}, jobs, {"azure"})
    assert [r["posted_days_ago"] for r in out["rows"]] == [1]
    out = search({"employment": ["full_time"]}, jobs, {"azure"})
    assert out["total"] == 2


def test_add_applied_job_excluded_from_skills_and_job_types(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    profile = profiles.add_applied_job(p["id"], "SRE", "Acme", "Requires Terraform and Docker containers.",
                                        db_path=path)
    assert profile["skills"] == []
    assert not any(jt["possible"] for jt in profile["job_types"])
    doc = profile["documents"][0]
    assert doc["kind"] == "applied_job" and "Acme" in doc["label"]


def test_set_job_feedback_upserts_by_profile_and_url(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    profiles.set_job_feedback(p["id"], "http://job/1", "SRE", "Acme", "Azure and Kubernetes", "picked", db_path=path)
    profiles.set_job_feedback(p["id"], "http://job/1", "SRE", "Acme", "Azure and Kubernetes", "passed", db_path=path)
    assert profiles.get_feedback(p["id"], db_path=path) == {"http://job/1": "passed"}


def test_get_skill_weights_neutral_with_no_evidence(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    assert profiles.get_skill_weights(p["id"], db_path=path) == {}


def test_get_skill_weights_from_feedback_and_applied_jobs(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    profiles.set_job_feedback(p["id"], "http://job/1", "SRE", "Acme", "Azure experience required", "picked",
                               db_path=path)
    profiles.set_job_feedback(p["id"], "http://job/2", "SRE", "Beta", "Azure experience required", "passed",
                               db_path=path)
    profiles.add_applied_job(p["id"], "SRE", "Gamma", "Azure experience required", db_path=path)
    weights = profiles.get_skill_weights(p["id"], db_path=path)
    assert round(weights["azure"], 2) == 1.2  # picked=2 (1 feedback + 1 applied), passed=1 -> (2+1)/(2+1+2)*2


def test_get_weight_insight_none_until_enough_evidence(tmp_path):
    path = _db(tmp_path)
    p = profiles.get_or_create_profile("Jyothi", db_path=path)
    assert profiles.get_weight_insight(p["id"], db_path=path) is None
    profiles.set_job_feedback(p["id"], "http://job/1", "SRE", "Acme", "Azure experience", "picked", db_path=path)
    profiles.set_job_feedback(p["id"], "http://job/2", "SRE", "Beta", "Azure experience", "picked", db_path=path)
    profiles.set_job_feedback(p["id"], "http://job/3", "SRE", "Gamma", "Cobol experience", "passed", db_path=path)
    insight = profiles.get_weight_insight(p["id"], db_path=path)
    assert any(s["skill"] == "azure" for s in insight["up"])


def test_search_attaches_feedback_state():
    from jobfinder.web import search
    base = {**JOB, "employment": "full_time", "salary": None}
    out = search({"employment": ["full_time"]}, [base], {"azure"}, feedback={base["url"]: "picked"})
    assert out["rows"][0]["feedback"] == "picked"


def test_search_skill_weights_reorder_without_changing_ats():
    from jobfinder.web import search
    base = {**JOB, "employment": "full_time", "salary": None}
    out_neutral = search({"employment": ["full_time"]}, [base], {"azure", "kubernetes"})
    out_weighted = search({"employment": ["full_time"]}, [base], {"azure", "kubernetes"},
                           skill_weights={"azure": 3.0})
    assert out_neutral["rows"][0]["ats"] == out_weighted["rows"][0]["ats"]
