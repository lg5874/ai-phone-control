# PhoneControl — the native half

One `.js` file, eleven tools, zero dependencies. No shell, no adb, no root:
it drives the screen through Operit's own `Tools.UI` bridge, so it works on a
phone where the shell route in the parent directory is not available.

```
adapters/operit/com.operit.phone_control.js   the whole package
```

## Install

**Inside Operit (one command).** Point the platform editor at the file:

```
operit_editor:debug_install_js_package
  source_path = /sdcard/Download/.../com.operit.phone_control.js
```

It copies the file to
`Android/data/com.ai.assistance.operit/files/packages/PhoneControl.js`, enables
it, and reloads it.

**By hand.** Copy the file to that same `packages/` directory, then enable
`PhoneControl` in the package list (设置 → 包 / Packages).

Requires Operit's UI automation (accessibility) to be on — that is where
`getPageInfo`, `tap`, `swipe`, `pressKey` come from.

## The eleven tools

| tool | what it does | returns |
|---|---|---|
| `screen` | the screen as text, one node per line, with centre coordinates | `nodes`, `count`, `signature` |
| `find` | look without touching: is this text on screen, and where | `matches`, `hits` |
| `tap_text` | tap by visible text or content description | `tapped`, `at`, `changed` |
| `tap_xy` | tap raw coordinates | `at`, `changed` |
| `swipe` | swipe by direction (scaled to the real resolution) or four coordinates | `from`, `to`, `changed` |
| `press` | HOME / BACK / ENTER / RECENTS, with or without the `KEYCODE_` prefix | `key`, `changed` |
| `type_text` | type into the focused field, optionally by `resourceId` | `signature` |
| `screen_text` | only the text, deduplicated — the cheapest way to read a screen | `text`, `count` |
| `foreground` | which package/activity is in front | `app`, `page` |
| `shot` | screenshot | `path` (+ size) |
| `wait` | wait, then report the screen | `app`, `page` |

## The contract

The same rule as the shell half: **never report success for something that did
not happen.**

- `success: true` — the action was dispatched.
- `changed: true` — the screen really did change afterwards (a fingerprint of
  package + activity + node count + label length, sampled every 150 ms).
- `changed: false` — nothing moved. Not an error, the phone telling you the tap
  had no effect. Verify before continuing.
- Text not on screen → `success: false` with `NOT_ON_SCREEN: … — nothing was
  tapped`. The tool refuses instead of guessing a nearby node.

## Verified on hardware

V2403A / Android 15 / Operit, 2026-11-06, all against a live screen:

| check | result |
|---|---|
| `foreground` | `com.ai.assistance.operit/…MainActivity` |
| `screen` | 25 nodes with coordinates, `*` marking clickables |
| `screen_text` | 15 deduplicated lines |
| `find` (exact) | 1 match for `设置选项` at `844,2703` |
| `tap_text` | tapped `设置选项` → `changed: true`, signature `73/285 → 78/268` |
| `tap_text` (absent text) | `NOT_ON_SCREEN`, nothing tapped |
| `swipe up` | `630,1930 → 630,750`, `changed: true` (direction scaled from the real 1260×2680) |
| `press BACK` | accepted as `BACK` (no `KEYCODE_` needed), `changed: true` |
| `shot` | `…/9752.png`, 383012 bytes |

## Notes

- **Empty tree.** WebView, canvas and game screens expose no accessibility
  nodes: `screen` returns `count: 0` and says so. Take `shot` and read the image.
- **Exact matching** compares the raw `text` and the raw `contentDesc`
  separately. Comparing the combined `"text | desc"` label made exact mode miss
  nodes whose text and description both existed.
- **Swipe presets** are fractions of the size reported by
  `Tools.System.getDeviceInfo()`, never a hard-coded resolution.

## 中文速览

一个 `.js` 沙盒包，11 个工具，走 Operit 自带的无障碍桥，不需要 root、不需要
adb、不需要 eyes.sh。安装方式：把文件放进
`Android/data/com.ai.assistance.operit/files/packages/`（或用
`debug_install_js_package` 一键烧录），然后在包列表里启用 `PhoneControl`。

规矩和 shell 版一致：`success:true` 只代表动作发出去了，`changed:true` 才代表
界面真的变了；文字不在屏上就报 `NOT_ON_SCREEN` 并且一下都不点。
