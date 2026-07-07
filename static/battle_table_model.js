/* Battle table geometry model v7.
   This file is intentionally render-agnostic: it converts battle state into
   seat/block geometry, density modes and bbox diagnostics. Browser rendering
   layers should consume this model instead of re-encoding seat-specific magic
   numbers in CSS. */

(function initBattleTableModel(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.BattleTableModel = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function battleTableModelFactory() {
  const SEAT_ANGLES = [0, -90, 180, 90];
  const DEFAULT_CONFIG = Object.freeze({
    table: {
      width: 1500,
      height: 780,
      center: { x: 750, y: 340 },
      fieldBBox: { x: 58, y: 0, w: 1384, h: 684 },
    },
    center: { w: 360, h: 252 },
    activeHand: {
      maxTiles: 17,
      tileW: 62,
      tileH: 88,
      gap: 2,
      drawGap: 14,
      y: 682,
      desktopBaseTileW: 88,
      mobileBaseTileW: 102,
      desktopMinTileW: 58,
      mobileMinTileW: 52,
      desktopMinScale: 0.7,
      mobileMinScale: 0.72,
      desktopDesiredGap: 1,
      mobileDesiredGap: 2,
      maxOverlapRatio: 0,
      desktopEdgeInset: 18,
      mobileEdgeInset: 16,
    },
    remoteHand: {
      maxTiles: 17,
      tileW: 35,
      tileH: 54,
      overlap: 0,
      revealedGap: 1,
      y: 70,
      sideInset: 88,
      sideProjectionLean: 0,
    },
    river: {
      tileW: 41.472,
      tileH: 58.752,
      gap: 3.456,
      cols: 6,
      normalLimit: 12,
      denseLimit: 15,
      yGapFromCenter: 14,
    },
    publicArea: {
      tileW: 46.08,
      tileH: 64.8,
      gap: 2.88,
      rowGap: 5.76,
      rowUnitLimit: 10.45,
      maxMeldsPerMainRow: 2,
      overflowMeldsPerMainRow: 3,
      normalTotalLimit: 20,
      compactTotalLimit: 26,
      compactScale: 0.9,
      overflowScale: 0.78,
      flowerFoldThreshold: 9,
      flowerFoldVisible: 4,
      flowerBadgeUnits: 2.2,
      safeLeft: 330,
      y: 460,
      topX: 1036,
      topY: 104,
      sideInset: 125,
      sideY: 284,
    },
    layoutBoxes: [
      { type: "field", row: "fixed", x: 58, y: 0, w: 1384, h: 684, innerAlign: "start", innerFlow: "forward" },
      { type: "center", row: "fixed", x: 570, y: 230, w: 360, h: 252, innerAlign: "start", innerFlow: "forward" },
      { type: "centerLabel", seat: 0, row: "bottom", x: 686, y: 400, w: 128, h: 43, innerAlign: "start", innerFlow: "forward" },
      { type: "centerLabel", seat: 1, row: "right", x: 794, y: 318, w: 128, h: 43, innerAlign: "start", innerFlow: "forward" },
      { type: "centerLabel", seat: 2, row: "top", x: 686, y: 237, w: 128, h: 43, innerAlign: "start", innerFlow: "forward" },
      { type: "centerLabel", seat: 3, row: "left", x: 578, y: 318, w: 128, h: 43, innerAlign: "start", innerFlow: "forward" },
      { type: "hand", seat: 0, row: "active", x: 207, y: 682, w: 1086, h: 88, innerAlign: "center", innerFlow: "forward" },
      { type: "hand", seat: 1, row: "remote", x: 1387, y: 43, w: 54, h: 595, innerAlign: "center", innerFlow: "forward" },
      { type: "hand", seat: 2, row: "remote", x: 453, y: 0, w: 595, h: 54, innerAlign: "center", innerFlow: "forward" },
      { type: "hand", seat: 3, row: "remote", x: 59, y: 43, w: 54, h: 595, innerAlign: "center", innerFlow: "forward" },
      { type: "river", seat: 0, row: "dense", x: 550, y: 500, w: 400, h: 175, innerAlign: "start", innerFlow: "forward" },
      { type: "river", seat: 1, row: "dense", x: 960, y: 245, w: 205, h: 295, innerAlign: "start", innerFlow: "forward" },
      { type: "river", seat: 2, row: "dense", x: 545, y: 110, w: 420, h: 100, innerAlign: "start", innerFlow: "forward" },
      { type: "river", seat: 3, row: "dense", x: 300, y: 150, w: 245, h: 295, innerAlign: "start", innerFlow: "forward" },
      { type: "public", seat: 0, row: "overflow", x: 135, y: 455, w: 410, h: 165, innerAlign: "start", innerFlow: "forward" },
      { type: "public", seat: 1, row: "overflow", x: 1195, y: 262, w: 186, h: 416, innerAlign: "start", innerFlow: "forward" },
      { type: "public", seat: 2, row: "overflow", x: 970, y: 56, w: 360, h: 185, innerAlign: "start", innerFlow: "forward" },
      { type: "public", seat: 3, row: "overflow", x: 125, y: 50, w: 170, h: 390, innerAlign: "start", innerFlow: "forward" },
      { type: "flowers", seat: 0, row: "overflow", x: 145, y: 570, w: 236, h: 50, innerAlign: "start", innerFlow: "forward" },
      { type: "flowers", seat: 1, row: "overflow", x: 1320, y: 395, w: 50, h: 236, innerAlign: "start", innerFlow: "forward" },
      { type: "flowers", seat: 2, row: "overflow", x: 1080, y: 65, w: 236, h: 50, innerAlign: "start", innerFlow: "forward" },
      { type: "flowers", seat: 3, row: "overflow", x: 130, y: 65, w: 50, h: 236, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 0, row: "main", x: 145, y: 515, w: 390, h: 50, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 0, row: "overflow", x: 145, y: 460, w: 258, h: 50, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 1, row: "main", x: 1265, y: 280, w: 50, h: 350, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 1, row: "overflow", x: 1210, y: 375, w: 50, h: 258, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 2, row: "main", x: 1025, y: 119, w: 290, h: 55, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 2, row: "overflow", x: 1055, y: 180, w: 258, h: 50, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 3, row: "main", x: 180, y: 65, w: 50, h: 360, innerAlign: "start", innerFlow: "forward" },
      { type: "melds", seat: 3, row: "overflow", x: 235, y: 60, w: 50, h: 258, innerAlign: "start", innerFlow: "forward" },
    ],
  });

  function cloneConfig(config) {
    return JSON.parse(JSON.stringify(config || DEFAULT_CONFIG));
  }

  function num(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function rect(x, y, w, h) {
    return { x, y, w, h };
  }

  function rectCenter(r) {
    return { x: r.x + r.w / 2, y: r.y + r.h / 2 };
  }

  function rectFromCenter(cx, cy, w, h) {
    return rect(cx - w / 2, cy - h / 2, w, h);
  }

  function layoutRect(box) {
    if (!box) return null;
    return rect(num(box.x, 0), num(box.y, 0), num(box.w, 0), num(box.h, 0));
  }

  function layoutRecord(config, type, seat = undefined, row = undefined) {
    const boxes = Array.isArray(config?.layoutBoxes) ? config.layoutBoxes : [];
    const typed = boxes.filter((box) => box?.type === type);
    const seatFiltered = seat === undefined
      ? typed
      : typed.filter((box) => Number(box?.seat) === Number(seat));
    if (row !== undefined) {
      const exact = seatFiltered.find((box) => String(box?.row || "") === String(row));
      if (exact) return exact;
    }
    if (seat !== undefined) {
      const bySeat = seatFiltered[0];
      if (bySeat) return bySeat;
    }
    const generic = typed.find((box) => box?.seat === undefined || box?.seat === null) || typed[0];
    return generic || null;
  }

  function exactLayoutRecord(config, type, seat = undefined, row = undefined) {
    const boxes = Array.isArray(config?.layoutBoxes) ? config.layoutBoxes : [];
    return boxes.find((box) => (
      box?.type === type
      && (seat === undefined || Number(box?.seat) === Number(seat))
      && (row === undefined || String(box?.row || "") === String(row))
    )) || null;
  }

  function layoutBox(config, type, seat = undefined, row = undefined) {
    return layoutRect(layoutRecord(config, type, seat, row));
  }

  function defaultInnerAlign(type) {
    if (type === "hand") return "center";
    return "start";
  }

  function normalizeInnerAlign(value, type) {
    const normalized = String(value || "").trim().toLowerCase();
    if (normalized === "start" || normalized === "center" || normalized === "end") return normalized;
    return defaultInnerAlign(type);
  }

  function normalizeInnerFlow(value) {
    const normalized = String(value || "").trim().toLowerCase();
    if (normalized === "reverse" || normalized === "backward" || normalized === "right-to-left" || normalized === "bottom-to-top") {
      return "reverse";
    }
    return "forward";
  }

  function layoutOptions(box, type) {
    return {
      innerAlign: normalizeInnerAlign(box?.innerAlign ?? box?.contentAlign ?? box?.align, type),
      innerFlow: normalizeInnerFlow(box?.innerFlow ?? box?.contentFlow ?? box?.flow),
    };
  }

  function rectPairFromScreen(screenBBox, seat, config) {
    const canonicalBBox = inverseTransformRect(screenBBox, seat, config);
    return {
      canonicalBBox,
      bbox: transformCanonicalRect(canonicalBBox, seat, config),
    };
  }

  function localSizeForSeat(screenBBox, seat) {
    const vertical = Number(seat) === 1 || Number(seat) === 3;
    return vertical
      ? { w: screenBBox.h, h: screenBBox.w }
      : { w: screenBBox.w, h: screenBBox.h };
  }

  function fitLineMetricsToBox(screenBBox, seat, count, baseTileW, baseTileH, baseStep) {
    const local = localSizeForSeat(screenBBox, seat);
    const tileCount = Math.max(1, num(count, 1));
    const contentW = baseTileW + Math.max(0, tileCount - 1) * baseStep;
    const contentH = baseTileH;
    const fitScale = Math.min(
      1,
      local.w > 0 ? local.w / Math.max(1, contentW) : 1,
      local.h > 0 ? local.h / Math.max(1, contentH) : 1
    );
    return {
      tileW: baseTileW * fitScale,
      tileH: baseTileH * fitScale,
      step: baseStep * fitScale,
      fitScale,
    };
  }

  function rectCorners(r) {
    return [
      { x: r.x, y: r.y },
      { x: r.x + r.w, y: r.y },
      { x: r.x + r.w, y: r.y + r.h },
      { x: r.x, y: r.y + r.h },
    ];
  }

  function rotatePoint(point, center, degrees) {
    if (!degrees) return { x: point.x, y: point.y };
    const rad = degrees * Math.PI / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    const dx = point.x - center.x;
    const dy = point.y - center.y;
    return {
      x: center.x + dx * cos - dy * sin,
      y: center.y + dx * sin + dy * cos,
    };
  }

  function rotateRect(r, center, degrees) {
    const points = rectCorners(r).map((point) => rotatePoint(point, center, degrees));
    const xs = points.map((point) => point.x);
    const ys = points.map((point) => point.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    return rect(minX, minY, maxX - minX, maxY - minY);
  }

  function inflateRect(r, amount) {
    return rect(r.x - amount, r.y - amount, r.w + amount * 2, r.h + amount * 2);
  }

  function intersects(a, b, padding = 0) {
    const aa = padding ? inflateRect(a, padding) : a;
    const bb = padding ? inflateRect(b, padding) : b;
    return aa.x < bb.x + bb.w
      && aa.x + aa.w > bb.x
      && aa.y < bb.y + bb.h
      && aa.y + aa.h > bb.y;
  }

  function outside(container, item, epsilon = 0.001) {
    return item.x < container.x - epsilon
      || item.y < container.y - epsilon
      || item.x + item.w > container.x + container.w + epsilon
      || item.y + item.h > container.y + container.h + epsilon;
  }

  function normalizePlayers(state) {
    const players = Array.isArray(state?.players) ? state.players : [];
    return [0, 1, 2, 3].map((seat) => {
      const found = players.find((player) => Number(player?.seat) === seat);
      return found || {
        seat,
        hand_count: 0,
        melds: [],
        flowers: [],
        flower_count: 0,
        discards: [],
      };
    });
  }

  function flowerCount(player) {
    if (Array.isArray(player?.flowers) && player.flowers.length) return player.flowers.length;
    return Math.max(0, num(player?.flower_count, 0));
  }

  function visibleDiscardCount(player) {
    return Array.isArray(player?.visible_discards)
      ? player.visible_discards.length
      : Array.isArray(player?.discards)
        ? player.discards.length
        : Math.max(0, num(player?.discard_count, 0));
  }

  function handObjectTileCount(player) {
    const hand = player?.hand;
    if (!hand || typeof hand !== "object") return 0;
    return Object.values(hand).reduce((sum, value) => sum + Math.max(0, num(value, 0)), 0);
  }

  function meldTileCount(meld) {
    if (Array.isArray(meld?.tiles) && meld.tiles.length) return meld.tiles.length;
    if (meld?.type === "chi" || meld?.type === "peng") return 3;
    if (String(meld?.type || "").includes("gang") || String(meld?.type || "").includes("kan")) return 4;
    return 3;
  }

  function meldHasClaimedTile(meld) {
    const type = String(meld?.type || "");
    if (type === "an_gang" || type === "closed_kan") return false;
    if (type === "chi" || type === "peng" || type === "ming_gang" || type === "open_kan" || type === "bu_gang" || type === "late_kan") return true;
    return Number.isInteger(Number(meld?.from));
  }

  function meldUnits(meld) {
    const count = meldTileCount(meld);
    if (!meldHasClaimedTile(meld)) return count;
    return Math.max(0, count - 1) + 1.40625;
  }

  function splitMeldRows(melds, rowLimit, maxMainCount = Number.POSITIVE_INFINITY) {
    const main = [];
    const overflow = [];
    let mainUnits = 0;
    let overflowUnits = 0;
    for (const meld of melds || []) {
      const units = meldUnits(meld);
      const mainHasRoom = main.length < maxMainCount && mainUnits + units <= rowLimit;
      if (!main.length || mainHasRoom) {
        main.push({ meld, units });
        mainUnits += units;
      } else {
        overflow.push({ meld, units });
        overflowUnits += units;
      }
    }
    return { main, overflow, mainUnits, overflowUnits };
  }

  function flowerLayout(flowers, density, config) {
    const count = Math.max(0, num(flowers, 0));
    const folded = density === "overflow" && count >= config.publicArea.flowerFoldThreshold;
    const visibleCount = folded
      ? Math.min(count, config.publicArea.flowerFoldVisible)
      : count;
    const hiddenCount = Math.max(0, count - visibleCount);
    const badgeUnits = hiddenCount > 0 ? config.publicArea.flowerBadgeUnits : 0;
    return {
      count,
      folded,
      visibleCount,
      hiddenCount,
      badgeUnits,
      rowUnits: visibleCount + badgeUnits,
    };
  }

  function activeHandLayout(options = {}, config = DEFAULT_CONFIG) {
    const hand = config.activeHand || DEFAULT_CONFIG.activeHand;
    const mobile = Boolean(options.mobile);
    const maxTiles = Math.max(1, num(options.maxTiles, hand.maxTiles || 17));
    const count = Math.min(Math.max(0, num(options.count ?? options.tileCount, maxTiles)), maxTiles);
    const tileCount = Math.max(1, count || maxTiles);
    const tableWidth = Math.max(1, num(options.tableWidth, config.table?.width || DEFAULT_CONFIG.table.width));
    const baseTileW = num(options.baseTileW, mobile ? hand.mobileBaseTileW : hand.desktopBaseTileW);
    const minTileW = num(options.minTileW, mobile ? hand.mobileMinTileW : hand.desktopMinTileW);
    const minScale = num(options.minScaleLimit, mobile ? hand.mobileMinScale : hand.desktopMinScale);
    const desiredGap = num(options.desiredGap, mobile ? hand.mobileDesiredGap : hand.desktopDesiredGap);
    const hasNewDraw = Boolean(options.hasNewDraw);
    const edgeInset = num(options.edgeInset, mobile ? hand.mobileEdgeInset : hand.desktopEdgeInset);
    const leftReserve = Math.max(0, num(options.leftReserve, 0));
    const rightReserve = Math.max(0, num(options.rightReserve, 0));
    const safeWidth = Math.max(
      minTileW * Math.min(5, tileCount),
      tableWidth - leftReserve - rightReserve - edgeInset
    );
    const drawGapBase = hasNewDraw
      ? Math.max(9, num(options.drawGap, Math.round(baseTileW * 0.15)))
      : 0;
    const regularGapSlots = Math.max(0, tileCount - (hasNewDraw ? 2 : 1));
    const safeWithoutDraw = Math.max(minTileW, safeWidth - drawGapBase);
    const noOverlapTileW = (safeWithoutDraw - regularGapSlots * desiredGap) / tileCount;
    const preferredTileW = Math.min(baseTileW, Math.max(baseTileW * minScale, noOverlapTileW));
    const overlapRatio = Math.max(0, Math.min(0.45, num(options.maxOverlapRatio, hand.maxOverlapRatio)));
    const overlapDenominator = Math.max(1, tileCount - regularGapSlots * overlapRatio);
    const maxTileWByOverlap = safeWithoutDraw / overlapDenominator;
    const enforceNoOverlap = overlapRatio <= 0;
    const effectiveMinTileW = enforceNoOverlap ? 1 : minTileW;
    const tileW = Math.max(effectiveMinTileW, Math.min(preferredTileW, maxTileWByOverlap));
    const drawGap = hasNewDraw ? Math.max(9, drawGapBase * (tileW / baseTileW)) : 0;
    const availableForRegularGaps = safeWidth - drawGap - tileCount * tileW;
    const tileGap = regularGapSlots > 0
      ? Math.max(0, Math.min(desiredGap, availableForRegularGaps / regularGapSlots))
      : 0;
    const contentWidth = tileCount * tileW + regularGapSlots * tileGap + drawGap;
    return {
      count,
      tileCount,
      tableWidth,
      safeWidth,
      leftReserve,
      rightReserve,
      tileW,
      tileGap,
      drawGap,
      contentWidth,
      fits: contentWidth <= safeWidth + 0.5,
      overlapRatio: tileGap < 0 ? Math.abs(tileGap) / tileW : 0,
    };
  }

  function publicMetrics(player, config) {
    const flowers = flowerCount(player);
    const melds = Array.isArray(player?.melds) ? player.melds : [];
    const meldTotalUnits = melds.reduce((sum, meld) => sum + meldUnits(meld), 0);
    const totalUnits = meldTotalUnits + flowers;
    const density = totalUnits > config.publicArea.compactTotalLimit || flowers >= 9 || melds.length >= 5
      ? "overflow"
      : totalUnits > config.publicArea.normalTotalLimit || flowers >= 7
        ? "compact"
        : "normal";
    const maxMainCount = density === "overflow"
      ? num(config.publicArea.overflowMeldsPerMainRow, 3)
      : num(config.publicArea.maxMeldsPerMainRow, 2);
    const rows = splitMeldRows(melds, config.publicArea.rowUnitLimit, maxMainCount);
    const flowersLayout = flowerLayout(flowers, density, config);
    const maxRowUnits = Math.max(flowersLayout.rowUnits, rows.mainUnits, rows.overflowUnits, 0);
    const scale = density === "overflow"
      ? config.publicArea.overflowScale
      : density === "compact"
        ? config.publicArea.compactScale
        : 1;
    const rowCount = (flowers > 0 ? 1 : 0) + (rows.main.length ? 1 : 0) + (rows.overflow.length ? 1 : 0);
    const tileW = config.publicArea.tileW * scale;
    const tileH = config.publicArea.tileH * scale;
    const gap = config.publicArea.gap * scale;
    const width = maxRowUnits > 0
      ? (maxRowUnits * tileW) + Math.max(0, Math.ceil(maxRowUnits) - 1) * gap
      : 0;
    const height = rowCount > 0
      ? rowCount * tileH + Math.max(0, rowCount - 1) * config.publicArea.rowGap * scale
      : 0;
    return {
      flowers,
      flowerLayout: flowersLayout,
      meldCount: melds.length,
      meldTotalUnits,
      maxRowUnits,
      totalUnits,
      rows,
      rowCount,
      density,
      scale,
      tileW,
      tileH,
      gap,
      width,
      height,
    };
  }

  function seatTransform(seat, config) {
    const index = ((Number(seat) % 4) + 4) % 4;
    return {
      seat: index,
      angle: SEAT_ANGLES[index] || 0,
      center: { ...config.table.center },
    };
  }

  function transformCanonicalRect(canonical, seat, config) {
    const transform = seatTransform(seat, config);
    return rotateRect(canonical, transform.center, transform.angle);
  }

  function inverseTransformRect(screenRect, seat, config) {
    const transform = seatTransform(seat, config);
    return rotateRect(screenRect, transform.center, -transform.angle);
  }

  function remoteHandScreenRect(tileCount, seat, config, mode = "standing") {
    const presetRecord = mode === "revealed"
      ? exactLayoutRecord(config, "hand", seat, "revealed")
      : (
        num(config?.remoteHand?.sideInset, DEFAULT_CONFIG.remoteHand.sideInset) === DEFAULT_CONFIG.remoteHand.sideInset
          ? layoutRecord(config, "hand", seat, "remote")
          : null
      );
    const preset = layoutRect(presetRecord);
    if (preset) return preset;
    const revealed = mode === "revealed";
    const step = revealed
      ? config.remoteHand.tileW + num(config.remoteHand.revealedGap, 1)
      : config.remoteHand.tileW - config.remoteHand.overlap;
    const width = config.remoteHand.tileW
      + Math.max(0, tileCount - 1) * step;
    const height = config.remoteHand.tileH;
    const remotePreset = revealed ? layoutBox(config, "hand", seat, "remote") : null;
    if (remotePreset) {
      const center = rectCenter(remotePreset);
      if (seat === 1 || seat === 3) return rectFromCenter(center.x, center.y, remotePreset.w, width);
      return rectFromCenter(center.x, center.y, width, remotePreset.h);
    }
    const sideVisualWidth = height;
    const center = config.table.center;
    if (seat === 2) return rectFromCenter(center.x, config.remoteHand.y, width, height);
    if (seat === 1) return rectFromCenter(config.table.width - config.remoteHand.sideInset, center.y, sideVisualWidth, width);
    return rectFromCenter(config.remoteHand.sideInset, center.y, sideVisualWidth, width);
  }

  function remoteHandRects(tileCount, seat, config, mode = "standing") {
    const screenBBox = remoteHandScreenRect(tileCount, seat, config, mode);
    const canonicalBBox = inverseTransformRect(screenBBox, seat, config);
    return {
      canonicalBBox,
      bbox: transformCanonicalRect(canonicalBBox, seat, config),
    };
  }

  function riverScreenRect(mode, seat, config) {
    const preset = layoutBox(config, "river", seat, mode);
    if (preset) return preset;
    const rows = mode === "dense" ? 3 : 2;
    const tileW = mode === "dense" ? config.river.tileW * 0.9 : config.river.tileW;
    const tileH = mode === "dense" ? config.river.tileH * 0.9 : config.river.tileH;
    const width = config.river.cols * tileW + Math.max(0, config.river.cols - 1) * config.river.gap;
    const height = rows * tileH + Math.max(0, rows - 1) * config.river.gap;
    const center = config.table.center;
    const gap = config.river.yGapFromCenter;
    if (seat === 0) {
      return rectFromCenter(center.x, center.y + config.center.h / 2 + gap + height / 2, width, height);
    }
    if (seat === 2) {
      return rectFromCenter(center.x, center.y - config.center.h / 2 - gap - height / 2, width, height);
    }
    if (seat === 1) {
      return rectFromCenter(center.x + config.center.w / 2 + gap + height / 2, center.y, height, width);
    }
    return rectFromCenter(center.x - config.center.w / 2 - gap - height / 2, center.y, height, width);
  }

  function riverBlockRects(mode, seat, config) {
    const screenBBox = riverScreenRect(mode, seat, config);
    const canonicalBBox = inverseTransformRect(screenBBox, seat, config);
    return {
      canonicalBBox,
      bbox: transformCanonicalRect(canonicalBBox, seat, config),
    };
  }

  function publicScreenRect(metrics, seat, config) {
    if (!metrics.width || !metrics.height) {
      return rect(config.publicArea.safeLeft, config.publicArea.y, 0, 0);
    }
    const preset = layoutBox(config, "public", seat, metrics.density);
    if (preset) return preset;
    if (seat === 0) {
      return rect(config.publicArea.safeLeft, config.publicArea.y, metrics.width, metrics.height);
    }
    if (seat === 2) {
      const topX = Number.isFinite(Number(config.publicArea.topX))
        ? num(config.publicArea.topX, config.table.width - config.publicArea.safeLeft - metrics.width)
        : config.table.width - config.publicArea.safeLeft - metrics.width;
      return rect(
        topX,
        config.publicArea.topY,
        metrics.width,
        metrics.height
      );
    }
    const sideWidth = metrics.height;
    const sideHeight = metrics.width;
    if (seat === 1) {
      return rect(
        config.table.width - config.publicArea.sideInset - sideWidth,
        config.publicArea.sideY,
        sideWidth,
        sideHeight
      );
    }
    return rect(config.publicArea.sideInset, config.publicArea.sideY, sideWidth, sideHeight);
  }

  function publicBlockRects(metrics, seat, config) {
    const screenBBox = publicScreenRect(metrics, seat, config);
    const canonicalBBox = inverseTransformRect(screenBBox, seat, config);
    return {
      canonicalBBox,
      bbox: transformCanonicalRect(canonicalBBox, seat, config),
    };
  }

  function createCenterBlock(config) {
    const presetRecord = layoutRecord(config, "center", null, "fixed");
    const bbox = layoutRect(presetRecord)
      || rectFromCenter(config.table.center.x, config.table.center.y, config.center.w, config.center.h);
    return {
      type: "center",
      seat: null,
      mode: "fixed",
      canonicalBBox: bbox,
      bbox,
      layout: layoutOptions(presetRecord, "center"),
    };
  }

  function createFieldBlock(config) {
    const presetRecord = layoutRecord(config, "field", null, "fixed");
    const bbox = layoutRect(presetRecord) || { ...config.table.fieldBBox };
    return {
      type: "field",
      seat: null,
      mode: "fixed",
      canonicalBBox: { ...bbox },
      bbox: { ...bbox },
      layout: layoutOptions(presetRecord, "field"),
    };
  }

  function createFrameBlock(config) {
    const bbox = rect(0, 0, config.table.width, config.table.height);
    return {
      type: "frame",
      seat: null,
      mode: "fixed",
      canonicalBBox: bbox,
      bbox,
    };
  }

  function createCenterLabelBlocks(config) {
    const center = createCenterBlock(config).bbox;
    const labelW = Math.max(72, config.center.w * 0.32);
    const labelH = Math.max(34, config.center.h * 0.18);
    const gap = Math.max(6, config.center.h * 0.035);
    const labels = [
      rectFromCenter(config.table.center.x, center.y + center.h - labelH / 2 - gap, labelW, labelH),
      rectFromCenter(center.x + center.w - labelW / 2 - gap, config.table.center.y, labelW, labelH),
      rectFromCenter(config.table.center.x, center.y + labelH / 2 + gap, labelW, labelH),
      rectFromCenter(center.x + labelW / 2 + gap, config.table.center.y, labelW, labelH),
    ];
    const positions = ["bottom", "right", "top", "left"];
    return labels.map((screenBBox, seat) => {
      const presetRecord = layoutRecord(config, "centerLabel", seat, positions[seat]);
      const preset = layoutRect(presetRecord);
      const bboxSource = preset || screenBBox;
      const canonicalBBox = inverseTransformRect(bboxSource, seat, config);
      const bbox = transformCanonicalRect(canonicalBBox, seat, config);
      return {
        type: "centerLabel",
        seat,
        position: positions[seat],
        mode: "fixed",
        canonicalBBox,
        bbox,
        localBBox: rect(bbox.x - center.x, bbox.y - center.y, bbox.w, bbox.h),
        layout: layoutOptions(presetRecord, "centerLabel"),
      };
    });
  }

  function createHandBlock(player, seat, config) {
    const count = Math.min(
      Math.max(0, num(player?.hand_count, 0)),
      config.activeHand.maxTiles
    );
    if (seat === 0) {
      const presetRecord = layoutRecord(config, "hand", seat, "active");
      const preset = layoutRect(presetRecord);
      const tileCount = Math.max(1, count || config.activeHand.maxTiles);
      const width = tileCount * config.activeHand.tileW
        + Math.max(0, tileCount - 1) * config.activeHand.gap
        + (player?.last_draw ? config.activeHand.drawGap : 0);
      const bbox = preset
        || rectFromCenter(config.table.center.x, config.activeHand.y + config.activeHand.tileH / 2, width, config.activeHand.tileH);
      return {
        type: "hand",
        seat,
        mode: "active",
        tileCount: count,
        canonicalBBox: bbox,
        bbox,
        layout: layoutOptions(presetRecord, "hand"),
      };
    }
    const tileCount = Math.max(1, count || config.remoteHand.maxTiles);
    const revealedCount = handObjectTileCount(player);
    const revealed = revealedCount > 0;
    const remoteTileCount = Math.max(1, revealed ? revealedCount : tileCount);
    const presetRecord = layoutRecord(config, "hand", seat, revealed ? "revealed" : "remote");
    const rects = remoteHandRects(remoteTileCount, seat, config, revealed ? "revealed" : "standing");
    const baseStep = revealed
      ? config.remoteHand.tileW + num(config.remoteHand.revealedGap, 1)
      : config.remoteHand.tileW - config.remoteHand.overlap;
    const fitted = fitLineMetricsToBox(
      rects.bbox,
      seat,
      remoteTileCount,
      config.remoteHand.tileW,
      config.remoteHand.tileH,
      baseStep
    );
    return {
      type: "hand",
      seat,
      mode: revealed ? "remoteRevealed" : "remote",
      pose: revealed ? "revealed" : "standing",
      tileCount: revealed ? revealedCount : count,
      canonicalBBox: rects.canonicalBBox,
      bbox: rects.bbox,
      layout: layoutOptions(presetRecord, "hand"),
      metrics: {
        tileW: fitted.tileW,
        tileH: fitted.tileH,
        step: fitted.step,
        fitScale: fitted.fitScale,
        projectionLean: 0,
      },
    };
  }

  function createRiverBlock(player, seat, config) {
    const count = visibleDiscardCount(player);
    const mode = count > config.river.normalLimit ? "dense" : "normal";
    const rows = mode === "dense" ? 3 : 2;
    const visibleLimit = mode === "dense" ? config.river.denseLimit : config.river.normalLimit;
    const presetRecord = layoutRecord(config, "river", seat, mode);
    const rects = riverBlockRects(mode, seat, config);
    return {
      type: "river",
      seat,
      mode,
      discardCount: count,
      visibleLimit,
      overflowCount: Math.max(0, count - visibleLimit),
      rows,
      cols: config.river.cols,
      canonicalBBox: rects.canonicalBBox,
      bbox: rects.bbox,
      layout: layoutOptions(presetRecord, "river"),
    };
  }

  function createPublicBlock(player, seat, config) {
    const metrics = publicMetrics(player, config);
    const presetRecord = layoutRecord(config, "public", seat, metrics.density);
    const rects = publicBlockRects(metrics, seat, config);
    return {
      type: "public",
      seat,
      mode: metrics.density,
      metrics,
      canonicalBBox: rects.canonicalBBox,
      bbox: rects.bbox,
      layout: layoutOptions(presetRecord, "public"),
    };
  }

  function rowUnitsToWidth(units, metrics, config) {
    if (!units) return 0;
    return units * metrics.tileW + Math.max(0, Math.ceil(units) - 1) * metrics.gap;
  }

  function publicRowRect(parent, metrics, seat, rowIndex, rowUnits, config) {
    const rowWidth = rowUnitsToWidth(rowUnits, metrics, config);
    if (!rowWidth || !metrics.tileH) return null;
    const rowGap = config.publicArea.rowGap * metrics.scale;
    const alongOffset = rowIndex * (metrics.tileH + rowGap);
    if (seat === 0 || seat === 2) {
      const x = seat === 0
        ? parent.bbox.x
        : parent.bbox.x + parent.bbox.w - rowWidth;
      return rect(x, parent.bbox.y + alongOffset, rowWidth, metrics.tileH);
    }
    const x = seat === 1
      ? parent.bbox.x + alongOffset
      : parent.bbox.x + parent.bbox.w - metrics.tileH - alongOffset;
    const y = seat === 1
      ? parent.bbox.y
      : parent.bbox.y + parent.bbox.h - rowWidth;
    return rect(x, y, metrics.tileH, rowWidth);
  }

  function publicLocalRect(parent, screenRect, seat) {
    const center = rectCenter(parent.bbox);
    const angle = -(SEAT_ANGLES[seat] || 0);
    const local = rotateRect(screenRect, center, angle);
    return rect(local.x - center.x, local.y - center.y, local.w, local.h);
  }

  function createPublicDetailBlocks(parent, player, seat, config) {
    const metrics = parent.metrics;
    if (!metrics || parent.bbox.w <= 0 || parent.bbox.h <= 0) return [];
    const blocks = [];
    let rowIndex = 0;
    if (metrics.flowers > 0) {
      const presetRecord = layoutRecord(config, "flowers", seat, metrics.density)
        || layoutRecord(config, "flowers", seat);
      const screenBBox = layoutRect(presetRecord)
        || publicRowRect(parent, metrics, seat, rowIndex, metrics.flowerLayout.rowUnits, config);
      if (screenBBox) {
        const canonicalBBox = inverseTransformRect(screenBBox, seat, config);
        const bbox = transformCanonicalRect(canonicalBBox, seat, config);
        blocks.push({
          type: "flowers",
          seat,
          mode: metrics.density,
          parent: blockId(parent),
          count: metrics.flowers,
          visibleCount: metrics.flowerLayout.visibleCount,
          hiddenCount: metrics.flowerLayout.hiddenCount,
          folded: metrics.flowerLayout.folded,
          canonicalBBox,
          bbox,
          localBBox: publicLocalRect(parent, bbox, seat),
          layout: layoutOptions(presetRecord, "flowers"),
        });
      }
      rowIndex += 1;
    }
    if (metrics.rows.main.length) {
      const presetRecord = layoutRecord(config, "melds", seat, "main");
      const screenBBox = layoutRect(presetRecord)
        || publicRowRect(parent, metrics, seat, rowIndex, metrics.rows.mainUnits, config);
      if (screenBBox) {
        const canonicalBBox = inverseTransformRect(screenBBox, seat, config);
        const bbox = transformCanonicalRect(canonicalBBox, seat, config);
        blocks.push({
          type: "melds",
          seat,
          mode: metrics.density,
          row: "main",
          parent: blockId(parent),
          meldCount: metrics.rows.main.length,
          units: metrics.rows.mainUnits,
          canonicalBBox,
          bbox,
          localBBox: publicLocalRect(parent, bbox, seat),
          layout: layoutOptions(presetRecord, "melds"),
        });
      }
      rowIndex += 1;
    }
    if (metrics.rows.overflow.length) {
      const presetRecord = layoutRecord(config, "melds", seat, "overflow");
      const screenBBox = layoutRect(presetRecord)
        || publicRowRect(parent, metrics, seat, rowIndex, metrics.rows.overflowUnits, config);
      if (screenBBox) {
        const canonicalBBox = inverseTransformRect(screenBBox, seat, config);
        const bbox = transformCanonicalRect(canonicalBBox, seat, config);
        blocks.push({
          type: "melds",
          seat,
          mode: metrics.density,
          row: "overflow",
          parent: blockId(parent),
          meldCount: metrics.rows.overflow.length,
          units: metrics.rows.overflowUnits,
          canonicalBBox,
          bbox,
          localBBox: publicLocalRect(parent, bbox, seat),
          layout: layoutOptions(presetRecord, "melds"),
        });
      }
    }
    return blocks;
  }

  function blockId(block) {
    return block.seat === null || block.seat === undefined
      ? block.type
      : `${block.type}:${block.seat}`;
  }

  function diagnoseModel(blocks, config) {
    const byType = new Map();
    for (const block of blocks) {
      if (!byType.has(block.type)) byType.set(block.type, []);
      byType.get(block.type).push(block);
    }
    const diagnostics = [];
    const center = byType.get("center")?.[0];
    const table = rect(0, 0, config.table.width, config.table.height);
    const field = config.table.fieldBBox;
    for (const block of blocks) {
      if (block.bbox.w <= 0 || block.bbox.h <= 0) continue;
      if (outside(table, block.bbox)) {
        diagnostics.push({
          severity: block.mode === "overflow" ? "warning" : "error",
          code: "outside-table",
          block: blockId(block),
        });
      }
      const fieldBound = block.type === "river"
        || (block.type === "hand" && (block.mode === "remote" || block.mode === "remoteRevealed"));
      if (fieldBound && outside(field, block.bbox)) {
        diagnostics.push({
          severity: block.mode === "overflow" ? "warning" : "error",
          code: "outside-field",
          block: blockId(block),
        });
      }
    }
    if (center) {
      for (const river of byType.get("river") || []) {
        if (intersects(center.bbox, river.bbox, 0)) {
          diagnostics.push({ severity: "error", code: "center-river-overlap", blocks: [blockId(center), blockId(river)] });
        }
      }
      for (const pub of byType.get("public") || []) {
        if (pub.bbox.w > 0 && pub.bbox.h > 0 && intersects(center.bbox, pub.bbox, 0)) {
          diagnostics.push({
            severity: pub.mode === "overflow" ? "warning" : "error",
            code: "center-public-overlap",
            blocks: [blockId(center), blockId(pub)],
          });
        }
      }
    }
    const riverBlocks = byType.get("river") || [];
    const publicBlocks = byType.get("public") || [];
    for (const river of riverBlocks) {
      if (river.bbox.w <= 0 || river.bbox.h <= 0) continue;
      for (const pub of publicBlocks) {
        if (pub.bbox.w <= 0 || pub.bbox.h <= 0) continue;
        if (intersects(river.bbox, pub.bbox, 0)) {
          diagnostics.push({
            severity: pub.mode === "overflow" || river.mode === "dense" ? "warning" : "error",
            code: "river-public-overlap",
            blocks: [blockId(river), blockId(pub)],
          });
        }
      }
    }
    const hands = byType.get("hand") || [];
    for (const pub of publicBlocks) {
      if (pub.bbox.w <= 0 || pub.bbox.h <= 0) continue;
      const sameSeatHand = hands.find((hand) => hand.seat === pub.seat);
      if (sameSeatHand && intersects(sameSeatHand.bbox, pub.bbox, 0)) {
        diagnostics.push({
          severity: pub.mode === "overflow" ? "warning" : "error",
          code: "hand-public-overlap",
          blocks: [blockId(sameSeatHand), blockId(pub)],
        });
      }
    }
    for (let i = 0; i < publicBlocks.length; i += 1) {
      const left = publicBlocks[i];
      if (left.bbox.w <= 0 || left.bbox.h <= 0) continue;
      for (let j = i + 1; j < publicBlocks.length; j += 1) {
        const right = publicBlocks[j];
        if (right.bbox.w <= 0 || right.bbox.h <= 0) continue;
        if (intersects(left.bbox, right.bbox, 0)) {
          diagnostics.push({
            severity: left.mode === "overflow" || right.mode === "overflow" ? "warning" : "error",
            code: "public-public-overlap",
            blocks: [blockId(left), blockId(right)],
          });
        }
      }
    }
    return diagnostics;
  }

  function createBattleTableModel(state, options = {}) {
    const config = cloneConfig(options.config || DEFAULT_CONFIG);
    const players = normalizePlayers(state);
    const blocks = [
      createFrameBlock(config),
      createFieldBlock(config),
      createCenterBlock(config),
      ...createCenterLabelBlocks(config),
    ];
    for (const player of players) {
      const seat = num(player.seat, 0);
      blocks.push(createHandBlock(player, seat, config));
      blocks.push(createRiverBlock(player, seat, config));
      const publicBlock = createPublicBlock(player, seat, config);
      blocks.push(publicBlock);
      blocks.push(...createPublicDetailBlocks(publicBlock, player, seat, config));
    }
    const diagnostics = diagnoseModel(blocks, config);
    return {
      version: "v7-table-model-2",
      table: config.table,
      config,
      blocks,
      diagnostics,
      ok: diagnostics.every((item) => item.severity !== "error"),
    };
  }

  return {
    DEFAULT_CONFIG,
    SEAT_ANGLES,
    createBattleTableModel,
    publicMetrics,
    flowerLayout,
    activeHandLayout,
    meldUnits,
    splitMeldRows,
    seatTransform,
    transformCanonicalRect,
    inverseTransformRect,
    rotatePoint,
    rotateRect,
    intersects,
    outside,
  };
});
