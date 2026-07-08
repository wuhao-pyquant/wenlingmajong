from __future__ import annotations

import ast
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryBoundaryTests(unittest.TestCase):
    def test_core_manifest_matches_packaged_files(self) -> None:
        core_root = ROOT / "packages" / "wenling_core" / "wenling_core"
        manifest = json.loads(
            (ROOT / "packages" / "wenling_core" / "CORE_MANIFEST.json").read_text(encoding="utf-8")
        )
        for entry in manifest:
            path = core_root / entry["path"]
            payload = path.read_bytes()
            self.assertEqual(len(payload), entry["bytes"], entry["path"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"], entry["path"])

    def test_lan_source_does_not_import_training_or_cloudflare(self) -> None:
        forbidden = {"torch", "wenling_training", "dmc_model", "training_manager", "expert_selfplay", "cloudflared"}
        found: set[str] = set()
        for path in (ROOT / "src" / "wenling_lan_host").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    found.add(node.module)
        self.assertFalse({name for name in found if any(name == item or name.startswith(f"{item}.") for item in forbidden)})

    def test_winner_animation_contract_uses_luck_and_has_no_time_cap(self) -> None:
        script = (ROOT / "static" / "battle_app.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        gif = ROOT / "static" / "assets" / "q_dazed_drool_5s.gif"

        self.assertIn("luck !== null && luck >= 95", script)
        self.assertIn('data-win-animation="normal"', script)
        self.assertIn('data-win-animation="exceptional-luck"', script)
        self.assertNotIn("lastWinAnimationStartedAt", script)
        self.assertIn("winnerBurstShell 5s ease-in-out infinite", styles)
        self.assertIn("winnerSeatGlow 5s ease-in-out infinite", styles)
        self.assertIn("--winner-burst-opacity: 0.72", styles)
        self.assertIn("opacity: var(--winner-burst-opacity)", styles)
        self.assertIn("rgba(255, 244, 151, 0.42)", styles)
        self.assertIn("opacity: 0.44", styles)
        self.assertTrue(gif.is_file())

    def test_android_room_service_holds_and_releases_runtime_locks(self) -> None:
        manifest = (ROOT / "android-host" / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")
        service = (
            ROOT
            / "android-host"
            / "app"
            / "src"
            / "main"
            / "java"
            / "cn"
            / "wenling"
            / "mahjong"
            / "host"
            / "HostService.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("android.permission.WAKE_LOCK", manifest)
        self.assertIn("android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS", manifest)
        self.assertIn("android.permission.FOREGROUND_SERVICE_DATA_SYNC", manifest)
        self.assertIn('android:foregroundServiceType="connectedDevice|dataSync"', manifest)
        self.assertIn("PowerManager.PARTIAL_WAKE_LOCK", service)
        self.assertIn("WifiManager.WIFI_MODE_FULL_HIGH_PERF", service)
        self.assertNotIn("WifiManager.WIFI_MODE_FULL_LOW_LATENCY", service)
        self.assertIn("return START_STICKY", service)
        self.assertIn("startWatchdog()", service)
        self.assertIn("checkHttpHealth(\"http://127.0.0.1:$port/api/health\")", service)
        self.assertIn("recoverPythonHost(port)", service)
        self.assertIn("releaseRuntimeLocks()", service)

    def test_android_start_flow_requests_battery_exemption(self) -> None:
        activity = (
            ROOT
            / "android-host"
            / "app"
            / "src"
            / "main"
            / "java"
            / "cn"
            / "wenling"
            / "mahjong"
            / "host"
            / "MainActivity.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS", activity)
        self.assertIn("requestBatteryUnrestricted()\n        if (model.state.value.connectionMode", activity)

    def test_browser_discard_and_claimed_meld_interaction_contract(self) -> None:
        script = (ROOT / "static" / "battle_app.js").read_text(encoding="utf-8")
        battle_html = (ROOT / "static" / "battle.html").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        geometry_v7 = (ROOT / "static" / "battle_geometry_v7.css").read_text(encoding="utf-8")

        self.assertIn("20260702-v7-room-menu-1", battle_html)
        self.assertIn("/battle_geometry_v7.css", battle_html)
        self.assertNotIn("battle_geometry_v3.css", battle_html)
        self.assertNotIn("battle_geometry_v5.css", battle_html)
        self.assertNotIn("battle_geometry_v6.css", battle_html)
        self.assertIn('<div class="center-hud-grid">', script)
        self.assertIn("centerSeatHudHtml(2, \"top\")", script)
        self.assertIn('<span class="center-seat-wind">${escapeXml(wind)}</span>', script)
        self.assertIn('<span class="center-seat-chip">${escapeXml(chips)}</span>', script)
        self.assertIn("center-seat-status center-seat-warning", script)
        self.assertIn("center-seat-status center-seat-bao", script)
        self.assertIn(">2连</span>", script)
        self.assertIn("grid-template-areas:", geometry_v7)
        self.assertIn(".center-seat-card-top", geometry_v7)
        self.assertIn("grid-area: top !important", geometry_v7)
        self.assertIn(".center-seat-card-left", geometry_v7)
        self.assertIn("grid-area: left !important", geometry_v7)
        self.assertIn(".center-seat-card-right", geometry_v7)
        self.assertIn("grid-area: right !important", geometry_v7)
        self.assertIn(".center-seat-card-bottom", geometry_v7)
        self.assertIn("grid-area: bottom !important", geometry_v7)
        self.assertIn("grid-area: core !important", geometry_v7)
        self.assertIn(".center-seat-status", geometry_v7)
        self.assertIn("flex: 0 0 34px !important", geometry_v7)
        self.assertIn("width: 34px !important", geometry_v7)
        self.assertIn("animation: centerSeatStatusPulse 0.9s ease-in-out infinite alternate !important", geometry_v7)
        self.assertIn("@keyframes centerSeatStatusPulse", geometry_v7)
        self.assertIn("Room menu placement authority", geometry_v7)
        self.assertIn("body.battle-app-mode .mahjong-table[data-geometry=\"v7\"] .room-menu-panel", geometry_v7)
        self.assertIn("right: 18px !important", geometry_v7)
        self.assertIn("left: auto !important", geometry_v7)
        self.assertIn("max-width: calc(100% - 36px) !important", geometry_v7)
        self.assertIn("max-height: calc(var(--battle-content-h, 780px) - 132px) !important", geometry_v7)
        self.assertIn("drawCenter: false", script)
        self.assertIn('table.dataset.centerCanvas = "0"', script)
        self.assertNotIn("const cornerHeads", script)
        self.assertNotIn("corner-player-head", script)
        self.assertIn('span.textContent = "双击出牌";', script)
        self.assertNotIn('span.textContent = "请选择出牌";', script)
        self.assertNotIn('span.textContent = "请选择一张手牌";', script)
        self.assertIn("const same = selectedDiscardTile === tile;", script)
        self.assertIn('sendAction({ type: "discard", tile });', script)
        self.assertIn("const replacementIndex = tiles.findIndex((code) => code === selectedDiscardTile);", script)
        self.assertIn('["chi", "peng", "ming_gang", "bu_gang"].includes(meld.type)', script)
        self.assertIn('direction === "left" ? 0 : direction === "top" ? 1 : entries.length', script)
        self.assertIn('({ 1: "right", 2: "top", 3: "left" })', script)
        self.assertIn("tile.small.claimed-discard", styles)
        self.assertIn("transform: rotate(90deg) !important", styles)
        self.assertIn(".tile.tile-selected-match", geometry_v7)
        self.assertIn("outline: 0 !important", geometry_v7)
        self.assertIn("brightness(1.12)", geometry_v7)
        self.assertIn("function shouldAnimateSpokenAction", script)
        self.assertIn('entry.event === "discard" || entry.event === "win"', script)
        self.assertIn("triggerSeatActionEffect(entry, text)", script)
        self.assertIn("seat-action-anchor", script)
        self.assertIn("seat-action-pop", script)
        self.assertIn("renderTableCanvas();\n        updateSelectedTileHighlights();", script)
        self.assertIn("function applyDomV7FallbackLayout", script)
        self.assertIn('applyDomV7FallbackLayout(rendererState, "canvas-error")', script)
        self.assertIn("battle-seat-v7", script)
        self.assertNotIn("player-panel table-seat", script)
        self.assertIn(".seat-action-anchor", styles)
        self.assertIn("animation: seatActionPop 1s ease-out both", styles)
        self.assertIn(".battle-seat-v7", geometry_v7)
        self.assertIn("background: transparent !important", geometry_v7)
        self.assertIn("backdrop-filter: none !important", geometry_v7)

    def test_browser_response_actions_refresh_stale_tokens_before_retry(self) -> None:
        script = (ROOT / "static" / "battle_app.js").read_text(encoding="utf-8")

        self.assertIn("function sameActionIntent", script)
        self.assertIn("function currentLegalActionForIntent", script)
        self.assertIn("const currentAction = battlePath ? currentLegalActionForIntent(action) : action;", script)
        self.assertIn("battle action stale; refreshing and retrying current action", script)
        self.assertIn("牌局已更新，请按当前画面重新选择动作", script)
