"""
Create or update the cron-job.org job that starts the Wheel Bot workflow.

GitHub's own schedule is throttled (runs hours late or not at all), so an
outside timer calls GitHub's "run workflow" API on time instead. The code
still lives in GitHub; this job only says "run main now".

Needs .env.trigger (gitignored) with:
    GH_TRIGGER_TOKEN  fine-grained GitHub token: this repo only, Actions read/write
    CRONJOB_API_KEY   cron-job.org API key (Console -> Settings -> API)

Run: python setup_trigger.py   (safe to re-run, e.g. to swap in a new token)
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

REPO = "danielkwon7607-del/wheelagent"
WORKFLOW = "wheel.yml"
JOB_TITLE = "wheel bot trigger"
CRONJOB_API = "https://api.cron-job.org"
DISPATCH_URL = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"


def github_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "wheel-bot-trigger",
    }


def job_definition(token: str) -> dict:
    return {
        "title": JOB_TITLE,
        "enabled": True,
        "url": DISPATCH_URL,
        "requestMethod": 1,  # POST
        "requestTimeout": 30,
        "saveResponses": True,
        "schedule": {
            # Exchange time, so DST is handled for us. 9:00 and 9:15 are
            # no-ops; the bot's own market-hours check starts at 9:30.
            "timezone": "America/New_York",
            "expiresAt": 0,
            "hours": list(range(9, 16)),
            "minutes": [0, 15, 30, 45],
            "mdays": [-1],
            "months": [-1],
            "wdays": [1, 2, 3, 4, 5],
        },
        "extendedData": {"headers": github_headers(token), "body": json.dumps({"ref": "main"})},
        # Email if two runs in a row fail (e.g. the token expired).
        "notification": {"onFailure": True, "onFailureCount": 2, "onSuccess": False, "onDisable": True},
    }


def main() -> None:
    load_dotenv(".env.trigger")
    token = os.environ.get("GH_TRIGGER_TOKEN", "").strip()
    api_key = os.environ.get("CRONJOB_API_KEY", "").strip()
    if not token or not api_key:
        sys.exit("Fill in GH_TRIGGER_TOKEN and CRONJOB_API_KEY in .env.trigger first.")

    # Prove the token can start the workflow before handing it to cron-job.org.
    r = requests.post(DISPATCH_URL, headers=github_headers(token), json={"ref": "main"}, timeout=30)
    if r.status_code != 204:
        sys.exit(f"GitHub token can't start the workflow: HTTP {r.status_code} {r.text[:200]}")
    print("GitHub token OK: started one Wheel Bot run.")

    cron = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.get(f"{CRONJOB_API}/jobs", headers=cron, timeout=30)
    if r.status_code != 200:
        sys.exit(f"cron-job.org API key rejected: HTTP {r.status_code} {r.text[:200]}")
    existing = [j for j in r.json().get("jobs", []) if j.get("title") == JOB_TITLE]

    body = {"job": job_definition(token)}
    if existing:
        job_id = existing[0]["jobId"]
        r = requests.patch(f"{CRONJOB_API}/jobs/{job_id}", headers=cron, json=body, timeout=30)
    else:
        r = requests.put(f"{CRONJOB_API}/jobs", headers=cron, json=body, timeout=30)
        job_id = r.json().get("jobId") if r.ok else None
    if not r.ok:
        sys.exit(f"cron-job.org refused the job: HTTP {r.status_code} {r.text[:200]}")
    print(f"cron-job.org job {job_id} {'updated' if existing else 'created'}.")

    r = requests.get(f"{CRONJOB_API}/jobs/{job_id}/history", headers=cron, timeout=30)
    if r.ok:
        from datetime import datetime
        from logging_setup import PACIFIC
        for ts in r.json().get("predictions", []):
            print("  next run:", datetime.fromtimestamp(ts, PACIFIC).strftime("%a %b %d %I:%M%p %Z"))


if __name__ == "__main__":
    main()
