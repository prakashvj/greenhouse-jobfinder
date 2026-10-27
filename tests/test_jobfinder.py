import httpx

from jobfinder.greenhouse import fetch_board, strip_html
from jobfinder.matcher import location_ok, rank, score_job
from jobfinder.resume import extract_skills, has_term

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
