from __future__ import annotations

import json
import subprocess
import sys
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


class BattleTableRendererTests(unittest.TestCase):
    def test_render_plan_contains_openriichi_style_element_blocks(self) -> None:
        result = run_node(
            """
            globalThis.BattleTableModel = require('./static/battle_table_model.js');
            const renderer = require('./static/battle_table_renderer.js');
            function meld(type, from, n) {
              return {type, from, tile: 'm1', tiles: Array(n).fill('m1')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                hand: seat === 0 ? {m1: 3, m2: 2, t1: 4, b1: 4, east: 4} : {},
                melds: [meld('peng', (seat + 1) % 4, 3), meld('ming_gang', (seat + 2) % 4, 4)],
                flowers: ['rh1', 'rh2', 'bh1'],
                visible_discards: Array(12).fill('t1'),
              };
            }
            const plan = renderer.createRenderPlan({
              phase: 'turn',
              players: [0, 1, 2, 3].map(player),
              history: [{event: 'discard', seat: 1, tile: 't1'}],
            });
            const counts = plan.commands.reduce((acc, command) => {
              acc[command.type] = (acc[command.type] || 0) + 1;
              return acc;
            }, {});
            console.log(JSON.stringify({
              ok: plan.ok,
              diagnostics: plan.diagnostics,
              counts,
              handSeats: plan.commands.filter((command) => command.type === 'hand').map((command) => command.seat),
              handBackSprites: plan.commands.filter((command) => command.type === 'hand').map((command) => command.backSprite),
              handLabelsReady: plan.commands
                .filter((command) => command.type === 'hand')
                .every((command) => command.labels && command.labels.east === '东'),
              riverModes: plan.commands.filter((command) => command.type === 'river').map((command) => command.mode),
              publicModes: plan.commands.filter((command) => command.type === 'public').map((command) => command.mode),
              hitBoxCounts: plan.hitBoxes.reduce((acc, hitBox) => {
                acc[hitBox.type] = (acc[hitBox.type] || 0) + 1;
                return acc;
              }, {}),
              claimedPublicHitBoxes: plan.hitBoxes.filter((hitBox) => hitBox.type === 'publicTile' && hitBox.claimed).length,
              allHitBoxesHavePositiveRects: plan.hitBoxes.every((hitBox) => hitBox.rect.w > 0 && hitBox.rect.h > 0),
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["counts"]["table"], 1)
        self.assertEqual(result["counts"]["center"], 1)
        self.assertEqual(result["counts"]["hand"], 3)
        self.assertEqual(result["counts"]["river"], 4)
        self.assertEqual(result["counts"]["public"], 4)
        self.assertEqual(result["handSeats"], [1, 2, 3])
        self.assertEqual(
            result["handBackSprites"],
            ["tile_back_standing_right", "tile_back_standing_top", "tile_back_standing_left"],
        )
        self.assertTrue(result["handLabelsReady"])
        self.assertEqual(result["riverModes"], ["normal", "normal", "normal", "normal"])
        self.assertEqual(result["publicModes"], ["normal", "normal", "normal", "normal"])
        self.assertEqual(result["hitBoxCounts"], {"riverTile": 48, "publicTile": 40, "centerSeat": 4})
        self.assertEqual(result["claimedPublicHitBoxes"], 8)
        self.assertTrue(result["allHitBoxesHavePositiveRects"])

    def test_render_plan_keeps_dense_and_overflow_modes_from_table_model(self) -> None:
        result = run_node(
            """
            globalThis.BattleTableModel = require('./static/battle_table_model.js');
            const renderer = require('./static/battle_table_renderer.js');
            function meld(type, from, n) {
              return {type, from, tile: 'm1', tiles: Array(n).fill('m1')};
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
                flowers: Array(10).fill('rh1'),
                visible_discards: Array(16).fill('b9'),
              };
            }
            const plan = renderer.createRenderPlan({phase: 'turn', players: [0, 1, 2, 3].map(player)});
            console.log(JSON.stringify({
              ok: plan.ok,
              diagnostics: plan.diagnostics,
              riverModes: plan.commands.filter((command) => command.type === 'river').map((command) => ({
                mode: command.mode,
                overflowCount: command.overflowCount,
                tiles: command.tiles.length,
              })),
              publicModes: plan.commands.filter((command) => command.type === 'public').map((command) => command.mode),
              publicFlowerLayouts: plan.commands.filter((command) => command.type === 'public').map((command) => command.metrics.flowerLayout),
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(
            result["riverModes"],
            [
                {"mode": "dense", "overflowCount": 1, "tiles": 15},
                {"mode": "dense", "overflowCount": 1, "tiles": 15},
                {"mode": "dense", "overflowCount": 1, "tiles": 15},
                {"mode": "dense", "overflowCount": 1, "tiles": 15},
            ],
        )
        self.assertEqual(result["publicModes"], ["overflow", "overflow", "overflow", "overflow"])
        self.assertEqual(
            result["publicFlowerLayouts"],
            [
                {
                    "count": 10,
                    "folded": True,
                    "visibleCount": 4,
                    "hiddenCount": 6,
                    "badgeUnits": 2.2,
                    "rowUnits": 6.2,
                },
                {
                    "count": 10,
                    "folded": True,
                    "visibleCount": 4,
                    "hiddenCount": 6,
                    "badgeUnits": 2.2,
                    "rowUnits": 6.2,
                },
                {
                    "count": 10,
                    "folded": True,
                    "visibleCount": 4,
                    "hiddenCount": 6,
                    "badgeUnits": 2.2,
                    "rowUnits": 6.2,
                },
                {
                    "count": 10,
                    "folded": True,
                    "visibleCount": 4,
                    "hiddenCount": 6,
                    "badgeUnits": 2.2,
                    "rowUnits": 6.2,
                },
            ],
        )

    def test_round_over_render_plan_spreads_remote_revealed_hands(self) -> None:
        result = run_node(
            """
            globalThis.BattleTableModel = require('./static/battle_table_model.js');
            const renderer = require('./static/battle_table_renderer.js');
            function player(seat, revealed) {
              return {
                seat,
                hand_count: 17,
                hand: revealed && seat !== 0 ? {m1: 4, m2: 4, t1: 4, b1: 4, east: 1} : {},
                melds: [],
                flowers: [],
                visible_discards: [],
              };
            }
            const standingPlan = renderer.createRenderPlan({phase: 'turn', players: [0, 1, 2, 3].map((seat) => player(seat, false))});
            const revealedPlan = renderer.createRenderPlan({phase: 'round_over', players: [0, 1, 2, 3].map((seat) => player(seat, true))});
            const standing = standingPlan.commands.filter((command) => command.type === 'hand');
            const revealed = revealedPlan.commands.filter((command) => command.type === 'hand');
            console.log(JSON.stringify({
              standingOk: standingPlan.ok,
              revealedOk: revealedPlan.ok,
              standingDiagnostics: standingPlan.diagnostics,
              revealedDiagnostics: revealedPlan.diagnostics,
              standing: standing.map((command) => ({seat: command.seat, mode: command.mode, tileStep: command.tileStep, tileCount: command.tileCount, bbox: command.bbox, projectionLean: command.projectionLean})),
              revealed: revealed.map((command) => ({seat: command.seat, mode: command.mode, tileStep: command.tileStep, tileCount: command.tileCount, tiles: command.tiles.length, bbox: command.bbox})),
            }));
            """
        )
        self.assertTrue(result["standingOk"], result["standingDiagnostics"])
        self.assertTrue(result["revealedOk"], result["revealedDiagnostics"])
        self.assertEqual([hand["mode"] for hand in result["standing"]], ["standing", "standing", "standing"])
        self.assertEqual([hand["mode"] for hand in result["revealed"]], ["revealed", "revealed", "revealed"])
        self.assertEqual(result["standing"][0]["projectionLean"], 0)
        self.assertEqual(result["standing"][1]["projectionLean"], 0)
        self.assertEqual(result["standing"][2]["projectionLean"], 0)
        self.assertTrue(all(hand["tileCount"] == hand["tiles"] == 17 for hand in result["revealed"]))
        self.assertGreater(result["revealed"][0]["tileStep"], result["standing"][0]["tileStep"])
        self.assertGreater(result["revealed"][0]["bbox"]["h"], result["standing"][0]["bbox"]["h"])
        self.assertGreater(result["revealed"][1]["bbox"]["w"], result["standing"][1]["bbox"]["w"])

    def test_render_plan_reuses_model_public_row_splits(self) -> None:
        result = run_node(
            """
            globalThis.BattleTableModel = require('./static/battle_table_model.js');
            const renderer = require('./static/battle_table_renderer.js');
            function meld(type, from, n) {
              return {type, from, tile: 'm1', tiles: Array(n).fill('m1')};
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
                flowers: Array(6).fill('rh1'),
                visible_discards: Array(12).fill('t1'),
              };
            }
            const plan = renderer.createRenderPlan({phase: 'turn', players: [0, 1, 2, 3].map(player)});
            const publicCommand = plan.commands.find((command) => command.type === 'public' && command.seat === 0);
            const publicBlock = plan.model.blocks.find((block) => block.type === 'public' && block.seat === 0);
            const rowBlocks = {
              flowers: publicCommand.rowBlocks.flowers,
              main: publicCommand.rowBlocks.main,
              overflow: publicCommand.rowBlocks.overflow,
            };
            const modelRowBlocks = {
              flowers: plan.model.blocks.find((block) => block.type === 'flowers' && block.seat === 0),
              main: plan.model.blocks.find((block) => block.type === 'melds' && block.row === 'main' && block.seat === 0),
              overflow: plan.model.blocks.find((block) => block.type === 'melds' && block.row === 'overflow' && block.seat === 0),
            };
            function summary(block) {
              return block && {
                type: block.type,
                seat: block.seat,
                row: block.row || '',
                parent: block.parent,
                localBBox: block.localBBox,
              };
            }
            console.log(JSON.stringify({
              ok: plan.ok,
              diagnostics: plan.diagnostics,
              commandRows: {
                main: publicCommand.meldRows.main.length,
                overflow: publicCommand.meldRows.overflow.length,
              },
              metricRows: {
                main: publicBlock.metrics.rows.main.length,
                overflow: publicBlock.metrics.rows.overflow.length,
              },
              rowBlocks: {
                flowers: summary(rowBlocks.flowers),
                main: summary(rowBlocks.main),
                overflow: summary(rowBlocks.overflow),
              },
              modelRowBlocks: {
                flowers: summary(modelRowBlocks.flowers),
                main: summary(modelRowBlocks.main),
                overflow: summary(modelRowBlocks.overflow),
              },
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertEqual(result["commandRows"], {"main": 2, "overflow": 2})
        self.assertEqual(result["commandRows"], result["metricRows"])
        self.assertEqual(result["rowBlocks"], result["modelRowBlocks"])
        self.assertEqual(result["rowBlocks"]["flowers"]["type"], "flowers")
        self.assertEqual(result["rowBlocks"]["main"]["row"], "main")
        self.assertEqual(result["rowBlocks"]["overflow"]["row"], "overflow")
        self.assertIn("x", result["rowBlocks"]["flowers"]["localBBox"])

    def test_claimed_meld_tile_order_matches_wenling_source_mapping(self) -> None:
        result = run_node(
            """
            const renderer = require('./static/battle_table_renderer.js');
            const base = {type: 'peng', tile: 'm1', tiles: ['m1', 'm1', 'm1']};
            const kong = {type: 'an_gang', tile: 'm8', tiles: ['m8', 'm8', 'm8', 'm8']};
            const cases = [
              renderer.meldDisplayEntries({...base, from: 3}, 0).map((entry) => entry.claimed),
              renderer.meldDisplayEntries({...base, from: 2}, 0).map((entry) => entry.claimed),
              renderer.meldDisplayEntries({...base, from: 1}, 0).map((entry) => entry.claimed),
            ];
            const concealedKong = renderer.meldDisplayEntries(kong, 0);
            console.log(JSON.stringify({cases, concealedKong}));
            """
        )
        self.assertEqual(
            result["cases"],
            [
                [True, False, False],
                [False, True, False],
                [False, False, True],
            ],
        )
        self.assertEqual(
            result["concealedKong"],
            [
                {"code": "*", "claimed": False, "direction": None},
                {"code": "m8", "claimed": False, "direction": None},
                {"code": "m8", "claimed": False, "direction": None},
                {"code": "*", "claimed": False, "direction": None},
            ],
        )

    def test_center_hud_contains_wenling_room_and_seat_fields(self) -> None:
        result = run_node(
            """
            globalThis.BattleTableModel = require('./static/battle_table_model.js');
            const renderer = require('./static/battle_table_renderer.js');
            const players = [0, 1, 2, 3].map((seat) => ({
              seat,
              name: seat === 0 ? '温岭玩家超长名字' : `AI${seat}`,
              chips: 25000 + seat * 100,
              hand_count: 17,
              melds: [],
              flowers: [],
              visible_discards: [],
              claim_warning: seat === 2 ? {reason: '连续2张'} : null,
            }));
            const plan = renderer.createRenderPlan({
              phase: 'turn',
              players,
              current_player: 1,
              dealer: 0,
              round_no: 3,
              room_round_count: 8,
              de_indicator: 'm1',
              wall_to_draw_game: 54,
              bao_liabilities: [{seat: 3, active: true, reason: '三连包牌'}],
            });
            const center = plan.commands.find((command) => command.type === 'center');
            const modelLabels = plan.model.blocks
              .filter((block) => block.type === 'centerLabel')
              .sort((left, right) => left.seat - right.seat);
            const commandLabels = Object.values(center.labelBlocks || {})
              .sort((left, right) => left.seat - right.seat);
            const summarizeLabel = (block) => ({
              type: block.type,
              seat: block.seat,
              position: block.position,
              bbox: block.bbox,
              localBBox: block.localBBox,
            });
            console.log(JSON.stringify({
              hasHud: Boolean(center && center.hud),
              roomRound: center.hud.roomRound,
              wallRemaining: center.hud.wallRemaining,
              indicatorTile: center.hud.indicatorTile,
              dealer: center.hud.seats.find((seat) => seat.seat === 0).dealer,
              active: center.hud.seats.find((seat) => seat.seat === 1).active,
              warning: center.hud.seats.find((seat) => seat.seat === 2).warning,
              bao: center.hud.seats.find((seat) => seat.seat === 3).bao,
              labelCount: commandLabels.length,
              labelPositions: commandLabels.map((block) => block.position),
              labelBlocks: commandLabels.map(summarizeLabel),
              modelLabelBlocks: modelLabels.map(summarizeLabel),
            }));
            """
        )
        self.assertTrue(result["hasHud"])
        self.assertEqual(result["roomRound"], 8)
        self.assertEqual(result["wallRemaining"], 54)
        self.assertEqual(result["indicatorTile"], "m1")
        self.assertTrue(result["dealer"])
        self.assertTrue(result["active"])
        self.assertTrue(result["warning"])
        self.assertTrue(result["bao"])
        self.assertEqual(result["labelCount"], 4)
        self.assertEqual(result["labelPositions"], ["bottom", "right", "top", "left"])
        self.assertEqual(result["labelBlocks"], result["modelLabelBlocks"])
        self.assertIn("x", result["labelBlocks"][0]["localBBox"])

    def test_render_reports_performance_metrics_and_canvas_draw_calls(self) -> None:
        result = run_node(
            """
            globalThis.BattleTableModel = require('./static/battle_table_model.js');
            const renderer = require('./static/battle_table_renderer.js');
            const noop = () => {};
            const gradient = {addColorStop: noop};
            const ctx = new Proxy({}, {
              get(target, prop) {
                if (prop === 'createLinearGradient' || prop === 'createRadialGradient') return () => gradient;
                if (prop === 'createPattern') return () => ({});
                if (prop === 'measureText') return (text) => ({width: String(text || '').length * 8});
                if (!(prop in target)) target[prop] = noop;
                return target[prop];
              },
              set(target, prop, value) {
                target[prop] = value;
                return true;
              },
            });
            const canvas = {
              width: 0,
              height: 0,
              dataset: {},
              parentElement: {clientWidth: 844, clientHeight: 390},
              getBoundingClientRect: () => ({width: 844, height: 390}),
              getContext: () => ctx,
            };
            function meld(type, from, n) {
              return {type, from, tile: 'm1', tiles: Array(n).fill('m1')};
            }
            function player(seat) {
              return {
                seat,
                hand_count: 17,
                hand: seat === 0 ? {m1: 3, m2: 2, t1: 4, b1: 4, east: 4} : {},
                melds: [meld('peng', (seat + 1) % 4, 3), meld('ming_gang', (seat + 2) % 4, 4)],
                flowers: ['rh1', 'rh2', 'bh1'],
                visible_discards: Array(12).fill('t1'),
              };
            }
            renderer.__setAtlasManifestForTest({
              world_style: {
                version: 'test-world-style',
              },
              poses: {
                remote_hand_wall: {
                  material_overlay: {
                    top_highlight_alpha: 0.34,
                    seam_alpha: 0.22,
                    side_shade_alpha: 0.32,
                    bottom_shade_alpha: 0.26,
                    cap_alpha: 0.38,
                  },
                },
                river_tile: {
                  directional_sprite_prefixes: {
                    bottom: 'tile_river_bottom_',
                    top: 'tile_river_top_',
                    right: 'tile_river_right_',
                    left: 'tile_river_left_',
                  },
                  depth_style: {
                    depth_ratio: 0.092,
                    edge_ratio: 0.075,
                    highlight_alpha: 0.22,
                    shadow_alpha: 0.24,
                  },
                },
                public_tile: {
                  directional_sprite_prefixes: {
                    bottom: 'tile_public_bottom_',
                    top: 'tile_public_top_',
                    right: 'tile_public_right_',
                    left: 'tile_public_left_',
                  },
                  depth_style: {
                    depth_ratio: 0.108,
                    edge_ratio: 0.082,
                    highlight_alpha: 0.25,
                    shadow_alpha: 0.28,
                  },
                  claimed_depth_style: {
                    depth_ratio: 0.078,
                    edge_ratio: 0.058,
                    highlight_alpha: 0.2,
                    shadow_alpha: 0.24,
                  },
                },
              },
              sprites: {},
            });
            const plan = renderer.render(canvas, {
              phase: 'turn',
              players: [0, 1, 2, 3].map(player),
              history: [{event: 'discard', seat: 1, tile: 't1'}],
            });
            const atlasStatus = renderer.atlasStatus();
            console.log(JSON.stringify({
              ok: plan.ok,
              diagnostics: plan.diagnostics,
              performance: plan.performance,
              atlasStatus,
              dataset: {
                renderMs: canvas.dataset.renderMs,
                drawMs: canvas.dataset.drawMs,
                firstFrameMs: canvas.dataset.firstFrameMs,
                commandCount: canvas.dataset.commandCount,
                tableHitBoxCount: canvas.dataset.tableHitBoxCount,
                canvasDrawCalls: canvas.dataset.canvasDrawCalls,
                tileDraws: canvas.dataset.tileDraws,
              },
              canvasHitBoxes: canvas.__battleTableHitBoxes.length,
              globalHitBoxes: globalThis.tableHitBoxes.length,
            }));
            """
        )
        self.assertTrue(result["ok"], result["diagnostics"])
        self.assertGreater(result["performance"]["commandCount"], 0)
        self.assertGreater(result["performance"]["canvasDrawCalls"], 0)
        self.assertGreater(result["performance"]["tileDraws"], 0)
        self.assertEqual(result["performance"]["tilePoseDepthDraws"], 0)
        self.assertEqual(result["performance"]["tileContactShadowDraws"], 0)
        self.assertEqual(
            result["atlasStatus"]["poseDepthStyles"],
            {"river": True, "public": True, "claimed": True},
        )
        self.assertEqual(result["atlasStatus"]["poseSpriteStyles"], {"river": True, "public": True})
        self.assertEqual(result["atlasStatus"]["worldStyleVersion"], "test-world-style")
        self.assertEqual(result["atlasStatus"]["poseMaterialStyles"], {"remoteHandWall": True})
        self.assertIn("totalMs", result["performance"])
        self.assertIn("drawMs", result["performance"])
        self.assertIn("firstFrameMs", result["performance"])
        self.assertEqual(result["dataset"]["commandCount"], str(result["performance"]["commandCount"]))
        self.assertEqual(result["dataset"]["tableHitBoxCount"], str(result["performance"]["hitBoxCount"]))
        self.assertEqual(result["canvasHitBoxes"], result["performance"]["hitBoxCount"])
        self.assertEqual(result["globalHitBoxes"], result["performance"]["hitBoxCount"])
        self.assertEqual(result["dataset"]["canvasDrawCalls"], str(result["performance"]["canvasDrawCalls"]))
        self.assertEqual(result["dataset"]["tileDraws"], str(result["performance"]["tileDraws"]))

    @unittest.skip("deprecated UI QA tooling is no longer packaged or maintained")
    def test_qa_scene_matrix_covers_tid_extreme_cases(self) -> None:
        result = run_node(
            """
            global.window = globalThis;
            global.location = {search: ''};
            global.addEventListener = () => {};
            require('./static/battle_ui_qa.js');
            const scenes = globalThis.BattleUiQa.SCENES;
            globalThis.BattleTableModel = require('./static/battle_table_model.js');
            const renderer = require('./static/battle_table_renderer.js');
            const summarize = (name) => {
              const scene = scenes[name];
              const state = scene.makeState();
              const players = state.players || [];
              const plan = renderer.createRenderPlan(state, {tileNames: {
                east: '东', south: '南', west: '西', north: '北',
                zhong: '中', fa: '发', bai: '白',
              }});
              return {
                exists: Boolean(scene),
                phase: state.phase || null,
                activeHandCount: scene.activeHandTiles?.length || 0,
                winnerAnimation: scene.winnerAnimation || null,
                hitBoxDiagnostics: globalThis.BattleUiQa.diagnoseHitBoxes(plan),
                publicBackTiles: plan.hitBoxes.filter((hitBox) => hitBox.type === 'publicTile' && hitBox.tile === '*').length,
                claimedPublicTiles: plan.hitBoxes.filter((hitBox) => hitBox.type === 'publicTile' && hitBox.claimed).length,
                discardCounts: players.map((player) => player.visible_discards?.length || 0),
                meldCounts: players.map((player) => player.melds?.length || 0),
                flowerCounts: players.map((player) => player.flowers?.length || 0),
                revealedHandCounts: players.map((player) => Object.values(player.hand || {})
                  .reduce((sum, value) => sum + Number(value || 0), 0)),
              };
            };
            const required = [
              'initial_dark_wall',
              'river_12',
              'river_15_dense',
              'public_4_melds_6_flowers',
              'public_5_melds_4_flowers',
              'public_concealed_kong',
              'flowers_11_overflow',
              'revealed_round_over',
              'active_hand_17',
              'public_active_hand_extreme',
              'hu_animation_normal',
              'hu_animation_luck95',
            ];
            console.log(JSON.stringify({
              keys: Object.keys(scenes),
              required,
              summary: Object.fromEntries(required.map((name) => [name, summarize(name)])),
            }));
            """
        )
        self.assertEqual(set(result["required"]) - set(result["keys"]), set())
        for scene_name in result["required"]:
            self.assertEqual(result["summary"][scene_name]["hitBoxDiagnostics"], [])
        self.assertEqual(result["summary"]["river_12"]["discardCounts"], [12, 12, 12, 12])
        self.assertEqual(result["summary"]["river_15_dense"]["discardCounts"], [15, 15, 15, 15])
        self.assertEqual(result["summary"]["public_4_melds_6_flowers"]["meldCounts"], [4, 4, 4, 4])
        self.assertEqual(result["summary"]["public_4_melds_6_flowers"]["flowerCounts"], [6, 6, 6, 6])
        self.assertEqual(result["summary"]["public_5_melds_4_flowers"]["meldCounts"], [5, 5, 5, 5])
        self.assertEqual(result["summary"]["public_5_melds_4_flowers"]["flowerCounts"], [4, 4, 4, 4])
        self.assertEqual(result["summary"]["public_concealed_kong"]["meldCounts"], [3, 3, 3, 3])
        self.assertEqual(result["summary"]["public_concealed_kong"]["flowerCounts"], [2, 2, 2, 2])
        self.assertEqual(result["summary"]["public_concealed_kong"]["publicBackTiles"], 8)
        self.assertEqual(result["summary"]["public_concealed_kong"]["claimedPublicTiles"], 8)
        self.assertEqual(result["summary"]["flowers_11_overflow"]["flowerCounts"], [11, 11, 11, 11])
        self.assertEqual(result["summary"]["active_hand_17"]["activeHandCount"], 17)
        self.assertEqual(result["summary"]["public_active_hand_extreme"]["activeHandCount"], 17)
        self.assertEqual(result["summary"]["public_active_hand_extreme"]["meldCounts"], [5, 5, 5, 5])
        self.assertEqual(result["summary"]["public_active_hand_extreme"]["flowerCounts"], [11, 11, 11, 11])
        self.assertEqual(result["summary"]["revealed_round_over"]["phase"], "round_over")
        self.assertGreater(min(result["summary"]["revealed_round_over"]["revealedHandCounts"]), 0)
        self.assertEqual(
            result["summary"]["hu_animation_normal"]["winnerAnimation"],
            {"seat": 0, "kind": "normal"},
        )
        self.assertEqual(
            result["summary"]["hu_animation_luck95"]["winnerAnimation"],
            {"seat": 2, "kind": "exceptional-luck"},
        )

    @unittest.skip("deprecated UI QA tooling is no longer packaged or maintained")
    def test_visual_qa_runner_exposes_required_tid_matrix(self) -> None:
        completed = subprocess.run(
            ["node", "tools/battle_ui_qa/run_visual_qa.js", "--list-json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            encoding="utf-8",
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(
            [size["value"] for size in result["sizes"]],
            ["1280x720", "844x390", "740x360"],
        )
        scene_names = {scene["name"] for scene in result["scenes"]}
        for required_scene in [
            "initial_dark_wall",
            "river_12",
            "river_15_dense",
            "public_4_melds_6_flowers",
            "public_5_melds_4_flowers",
            "public_concealed_kong",
            "flowers_11_overflow",
            "revealed_round_over",
            "hu_animation_normal",
            "hu_animation_luck95",
        ]:
            self.assertIn(required_scene, scene_names)

    @unittest.skip("deprecated UI QA tooling is no longer packaged or maintained")
    def test_battle_page_qa_runner_exposes_real_page_checks(self) -> None:
        completed = subprocess.run(
            ["node", "tools/battle_ui_qa/run_battle_page_qa.js", "--list-json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            encoding="utf-8",
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertFalse(result["requiresAccountOrToken"])
        self.assertTrue(result["supportsAutoAccount"])
        self.assertTrue(result["supportsQaAccount"])
        self.assertTrue(result["autoAccountDefault"])
        self.assertFalse(result["ensureAccountDefault"])
        self.assertEqual(result["qaAccount"], "")
        self.assertEqual(result["playwrightPackageFallback"], "playwright-core")
        self.assertEqual(result["availableAccountsEndpoint"], "/api/battle/available-accounts")
        self.assertEqual(
            [size["value"] for size in result["sizes"]],
            ["1280x720", "844x390", "740x360"],
        )
        checks = {(item["renderer"], item["expectedGeometry"]): item["sizes"] for item in result["rendererChecks"]}
        self.assertEqual(checks[("canvas", "v7")], ["1280x720", "844x390", "740x360"])
        self.assertEqual(checks[("dom", "v6")], ["844x390"])

    @unittest.skip("deprecated UI QA tooling is no longer packaged or maintained")
    def test_battle_page_qa_runner_supports_dedicated_qa_account(self) -> None:
        completed = subprocess.run(
            [
                "node",
                "tools/battle_ui_qa/run_battle_page_qa.js",
                "--list-json",
                "--qa-account=__qa_smoke__",
                "--ensure-account",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            encoding="utf-8",
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["supportsQaAccount"])
        self.assertEqual(result["qaAccount"], "__qa_smoke__")
        self.assertTrue(result["ensureAccountDefault"])

    @unittest.skip("deprecated UI QA tooling is no longer packaged or maintained")
    def test_isolated_battle_page_qa_wrapper_is_available(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/battle_ui_qa/run_isolated_battle_page_qa.py", "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            encoding="utf-8",
            text=True,
        )
        self.assertIn("isolated Wenling LAN host", completed.stdout)
        self.assertIn("--keep-data", completed.stdout)


if __name__ == "__main__":
    unittest.main()
