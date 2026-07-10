# Task 6 Browser Timer Fix Report

## Root Cause

`static/photon_scene.js` constructed `new THREE.Clock()`. In local Three 0.185.1,
that constructor emits the browser QA deprecation warning and is replaced by
`THREE.Timer`.

## TDD Record

RED was recorded before production edits with:

```powershell
python tests\test_photon_frontend.py PhotonFrontendTests.test_three_timer_contract_excludes_hidden_time_and_disposes_on_destroy
```

The test failed at `assertNotIn("new THREE.Clock", script)`, because the source
still constructed `new THREE.Clock()`.

## Fix

- Replace `THREE.Clock` with `THREE.Timer`.
- Call `timer.update()` before `timer.getElapsed()` on every Three frame.
- Call `timer.reset()` when the Three layer starts or resumes after visibility
  restoration, excluding hidden time.
- Call `timer.dispose()` through the existing idempotent Three cleanup path.
- Keep the existing single global `visibilitychange` listener unchanged.

The browser harness now models `Timer.update()`, `getElapsed()`, `reset()`, and
`dispose()`. The new contract verifies source selection, update-before-read,
frame animation, resume reset, destroy disposal, and listener cleanup.

## Verification

- Focused Timer contract: passed.
- Existing Three resume quality-window contract: passed.
- `node --check static\photon_scene.js`: passed.
- `python tests\test_photon_frontend.py`: 38 passed.
- `$env:PYTHONPATH='src;packages\wenling_core'; python -m unittest discover -s tests`: 269 passed, 5 skipped.
- `git diff --check`: passed.
