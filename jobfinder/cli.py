import argparse
import csv
import sys
from pathlib import Path

import yaml

from .greenhouse import fetch_board
from .matcher import rank
from .resume import extract_skills, extract_text


def write_reports(results, outdir):
    out = Path(outdir)
    out.mkdir(exist_ok=True)
    cols = ["score", "company", "title", "location", "matched", "url"]
    with open(out / "matches.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in results:
            w.writerow([r["score"], r["company"], r["title"], r["location"], "; ".join(r["matched"]), r["url"]])
    with open(out / "matches.md", "w", encoding="utf-8") as f:
        f.write(f"# Matching jobs ({len(results)})\n\n")
        for r in results:
            f.write(f"- **{r['score']}** [{r['title']}]({r['url']}) - {r['company']}, {r['location']}  \n"
                    f"  skills: {', '.join(r['matched'])}\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--resume", help="overrides resume: in config")
    a = ap.parse_args(argv)
    with open(a.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    sources = [a.resume] if a.resume else [cfg["resume"], *cfg.get("master_resume", [])]
    text = "\n".join(extract_text(p) for p in sources)
    skills = extract_skills(text, cfg.get("extra_skills", []))
    print(f"Resume skills ({len(skills)}): {', '.join(sorted(skills))}")
    jobs = []
    for token in cfg["boards"]:
        got = fetch_board(token)
        print(f"  {token}: {len(got)} jobs")
        jobs += got
    results = rank(jobs, skills, cfg.get("min_score", 40),
                   target_titles=cfg.get("target_titles", []),
                   include_locations=cfg.get("include_locations", []),
                   exclude_locations=cfg.get("exclude_locations", []))
    write_reports(results, "output")
    print(f"{len(jobs)} jobs scanned, {len(results)} matches -> output/matches.md, matches.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
