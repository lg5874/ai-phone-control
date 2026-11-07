#!/usr/bin/env python3
"""Re-mark which release is "latest".

GitHub decides `latest` by *creation* time, not by version. So back-filling an
older release (v1.4.0, created after v1.4.1) silently steals the badge and the
repo page goes back to advertising the older version -- the exact symptom this
whole exercise started from. `make_latest` on PATCH is the only way to say
"this one, by version".
"""
import json
import os
import sys
import urllib.request

REPO = "lg5874/ai-phone-control"
TOKEN = os.environ["GH_TOKEN"]


def api(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        data=body, method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "lcs-release",
        })
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read() or b"{}")


def main():
    tag = sys.argv[1]
    rel = api("GET", f"/releases/tags/{tag}")
    api("PATCH", f"/releases/{rel['id']}", {"make_latest": "true"})
    latest = api("GET", "/releases/latest")
    print(f"latest is now {latest['tag_name']} ({latest['html_url']})")
    return 0 if latest["tag_name"] == tag else 1


if __name__ == "__main__":
    sys.exit(main())