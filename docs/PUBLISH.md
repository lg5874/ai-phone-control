# Publishing notes

Paste these into the GitHub repo settings after creating it. The repo name is
only one of four things GitHub indexes; description, topics, and README text
carry at least as much weight for search.

## Description (the one-line box)

```
Give an LLM agent eyes and hands on an Android phone. One-shot shell commands,
no daemon, no accessibility service, no OCR. Works with KernelSU / Magisk / adb root.
```

## Topics

```
android  ai-agent  llm  computer-use  gui-automation  screen-capture
uiautomator  adb  kernelsu  magisk  agent  automation  mobile-agent
phone-control  android-automation  ai-controls-phone
```

## Commands to set them (needs a token with `repo` scope)

```bash
export GH_TOKEN=...
REPO=YOURNAME/ai-phone-control

curl -s -X PATCH \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO" \
  -d '{"description":"Give an LLM agent eyes and hands on an Android phone. One-shot shell commands, no daemon, no accessibility service, no OCR. Works with KernelSU / Magisk / adb root.","has_issues":true,"has_wiki":false}'

curl -s -X PUT \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO/topics" \
  -d '{"names":["android","ai-agent","llm","computer-use","gui-automation","screen-capture","uiautomator","adb","kernelsu","magisk","agent","automation","mobile-agent","phone-control","android-automation"]}'
```

## Pushing from here

```bash
cd /root/ai-phone-control
git remote add origin https://github.com/YOURNAME/ai-phone-control.git
git push -u origin main
```

If the remote already has a README (created via the web UI with a licence),
pull with `--allow-unrelated-histories` or create the repo empty instead.

## Name check

`ai-phone-control` had no exact-name collision when checked: 17 repos matched
the query, none used the name. `android-computer-use` was the runner-up (4
matches, none exact). `phone-use` was rejected — 795 matches, 15 exact, the
top one at 46 stars.
