#!/usr/bin/env python3
"""Create a GitHub Release for a tag.

A tag is not a release. The repository page's "Releases" sidebar, and
/releases/latest, read *Releases* only -- so five tags and two releases is a
page that proudly announces v1.2.0 while main is four commits past v1.4.0.
That is exactly what happened, and it is why this script exists.
"""
import json
import os
import sys
import urllib.error
import urllib.request

REPO = "lg5874/ai-phone-control"
TOKEN = os.environ["GH_TOKEN"]


def api(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "lcs-release",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main():
    tag = sys.argv[1]
    notes = open(sys.argv[2], encoding="utf-8").read()
    # The title comes from the notes, not from this script: a hardcoded one
    # silently mislabelled v1.4.0 with v1.4.1's headline when back-filling.
    # CHANGELOG's heading is "## v1.4.0 — the panel actually talks", so take
    # what follows the tag.
    title = notes.splitlines()[0].lstrip("# ").strip()
    if title.startswith(tag):
        title = title[len(tag):].lstrip("—- ").strip() or tag

    status, cur = api("GET", f"/releases/tags/{tag}")
    if status == 200:
        print(f"release {tag} already exists (id {cur['id']}); leaving it alone")
        return 0
    if status != 404:
        print(f"GET release {tag}: HTTP {status} {cur}", file=sys.stderr)
        return 1

    # Not a prerelease, not a draft: a draft is invisible on the repo page,
    # which would leave the sidebar still showing the old version.
    status, out = api("POST", "/releases", {
        "tag_name": tag,
        "name": f"{tag} — {title}",
        "body": notes,
        "draft": False,
        "prerelease": False,
        "make_latest": "true",
    })
    if status not in (200, 201):
        print(f"POST release: HTTP {status} {out}", file=sys.stderr)
        return 1
    print(f"created release {tag}: {out['html_url']}")

    status, latest = api("GET", "/releases/latest")
    print(f"/releases/latest now: {latest.get('tag_name')} (HTTP {status})")
    return 0 if latest.get("tag_name") == tag else 1


if __name__ == "__main__":
    sys.exit(main())
