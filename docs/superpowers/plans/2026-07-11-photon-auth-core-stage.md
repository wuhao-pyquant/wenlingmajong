# Photon Auth Core Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all login-page promotional copy and turn its former area into a stable, unobstructed stage for the existing white Photon Mahjong core.

**Architecture:** Replace the copy block with an empty visual spacer, keep the auth console and all functional contracts unchanged, and derive the Three.js tile-group position from page type plus viewport width and height. Keep lobby and battle behavior isolated, and bump the shared Photon cache token so NAS and mobile browsers load the new layout.

**Tech Stack:** Static HTML/CSS, vanilla JavaScript, Three.js 0.185.1, Python `unittest`, Wenling HTTP host, Docker/NAS deployment.

## Global Constraints

- Preserve the top “温岭麻将” brand and `SYSTEM ONLINE` status.
- Remove `PHOTON GAME NETWORK`, `连接牌桌`, `进入对局`, and `温岭好友牌局 · ONLINE` from `/battle-login`.
- Do not change auth IDs, APIs, session keys, `/battle-lobby`, or `/battle` behavior.
- Keep the visual spacer text-free, unframed, and `aria-hidden="true"`.
- Keep `440 x 956` free of horizontal overflow and preserve a complete bottom auth console.
- Keep Three.js, Canvas, static fallback, lifecycle, and quality downgrade behavior unchanged.
- Use cache token `20260711-photon-5` on both login and lobby entry pages.

---

### Task 1: Replace Promotional Copy With a Visual Stage

**Files:**
- Modify: `tests/test_photon_frontend.py`
- Modify: `static/battle_login.html`
- Modify: `static/battle_lobby.html`
- Modify: `docs/superpowers/plans/2026-07-10-photon-auth-lobby.md`

**Interfaces:**
- Consumes: existing `.photon-auth-stage`, `.photon-auth-console`, auth element IDs, and shared Photon asset URLs.
- Produces: `<div class="photon-auth-visual" aria-hidden="true"></div>` and shared cache token `20260711-photon-5`.

- [ ] **Step 1: Write the failing markup and cache tests**

Add to `PhotonFrontendTests`:

```python
def test_auth_page_reserves_text_free_photon_core_stage(self) -> None:
    html = (ROOT / "static" / "battle_login.html").read_text(encoding="utf-8")
    self.assertIn('<div class="photon-auth-visual" aria-hidden="true"></div>', html)
    for removed_copy in (
        "PHOTON GAME NETWORK",
        "连接牌桌",
        "进入对局",
        "温岭好友牌局 · ONLINE",
    ):
        self.assertNotIn(removed_copy, html)
    self.assertIn("温岭麻将", html)
    self.assertIn("SYSTEM ONLINE", html)
```

In `test_photon_entry_pages_share_the_final_cache_token`, require:

```python
self.assertIn(f"{asset}?v=20260711-photon-5", html)
self.assertNotIn("20260711-photon-4", html)
self.assertNotIn("20260711-photon-3", html)
```

Also update `test_auth_page_uses_photon_stage_and_preserves_contract_ids` to require:

```python
self.assertIn('/photon_lobby.css?v=20260711-photon-5', html)
self.assertIn('/photon_scene.js?v=20260711-photon-5', html)
```

- [ ] **Step 2: Run the tests and verify RED**

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_auth_page_reserves_text_free_photon_core_stage tests.test_photon_frontend.PhotonFrontendTests.test_photon_entry_pages_share_the_final_cache_token tests.test_photon_frontend.PhotonFrontendTests.test_auth_page_uses_photon_stage_and_preserves_contract_ids -v
```

Expected: cache assertions FAIL while the entry pages still reference `photon-4`; the markup assertion also fails until the text-free stage replacement is present.

- [ ] **Step 3: Implement the stage and cache bump**

Replace `.photon-auth-copy` in `static/battle_login.html` with:

```html
<div class="photon-auth-visual" aria-hidden="true"></div>
```

Change the three Photon entry asset references in both HTML files to:

```html
<link rel="stylesheet" href="/photon_lobby.css?v=20260711-photon-5" />
<script src="/photon_scene.js?v=20260711-photon-5" defer></script>
<script src="/battle_lobby.js?v=20260711-photon-5" defer></script>
```

Update matching examples and assertions in `docs/superpowers/plans/2026-07-10-photon-auth-lobby.md`.

- [ ] **Step 4: Run Step 2 and verify both tests PASS**

- [ ] **Step 5: Commit Task 1**

```powershell
git add static/battle_login.html static/battle_lobby.html tests/test_photon_frontend.py docs/superpowers/plans/2026-07-10-photon-auth-lobby.md
git commit -m "Create text-free Photon auth stage"
```

---

### Task 2: Reserve Responsive Space for the Core

**Files:**
- Modify: `tests/test_photon_frontend.py`
- Modify: `static/photon_lobby.css`

**Interfaces:**
- Consumes: `.photon-auth-visual` from Task 1 and existing `760px`/low-height breakpoints.
- Produces: stable desktop, phone portrait, and low-height landscape geometry without changing the auth console.

- [ ] **Step 1: Write the failing responsive CSS test**

```python
def test_auth_visual_stage_reserves_responsive_core_space(self) -> None:
    css = (ROOT / "static" / "photon_lobby.css").read_text(encoding="utf-8")
    self.assertIn(".photon-auth-page .photon-auth-visual", css)
    self.assertIn("min-height: clamp(320px, 62vh, 680px)", css)
    self.assertIn("grid-template-rows: minmax(240px, 1fr) auto", css)
    self.assertIn("min-height: clamp(240px, 38svh, 360px)", css)
    self.assertIn("min-height: 180px", css)
```

Update `test_photon_css_uses_fixed_heading_sizes_without_viewport_font_scaling` so the deleted auth heading is no longer a contract:

```python
self.assertNotIn(".photon-auth-page .photon-auth-copy", css)
self.assertIn(".photon-lobby-page .photon-lobby-heading h1", css)
self.assertIn("font-size: 56px", css)
self.assertNotRegex(css, viewport_font_size)
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_auth_visual_stage_reserves_responsive_core_space -v
```

Expected: FAIL because `.photon-auth-visual` has no CSS contract.

- [ ] **Step 3: Implement the responsive visual stage**

Replace obsolete `.photon-auth-copy` rules with:

```css
.photon-auth-page .photon-auth-visual {
  min-width: 0;
  min-height: clamp(320px, 62vh, 680px);
}
```

Inside `@media (max-width: 760px)`, set:

```css
.photon-auth-page .photon-auth-stage {
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(240px, 1fr) auto;
  align-content: stretch;
  gap: 18px;
  min-height: 0;
  padding-top: 12px;
}
.photon-auth-page .photon-auth-visual {
  min-height: clamp(240px, 38svh, 360px);
}
```

Inside the low-height landscape media query, set:

```css
.photon-auth-page .photon-auth-stage {
  grid-template-columns: minmax(180px, .8fr) minmax(0, 1.2fr);
  grid-template-rows: minmax(0, 1fr);
}
.photon-auth-page .photon-auth-visual { min-height: 180px; }
```

Remove all `.photon-auth-copy` media rules.

- [ ] **Step 4: Run focused CSS tests**

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_auth_visual_stage_reserves_responsive_core_space tests.test_photon_frontend.PhotonFrontendTests.test_photon_css_adds_scoped_accessible_responsive_state_polish tests.test_photon_frontend.PhotonFrontendTests.test_photon_css_uses_fixed_heading_sizes_without_viewport_font_scaling -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add static/photon_lobby.css tests/test_photon_frontend.py
git commit -m "Reserve responsive Photon core space"
```

---

### Task 3: Position the Mahjong Core and Verify Deployment

**Files:**
- Modify: `tests/test_photon_frontend.py`
- Modify: `static/photon_scene.js`

**Interfaces:**
- Consumes: `root.dataset.page`, `window.innerWidth`, `window.innerHeight`, and the existing Three.js `tileGroup`.
- Produces: `tileGroupPosition(page, viewportWidth, viewportHeight)` returning `[x, y, z]`, exported through the CommonJS test surface and re-applied from the resize callback. Low-height landscape auth projects the left visual-column center at NDC x `-0.6` into world space using the shared camera FOV `44` and distance `12` constants.

- [ ] **Step 1: Write the failing pure positioning test**

```python
def test_tile_group_position_targets_auth_visual_stage(self) -> None:
    payload = self.run_node_json(
        """
        const photon = require('./static/photon_scene.js');
        console.log(JSON.stringify({
          desktopAuth: photon.tileGroupPosition('auth', 1280, 720),
          portraitAuth: photon.tileGroupPosition('auth', 440, 956),
          landscapeAuth: photon.tileGroupPosition('auth', 667, 375),
          wideLandscapeAuth: photon.tileGroupPosition('auth', 844, 390),
          lobby: photon.tileGroupPosition('lobby', 440, 390),
        }));
        """
    )
    self.assertEqual(payload["desktopAuth"], [-2.6, 0.25, 0])
    self.assertEqual(payload["portraitAuth"], [0, 1.15, 0])
    self.assertEqual(payload["lobby"], [2.5, 0.25, 0])
    self.assertAlmostEqual(payload["landscapeAuth"][0], -5.174121458535351)
    self.assertEqual(payload["landscapeAuth"][1:], [0.25, 0])
    self.assertAlmostEqual(payload["wideLandscapeAuth"][0], -6.295350177320719)
    self.assertEqual(payload["wideLandscapeAuth"][1:], [0.25, 0])
```

Update the behavioral Three probe test to boot auth and lobby at `440x956`, dispatch the registered resize listener at `667x375` and `844x390`, and inspect the live `Group.position`. Auth must use the projected X values above while lobby remains `[2.5, 0.25, 0]` throughout.

- [ ] **Step 2: Run the test and verify RED**

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend.PhotonFrontendTests.test_tile_group_position_targets_auth_visual_stage tests.test_photon_frontend.PhotonFrontendTests.test_three_resize_repositions_auth_tiles_and_preserves_lobby_position -v
```

Expected: both tests FAIL because low-height landscape auth still uses the desktop offset `-2.6`, placing the core near 37% of viewport width instead of the left visual-column center at 20%.

- [ ] **Step 3: Update and use the pure helper**

```javascript
const PHOTON_CAMERA_FOV_DEGREES = 44;
const PHOTON_CAMERA_DISTANCE = 12;
const AUTH_STAGE_CENTER_NDC_X = -0.6;

function authLandscapeStageX(viewportWidth, viewportHeight) {
  const halfFovRadians = (PHOTON_CAMERA_FOV_DEGREES * Math.PI / 180) / 2;
  const halfVisibleWorldWidth = PHOTON_CAMERA_DISTANCE
    * Math.tan(halfFovRadians)
    * (Number(viewportWidth) / Number(viewportHeight));
  return AUTH_STAGE_CENTER_NDC_X * halfVisibleWorldWidth;
}

function tileGroupPosition(page, viewportWidth, viewportHeight) {
  if (page === "lobby") return [2.5, 0.25, 0];
  if (Number(viewportHeight) <= 520 && Number(viewportWidth) > Number(viewportHeight)) {
    return [authLandscapeStageX(viewportWidth, viewportHeight), 0.25, 0];
  }
  if (Number(viewportWidth) <= 760) return [0, 1.15, 0];
  return [-2.6, 0.25, 0];
}
```

Use the same constants when constructing and positioning the live camera:

```javascript
const camera = new THREE.PerspectiveCamera(PHOTON_CAMERA_FOV_DEGREES, 1, 0.1, 80);
camera.position.set(0, 0, PHOTON_CAMERA_DISTANCE);
```

Add a source-level regression test requiring the helper calculation, `PerspectiveCamera` constructor, and camera z position to reference `PHOTON_CAMERA_FOV_DEGREES` and `PHOTON_CAMERA_DISTANCE`, preventing projection drift.

Keep `tileGroupPosition` in `testExports`, then update the initial assignment to:

```javascript
tileGroup.position.set(...tileGroupPosition(root.dataset.page, window.innerWidth, window.innerHeight));
```

Inside the existing resize callback, re-apply the position after the renderer and camera update:

```javascript
tileGroup.position.set(...tileGroupPosition(root.dataset.page, width, height));
```

- [ ] **Step 4: Run focused and complete verification**

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest tests.test_photon_frontend tests.test_online_server tests.test_repository_boundaries -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node --check static/photon_scene.js
node --check static/battle_lobby.js
git diff --check
git diff --exit-code a758440 -- static/battle.html static/battle_app.js static/battle_geometry_v7.css
```

Expected: all Python tests PASS, syntax and diff checks exit `0`, and battle sources remain unchanged.

- [ ] **Step 5: Verify the `440 x 956` browser layout**

Open `/battle-login` with viewport `440 x 956`. Verify `window.innerWidth === 440`, `window.innerHeight === 956`, `data-photon-quality === "mobile"`, and horizontal overflow equals `0`. Visually confirm the four strings are absent, the white Mahjong core occupies the central stage, and the complete auth console remains below it.

- [ ] **Step 6: Commit, push, and verify NAS**

```powershell
git add static/photon_scene.js tests/test_photon_frontend.py
git commit -m "Center Photon core on auth stage"
git push origin main
```

After Gitee and NAS auto-update reach the commit, run:

```powershell
$base='http://192.168.31.116:8766'
Invoke-WebRequest -UseBasicParsing "$base/battle-login" -Headers @{'X-Forwarded-For'='192.168.1.22'}
Invoke-WebRequest -UseBasicParsing "$base/photon_scene.js?v=20260711-photon-5" -Headers @{'X-Forwarded-For'='192.168.1.22'}
Invoke-WebRequest -UseBasicParsing "$base/photon_lobby.css?v=20260711-photon-5" -Headers @{'X-Forwarded-For'='192.168.1.22'}
```

Expected: all requests return HTTP `200` and login HTML references `20260711-photon-5`.
