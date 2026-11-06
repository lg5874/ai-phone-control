/*
METADATA
{
    "name": "PhoneControl",
    "description": {
        "zh": "把手机屏幕变成结构化、可验证的信号：读屏、按文本点击、滑动、按键、输入、截图。每个动作都回报是否真的生效，绝不谎报成功。",
        "en": "Turn the phone screen into structured, verifiable signal: read the screen, tap by text, swipe, press keys, type, screenshot. Every action reports whether it actually took effect."
    },
    "category": "Utility",
    "tools": [
        {
            "name": "screen",
            "description": {
                "zh": "列出当前屏幕上可操作/有文字的节点，一行一个，带中心坐标。agent 的“眼睛”。",
                "en": "List actionable / labelled nodes on screen, one per line, with centre coordinates."
            },
            "parameters": [
                {
                    "name": "scope",
                    "description": {
                        "zh": "actionable（默认，只出可点或有文字的）/ clickable / text / all",
                        "en": "actionable (default) / clickable / text / all"
                    },
                    "type": "string",
                    "required": false
                },
                {
                    "name": "max",
                    "description": {
                        "zh": "最多返回多少行，默认 200",
                        "en": "Max lines, default 200"
                    },
                    "type": "integer",
                    "required": false
                }
            ]
        },
        {
            "name": "find",
            "description": {
                "zh": "只查不点：某段文字在不在屏上，在哪。用来验证按钮是否存在。",
                "en": "Look, do not touch: is this text on screen, and where. Use it to verify a control exists."
            },
            "parameters": [
                {
                    "name": "text",
                    "description": {
                        "zh": "要找的文字（匹配 text 或 contentDesc）",
                        "en": "Text to look for (matches text or contentDesc)"
                    },
                    "type": "string",
                    "required": true
                },
                {
                    "name": "exact",
                    "description": {
                        "zh": "\"true\" 表示完全相等，默认包含匹配",
                        "en": "\"true\" for exact equality, default is substring"
                    },
                    "type": "string",
                    "required": false
                }
            ]
        },
        {
            "name": "tap_text",
            "description": {
                "zh": "按文字点击。找不到就明确报 NOT_ON_SCREEN；点了但界面没变会回报 changed=false。",
                "en": "Tap by text. Reports NOT_ON_SCREEN when absent; reports changed=false when the tap did not alter the screen."
            },
            "parameters": [
                {
                    "name": "text",
                    "description": {
                        "zh": "要点的文字（匹配 text 或 contentDesc）",
                        "en": "Text to tap (matches text or contentDesc)"
                    },
                    "type": "string",
                    "required": true
                },
                {
                    "name": "exact",
                    "description": {
                        "zh": "\"true\" 完全相等，默认包含",
                        "en": "\"true\" for exact, default substring"
                    },
                    "type": "string",
                    "required": false
                },
                {
                    "name": "index",
                    "description": {
                        "zh": "多个匹配时取第几个（0 起），默认自动优先可点节点",
                        "en": "Which match to use (0-based); default prefers a clickable node"
                    },
                    "type": "integer",
                    "required": false
                },
                {
                    "name": "waitMs",
                    "description": {
                        "zh": "点击后观察界面变化多久，默认 700",
                        "en": "How long to watch for a change after tapping, default 700"
                    },
                    "type": "integer",
                    "required": false
                }
            ]
        },
        {
            "name": "tap_xy",
            "description": {
                "zh": "按坐标点击，同样会回报界面是否变化。",
                "en": "Tap raw coordinates; also reports whether the screen changed."
            },
            "parameters": [
                {
                    "name": "x",
                    "description": {
                        "zh": "X 坐标",
                        "en": "X coordinate"
                    },
                    "type": "integer",
                    "required": true
                },
                {
                    "name": "y",
                    "description": {
                        "zh": "Y 坐标",
                        "en": "Y coordinate"
                    },
                    "type": "integer",
                    "required": true
                },
                {
                    "name": "waitMs",
                    "description": {
                        "zh": "观察时长，默认 700",
                        "en": "Observation window, default 700"
                    },
                    "type": "integer",
                    "required": false
                }
            ]
        },
        {
            "name": "swipe",
            "description": {
                "zh": "滑动。可用 direction（up/down/left/right）自动按真实分辨率算距离，也可给四点坐标。",
                "en": "Swipe. Use direction (up/down/left/right) scaled to the real screen size, or pass all four coordinates."
            },
            "parameters": [
                {
                    "name": "direction",
                    "description": {
                        "zh": "up / down / left / right",
                        "en": "up / down / left / right"
                    },
                    "type": "string",
                    "required": false
                },
                {
                    "name": "x1",
                    "description": {
                        "zh": "起点 X",
                        "en": "Start X"
                    },
                    "type": "integer",
                    "required": false
                },
                {
                    "name": "y1",
                    "description": {
                        "zh": "起点 Y",
                        "en": "Start Y"
                    },
                    "type": "integer",
                    "required": false
                },
                {
                    "name": "x2",
                    "description": {
                        "zh": "终点 X",
                        "en": "End X"
                    },
                    "type": "integer",
                    "required": false
                },
                {
                    "name": "y2",
                    "description": {
                        "zh": "终点 Y",
                        "en": "End Y"
                    },
                    "type": "integer",
                    "required": false
                },
                {
                    "name": "duration",
                    "description": {
                        "zh": "滑动时长毫秒，默认 260",
                        "en": "Swipe duration in ms, default 260"
                    },
                    "type": "integer",
                    "required": false
                }
            ]
        },
        {
            "name": "press",
            "description": {
                "zh": "按键：HOME / BACK / ENTER / RECENTS 等。",
                "en": "Press a key: HOME / BACK / ENTER / RECENTS and friends."
            },
            "parameters": [
                {
                    "name": "key",
                    "description": {
                        "zh": "键名，可带或不带 KEYCODE_ 前缀",
                        "en": "Key name, with or without the KEYCODE_ prefix"
                    },
                    "type": "string",
                    "required": true
                },
                {
                    "name": "waitMs",
                    "description": {
                        "zh": "观察时长，默认 600",
                        "en": "Observation window, default 600"
                    },
                    "type": "integer",
                    "required": false
                }
            ]
        },
        {
            "name": "type_text",
            "description": {
                "zh": "向当前焦点输入框输入文字，可指定 resourceId。",
                "en": "Type into the focused input, optionally by resourceId."
            },
            "parameters": [
                {
                    "name": "text",
                    "description": {
                        "zh": "要输入的文字",
                        "en": "Text to enter"
                    },
                    "type": "string",
                    "required": true
                },
                {
                    "name": "resourceId",
                    "description": {
                        "zh": "可选，目标输入框的 resourceId",
                        "en": "Optional target resourceId"
                    },
                    "type": "string",
                    "required": false
                }
            ]
        },
        {
            "name": "screen_text",
            "description": {
                "zh": "只取屏上所有文字（去重、按顺序），最省 token 的读屏方式。",
                "en": "All on-screen text, deduplicated and ordered. The cheapest way to read a screen."
            },
            "parameters": [
                {
                    "name": "max",
                    "description": {
                        "zh": "最多多少条，默认 120",
                        "en": "Max lines, default 120"
                    },
                    "type": "integer",
                    "required": false
                }
            ]
        },
        {
            "name": "foreground",
            "description": {
                "zh": "当前前台包名与 Activity，用来确认“我到底在哪个界面”。",
                "en": "Current foreground package and activity, to confirm which screen you are actually on."
            },
            "parameters": []
        },
        {
            "name": "shot",
            "description": {
                "zh": "截图并返回文件路径与大小。无障碍树为空时用它看画面。",
                "en": "Screenshot, returning path and size. Use it when the accessibility tree is empty."
            },
            "parameters": []
        },
        {
            "name": "wait",
            "description": {
                "zh": "等一会儿再看屏幕，常用于等加载完成。",
                "en": "Wait, then report the screen, typically for loading."
            },
            "parameters": [
                {
                    "name": "ms",
                    "description": {
                        "zh": "等待毫秒，默认 800",
                        "en": "Milliseconds, default 800"
                    },
                    "type": "integer",
                    "required": false
                }
            ]
        }
    ]
}
*/

// PhoneControl — the native half of ai-phone-control.
// No shell, no adb, no uiautomator dump: it rides Operit's own UI bridge.
// The one rule borrowed from the host-side project: never report success
// for something that did not happen. Every action says whether the screen
// actually changed.

var PhoneControl = (function () {
    function isTrue(value) {
        if (value === true || value === 1) return true;
        var text = value === undefined || value === null ? '' : String(value);
        var lower = text.toLowerCase();
        return lower === 'true' || lower === '1' || lower === 'yes';
    }

    function intOf(value, fallback) {
        var parsed = parseInt(value === undefined || value === null ? '' : String(value), 10);
        return isNaN(parsed) ? fallback : parsed;
    }

    function centerOf(bounds) {
        if (!bounds || typeof bounds !== 'string') return null;
        var parts = bounds.match(/-?\d+/g);
        if (!parts || parts.length < 4) return null;
        var x1 = parseInt(parts[0], 10);
        var y1 = parseInt(parts[1], 10);
        var x2 = parseInt(parts[2], 10);
        var y2 = parseInt(parts[3], 10);
        return { x: Math.round((x1 + x2) / 2), y: Math.round((y1 + y2) / 2) };
    }

    function labelOf(node) {
        var text = node.text ? String(node.text).trim() : '';
        var desc = node.contentDesc ? String(node.contentDesc).trim() : '';
        if (text && desc && text !== desc) return text + ' | ' + desc;
        return text || desc;
    }

    function collect(node, out, limit) {
        if (!node || out.length >= limit) return out;
        var text = node.text ? String(node.text).trim() : '';
        var desc = node.contentDesc ? String(node.contentDesc).trim() : '';
        var label = labelOf(node);
        var centre = centerOf(node.bounds);
        if (label || node.isClickable) {
            out.push({
                label: label,
                text: text,
                desc: desc,
                className: node.className ? String(node.className) : '',
                resourceId: node.resourceId ? String(node.resourceId) : '',
                clickable: !!node.isClickable,
                x: centre ? centre.x : -1,
                y: centre ? centre.y : -1
            });
        }
        var kids = node.children || [];
        for (var i = 0; i < kids.length; i++) collect(kids[i], out, limit);
        return out;
    }

    function countNodes(node) {
        if (!node) return 0;
        var total = 1;
        var kids = node.children || [];
        for (var i = 0; i < kids.length; i++) total += countNodes(kids[i]);
        return total;
    }

    // A screen fingerprint: package + activity + node count + total label length.
    // Stable enough to tell "nothing happened" from "a new screen appeared",
    // cheap enough to compute on every action.
    function signature(page) {
        var nodes = collect(page.uiElements, [], 60);
        var chars = 0;
        for (var i = 0; i < nodes.length; i++) chars += nodes[i].label.length;
        return (page.packageName || '') + '/' + (page.activityName || '') + '/' +
            countNodes(page.uiElements) + '/' + chars;
    }

    async function snapshot() {
        var page = await Tools.UI.getPageInfo();
        return {
            packageName: page.packageName || '',
            activityName: page.activityName || '',
            root: page.uiElements,
            signature: signature(page)
        };
    }

    async function screenSize() {
        try {
            var info = await Tools.System.getDeviceInfo();
            var resolution = info && info.screenResolution ? String(info.screenResolution) : '';
            var match = resolution.match(/(\d+)\s*[x×*]\s*(\d+)/);
            if (match) {
                return { w: parseInt(match[1], 10), h: parseInt(match[2], 10) };
            }
        } catch (error) {
            // fall through: caller must pass explicit coordinates
        }
        return null;
    }

    // Watch the screen for a while and report whether it changed at all.
    async function settle(budgetMs, beforeSignature) {
        var budget = budgetMs > 0 ? budgetMs : 0;
        var step = 150;
        var waited = 0;
        var last = null;
        while (waited < budget) {
            await Tools.System.sleep(step);
            waited += step;
            last = await snapshot();
            if (beforeSignature && last.signature !== beforeSignature) {
                return { changed: true, snap: last, waited: waited };
            }
        }
        if (!last) last = await snapshot();
        return { changed: false, snap: last, waited: waited };
    }

    // Match against the raw text, the raw contentDesc and the combined label.
    // Exact mode used to fail whenever text and description both existed,
    // because the combined label is "text | desc" and never equals the pin.
    function matches(item, needle, exact) {
        if (!item) return false;
        var pin = needle.toLowerCase();
        var fields = [item.text || '', item.desc || '', item.label || ''];
        for (var i = 0; i < fields.length; i++) {
            var field = fields[i];
            if (!field) continue;
            var hay = field.toLowerCase();
            if (exact ? hay === pin : hay.indexOf(pin) >= 0) return true;
        }
        return false;
    }

    async function screen(params) {
        var scope = params.scope ? String(params.scope).toLowerCase() : 'actionable';
        var max = intOf(params.max, 200);
        var snap = await snapshot();
        var all = collect(snap.root, [], 4000);
        var picked = [];
        for (var i = 0; i < all.length; i++) {
            var node = all[i];
            if (scope === 'clickable' && !node.clickable) continue;
            if (scope === 'text' && !node.label) continue;
            if (scope === 'actionable' && !node.label && !node.clickable) continue;
            picked.push(node);
            if (picked.length >= max) break;
        }
        var lines = [];
        for (var j = 0; j < picked.length; j++) {
            var row = picked[j];
            var at = row.x >= 0 ? '@' + row.x + ',' + row.y : '@?';
            lines.push('[' + j + ']' + (row.clickable ? '*' : ' ') + ' ' + JSON.stringify(row.label) + ' ' + at);
        }
        var message;
        if (picked.length === 0) {
            message = 'No actionable nodes on ' + snap.packageName + '/' + snap.activityName +
                ' — this screen exposes no accessibility tree (WebView / canvas / game). Use shot and read the image instead.';
        } else {
            message = picked.length + ' node(s) on ' + snap.packageName + '/' + snap.activityName + ' (* = clickable)';
        }
        return {
            success: true,
            message: message,
            app: snap.packageName,
            page: snap.activityName,
            count: picked.length,
            nodes: lines.join('\n'),
            signature: snap.signature
        };
    }

    async function find(params) {
        var needle = params.text === undefined || params.text === null ? '' : String(params.text);
        if (!needle) return { success: false, message: 'Missing required parameter: text' };
        var exact = isTrue(params.exact);
        var snap = await snapshot();
        var all = collect(snap.root, [], 4000);
        var hits = [];
        for (var i = 0; i < all.length; i++) {
            if (matches(all[i], needle, exact)) hits.push(all[i]);
        }
        if (hits.length === 0) {
            return {
                success: false,
                message: 'NOT_ON_SCREEN: nothing matches ' + JSON.stringify(needle) + ' on ' +
                    snap.packageName + '/' + snap.activityName + ' (' + all.length + ' nodes scanned)',
                app: snap.packageName,
                page: snap.activityName,
                matches: 0
            };
        }
        var lines = [];
        for (var k = 0; k < hits.length; k++) {
            lines.push(hits[k].label + ' @' + hits[k].x + ',' + hits[k].y + (hits[k].clickable ? ' (clickable)' : ''));
        }
        return {
            success: true,
            message: hits.length + ' match(es) for ' + JSON.stringify(needle),
            app: snap.packageName,
            page: snap.activityName,
            matches: hits.length,
            hits: lines.join('\n')
        };
    }

    async function tapText(params) {
        var needle = params.text === undefined || params.text === null ? '' : String(params.text);
        if (!needle) return { success: false, message: 'Missing required parameter: text' };
        var exact = isTrue(params.exact);
        var waitMs = intOf(params.waitMs, 700);
        var index = intOf(params.index, -1);

        var before = await snapshot();
        var all = collect(before.root, [], 4000);
        var hits = [];
        for (var i = 0; i < all.length; i++) {
            if (matches(all[i], needle, exact)) hits.push(all[i]);
        }
        if (hits.length === 0) {
            return {
                success: false,
                message: 'NOT_ON_SCREEN: nothing matches ' + JSON.stringify(needle) + ' on ' +
                    before.packageName + '/' + before.activityName + ' — nothing was tapped',
                app: before.packageName,
                page: before.activityName
            };
        }

        var target = null;
        if (index >= 0) {
            if (index >= hits.length) {
                return {
                    success: false,
                    message: 'INDEX_OUT_OF_RANGE: ' + hits.length + ' match(es), asked for index ' + index,
                    matches: hits.length
                };
            }
            target = hits[index];
        } else {
            for (var c = 0; c < hits.length; c++) {
                if (hits[c].clickable && hits[c].x >= 0) { target = hits[c]; break; }
            }
            if (!target) target = hits[0];
        }

        if (target.x < 0 || target.y < 0) {
            return {
                success: false,
                message: 'NO_COORDINATES: ' + JSON.stringify(target.label) + ' has no bounds, cannot tap it'
            };
        }

        await Tools.UI.tap(target.x, target.y);
        var after = await settle(waitMs, before.signature);
        return {
            success: true,
            message: 'Tapped ' + JSON.stringify(target.label) + ' at ' + target.x + ',' + target.y +
                (after.changed
                    ? ' → screen changed (' + after.snap.packageName + '/' + after.snap.activityName + ')'
                    : ' → screen did NOT change within ' + after.waited + 'ms, verify before trusting this'),
            tapped: target.label,
            at: target.x + ',' + target.y,
            changed: after.changed,
            app: after.snap.packageName,
            page: after.snap.activityName,
            signature: after.snap.signature
        };
    }

    async function tapXy(params) {
        var x = intOf(params.x, -1);
        var y = intOf(params.y, -1);
        if (x < 0 || y < 0) return { success: false, message: 'Missing required parameters: x and y' };
        var waitMs = intOf(params.waitMs, 700);
        var before = await snapshot();
        await Tools.UI.tap(x, y);
        var after = await settle(waitMs, before.signature);
        return {
            success: true,
            message: 'Tapped ' + x + ',' + y + (after.changed ? ' → screen changed' : ' → screen did NOT change'),
            at: x + ',' + y,
            changed: after.changed,
            app: after.snap.packageName,
            page: after.snap.activityName,
            signature: after.snap.signature
        };
    }

    async function swipe(params) {
        var before = await snapshot();
        var duration = intOf(params.duration, 260);
        var waitMs = intOf(params.waitMs, 500);
        var x1 = intOf(params.x1, -1);
        var y1 = intOf(params.y1, -1);
        var x2 = intOf(params.x2, -1);
        var y2 = intOf(params.y2, -1);

        if (x1 < 0 || y1 < 0 || x2 < 0 || y2 < 0) {
            var direction = params.direction ? String(params.direction).toLowerCase() : '';
            if (!direction) {
                return { success: false, message: 'Give either direction (up/down/left/right) or all four of x1,y1,x2,y2' };
            }
            var size = await screenSize();
            if (!size) {
                return { success: false, message: 'Cannot determine screen size — pass explicit x1,y1,x2,y2' };
            }
            var cx = Math.round(size.w / 2);
            var cy = Math.round(size.h / 2);
            if (direction === 'up') {
                x1 = cx; y1 = Math.round(size.h * 0.72); x2 = cx; y2 = Math.round(size.h * 0.28);
            } else if (direction === 'down') {
                x1 = cx; y1 = Math.round(size.h * 0.28); x2 = cx; y2 = Math.round(size.h * 0.72);
            } else if (direction === 'left') {
                x1 = Math.round(size.w * 0.78); y1 = cy; x2 = Math.round(size.w * 0.22); y2 = cy;
            } else if (direction === 'right') {
                x1 = Math.round(size.w * 0.22); y1 = cy; x2 = Math.round(size.w * 0.78); y2 = cy;
            } else {
                return { success: false, message: 'Unknown direction: ' + direction + ' (up/down/left/right)' };
            }
        }

        await Tools.UI.swipe(x1, y1, x2, y2, duration);
        var after = await settle(waitMs, before.signature);
        return {
            success: true,
            message: 'Swiped ' + x1 + ',' + y1 + ' → ' + x2 + ',' + y2 +
                (after.changed ? ' → screen changed' : ' → screen did NOT change'),
            from: x1 + ',' + y1,
            to: x2 + ',' + y2,
            changed: after.changed,
            app: after.snap.packageName,
            page: after.snap.activityName,
            signature: after.snap.signature
        };
    }

    async function press(params) {
        var key = params.key ? String(params.key).trim() : '';
        if (!key) return { success: false, message: 'Missing required parameter: key (HOME, BACK, ENTER, RECENTS, ...)' };
        var waitMs = intOf(params.waitMs, 600);
        var before = await snapshot();
        var upper = key.toUpperCase();
        var candidates = upper.indexOf('KEYCODE_') === 0 ? [upper] : [upper, 'KEYCODE_' + upper];
        var used = '';
        var lastError = null;
        for (var i = 0; i < candidates.length; i++) {
            try {
                await Tools.UI.pressKey(candidates[i]);
                used = candidates[i];
                break;
            } catch (error) {
                lastError = error;
            }
        }
        if (!used) {
            var reason = lastError && lastError.message ? lastError.message : 'pressKey failed';
            return { success: false, message: 'PRESS_FAILED for ' + key + ': ' + reason };
        }
        var after = await settle(waitMs, before.signature);
        return {
            success: true,
            message: 'Pressed ' + used + (after.changed ? ' → screen changed' : ' → screen did NOT change'),
            key: used,
            changed: after.changed,
            app: after.snap.packageName,
            page: after.snap.activityName,
            signature: after.snap.signature
        };
    }

    async function typeText(params) {
        var text = params.text === undefined || params.text === null ? '' : String(params.text);
        if (!text) return { success: false, message: 'Missing required parameter: text' };
        var resourceId = params.resourceId ? String(params.resourceId) : '';
        if (resourceId) {
            await Tools.UI.setText(text, resourceId);
        } else {
            await Tools.UI.setText(text);
        }
        await Tools.System.sleep(300);
        var snap = await snapshot();
        return {
            success: true,
            message: 'Typed ' + text.length + ' character(s)' + (resourceId ? ' into ' + resourceId : ' into the focused field'),
            app: snap.packageName,
            page: snap.activityName,
            signature: snap.signature
        };
    }

    async function screenText(params) {
        var max = intOf(params.max, 120);
        var snap = await snapshot();
        var all = collect(snap.root, [], 4000);
        var seen = {};
        var lines = [];
        for (var i = 0; i < all.length; i++) {
            var label = all[i].label;
            if (!label) continue;
            if (seen[label]) continue;
            seen[label] = true;
            lines.push(label);
            if (lines.length >= max) break;
        }
        return {
            success: true,
            message: lines.length + ' text line(s) on ' + snap.packageName + '/' + snap.activityName,
            app: snap.packageName,
            page: snap.activityName,
            count: lines.length,
            text: lines.join('\n'),
            signature: snap.signature
        };
    }

    async function foreground() {
        var snap = await snapshot();
        return {
            success: true,
            message: snap.packageName + '/' + snap.activityName,
            app: snap.packageName,
            page: snap.activityName,
            signature: snap.signature
        };
    }

    async function shot() {
        var path = await Tools.UI.captureScreenshot();
        var info = '';
        try {
            var stat = await Tools.Files.info(path);
            var size = stat && (stat.size !== undefined ? stat.size : stat.fileSize);
            if (size !== undefined) info = ' (' + size + ' bytes)';
        } catch (error) {
            info = ' (size unknown: ' + (error && error.message ? error.message : String(error)) + ')';
        }
        return {
            success: true,
            message: 'Screenshot saved: ' + path + info,
            path: path
        };
    }

    async function wait(params) {
        var ms = intOf(params.ms, 800);
        await Tools.System.sleep(ms);
        var snap = await snapshot();
        return {
            success: true,
            message: 'Waited ' + ms + 'ms; now on ' + snap.packageName + '/' + snap.activityName,
            app: snap.packageName,
            page: snap.activityName,
            signature: snap.signature
        };
    }

    return {
        screen: screen,
        find: find,
        tap_text: tapText,
        tap_xy: tapXy,
        swipe: swipe,
        press: press,
        type_text: typeText,
        screen_text: screenText,
        foreground: foreground,
        shot: shot,
        wait: wait
    };
})();

// Export every tool through one guard, so a thrown bridge error never escapes
// as a bare exception: the agent always gets { success:false, message }.
(function () {
    var names = ['screen', 'find', 'tap_text', 'tap_xy', 'swipe', 'press',
                 'type_text', 'screen_text', 'foreground', 'shot', 'wait'];
    for (var i = 0; i < names.length; i++) {
        (function (name) {
            var fn = PhoneControl[name];
            exports[name] = async function (params) {
                try {
                    return await fn(params || {});
                } catch (error) {
                    var msg = error && error.message ? error.message : String(error);
                    return { success: false, message: 'ERROR: ' + msg };
                }
            };
        })(names[i]);
    }
})();
