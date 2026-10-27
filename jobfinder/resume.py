"""Extract text and a skill set from a resume (PDF or DOCX)."""
import re
from pathlib import Path

# Canonical skill -> aliases (all lowercase). Extend freely.
SKILLS = {
    "site reliability engineering": ["sre", "site reliability"],
    "azure": ["azure"],
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud"],
    "kubernetes": ["kubernetes", "k8s"],
    "docker": ["docker", "containers"],
    "devops": ["devops", "ci/cd", "cicd"],
    "terraform": ["terraform", "infrastructure as code", "iac"],
    "sql server": ["sql server", "mssql"],
    "oracle": ["oracle"],
    "databases": ["dba", "database", "dbms", "postgres", "mysql", "cosmos db"],
    "distributed systems": ["distributed systems", "distributed system"],
    "observability": ["observability", "monitoring", "application insights", "datadog",
                      "prometheus", "grafana", "geneva", "azure data explorer", "kusto"],
    "incident management": ["incident management", "on-call", "oncall", "incident response", "postmortem"],
    "automation": ["automation", "powershell"],
    "engineering management": ["engineering manager", "software engineering manager", "people manager",
                               "mentoring", "managing teams", "lead a team", "leading a team"],
    "reliability": ["reliability", "slo", "sla", "availability"],
    "data platform": ["data factory", "data lake", "etl", "data pipeline"],
    "slo/sli": ["slo", "sli", "error budget", "error budgets"],
    "disaster recovery": ["bcdr", "disaster recovery", "failover", "business continuity"],
    "power bi": ["power bi"],
    "kql": ["kql", "kusto"],
    "cosmos db": ["cosmos db"],
    "vendor management": ["vendor management", "vendor organization", "tier 1", "managed services"],
    "compliance": ["sox", "compliance", "zero-trust", "zero trust"],
    "cost optimization": ["finops", "cost optimization", "cloud spend", "spot vms"],
    "python": ["python"],
    "go": ["golang", "go programming", "go language"],
    "java": ["java"],
    "c#": ["c#", ".net"],
    "javascript": ["javascript", "typescript", "node.js"],
    "linux": ["linux"],
    "networking": ["networking", "tcp/ip", "dns", "load balancing"],
    "ansible/chef/puppet": ["ansible", "chef", "puppet"],
    "jenkins/ci": ["jenkins", "github actions", "gitlab ci", "azure devops"],
    "splunk/elk": ["splunk", "elasticsearch", "elk"],
    "kafka": ["kafka"],
    "redis": ["redis"],
    "capacity planning": ["capacity planning"],
    "chaos engineering": ["chaos engineering"],
    "machine learning": ["machine learning", "llm", "generative ai"],
    "security": ["key vault", "azure ad", "entra", "iam"],
}


def extract_text(path):
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)
    if p.suffix.lower() == ".docx":
        from docx import Document
        return "\n".join(par.text for par in Document(str(p)).paragraphs)
    return p.read_text(encoding="utf-8")


def has_term(text, term):
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text.lower()) is not None


def extract_skills(text, extra=()):
    """Return canonical skills (plus user-supplied extras) found in text."""
    found = {c for c, aliases in SKILLS.items() if any(has_term(text, a) for a in aliases)}
    return found | {e.lower() for e in extra}
