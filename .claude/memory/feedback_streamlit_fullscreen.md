---
name: vis.js fullscreen inside Streamlit iframe
description: How to make vis.js graphs fill the entire browser window when rendered inside a Streamlit components.html iframe
type: feedback
---

Streamlit components.html renders vis.js graphs inside a constrained iframe. Fullscreen must break out of the iframe.

**Why:** iframe default height is 720px. Browser Fullscreen API on `document.documentElement` fills the iframe viewport but not the parent browser window. Parent containers (body, html, Streamlit wrapper) constrain size.

**How to apply:**
- Call `document.documentElement.requestFullscreen()` first
- Also expand `window.frameElement` (the iframe itself) to `position:fixed;top:0;left:0;width:100vw;height:100vh`
- Walk up parent DOM tree (`body.parentElement` chain), set each to `position:fixed;width:100vw;height:100vh`
- Restore on exit: remove overlay, restore original network visibility, call `document.exitFullscreen()`

**vis.DataSet cloning gotcha:** `network.getOptions()` returns edge colors as objects (`{color:'#CFD8DC', highlight:'#CFD8DC'}`). `edges.get()` may return same format. New vis.js instance needs **plain hex strings** for colors. Must normalize: `c.color || c` for objects, passthrough for strings. Same for node colors — `c.background` for objects. Without this, fullscreen shows gray canvas with no nodes.

**Container sizing:** vis.js canvas needs explicit dimensions. Use `position:absolute;top:48px;left:0;right:0;bottom:0` not `width:100%;height:100%` — the latter computes to 0 when parent has no intrinsic size.
