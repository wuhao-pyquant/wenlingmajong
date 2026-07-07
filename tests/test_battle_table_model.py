from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


class BattleTableModelTests(unittest.TestCase):
    def test_capacity_layout_boxes_match_latest_editor_export(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            const boxes = new Map(model.DEFAULT_CONFIG.layoutBoxes.map((box) => [`${box.type}:${box.seat ?? 'x'}:${box.row}`, box]));
            const pick = (key) => boxes.get(key);
            console.log(JSON.stringify({
              topHand: pick('hand:2:remote'),
              rightPublic: pick('public:1:overflow'),
              topPublic: pick('public:2:overflow'),
              topFlowers: pick('flowers:2:overflow'),
              topMeldMain: pick('melds:2:main'),
              topMeldOverflow: pick('melds:2:overflow'),
            }));
            """
        )
        self.assertEqual(result["topHand"]["x"], 453)
        self.assertEqual(result["rightPublic"]["y"], 262)
        self.assertEqual(result["rightPublic"]["h"], 416)
        self.assertEqual(result["topPublic"]["y"], 56)
        self.assertEqual(result["topFlowers"]["y"], 65)
        self.assertEqual(result["topMeldMain"]["y"], 119)
        self.assertEqual(result["topMeldOverflow"]["y"], 180)

    def test_four_meld_six_flower_layout_is_valid_without_gang_pressure(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('peng', 3, 3),
                  meld('chi', 1, 3),
                ],
                flowers: Array(6).fill('H1'),
                discards: Array(12).fill('1W'),
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const publicBlocks = table.blocks.filter((block) => block.type === 'public');
            const bottomPublic = publicBlocks.find((block) => block.seat === 0);
            const bottomRiver = table.blocks.find((block) => block.type === 'river' && block.seat === 0);
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              publicModes: publicBlocks.map((block) => block.mode),
              overlapDiagnostics: table.diagnostics.filter((item) => (
                item.code === 'river-public-overlap'
                || item.code === 'center-public-overlap'
                || item.code === 'hand-public-overlap'
              )),
              bottomPublicRight: bottomPublic.bbox.x + bottomPublic.bbox.w,
              bottomRiverLeft: bottomRiver.bbox.x,
              bottomPublicRows: {
                main: bottomPublic.metrics.rows.main.length,
                overflow: bottomPublic.metrics.rows.overflow.length,
              },
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["publicModes"], ["normal", "normal", "normal", "normal"])
        self.assertEqual(result["overlapDiagnostics"], [])
        self.assertEqual(result["bottomPublicRows"], {"main": 2, "overflow": 2})
        self.assertLess(result["bottomPublicRight"], result["bottomRiverLeft"])

    def test_gang_heavy_public_area_compacts_without_overlap_errors(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                ],
                flowers: Array(6).fill('H1'),
                discards: Array(12).fill('1W'),
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              publicModes: table.blocks.filter((block) => block.type === 'public').map((block) => block.mode),
              overlapDiagnostics: table.diagnostics.filter((item) => (
                item.code === 'river-public-overlap'
                || item.code === 'center-public-overlap'
                || item.code === 'hand-public-overlap'
              )),
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["publicModes"], ["compact", "compact", "compact", "compact"])
        self.assertEqual(result["overlapDiagnostics"], [])

    def test_five_meld_or_many_flowers_enters_overflow_but_stays_inside_table(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                  meld('ming_gang', 2, 4),
                ],
                flowers: Array(10).fill('H1'),
                discards: Array(15).fill('1W'),
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              publicModes: table.blocks.filter((block) => block.type === 'public').map((block) => block.mode),
              outside: table.diagnostics.filter((item) => item.code === 'outside-table'),
              overlapDiagnostics: table.diagnostics.filter((item) => (
                item.code === 'river-public-overlap'
                || item.code === 'center-public-overlap'
                || item.code === 'hand-public-overlap'
              )),
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["publicModes"], ["overflow", "overflow", "overflow", "overflow"])
        self.assertEqual(result["outside"], [])
        self.assertEqual(result["overlapDiagnostics"], [])

    def test_overflow_flowers_fold_into_stack_units(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            const metrics = model.publicMetrics({
              seat: 0,
              hand_count: 17,
              melds: [],
              flowers: Array(11).fill('H1'),
              discards: [],
            }, model.DEFAULT_CONFIG);
            console.log(JSON.stringify({
              density: metrics.density,
              flowers: metrics.flowers,
              layout: metrics.flowerLayout,
              maxRowUnits: metrics.maxRowUnits,
            }));
            """
        )
        self.assertEqual(result["density"], "overflow")
        self.assertEqual(result["flowers"], 11)
        self.assertTrue(result["layout"]["folded"])
        self.assertEqual(result["layout"]["visibleCount"], 4)
        self.assertEqual(result["layout"]["hiddenCount"], 7)
        self.assertAlmostEqual(result["layout"]["rowUnits"], 6.2)
        self.assertAlmostEqual(result["maxRowUnits"], 6.2)

    def test_active_hand_layout_fits_seventeen_tiles_on_narrow_mobile(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            const layout = model.activeHandLayout({
              count: 17,
              tableWidth: 740,
              mobile: true,
              hasNewDraw: true,
            });
            console.log(JSON.stringify(layout));
            """
        )
        self.assertTrue(result["fits"], result)
        self.assertLessEqual(result["contentWidth"], result["safeWidth"] + 0.5)
        self.assertGreater(result["tileW"], 0)
        self.assertEqual(result["overlapRatio"], 0)
        self.assertGreaterEqual(result["tileGap"], 0)
        self.assertGreaterEqual(result["drawGap"], 9)

    def test_active_hand_layout_keeps_regular_mobile_hand_larger_than_minimum(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            const layout = model.activeHandLayout({
              count: 13,
              tableWidth: 844,
              mobile: true,
              hasNewDraw: false,
            });
            console.log(JSON.stringify(layout));
            """
        )
        self.assertTrue(result["fits"], result)
        self.assertGreater(result["tileW"], 0)
        self.assertEqual(result["overlapRatio"], 0)
        self.assertGreaterEqual(result["tileGap"], 0)

    def test_active_hand_does_not_overlap_bottom_public_area_on_mobile(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                last_draw: seat === 0 ? '1W' : null,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                  meld('ming_gang', 2, 4),
                ],
                flowers: Array(11).fill('H1'),
                discards: Array(15).fill('1W'),
              };
            }
            function intersects(a, b, padding = 0) {
              const aa = {x: a.x - padding, y: a.y - padding, w: a.w + padding * 2, h: a.h + padding * 2};
              const bb = {x: b.x - padding, y: b.y - padding, w: b.w + padding * 2, h: b.h + padding * 2};
              return aa.x < bb.x + bb.w
                && aa.x + aa.w > bb.x
                && aa.y < bb.y + bb.h
                && aa.y + aa.h > bb.y;
            }
            function screenCheck(width, height) {
              const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
              const publicBlock = table.blocks.find((block) => block.type === 'public' && block.seat === 0);
              const layout = model.activeHandLayout({
                count: 17,
                tableWidth: width,
                mobile: width <= 900,
                hasNewDraw: true,
              });
              const sx = width / table.table.width;
              const sy = height / table.table.height;
              const publicRect = {
                x: publicBlock.bbox.x * sx,
                y: publicBlock.bbox.y * sy,
                w: publicBlock.bbox.w * sx,
                h: publicBlock.bbox.h * sy,
              };
              const handHeight = layout.tileW * 1.40625;
              const handRect = {
                x: (width - layout.contentWidth) / 2,
                y: height - 7 - handHeight,
                w: layout.contentWidth,
                h: handHeight,
              };
              return {
                width,
                height,
                layout,
                publicRect,
                handRect,
                gap: handRect.y - (publicRect.y + publicRect.h),
                overlaps: intersects(handRect, publicRect, 2),
              };
            }
            console.log(JSON.stringify({
              checks: [screenCheck(740, 360), screenCheck(844, 390)],
            }));
            """
        )
        for check in result["checks"]:
            self.assertFalse(check["overlaps"], check)
            self.assertGreaterEqual(check["gap"], 2, check)
            self.assertTrue(check["layout"]["fits"], check)
            self.assertGreater(check["layout"]["tileW"], 0, check)
            self.assertEqual(check["layout"]["overlapRatio"], 0, check)
            self.assertGreaterEqual(check["layout"]["tileGap"], 0, check)

    def test_public_blocks_do_not_overlap_each_other_in_all_player_extreme_overflow(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                  meld('ming_gang', 2, 4),
                ],
                flowers: Array(11).fill('H1'),
                discards: Array(15).fill('1W'),
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              publicBlocks: table.blocks
                .filter((block) => block.type === 'public')
                .map((block) => ({seat: block.seat, mode: block.mode, bbox: block.bbox})),
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(
            [item for item in result["diagnostics"] if item["code"] == "public-public-overlap"],
            [],
        )
        self.assertEqual(
            [item for item in result["diagnostics"] if item["code"] == "river-public-overlap"],
            [],
        )
        self.assertEqual([block["mode"] for block in result["publicBlocks"]], ["overflow"] * 4)

    def test_dense_river_uses_six_by_three_grid_and_overflow_count(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [],
                flowers: [],
                discards: Array(16).fill('1W'),
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              rivers: table.blocks
                .filter((block) => block.type === 'river')
                .map((block) => ({
                  mode: block.mode,
                  rows: block.rows,
                  cols: block.cols,
                  overflowCount: block.overflowCount,
                })),
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(
            result["rivers"],
            [
                {"mode": "dense", "rows": 3, "cols": 6, "overflowCount": 1},
                {"mode": "dense", "rows": 3, "cols": 6, "overflowCount": 1},
                {"mode": "dense", "rows": 3, "cols": 6, "overflowCount": 1},
                {"mode": "dense", "rows": 3, "cols": 6, "overflowCount": 1},
            ],
        )

    def test_river_blocks_are_transform_outputs_from_canonical_grid(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [],
                flowers: [],
                discards: Array(seat === 1 ? 15 : 12).fill('1W'),
              };
            }
            function roundRect(rect) {
              return {
                x: Math.round(rect.x * 1000) / 1000,
                y: Math.round(rect.y * 1000) / 1000,
                w: Math.round(rect.w * 1000) / 1000,
                h: Math.round(rect.h * 1000) / 1000,
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const rivers = table.blocks.filter((block) => block.type === 'river');
            const checks = rivers.map((block) => ({
              seat: block.seat,
              mode: block.mode,
              bbox: roundRect(block.bbox),
              transformed: roundRect(model.transformCanonicalRect(block.canonicalBBox, block.seat, table.config)),
              canonicalDifferentFromScreen: JSON.stringify(roundRect(block.canonicalBBox)) !== JSON.stringify(roundRect(block.bbox)),
            }));
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              checks,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual([item["seat"] for item in result["checks"]], [0, 1, 2, 3])
        self.assertEqual([item["mode"] for item in result["checks"]], ["normal", "dense", "normal", "normal"])
        for item in result["checks"]:
            self.assertEqual(item["bbox"], item["transformed"])
        self.assertFalse(result["checks"][0]["canonicalDifferentFromScreen"])
        self.assertTrue(all(item["canonicalDifferentFromScreen"] for item in result["checks"][1:]))

    def test_public_blocks_are_transform_outputs_from_canonical_area(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                ],
                flowers: Array(6).fill('H1'),
                discards: Array(12).fill('1W'),
              };
            }
            function roundRect(rect) {
              return {
                x: Math.round(rect.x * 1000) / 1000,
                y: Math.round(rect.y * 1000) / 1000,
                w: Math.round(rect.w * 1000) / 1000,
                h: Math.round(rect.h * 1000) / 1000,
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const publicBlocks = table.blocks.filter((block) => block.type === 'public');
            const checks = publicBlocks.map((block) => ({
              seat: block.seat,
              bbox: roundRect(block.bbox),
              transformed: roundRect(model.transformCanonicalRect(block.canonicalBBox, block.seat, table.config)),
              canonicalDifferentFromScreen: JSON.stringify(roundRect(block.canonicalBBox)) !== JSON.stringify(roundRect(block.bbox)),
            }));
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              checks,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual([item["seat"] for item in result["checks"]], [0, 1, 2, 3])
        for item in result["checks"]:
            self.assertEqual(item["bbox"], item["transformed"])
        self.assertFalse(result["checks"][0]["canonicalDifferentFromScreen"])
        self.assertTrue(all(item["canonicalDifferentFromScreen"] for item in result["checks"][1:]))

    def test_public_detail_blocks_are_transform_outputs_inside_parent(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                ],
                flowers: Array(6).fill('H1'),
                discards: Array(12).fill('1W'),
              };
            }
            function roundRect(rect) {
              return {
                x: Math.round(rect.x * 1000) / 1000,
                y: Math.round(rect.y * 1000) / 1000,
                w: Math.round(rect.w * 1000) / 1000,
                h: Math.round(rect.h * 1000) / 1000,
              };
            }
            function contains(parent, child) {
              const eps = 0.001;
              return child.x + eps >= parent.x
                && child.y + eps >= parent.y
                && child.x + child.w <= parent.x + parent.w + eps
                && child.y + child.h <= parent.y + parent.h + eps;
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const publicBySeat = new Map(
              table.blocks
                .filter((block) => block.type === 'public')
                .map((block) => [block.seat, block])
            );
            const detailBlocks = table.blocks.filter((block) => block.type === 'flowers' || block.type === 'melds');
            const checks = detailBlocks.map((block) => ({
              type: block.type,
              seat: block.seat,
              bbox: roundRect(block.bbox),
              transformed: roundRect(model.transformCanonicalRect(block.canonicalBBox, block.seat, table.config)),
              insideParent: contains(publicBySeat.get(block.seat).bbox, block.bbox),
              canonicalDifferentFromScreen: JSON.stringify(roundRect(block.canonicalBBox)) !== JSON.stringify(roundRect(block.bbox)),
            }));
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              detailCount: detailBlocks.length,
              flowerCount: detailBlocks.filter((block) => block.type === 'flowers').length,
              meldRowCount: detailBlocks.filter((block) => block.type === 'melds').length,
              checks,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["detailCount"], 12)
        self.assertEqual(result["flowerCount"], 4)
        self.assertEqual(result["meldRowCount"], 8)
        for item in result["checks"]:
            self.assertEqual(item["bbox"], item["transformed"])
            self.assertTrue(item["insideParent"], item)
        non_bottom = [item for item in result["checks"] if item["seat"] != 0]
        self.assertTrue(all(item["canonicalDifferentFromScreen"] for item in non_bottom))

    def test_center_label_blocks_are_transform_outputs_from_canonical_rail(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function player(seat) {
              return {seat, hand_count: 17, hand: {}, melds: [], flowers: [], discards: []};
            }
            function roundRect(rect) {
              return {
                x: Math.round(rect.x * 1000) / 1000,
                y: Math.round(rect.y * 1000) / 1000,
                w: Math.round(rect.w * 1000) / 1000,
                h: Math.round(rect.h * 1000) / 1000,
              };
            }
            function contains(parent, child) {
              const eps = 0.001;
              return child.x + eps >= parent.x
                && child.y + eps >= parent.y
                && child.x + child.w <= parent.x + parent.w + eps
                && child.y + child.h <= parent.y + parent.h + eps;
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const center = table.blocks.find((block) => block.type === 'center');
            const labels = table.blocks
              .filter((block) => block.type === 'centerLabel')
              .sort((left, right) => left.seat - right.seat);
            const transforms = [0, 1, 2, 3].map((seat) => model.seatTransform(seat, table.config));
            const checks = labels.map((block) => ({
              seat: block.seat,
              position: block.position,
              bbox: roundRect(block.bbox),
              transformed: roundRect(model.transformCanonicalRect(block.canonicalBBox, block.seat, table.config)),
              insideCenter: contains(center.bbox, block.bbox),
              canonicalDifferentFromScreen: JSON.stringify(roundRect(block.canonicalBBox)) !== JSON.stringify(roundRect(block.bbox)),
            }));
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              transforms,
              checks,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual([item["angle"] for item in result["transforms"]], [0, -90, 180, 90])
        self.assertEqual([item["seat"] for item in result["checks"]], [0, 1, 2, 3])
        self.assertEqual([item["position"] for item in result["checks"]], ["bottom", "right", "top", "left"])
        for item in result["checks"]:
            self.assertEqual(item["bbox"], item["transformed"])
            self.assertTrue(item["insideCenter"], item)
        self.assertFalse(result["checks"][0]["canonicalDifferentFromScreen"])
        self.assertTrue(all(item["canonicalDifferentFromScreen"] for item in result["checks"][1:]))

    def test_round_over_remote_hands_use_spread_revealed_rails(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function player(seat, revealed) {
              return {
                seat,
                hand_count: 17,
                hand: revealed && seat !== 0 ? {m1: 4, m2: 4, t1: 4, b1: 4, east: 1} : {},
                melds: [],
                flowers: [],
                discards: [],
              };
            }
            const standing = model.createBattleTableModel({players: [0, 1, 2, 3].map((seat) => player(seat, false))});
            const revealed = model.createBattleTableModel({players: [0, 1, 2, 3].map((seat) => player(seat, true))});
            const standingHands = standing.blocks.filter((block) => block.type === 'hand' && block.mode === 'remote');
            const revealedHands = revealed.blocks.filter((block) => block.type === 'hand' && block.mode === 'remoteRevealed');
            console.log(JSON.stringify({
              standingOk: standing.ok,
              revealedOk: revealed.ok,
              standingDiagnostics: standing.diagnostics,
              revealedDiagnostics: revealed.diagnostics,
              standingHands: standingHands.map((block) => ({seat: block.seat, mode: block.mode, bbox: block.bbox, step: block.metrics.step})),
              revealedHands: revealedHands.map((block) => ({seat: block.seat, mode: block.mode, pose: block.pose, tileCount: block.tileCount, bbox: block.bbox, step: block.metrics.step})),
            }));
            """
        )
        self.assertTrue(result["standingOk"], result["standingDiagnostics"])
        self.assertTrue(result["revealedOk"], result["revealedDiagnostics"])
        self.assertEqual(len(result["standingHands"]), 3)
        self.assertEqual(len(result["revealedHands"]), 3)
        self.assertTrue(all(hand["pose"] == "revealed" for hand in result["revealedHands"]))
        self.assertTrue(all(hand["tileCount"] == 17 for hand in result["revealedHands"]))
        self.assertGreater(result["revealedHands"][0]["step"], result["standingHands"][0]["step"])
        self.assertGreater(result["revealedHands"][0]["bbox"]["h"], result["standingHands"][0]["bbox"]["h"])
        self.assertGreater(result["revealedHands"][1]["bbox"]["w"], result["standingHands"][1]["bbox"]["w"])

    def test_remote_hand_blocks_are_transform_outputs_not_raw_screen_rects(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function player(seat) {
              return {seat, hand_count: 17, hand: {}, melds: [], flowers: [], discards: []};
            }
            function roundRect(rect) {
              return {
                x: Math.round(rect.x * 1000) / 1000,
                y: Math.round(rect.y * 1000) / 1000,
                w: Math.round(rect.w * 1000) / 1000,
                h: Math.round(rect.h * 1000) / 1000,
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const remoteHands = table.blocks.filter((block) => block.type === 'hand' && block.mode === 'remote');
            const checks = remoteHands.map((block) => ({
              seat: block.seat,
              bbox: roundRect(block.bbox),
              transformed: roundRect(model.transformCanonicalRect(block.canonicalBBox, block.seat, table.config)),
              canonicalDifferentFromScreen: JSON.stringify(roundRect(block.canonicalBBox)) !== JSON.stringify(roundRect(block.bbox)),
            }));
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              checks,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual([item["seat"] for item in result["checks"]], [1, 2, 3])
        for item in result["checks"]:
            self.assertEqual(item["bbox"], item["transformed"])
            self.assertTrue(item["canonicalDifferentFromScreen"])

    def test_remote_hand_side_rails_use_configured_inset(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            const config = JSON.parse(JSON.stringify(model.DEFAULT_CONFIG));
            config.remoteHand.sideInset = 210;
            function player(seat) {
              return {seat, hand_count: 17, hand: {}, melds: [], flowers: [], discards: []};
            }
            function center(rect) {
              return {x: Math.round(rect.x + rect.w / 2), y: Math.round(rect.y + rect.h / 2)};
            }
            const table = model.createBattleTableModel(
              {players: [0, 1, 2, 3].map(player)},
              {config}
            );
            const right = table.blocks.find((block) => block.type === 'hand' && block.seat === 1);
            const left = table.blocks.find((block) => block.type === 'hand' && block.seat === 3);
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              rightCenter: center(right.bbox),
              leftCenter: center(left.bbox),
              tableWidth: table.config.table.width,
              sideInset: table.config.remoteHand.sideInset,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["rightCenter"]["x"], result["tableWidth"] - result["sideInset"])
        self.assertEqual(result["leftCenter"]["x"], result["sideInset"])
        self.assertEqual(result["rightCenter"]["y"], result["leftCenter"]["y"])

    def test_remote_hand_side_rails_use_flat_edge_width(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function player(seat) {
              return {seat, hand_count: 17, hand: {}, melds: [], flowers: [], discards: []};
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const right = table.blocks.find((block) => block.type === 'hand' && block.seat === 1);
            const top = table.blocks.find((block) => block.type === 'hand' && block.seat === 2);
            const left = table.blocks.find((block) => block.type === 'hand' && block.seat === 3);
            const cfg = table.config.remoteHand;
            const standingWidth = cfg.tileW + (17 - 1) * (cfg.tileW - cfg.overlap);
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              rightWidth: right.bbox.w,
              leftWidth: left.bbox.w,
              topHeight: top.bbox.h,
              tileH: cfg.tileH,
              standingWidth,
              rightStep: right.metrics.step,
              leftStep: left.metrics.step,
              topStep: top.metrics.step,
              expectedStandingWidth: cfg.tileW * 17,
              rightLean: right.metrics.projectionLean,
              leftLean: left.metrics.projectionLean,
              topLean: top.metrics.projectionLean,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertAlmostEqual(result["rightWidth"], result["tileH"], places=6)
        self.assertAlmostEqual(result["leftWidth"], result["tileH"], places=6)
        self.assertAlmostEqual(result["topHeight"], result["tileH"], places=6)
        self.assertEqual(result["standingWidth"], result["expectedStandingWidth"])
        self.assertEqual(result["rightStep"], 35)
        self.assertEqual(result["leftStep"], 35)
        self.assertEqual(result["topStep"], 35)
        self.assertEqual(result["rightLean"], 0)
        self.assertEqual(result["leftLean"], 0)
        self.assertEqual(result["topLean"], 0)

    def test_claimed_tiles_consume_real_horizontal_width(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            console.log(JSON.stringify({
              openGang: model.meldUnits({type: 'ming_gang', from: 1, tiles: ['1W', '1W', '1W', '1W']}),
              closedGang: model.meldUnits({type: 'an_gang', tiles: ['1W', '1W', '1W', '1W']}),
            }));
            """
        )
        self.assertGreater(result["openGang"], 4)
        self.assertLess(result["openGang"], 4.5)
        self.assertEqual(result["closedGang"], 4)

    def test_default_center_panel_is_large_and_still_clear_of_extreme_blocks(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                  meld('ming_gang', 2, 4),
                ],
                flowers: Array(11).fill('H1'),
                discards: Array(15).fill('1W'),
              };
            }
            const table = model.createBattleTableModel({players: [0, 1, 2, 3].map(player)});
            const center = table.blocks.find((block) => block.type === 'center');
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              center: center.bbox,
              overlapDiagnostics: table.diagnostics.filter((item) => (
                item.code === 'center-river-overlap'
                || item.code === 'center-public-overlap'
                || item.code === 'river-public-overlap'
                || item.code === 'public-public-overlap'
              )),
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["center"], {"x": 570, "y": 230, "w": 360, "h": 252})
        self.assertEqual(result["overlapDiagnostics"], [])

    def test_model_exports_required_element_blocks_for_renderer_and_qa(self) -> None:
        result = run_node(
            """
            const model = require('./static/battle_table_model.js');
            function meld(type, from, n) {
              return {type, from, tiles: Array(n).fill('1W')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                melds: [
                  meld('peng', 1, 3),
                  meld('chi', 2, 3),
                  meld('ming_gang', 3, 4),
                  meld('peng', 1, 3),
                ],
                flowers: Array(6).fill('H1'),
                discards: Array(12).fill('1W'),
              };
            }
            function contains(parent, child) {
              const eps = 0.001;
              return child.x + eps >= parent.x
                && child.y + eps >= parent.y
                && child.x + child.w <= parent.x + parent.w + eps
                && child.y + child.h <= parent.y + parent.h + eps;
            }
            const table = model.createBattleTableModel(
              {players: [0, 1, 2, 3].map(player)},
              {viewport: {width: 740, height: 360}}
            );
            const byType = {};
            for (const block of table.blocks) {
              byType[block.type] = (byType[block.type] || 0) + 1;
            }
            const publicBySeat = new Map(
              table.blocks
                .filter((block) => block.type === 'public')
                .map((block) => [block.seat, block])
            );
            const detailBlocks = table.blocks.filter((block) => block.type === 'flowers' || block.type === 'melds');
            const detailInsideParent = detailBlocks.every((block) => contains(publicBySeat.get(block.seat).bbox, block.bbox));
            console.log(JSON.stringify({
              ok: table.ok,
              diagnostics: table.diagnostics,
              byType,
              detailInsideParent,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["byType"]["frame"], 1)
        self.assertEqual(result["byType"]["field"], 1)
        self.assertEqual(result["byType"]["center"], 1)
        self.assertEqual(result["byType"]["centerLabel"], 4)
        self.assertNotIn("activeHandSafeArea", result["byType"])
        self.assertEqual(result["byType"]["public"], 4)
        self.assertEqual(result["byType"]["flowers"], 4)
        self.assertEqual(result["byType"]["melds"], 8)
        self.assertTrue(result["detailInsideParent"], result)


if __name__ == "__main__":
    unittest.main()
