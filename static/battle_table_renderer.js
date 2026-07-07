/* Battle table renderer v7.
   Runtime contract:
   - BattleTableModel owns geometry and bbox diagnostics.
   - This renderer consumes the model and draws the non-interactive table world
     to a Canvas layer.
   - DOM still owns the active hand, action buttons, popups and center text. */

(function initBattleTableRenderer(root, factory) {
  const api = factory(root);
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.BattleTableRenderer = api;
})(typeof globalThis !== "undefined" ? globalThis : window, function battleTableRendererFactory(root) {
  const TILE_ORDER = [
    "m1","m2","m3","m4","m5","m6","m7","m8","m9",
    "t1","t2","t3","t4","t5","t6","t7","t8","t9",
    "b1","b2","b3","b4","b5","b6","b7","b8","b9",
    "east","south","west","north","zhong","fa","bai",
    "rh1","rh2","rh3","rh4","bh1","bh2","bh3","bh4",
  ];

  const SEAT_ANGLES = [0, -90, 180, 90];
  const DEFAULT_ATLAS_MANIFEST_URL = "";
  let activeRenderMetrics = null;
  const DEFAULT_LABELS = {
    east: "东", south: "南", west: "西", north: "北",
    zhong: "中", fa: "发", bai: "白",
    rh1: "梅", rh2: "兰", rh3: "菊", rh4: "竹",
    bh1: "春", bh2: "夏", bh3: "秋", bh4: "冬",
  };
  const ZH_LABELS = {
    east: "东", south: "南", west: "西", north: "北",
    zhong: "中", fa: "发", bai: "白",
    rh1: "梅", rh2: "兰", rh3: "菊", rh4: "竹",
    bh1: "春", bh2: "夏", bh3: "秋", bh4: "冬",
  };
  const atlasState = {
    url: "",
    loading: false,
    ready: false,
    manifest: null,
    image: null,
    error: "",
    lastRender: null,
  };
  const tileImageState = {
    paths: {},
    images: new Map(),
    lastRender: null,
    pendingRerender: false,
  };

  function seatClass(seat) {
    return ["bottom", "right", "top", "left"][Number(seat)] || "side";
  }

  function backSpriteForSeat(seat) {
    if (Number(seat) === 1) return "tile_back_standing_right";
    if (Number(seat) === 2) return "tile_back_standing_top";
    if (Number(seat) === 3) return "tile_back_standing_left";
    return "tile_back_standing";
  }

  function standingWallDirectionForSeat(seat) {
    if (Number(seat) === 1) return "right";
    if (Number(seat) === 2) return "top";
    if (Number(seat) === 3) return "left";
    return "top";
  }

  function handWallStripSprite(command, count) {
    const direction = standingWallDirectionForSeat(command.seat);
    const prefixes = atlasState.manifest?.poses?.remote_hand_wall?.strip_sprite_prefixes || {};
    const prefix = prefixes[direction] || `hand_wall_standing_${direction}_`;
    return `${prefix}${String(Math.max(1, Math.min(17, Number(count) || 1))).padStart(2, "0")}`;
  }

  function angleForSeat(seat) {
    return (SEAT_ANGLES[Number(seat)] || 0) * Math.PI / 180;
  }

  function tileRank(code) {
    const match = String(code || "").match(/\d+/);
    return match ? Number(match[0]) : 0;
  }

  function tileLabel(code, labels) {
    if (!code || code === "*") return "?";
    if (labels && labels[code]) return labels[code];
    const tileNumber = tileRank(code);
    if (/^m[1-9]$/.test(code)) return `${tileNumber}万`;
    if (/^t[1-9]$/.test(code)) return `${tileNumber}条`;
    if (/^b[1-9]$/.test(code)) return `${tileNumber}筒`;
    if (ZH_LABELS[code]) return ZH_LABELS[code];
    if (DEFAULT_LABELS[code]) return DEFAULT_LABELS[code];
    const rank = tileRank(code);
    if (/^m[1-9]$/.test(code)) return `${rank}万`;
    if (/^t[1-9]$/.test(code)) return `${rank}条`;
    if (/^b[1-9]$/.test(code)) return `${rank}筒`;
    return String(code);
  }

  function nowMs() {
    return root.performance?.now ? root.performance.now() : Date.now();
  }

  function roundedMs(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Number(number.toFixed(3)) : 0;
  }

  function markCanvasDraw(category, amount = 1) {
    if (!activeRenderMetrics) return;
    const count = Math.max(0, Number(amount) || 0);
    activeRenderMetrics.canvasDrawCalls += count;
    if (category) {
      activeRenderMetrics[category] = (Number(activeRenderMetrics[category]) || 0) + count;
    }
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function truncateText(value, maxChars) {
    const text = String(value ?? "");
    if (text.length <= maxChars) return text;
    return `${text.slice(0, Math.max(0, maxChars - 1))}…`;
  }

  function playerBySeat(state, seat) {
    return (Array.isArray(state?.players) ? state.players : [])
      .find((player) => Number(player?.seat) === Number(seat));
  }

  function seatWind(playerOrSeat) {
    if (playerOrSeat && typeof playerOrSeat === "object") {
      if (playerOrSeat.wind) return String(playerOrSeat.wind);
      return seatWind(playerOrSeat.seat);
    }
    return ["东", "南", "西", "北"][Number(playerOrSeat)] || "-";
  }

  function playerSeatMatches(target, player) {
    if (!target || !player) return false;
    const seat = Number(player.seat);
    return Number(target.seat) === seat || Number(target.absolute_seat) === seat;
  }

  function playerBaoReason(state, player) {
    if (!state || !player) return "";
    if (state.temporary_bao && playerSeatMatches(state.temporary_bao, player)) {
      return state.temporary_bao.reason || "包牌生效";
    }
    const liabilities = Array.isArray(state.bao_liabilities) ? state.bao_liabilities : [];
    const liability = liabilities.find((item) => item && item.active !== false && playerSeatMatches(item, player));
    return liability ? (liability.reason || "包牌") : "";
  }

  function createCenterHud(state, labels) {
    const wallRemaining = state?.wall_to_draw_game ?? state?.wall_remaining ?? "-";
    const roomRound = Number(state?.room_round_count ?? state?.round_no ?? 0);
    const indicatorMode = state?.center_indicator_mode || (state?.bao_phase ? "bao" : "de");
    return {
      roomRound: Number.isFinite(roomRound) && roomRound > 0 ? Math.trunc(roomRound) : null,
      wallRemaining,
      indicatorMode,
      indicatorTile: state?.de_indicator || null,
      phase: state?.phase || "",
      seats: [0, 1, 2, 3].map((seat) => {
        const player = playerBySeat(state, seat);
        const warningReason = player?.claim_warning?.reason || "连续2张舍牌被同一玩家吃碰杠";
        return {
          seat,
          wind: player ? seatWind(player) : seatWind(seat),
          name: player?.name || player?.account || player?.label || "",
          chips: player?.chips ?? "-",
          active: Number(state?.current_player) === seat && state?.phase !== "round_over",
          dealer: Number(state?.dealer) === seat,
          warning: Boolean(player?.claim_warning),
          warningReason,
          bao: Boolean(playerBaoReason(state, player)),
          baoReason: playerBaoReason(state, player),
        };
      }),
      labels,
    };
  }

  function expandHand(hand) {
    if (!hand || typeof hand !== "object") return [];
    const tiles = [];
    for (const code of TILE_ORDER) {
      const count = Number(hand[code]) || 0;
      for (let i = 0; i < count; i += 1) tiles.push(code);
    }
    return tiles;
  }

  function flowerCount(player) {
    if (Array.isArray(player?.flowers) && player.flowers.length) return player.flowers.length;
    return Math.max(0, Number(player?.flower_count) || 0);
  }

  function publicFlowers(player) {
    if (Array.isArray(player?.flowers) && player.flowers.length) return player.flowers;
    return Array.from({ length: flowerCount(player) }, () => "*");
  }

  function visibleDiscards(player) {
    if (Array.isArray(player?.visible_discards)) return player.visible_discards;
    if (Array.isArray(player?.discards)) return player.discards;
    return [];
  }

  function meldDisplayTiles(meld) {
    const tiles = Array.isArray(meld?.tiles) ? meld.tiles : [];
    if (meld?.type === "an_gang" && tiles.length >= 4) return ["*", tiles[1], tiles[2], "*"];
    return tiles;
  }

  function meldDisplayEntries(meld, ownerSeat) {
    const entries = meldDisplayTiles(meld).map((code) => ({
      code,
      claimed: false,
      direction: null,
    }));
    if (meld?.type === "an_gang") return entries;
    const fromSeat = Number(meld?.from);
    const seat = Number(ownerSeat);
    if (!Number.isInteger(fromSeat) || !Number.isInteger(seat) || fromSeat === seat) return entries;
    const direction = ({ 1: "right", 2: "top", 3: "left" })[(fromSeat - seat + 4) % 4];
    if (!direction) return entries;
    const claimedIndex = entries.findIndex((entry) => entry.code === meld?.tile);
    if (claimedIndex < 0) return entries;
    const [claimed] = entries.splice(claimedIndex, 1);
    claimed.claimed = true;
    claimed.direction = direction;
    const targetIndex = direction === "left"
      ? 0
      : direction === "top"
        ? Math.min(1, entries.length)
        : entries.length;
    entries.splice(targetIndex, 0, claimed);
    return entries;
  }

  function meldUnits(meld, tableModelApi) {
    if (tableModelApi?.meldUnits) return tableModelApi.meldUnits(meld);
    const entries = meldDisplayEntries(meld, 0);
    return entries.reduce((sum, entry) => sum + (entry.claimed ? 1.40625 : 1), 0);
  }

  function splitMeldRows(melds, rowLimit, tableModelApi, maxMainCount = Number.POSITIVE_INFINITY) {
    const main = [];
    const overflow = [];
    let mainUnits = 0;
    let overflowUnits = 0;
    for (const meld of melds || []) {
      const units = meldUnits(meld, tableModelApi);
      const mainHasRoom = main.length < maxMainCount && mainUnits + units <= rowLimit;
      if (!main.length || mainHasRoom) {
        main.push(meld);
        mainUnits += units;
      } else {
        overflow.push(meld);
        overflowUnits += units;
      }
    }
    return { main, overflow, mainUnits, overflowUnits };
  }

  function renderRowsFromMetrics(metrics) {
    const rows = metrics?.rows;
    if (!rows) return null;
    return {
      main: (rows.main || []).map((entry) => entry.meld || entry),
      overflow: (rows.overflow || []).map((entry) => entry.meld || entry),
      mainUnits: Number(rows.mainUnits) || 0,
      overflowUnits: Number(rows.overflowUnits) || 0,
    };
  }

  function blockBy(model, type, seat) {
    return model.blocks.find((block) => block.type === type && Number(block.seat) === Number(seat));
  }

  function publicRowBlocks(model, seat) {
    const blocks = Array.isArray(model?.blocks) ? model.blocks : [];
    return {
      flowers: blocks.find((block) => block.type === "flowers" && Number(block.seat) === Number(seat)) || null,
      main: blocks.find((block) => block.type === "melds" && block.row === "main" && Number(block.seat) === Number(seat)) || null,
      overflow: blocks.find((block) => block.type === "melds" && block.row === "overflow" && Number(block.seat) === Number(seat)) || null,
    };
  }

  function centerLabelBlocks(model) {
    const blocks = Array.isArray(model?.blocks) ? model.blocks : [];
    const labels = {};
    for (const block of blocks) {
      if (block.type !== "centerLabel") continue;
      labels[Number(block.seat)] = block;
    }
    return labels;
  }

  function localRectToTableRect(local, bbox, angle = 0) {
    const cx = bbox.x + bbox.w / 2;
    const cy = bbox.y + bbox.h / 2;
    const cos = Math.cos(angle || 0);
    const sin = Math.sin(angle || 0);
    const points = [
      { x: local.x, y: local.y },
      { x: local.x + local.w, y: local.y },
      { x: local.x + local.w, y: local.y + local.h },
      { x: local.x, y: local.y + local.h },
    ].map((point) => ({
      x: cx + point.x * cos - point.y * sin,
      y: cy + point.x * sin + point.y * cos,
    }));
    const xs = points.map((point) => point.x);
    const ys = points.map((point) => point.y);
    const x = Math.min(...xs);
    const y = Math.min(...ys);
    return {
      x: Number(x.toFixed(3)),
      y: Number(y.toFixed(3)),
      w: Number((Math.max(...xs) - x).toFixed(3)),
      h: Number((Math.max(...ys) - y).toFixed(3)),
    };
  }

  function copyTableRect(bbox) {
    return {
      x: Number(Number(bbox?.x || 0).toFixed(3)),
      y: Number(Number(bbox?.y || 0).toFixed(3)),
      w: Number(Number(bbox?.w || 0).toFixed(3)),
      h: Number(Number(bbox?.h || 0).toFixed(3)),
    };
  }

  function riverHitBoxes(command, tableConfig) {
    const dense = command.mode === "dense";
    let tileW = tableConfig.river.tileW * (dense ? 0.9 : 1);
    let tileH = tableConfig.river.tileH * (dense ? 0.9 : 1);
    let gap = tableConfig.river.gap;
    let width = command.cols * tileW + Math.max(0, command.cols - 1) * gap;
    let height = command.rows * tileH + Math.max(0, command.rows - 1) * gap;
    const localBox = localSizeForCommand(command);
    const fitScale = fitScaleToBox(width, height, localBox.w, localBox.h);
    if (fitScale < 1) {
      tileW *= fitScale;
      tileH *= fitScale;
      gap *= fitScale;
      width = command.cols * tileW + Math.max(0, command.cols - 1) * gap;
      height = command.rows * tileH + Math.max(0, command.rows - 1) * gap;
    }
    const layout = normalizedLayout(command.layout, "start");
    const startX = alignedLocalStart(localBox.w, width, layout);
    const startY = -localBox.h / 2 + contentOffset(localBox.h, height, layout.innerAlign);
    return (command.tiles || []).map((code, index) => {
      const col = index % command.cols;
      const row = Math.floor(index / command.cols);
      const visualCol = gridColumnIndex(col, command.cols, layout);
      return {
        type: "riverTile",
        seat: command.seat,
        seatClass: command.seatClass,
        tile: code,
        index,
        row,
        col,
        rect: localRectToTableRect(
          {
            x: startX + visualCol * (tileW + gap),
            y: startY + row * (tileH + gap),
            w: tileW,
            h: tileH,
          },
          command.bbox,
          command.localAngle
        ),
      };
    });
  }

  function meldRowHitBoxes(command, rowName, melds, rowBlock, tileW, tileH, gap) {
    if (!rowBlock?.localBBox || !Array.isArray(melds) || !melds.length) return [];
    const boxes = [];
    let localX = 0;
    melds.forEach((meld, meldIndex) => {
      const entries = meldDisplayEntries(meld, command.seat);
      entries.forEach((entry, tileIndex) => {
        const w = entry.claimed ? tileH : tileW;
        const h = entry.claimed ? tileW : tileH;
        boxes.push({
          type: "publicTile",
          subType: "meld",
          seat: command.seat,
          seatClass: command.seatClass,
          row: rowName,
          meldIndex,
          tileIndex,
          tile: entry.code,
          claimed: Boolean(entry.claimed),
          rect: localRectToTableRect(
            {
              x: rowBlock.localBBox.x + localX,
              y: rowBlock.localBBox.y,
              w,
              h,
            },
            command.bbox,
            command.localAngle
          ),
        });
        localX += w + gap;
      });
      localX += gap;
    });
    return boxes;
  }

  function publicHitBoxes(command, tableConfig) {
    const metrics = command.metrics || {};
    const scale = metrics.scale || 1;
    const tileW = metrics.tileW || tableConfig.publicArea.tileW * scale;
    const tileH = metrics.tileH || tableConfig.publicArea.tileH * scale;
    const gap = metrics.gap || tableConfig.publicArea.gap * scale;
    const boxes = [];
    const flowerRow = command.rowBlocks?.flowers;
    if (flowerRow?.localBBox && Array.isArray(command.flowers) && command.flowers.length) {
      const flowerLayout = metrics.flowerLayout || {
        visibleCount: command.flowers.length,
        hiddenCount: 0,
        badgeUnits: 0,
        count: command.flowers.length,
      };
      command.flowers.slice(0, flowerLayout.visibleCount).forEach((code, index) => {
        boxes.push({
          type: "publicTile",
          subType: "flower",
          seat: command.seat,
          seatClass: command.seatClass,
          row: "flowers",
          tile: code,
          index,
          rect: localRectToTableRect(
            {
              x: flowerRow.localBBox.x + index * (tileW + gap),
              y: flowerRow.localBBox.y,
              w: tileW,
              h: tileH,
            },
            command.bbox,
            command.localAngle
          ),
        });
      });
      if (flowerLayout.hiddenCount > 0) {
        const badgeW = flowerLayout.badgeUnits * tileW + Math.max(0, Math.ceil(flowerLayout.badgeUnits) - 1) * gap;
        boxes.push({
          type: "publicTile",
          subType: "flowerBadge",
          seat: command.seat,
          seatClass: command.seatClass,
          row: "flowers",
          hiddenCount: flowerLayout.hiddenCount,
          totalCount: flowerLayout.count,
          rect: localRectToTableRect(
            {
              x: flowerRow.localBBox.x + flowerLayout.visibleCount * (tileW + gap),
              y: flowerRow.localBBox.y,
              w: badgeW,
              h: tileH,
            },
            command.bbox,
            command.localAngle
          ),
        });
      }
    }
    boxes.push(...meldRowHitBoxes(command, "main", command.meldRows?.main || [], command.rowBlocks?.main, tileW, tileH, gap));
    boxes.push(...meldRowHitBoxes(command, "overflow", command.meldRows?.overflow || [], command.rowBlocks?.overflow, tileW, tileH, gap));
    return boxes;
  }

  function centerHitBoxes(command) {
    return Object.values(command.labelBlocks || {})
      .filter((block) => block?.bbox)
      .map((block) => ({
        type: "centerSeat",
        seat: block.seat,
        position: block.position,
        rect: copyTableRect(block.bbox),
      }));
  }

  function createTableHitBoxes(commands, tableConfig) {
    const boxes = [];
    for (const command of commands) {
      if (command.type === "river") boxes.push(...riverHitBoxes(command, tableConfig));
      if (command.type === "public") boxes.push(...publicHitBoxes(command, tableConfig));
      if (command.type === "center") boxes.push(...centerHitBoxes(command));
    }
    return boxes;
  }

  function resolveUrl(url, base) {
    try {
      return new URL(url, base || root.location?.href || "http://localhost/").toString();
    } catch {
      return url;
    }
  }

  function atlasImageUrl(manifest, manifestUrl) {
    return resolveUrl(manifest.webp || manifest.image || "atlas.png", manifestUrl);
  }

  function scheduleTileImageRerender() {
    if (tileImageState.pendingRerender) return;
    const last = tileImageState.lastRender;
    if (!last || typeof root.requestAnimationFrame !== "function") return;
    tileImageState.pendingRerender = true;
    root.requestAnimationFrame(() => {
      tileImageState.pendingRerender = false;
      const { canvas, state, options } = tileImageState.lastRender || {};
      if (canvas) render(canvas, state, options);
    });
  }

  function setTileImagePaths(paths = {}) {
    const next = paths && typeof paths === "object" ? paths : {};
    tileImageState.paths = next;
  }

  function ensureTileImages(options = {}) {
    setTileImagePaths(options.tileImagePaths || {});
    if (typeof root.Image !== "function") return;
    for (const [code, rawSrc] of Object.entries(tileImageState.paths)) {
      if (!code || !rawSrc) continue;
      const src = resolveUrl(rawSrc);
      const previous = tileImageState.images.get(code);
      if (previous && previous.src === src) continue;
      const entry = { src, image: new root.Image(), ready: false, error: "" };
      entry.image.onload = () => {
        entry.ready = true;
        entry.error = "";
        scheduleTileImageRerender();
      };
      entry.image.onerror = () => {
        entry.ready = false;
        entry.error = src;
      };
      entry.image.src = src;
      tileImageState.images.set(code, entry);
    }
  }

  function tileImageFor(code) {
    const entry = tileImageState.images.get(String(code || ""));
    return entry?.ready ? entry.image : null;
  }

  function drawTileSvgIcon(ctx, x, y, w, h, code) {
    const image = tileImageFor(code);
    if (!image) return false;
    const insetX = Math.max(1, w * 0.045);
    const insetY = Math.max(1, h * 0.04);
    markCanvasDraw("tileSvgImageDraws");
    ctx.drawImage(
      image,
      x + insetX,
      y + insetY,
      Math.max(1, w - insetX * 2),
      Math.max(1, h - insetY * 2)
    );
    return true;
  }

  function ensureAtlas(options = {}) {
    if (options.loadAtlas !== true && !options.atlasUrl) return;
    const rawManifestUrl = options.atlasUrl || DEFAULT_ATLAS_MANIFEST_URL;
    if (!rawManifestUrl) return;
    const manifestUrl = resolveUrl(rawManifestUrl);
    if (atlasState.ready && atlasState.url === manifestUrl) return;
    if (atlasState.loading && atlasState.url === manifestUrl) return;
    if (typeof root.fetch !== "function" || typeof root.Image !== "function") return;
    atlasState.url = manifestUrl;
    atlasState.loading = true;
    atlasState.error = "";
    root.fetch(manifestUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`atlas manifest HTTP ${response.status}`);
        return response.json();
      })
      .then((manifest) => new Promise((resolve, reject) => {
        const image = new root.Image();
        image.onload = () => resolve({ manifest, image });
        image.onerror = () => reject(new Error(`atlas image failed: ${atlasImageUrl(manifest, manifestUrl)}`));
        image.src = atlasImageUrl(manifest, manifestUrl);
      }))
      .then(({ manifest, image }) => {
        atlasState.manifest = manifest;
        atlasState.image = image;
        atlasState.ready = true;
        atlasState.loading = false;
        atlasState.error = "";
        if (atlasState.lastRender && typeof root.requestAnimationFrame === "function") {
          root.requestAnimationFrame(() => {
            const { canvas, state, options: lastOptions } = atlasState.lastRender;
            render(canvas, state, lastOptions);
          });
        }
      })
      .catch((error) => {
        atlasState.ready = false;
        atlasState.loading = false;
        atlasState.error = String(error?.message || error);
        if (root.console?.warn) root.console.warn("battle table atlas failed", error);
      });
  }

  function atlasSprite(name) {
    if (!atlasState.ready || !atlasState.manifest?.sprites || !atlasState.image) return null;
    return atlasState.manifest.sprites[name] || null;
  }

  function atlasPose(name) {
    return atlasState.manifest?.poses?.[name] || null;
  }

  function atlasWorldStyle() {
    return atlasState.manifest?.world_style || {};
  }

  function styleNumber(source, key, fallback, min = -Infinity, max = Infinity) {
    const value = Number(source?.[key]);
    if (!Number.isFinite(value)) return fallback;
    return clamp(value, min, max);
  }

  function setAtlasManifestForTest(manifest) {
    atlasState.url = DEFAULT_ATLAS_MANIFEST_URL;
    atlasState.loading = false;
    atlasState.ready = Boolean(manifest);
    atlasState.manifest = manifest || null;
    atlasState.image = null;
    atlasState.error = "";
  }

  function drawAtlasSprite(ctx, name, x, y, w, h) {
    const sprite = atlasSprite(name);
    if (!sprite) return false;
    markCanvasDraw("atlasDrawImageCalls");
    ctx.drawImage(
      atlasState.image,
      sprite.x,
      sprite.y,
      sprite.w,
      sprite.h,
      x,
      y,
      w,
      h
    );
    return true;
  }

  function tilePoseSpriteName(code, options = {}) {
    if (!code || code === "*") return null;
    const pose = String(options.pose || "");
    const direction = String(options.seatClass || "bottom");
    if (pose === "river") {
      const prefixes = atlasPose("river_tile")?.directional_sprite_prefixes || {};
      const prefix = prefixes[direction] || prefixes.bottom;
      return prefix ? `${prefix}${code}` : null;
    }
    if (pose === "public" && !options.claimed) {
      const prefixes = atlasPose("public_tile")?.directional_sprite_prefixes || {};
      const prefix = prefixes[direction] || prefixes.bottom;
      return prefix ? `${prefix}${code}` : null;
    }
    return null;
  }

  function latestDiscard(state) {
    const history = Array.isArray(state?.history) ? state.history : [];
    for (let i = history.length - 1; i >= 0; i -= 1) {
      if (history[i]?.event === "discard") return history[i];
    }
    return null;
  }

  function liveResponseDiscard(state, discardEvent) {
    const pending = state?.pending;
    if (!discardEvent || !pending || pending.kind !== "response_poll") return false;
    if (pending.response_kind && pending.response_kind !== "discard") return false;
    if (pending.tile && discardEvent.tile && String(pending.tile) !== String(discardEvent.tile)) return false;
    const pendingFrom = Number(pending.from);
    const discardSeat = Number(discardEvent.seat);
    if (Number.isInteger(pendingFrom) && Number.isInteger(discardSeat) && pendingFrom !== discardSeat) return false;
    return true;
  }

  function createRenderPlan(state, options = {}) {
    const tableModelApi = options.tableModelApi || root.BattleTableModel;
    if (!tableModelApi?.createBattleTableModel) {
      throw new Error("BattleTableModel is required before BattleTableRenderer");
    }
    const model = tableModelApi.createBattleTableModel(state, options.modelOptions || {});
    const players = Array.isArray(state?.players) ? state.players : [];
    const labels = { ...DEFAULT_LABELS, ...ZH_LABELS, ...(options.tileNames || {}) };
    const last = latestDiscard(state);
    const liveLast = liveResponseDiscard(state, last) ? last : null;
    const commands = [{ type: "table", bbox: { x: 0, y: 0, w: model.table.width, h: model.table.height } }];
    const center = model.blocks.find((block) => block.type === "center");
    if (center) {
      commands.push({
        type: "center",
        bbox: center.bbox,
        hud: createCenterHud(state, labels),
        labelBlocks: centerLabelBlocks(model),
      });
    }

    for (const player of players) {
      const seat = Number(player.seat);
      if (!Number.isInteger(seat)) continue;
      const handBlock = blockBy(model, "hand", seat);
      const riverBlock = blockBy(model, "river", seat);
      const publicBlock = blockBy(model, "public", seat);
      const handTiles = expandHand(player.hand);
      if (handBlock && seat !== 0) {
        const revealed = state?.phase === "round_over" && handTiles.length;
        commands.push({
          type: "hand",
          seat,
          seatClass: seatClass(seat),
          bbox: handBlock.bbox,
          localAngle: angleForSeat(seat),
          mode: revealed ? "revealed" : "standing",
          tileCount: Math.max(0, revealed ? handTiles.length : Number(player.hand_count) || handTiles.length || 0),
          tiles: handTiles,
          labels,
          backSprite: backSpriteForSeat(seat),
          layout: handBlock.layout,
          tileW: handBlock.metrics?.tileW,
          tileH: handBlock.metrics?.tileH,
          tileStep: handBlock.metrics?.step,
          projectionLean: Number(handBlock.metrics?.projectionLean) || 0,
        });
      }
      if (riverBlock) {
        const allDiscards = visibleDiscards(player);
        const displayDiscards = riverBlock.overflowCount
          ? allDiscards.slice(-riverBlock.visibleLimit)
          : allDiscards;
        commands.push({
          type: "river",
          seat,
          seatClass: seatClass(seat),
          bbox: riverBlock.bbox,
          localAngle: angleForSeat(seat),
          mode: riverBlock.mode,
          rows: riverBlock.rows,
          cols: riverBlock.cols,
          tiles: displayDiscards,
          overflowCount: riverBlock.overflowCount,
          latestTile: liveLast && Number(liveLast.seat) === seat ? liveLast.tile : null,
          layout: riverBlock.layout,
          labels,
        });
      }
      if (publicBlock && publicBlock.bbox.w > 0 && publicBlock.bbox.h > 0) {
        const melds = Array.isArray(player.melds) ? player.melds : [];
        const rows = renderRowsFromMetrics(publicBlock.metrics)
          || splitMeldRows(melds, model.config.publicArea.rowUnitLimit, tableModelApi);
        commands.push({
          type: "public",
          seat,
          seatClass: seatClass(seat),
          bbox: publicBlock.bbox,
          localAngle: angleForSeat(seat),
          mode: publicBlock.mode,
          metrics: publicBlock.metrics,
          flowers: publicFlowers(player),
          meldRows: rows,
          rowBlocks: publicRowBlocks(model, seat),
          layout: publicBlock.layout,
          labels,
        });
      }
    }
    return {
      version: "v7-canvas-render-plan-1",
      model,
      commands,
      hitBoxes: createTableHitBoxes(commands, model.config),
      diagnostics: model.diagnostics,
      ok: model.ok,
    };
  }

  function roundedRect(ctx, x, y, w, h, r) {
    const radius = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  function octagon(ctx, x, y, w, h, cut) {
    ctx.beginPath();
    ctx.moveTo(x + cut, y);
    ctx.lineTo(x + w - cut, y);
    ctx.lineTo(x + w, y + cut);
    ctx.lineTo(x + w, y + h - cut);
    ctx.lineTo(x + w - cut, y + h);
    ctx.lineTo(x + cut, y + h);
    ctx.lineTo(x, y + h - cut);
    ctx.lineTo(x, y + cut);
    ctx.closePath();
  }

  function traceTableFieldPath(ctx, width, height) {
    ctx.beginPath();
    ctx.moveTo(86, 24);
    ctx.lineTo(width - 86, 24);
    ctx.lineTo(width - 18, height - 20);
    ctx.lineTo(18, height - 20);
    ctx.closePath();
  }

  function drawWoodGrain(ctx, width, height) {
    const base = ctx.createLinearGradient(0, 0, 0, height);
    base.addColorStop(0, "#4b2816");
    base.addColorStop(0.34, "#7b4b28");
    base.addColorStop(0.68, "#5e341c");
    base.addColorStop(1, "#2f170d");
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, width, height);

    ctx.save();
    ctx.globalAlpha = 0.38;
    for (let y = 6; y < height; y += 13) {
      ctx.beginPath();
      for (let x = -20; x <= width + 20; x += 38) {
        const wave = Math.sin((x * 0.018) + (y * 0.09)) * 5;
        if (x <= -20) ctx.moveTo(x, y + wave);
        else ctx.lineTo(x, y + wave);
      }
      ctx.lineWidth = y % 3 === 0 ? 1.8 : 0.9;
      ctx.strokeStyle = y % 4 === 0 ? "rgba(255, 214, 137, 0.28)" : "rgba(35, 14, 6, 0.42)";
      ctx.stroke();
    }

    const knots = [
      { x: width * 0.18, y: height * 0.12, r: 44 },
      { x: width * 0.76, y: height * 0.86, r: 54 },
      { x: width * 0.92, y: height * 0.28, r: 34 },
    ];
    for (const knot of knots) {
      const glow = ctx.createRadialGradient(knot.x, knot.y, 2, knot.x, knot.y, knot.r);
      glow.addColorStop(0, "rgba(33, 12, 5, 0.36)");
      glow.addColorStop(0.46, "rgba(112, 63, 31, 0.22)");
      glow.addColorStop(1, "rgba(255, 211, 130, 0)");
      ctx.fillStyle = glow;
      ctx.fillRect(knot.x - knot.r, knot.y - knot.r, knot.r * 2, knot.r * 2);
    }
    ctx.restore();
  }

  function drawFrostedFelt(ctx, x, y, w, h, radius) {
    roundedRect(ctx, x, y, w, h, radius);
    ctx.clip();

    const felt = ctx.createRadialGradient(
      x + w * 0.52,
      y + h * 0.44,
      Math.max(12, w * 0.04),
      x + w * 0.5,
      y + h * 0.48,
      Math.max(w, h) * 0.62
    );
    felt.addColorStop(0, "#0d7b55");
    felt.addColorStop(0.52, "#0a6446");
    felt.addColorStop(1, "#063b2b");
    ctx.fillStyle = felt;
    ctx.fillRect(x, y, w, h);

    ctx.save();
    ctx.globalAlpha = 0.24;
    ctx.strokeStyle = "rgba(223, 255, 226, 0.16)";
    ctx.lineWidth = 1;
    for (let yy = y + 7; yy < y + h; yy += 9) {
      ctx.beginPath();
      ctx.moveTo(x + 10, yy);
      ctx.lineTo(x + w - 10, yy + Math.sin(yy * 0.07) * 1.4);
      ctx.stroke();
    }

    ctx.globalAlpha = 0.18;
    ctx.strokeStyle = "rgba(0, 25, 16, 0.36)";
    for (let xx = x + 14; xx < x + w; xx += 31) {
      ctx.beginPath();
      ctx.moveTo(xx, y + 8);
      ctx.lineTo(xx + Math.sin(xx * 0.05) * 2.5, y + h - 8);
      ctx.stroke();
    }

    ctx.globalAlpha = 0.2;
    for (let i = 0; i < 180; i += 1) {
      const px = x + ((i * 73) % Math.max(1, Math.floor(w)));
      const py = y + ((i * 47) % Math.max(1, Math.floor(h)));
      const light = i % 3 === 0;
      ctx.fillStyle = light ? "rgba(230, 255, 221, 0.28)" : "rgba(0, 26, 17, 0.18)";
      ctx.fillRect(px, py, i % 5 === 0 ? 2 : 1, 1);
    }
    ctx.restore();

    const vignette = ctx.createRadialGradient(
      x + w * 0.5,
      y + h * 0.46,
      w * 0.18,
      x + w * 0.5,
      y + h * 0.48,
      w * 0.58
    );
    vignette.addColorStop(0, "rgba(0, 0, 0, 0)");
    vignette.addColorStop(1, "rgba(0, 20, 13, 0.36)");
    ctx.fillStyle = vignette;
    ctx.fillRect(x, y, w, h);
  }

  function drawTexturedFlatTable(ctx, width, height, table = {}) {
    ctx.save();
    drawWoodGrain(ctx, width, height);

    const baseHeight = Math.max(1, Number(table.height) || 780);
    const extraY = Math.max(0, height - baseHeight);
    const baseField = table.fieldBBox || { x: 58, y: 32, w: width - 116, h: Math.max(1, baseHeight - 128) };
    const minWoodRailX = 26;
    const minWoodRailY = 22;
    const feltX = Math.max(minWoodRailX, baseField.x);
    const feltY = Math.max(minWoodRailY, baseField.y);
    const feltW = Math.max(1, Math.min(baseField.w, width - feltX * 2));
    const feltH = Math.max(1, Math.min(baseField.h + extraY, height - feltY - minWoodRailY));
    const framePad = 18;
    const frameX = Math.max(0, feltX - framePad);
    const frameY = Math.max(0, feltY - framePad);
    const frameW = Math.min(width - frameX, feltW + framePad * 2);
    const frameH = Math.min(height - frameY, feltH + framePad * 2);

    roundedRect(ctx, frameX, frameY, frameW, frameH, 24);
    ctx.fillStyle = "rgba(22, 10, 5, 0.76)";
    ctx.fill();
    ctx.lineWidth = 5;
    ctx.strokeStyle = "rgba(235, 188, 92, 0.42)";
    ctx.stroke();

    ctx.save();
    drawFrostedFelt(ctx, feltX, feltY, feltW, feltH, 18);
    ctx.restore();

    ctx.save();
    roundedRect(ctx, feltX, feltY, feltW, feltH, 18);
    ctx.clip();

    ctx.globalAlpha = 0.12;
    ctx.strokeStyle = "rgba(226, 255, 222, 0.28)";
    ctx.lineWidth = 1;
    for (let y = feltY + 10; y < feltY + feltH; y += 10) {
      ctx.beginPath();
      ctx.moveTo(feltX + 10, y);
      ctx.lineTo(feltX + feltW - 10, y);
      ctx.stroke();
    }

    ctx.globalAlpha = 0.08;
    ctx.strokeStyle = "rgba(0, 25, 16, 0.42)";
    for (let x = feltX + 12; x < feltX + feltW; x += 32) {
      ctx.beginPath();
      ctx.moveTo(x, feltY + 8);
      ctx.lineTo(x, feltY + feltH - 8);
      ctx.stroke();
    }

    ctx.globalAlpha = 1;
    ctx.strokeStyle = "rgba(255, 235, 155, 0.24)";
    ctx.lineWidth = 2;
    roundedRect(ctx, feltX, feltY, feltW, feltH, 18);
    ctx.stroke();
    ctx.restore();

    ctx.restore();
  }

  function drawTable(ctx, table, options = {}) {
    markCanvasDraw("tableDraws");
    const { width, height } = table;
    const drawHeight = Number(ctx.__battleLogicalHeight) || height;
    ctx.save();
    if (options.flatTable !== false) {
      drawTexturedFlatTable(ctx, width, drawHeight, table);
      ctx.restore();
      return;
    }

    const field = table.fieldBBox || { x: 58, y: 32, w: width - 116, h: height - 128 };
    const frame = ctx.createLinearGradient(0, 0, 0, height);
    frame.addColorStop(0, "#2b1710");
    frame.addColorStop(0.5, "#5a331c");
    frame.addColorStop(1, "#21100b");
    ctx.fillStyle = frame;
    ctx.fillRect(0, 0, width, height);

    roundedRect(
      ctx,
      field.x - 20,
      field.y - 18,
      field.w + 40,
      field.h + 36,
      22
    );
    ctx.fillStyle = "#1f120c";
    ctx.fill();
    ctx.lineWidth = 4;
    ctx.strokeStyle = "rgba(220, 170, 80, 0.55)";
    ctx.stroke();

    roundedRect(ctx, field.x, field.y, field.w, field.h, 16);
    const felt = ctx.createRadialGradient(
      width / 2,
      height * 0.42,
      width * 0.04,
      width / 2,
      height * 0.42,
      width * 0.56
    );
    felt.addColorStop(0, "#178a70");
    felt.addColorStop(0.64, "#0b6653");
    felt.addColorStop(1, "#064338");
    ctx.fillStyle = felt;
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(232, 204, 116, 0.42)";
    ctx.stroke();

    ctx.globalAlpha = 0.16;
    ctx.fillStyle = "#e4f6d9";
    for (let x = field.x + 42; x < field.x + field.w - 42; x += 58) {
      ctx.fillRect(x, field.y + 20, 22, 1.2);
      ctx.fillRect(x, field.y + field.h - 22, 22, 1.2);
    }
    ctx.restore();
  }

  function drawTablePerspectiveOverlay(_ctx, _width, _height, _atlasBacked = false) {
    // Flat table mode: keep the legacy hook, but do not draw perspective guides.
  }

  function drawCenterBase(ctx, bbox) {
    markCanvasDraw("centerBaseDraws");
    ctx.save();
    const cut = Math.max(24, Math.min(38, bbox.h * 0.16));
    ctx.shadowColor = "rgba(0, 10, 5, 0.28)";
    ctx.shadowBlur = 8;
    ctx.shadowOffsetY = 3;
    octagon(ctx, bbox.x, bbox.y, bbox.w, bbox.h, cut);
    ctx.fillStyle = "#182b2b";
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.lineWidth = Math.max(3, bbox.h * 0.018);
    ctx.strokeStyle = "rgba(239, 197, 96, 0.82)";
    ctx.stroke();

    octagon(ctx, bbox.x + 7, bbox.y + 7, bbox.w - 14, bbox.h - 14, Math.max(18, cut - 7));
    const inset = ctx.createLinearGradient(bbox.x, bbox.y, bbox.x, bbox.y + bbox.h);
    inset.addColorStop(0, "#124d45");
    inset.addColorStop(1, "#0b342f");
    ctx.fillStyle = inset;
    ctx.fill();

    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "rgba(247, 228, 151, 0.26)";
    ctx.stroke();
    ctx.restore();
  }

  function drawCenterPhysicalOverlay(ctx, bbox, atlasBacked = false) {
    markCanvasDraw("centerPhysicalOverlayDraws");
    const style = atlasWorldStyle().center_overlay || {};
    const topLightAlpha = styleNumber(style, "top_light_alpha", atlasBacked ? 0.38 : 0.28, 0, 0.72);
    const edgeAlpha = styleNumber(style, "edge_alpha", 0.58, 0, 0.9);
    const innerShadowAlpha = styleNumber(style, "inner_shadow_alpha", 0.42, 0, 0.85);
    const wellAlpha = styleNumber(style, "core_well_alpha", 0.34, 0, 0.72);
    const cut = Math.max(24, Math.min(40, bbox.h * 0.17));
    ctx.save();
    ctx.shadowBlur = 0;
    ctx.globalCompositeOperation = "source-over";

    ctx.globalAlpha = atlasBacked ? 0.58 : 0.42;
    octagon(ctx, bbox.x + 5, bbox.y + 4, bbox.w - 10, bbox.h - 8, Math.max(18, cut - 8));
    const topLight = ctx.createLinearGradient(bbox.x, bbox.y, bbox.x, bbox.y + bbox.h);
    topLight.addColorStop(0, `rgba(255, 240, 168, ${topLightAlpha})`);
    topLight.addColorStop(0.18, `rgba(255, 240, 168, ${topLightAlpha * 0.37})`);
    topLight.addColorStop(0.74, "rgba(0, 0, 0, 0.02)");
    topLight.addColorStop(1, "rgba(0, 0, 0, 0.26)");
    ctx.fillStyle = topLight;
    ctx.fill();

    ctx.globalAlpha = 0.88;
    octagon(ctx, bbox.x + 4, bbox.y + 4, bbox.w - 8, bbox.h - 8, Math.max(18, cut - 7));
    ctx.lineWidth = Math.max(2, bbox.h * 0.012);
    ctx.strokeStyle = `rgba(255, 218, 112, ${edgeAlpha})`;
    ctx.stroke();

    octagon(ctx, bbox.x + 14, bbox.y + 13, bbox.w - 28, bbox.h - 27, Math.max(15, cut - 16));
    ctx.lineWidth = Math.max(1.2, bbox.h * 0.008);
    ctx.strokeStyle = `rgba(23, 5, 0, ${innerShadowAlpha})`;
    ctx.stroke();

    const coreW = Math.max(112, Math.min(136, bbox.w * 0.37));
    const coreH = Math.max(80, Math.min(96, bbox.h * 0.44));
    const coreX = bbox.x + bbox.w / 2 - coreW / 2;
    const coreY = bbox.y + bbox.h / 2 - coreH / 2;
    roundedRect(ctx, coreX - 5, coreY - 5, coreW + 10, coreH + 10, 15);
    const well = ctx.createRadialGradient(
      bbox.x + bbox.w / 2,
      bbox.y + bbox.h / 2,
      coreW * 0.12,
      bbox.x + bbox.w / 2,
      bbox.y + bbox.h / 2,
      coreW * 0.78
    );
    well.addColorStop(0, "rgba(33, 118, 105, 0.22)");
    well.addColorStop(0.68, "rgba(0, 0, 0, 0.08)");
    well.addColorStop(1, `rgba(0, 0, 0, ${wellAlpha})`);
    ctx.fillStyle = well;
    ctx.fill();
    ctx.restore();
  }

  function drawBadge(ctx, x, y, text, color, textColor = "#fff3d5", radius = 7) {
    markCanvasDraw("badgeDraws");
    ctx.save();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = textColor;
    ctx.font = `900 ${Math.max(8, Math.floor(radius * 1.34))}px Microsoft YaHei, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x, y + 0.5);
    ctx.restore();
  }

  function drawCenterSeatCard(ctx, bbox, seatInfo, position, labelBlock = null) {
    const padX = Math.max(12, bbox.w * 0.038);
    const padY = Math.max(10, bbox.h * 0.045);
    const horizontalW = Math.max(124, Math.min(170, bbox.w * 0.42));
    const horizontalH = Math.max(38, Math.min(46, bbox.h * 0.19));
    const sideW = Math.max(94, Math.min(126, bbox.w * 0.31));
    const sideH = Math.max(38, Math.min(46, bbox.h * 0.19));
    const specs = {
      top: { x: bbox.x + bbox.w / 2 - horizontalW / 2, y: bbox.y + padY, w: horizontalW, h: horizontalH, align: "left" },
      bottom: { x: bbox.x + bbox.w / 2 - horizontalW / 2, y: bbox.y + bbox.h - padY - horizontalH, w: horizontalW, h: horizontalH, align: "left" },
      left: { x: bbox.x + padX, y: bbox.y + bbox.h / 2 - sideH / 2, w: sideW, h: sideH, align: "left" },
      right: { x: bbox.x + bbox.w - padX - sideW, y: bbox.y + bbox.h / 2 - sideH / 2, w: sideW, h: sideH, align: "right" },
    };
    const modelSpec = labelBlock?.bbox && Number.isFinite(labelBlock.bbox.x)
      ? {
        x: labelBlock.bbox.x,
        y: labelBlock.bbox.y,
        w: labelBlock.bbox.w,
        h: labelBlock.bbox.h,
        align: position === "right" ? "right" : "left",
      }
      : null;
    const spec = modelSpec || specs[position];
    if (!spec) return;
    ctx.save();
    roundedRect(ctx, spec.x, spec.y, spec.w, spec.h, Math.max(8, spec.h * 0.2));
    ctx.fillStyle = seatInfo.active ? "rgba(34, 128, 96, 0.94)" : "rgba(6, 20, 22, 0.58)";
    ctx.fill();
    ctx.lineWidth = seatInfo.active ? 2.2 : 1.2;
    ctx.strokeStyle = seatInfo.active ? "rgba(255, 211, 91, 0.94)" : "rgba(143, 210, 188, 0.28)";
    ctx.stroke();

    roundedRect(ctx, spec.x + 1, spec.y + 1, spec.w - 2, spec.h - 2, Math.max(7, spec.h * 0.18));
    ctx.clip();

    const windSize = Math.max(18, Math.min(26, spec.h - 10, spec.w * 0.23));
    const windX = position === "right" ? spec.x + spec.w - windSize / 2 - 5 : spec.x + windSize / 2 + 5;
    const windY = spec.y + spec.h / 2;
    const textX = position === "right" ? spec.x + 8 : spec.x + windSize + 12;
    const textRight = position === "right" ? spec.x + spec.w - windSize - 12 : spec.x + spec.w - 8;
    const textW = Math.max(28, textRight - textX);
    roundedRect(ctx, windX - windSize / 2, windY - windSize / 2, windSize, windSize, 7);
    ctx.fillStyle = seatInfo.active ? "#f2cf68" : "rgba(255, 246, 198, 0.16)";
    ctx.fill();
    ctx.fillStyle = seatInfo.active ? "#2b1d0a" : "#ffe69b";
    ctx.font = `900 ${Math.max(16, Math.floor(windSize * 0.66))}px Microsoft YaHei, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(seatInfo.wind || "-", windX, windY + 0.5);

    const badges = [];
    if (seatInfo.warning) badges.push(["!", "#c73328", "#fff3d5"]);
    if (seatInfo.bao) badges.push(["包", "#a81616", "#ffe3c1"]);
    if (seatInfo.dealer) badges.push(["庄", "#8d5b12", "#fff2bd"]);
    badges.forEach((badge, index) => {
      const r = 5.3;
      const bx = position === "right"
        ? spec.x + 8 + index * 12
        : spec.x + spec.w - 8 - index * 12;
      const by = spec.y + 7;
      drawBadge(ctx, bx, by, badge[0], badge[1], badge[2], r);
    });

    ctx.textAlign = position === "right" ? "right" : "left";
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = "#f4f2dc";
    ctx.font = `800 ${Math.max(11, Math.floor(spec.h * 0.28))}px Microsoft YaHei, sans-serif`;
    const name = truncateText(seatInfo.name || `A${seatInfo.seat}`, position === "top" || position === "bottom" ? 7 : 5);
    ctx.fillText(name, position === "right" ? textRight : textX, spec.y + spec.h * 0.44, textW);
    ctx.fillStyle = "rgba(214, 255, 210, 0.86)";
    ctx.font = `800 ${Math.max(10, Math.floor(spec.h * 0.24))}px Microsoft YaHei, sans-serif`;
    ctx.fillText(String(seatInfo.chips ?? "-"), position === "right" ? textRight : textX, spec.y + spec.h * 0.78, textW);
    ctx.restore();
  }

  function drawCenterHud(ctx, command) {
    markCanvasDraw("centerHudDraws");
    const bbox = command.bbox;
    const hud = command.hud;
    if (!bbox || !hud) return;
    ctx.save();
    roundedRect(ctx, bbox.x + 8, bbox.y + 8, bbox.w - 16, bbox.h - 16, Math.max(14, bbox.h * 0.07));
    ctx.clip();
    ctx.shadowColor = "rgba(0, 0, 0, 0.34)";
    ctx.shadowBlur = 3;
    const labelBlocks = command.labelBlocks || {};
    drawCenterSeatCard(ctx, bbox, hud.seats[2], "top", labelBlocks[2]);
    drawCenterSeatCard(ctx, bbox, hud.seats[3], "left", labelBlocks[3]);
    drawCenterSeatCard(ctx, bbox, hud.seats[1], "right", labelBlocks[1]);
    drawCenterSeatCard(ctx, bbox, hud.seats[0], "bottom", labelBlocks[0]);

    const coreW = Math.max(112, Math.min(136, bbox.w * 0.37));
    const coreH = Math.max(80, Math.min(96, bbox.h * 0.44));
    const coreX = bbox.x + bbox.w / 2 - coreW / 2;
    const coreY = bbox.y + bbox.h / 2 - coreH / 2;
    roundedRect(ctx, coreX, coreY, coreW, coreH, 12);
    ctx.fillStyle = "rgba(3, 34, 35, 0.78)";
    ctx.fill();
    ctx.lineWidth = 1.3;
    ctx.strokeStyle = "rgba(241, 210, 108, 0.42)";
    ctx.stroke();

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#f4df8a";
    ctx.font = `900 ${Math.max(14, Math.floor(coreH * 0.17))}px Microsoft YaHei, sans-serif`;
    ctx.fillText(`第 ${hud.roomRound || "-"} 局`, coreX + coreW / 2, coreY + coreH * 0.16);

    const indicatorX = coreX + coreW * 0.13;
    const indicatorY = coreY + coreH * 0.34;
    const indicatorW = Math.max(31, coreW * 0.27);
    const indicatorH = Math.max(39, coreH * 0.47);

    if (hud.indicatorMode === "bao") {
      roundedRect(ctx, indicatorX, indicatorY, indicatorW, indicatorH, 8);
      ctx.fillStyle = "#a81616";
      ctx.fill();
      ctx.fillStyle = "#ffe7c7";
      ctx.font = `900 ${Math.max(24, Math.floor(indicatorH * 0.64))}px Microsoft YaHei, sans-serif`;
      ctx.fillText("包", indicatorX + indicatorW / 2, indicatorY + indicatorH / 2 + 1);
    } else if (hud.indicatorTile) {
      drawTileFace(ctx, indicatorX, indicatorY, indicatorW, indicatorH, hud.indicatorTile, hud.labels, { shadow: false });
      ctx.fillStyle = "rgba(255, 226, 122, 0.95)";
      ctx.font = `900 ${Math.max(10, Math.floor(coreH * 0.12))}px Microsoft YaHei, sans-serif`;
      ctx.fillText("得", indicatorX + indicatorW / 2, indicatorY + indicatorH + coreH * 0.08);
    } else {
      ctx.fillStyle = "rgba(255, 226, 122, 0.95)";
      ctx.font = `900 ${Math.max(25, Math.floor(coreH * 0.34))}px Microsoft YaHei, sans-serif`;
      ctx.fillText("得", indicatorX + indicatorW / 2, indicatorY + indicatorH * 0.55);
    }

    const wallX = coreX + coreW * 0.72;
    ctx.fillStyle = "rgba(202, 255, 223, 0.8)";
    ctx.font = `800 ${Math.max(10, Math.floor(coreH * 0.13))}px Microsoft YaHei, sans-serif`;
    ctx.fillText("黄牌", wallX, coreY + coreH * 0.42);
    ctx.fillStyle = "#f8fff1";
    ctx.font = `900 ${Math.max(26, Math.floor(coreH * 0.34))}px Microsoft YaHei, sans-serif`;
    ctx.fillText(String(hud.wallRemaining ?? "-"), wallX, coreY + coreH * 0.64);
    ctx.font = `800 ${Math.max(9, Math.floor(coreH * 0.11))}px Microsoft YaHei, sans-serif`;
    ctx.fillStyle = "rgba(202, 255, 223, 0.8)";
    ctx.fillText("张", wallX, coreY + coreH * 0.86);
    ctx.restore();
  }

  function tileFaceColors(code) {
    const value = String(code || "");
    if (value.startsWith("m") || value === "zhong" || value.startsWith("rh")) return ["#27120f", "#c9332e"];
    if (value.startsWith("t") || value === "fa") return ["#0d3224", "#177b45"];
    if (value.startsWith("b")) return ["#111820", "#1c5b86"];
    return ["#171713", "#1c1c1c"];
  }

  function drawTileFace(ctx, x, y, w, h, code, labels, options = {}) {
    markCanvasDraw("tileDraws");
    ctx.save();
    ctx.shadowColor = options.shadow === false ? "transparent" : "rgba(0, 12, 7, 0.28)";
    ctx.shadowBlur = options.shadow === false ? 0 : Math.max(2, h * 0.06);
    ctx.shadowOffsetY = options.shadow === false ? 0 : Math.max(1, h * 0.05);
    roundedRect(ctx, x, y, w, h, Math.max(3, w * 0.12));
    const body = ctx.createLinearGradient(x, y, x, y + h);
    body.addColorStop(0, "#fffceb");
    body.addColorStop(0.72, "#eee7cf");
    body.addColorStop(1, "#d5ceb6");
    ctx.fillStyle = body;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(92, 82, 58, 0.38)";
    ctx.lineWidth = Math.max(1, w * 0.035);
    ctx.stroke();
    if (code === "*") {
      drawTileBack(ctx, x, y, w, h, { shadow: false });
      ctx.restore();
      return;
    }
    if (drawTileSvgIcon(ctx, x, y, w, h, code)) {
      ctx.restore();
      return;
    }
    const [ink, accent] = tileFaceColors(code);
    const label = tileLabel(code, labels);
    ctx.fillStyle = ink;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = `900 ${Math.max(10, Math.floor(h * 0.29))}px "Microsoft YaHei", "SimSun", serif`;
    if (/^[1-9][万条筒]$/.test(label)) {
      ctx.fillText(label.slice(0, 1), x + w / 2, y + h * 0.42);
      ctx.fillStyle = accent;
      ctx.font = `900 ${Math.max(9, Math.floor(h * 0.25))}px "Microsoft YaHei", "SimSun", serif`;
      ctx.fillText(label.slice(1), x + w / 2, y + h * 0.7);
    } else {
      ctx.fillStyle = accent;
      ctx.font = `900 ${Math.max(10, Math.floor(h * 0.34))}px "Microsoft YaHei", "SimSun", serif`;
      ctx.fillText(label.slice(0, 2), x + w / 2, y + h * 0.55);
    }
    ctx.restore();
  }

  function drawClaimedTileFace(ctx, x, y, w, h, code, labels, options = {}) {
    markCanvasDraw("claimedTileDraws");
    ctx.save();
    ctx.translate(x + w / 2, y + h / 2);
    ctx.rotate(Math.PI / 2);
    drawTileFace(ctx, -h / 2, -w / 2, h, w, code, labels, {
      ...options,
      pose: options.pose || "public",
      claimed: true,
    });
    ctx.restore();
  }

  function normalizeDepthStyle(style) {
    if (!style || typeof style !== "object") return null;
    const normalized = {
      depthRatio: Number(style.depthRatio ?? style.depth_ratio),
      edgeRatio: Number(style.edgeRatio ?? style.edge_ratio),
      highlightAlpha: Number(style.highlightAlpha ?? style.highlight_alpha),
      shadowAlpha: Number(style.shadowAlpha ?? style.shadow_alpha),
    };
    if (
      !Number.isFinite(normalized.depthRatio)
      || !Number.isFinite(normalized.edgeRatio)
      || !Number.isFinite(normalized.highlightAlpha)
      || !Number.isFinite(normalized.shadowAlpha)
    ) {
      return null;
    }
    return normalized;
  }

  function atlasDepthStyleForOptions(options = {}) {
    if (options.depthStyle) return normalizeDepthStyle(options.depthStyle);
    if (options.claimed) return normalizeDepthStyle(atlasPose("public_tile")?.claimed_depth_style);
    const pose = String(options.pose || "");
    if (pose === "river") return normalizeDepthStyle(atlasPose("river_tile")?.depth_style);
    if (pose === "public") return normalizeDepthStyle(atlasPose("public_tile")?.depth_style);
    return null;
  }

  function tileDepthProfile(options = {}) {
    if (options.poseDepth !== true) return null;
    if (options.depth === false) return null;
    return atlasDepthStyleForOptions(options);
  }

  function drawTileContactShadow(ctx, x, y, w, h, options = {}) {
    const profile = tileDepthProfile(options);
    if (!profile || options.shadow === false) return;
    markCanvasDraw("tileContactShadowDraws");
    const depth = clamp(Math.min(w, h) * profile.depthRatio, 1.2, Math.max(2.6, Math.min(w, h) * 0.16));
    ctx.save();
    ctx.shadowColor = `rgba(0, 9, 4, ${profile.shadowAlpha})`;
    ctx.shadowBlur = Math.max(1.4, depth * 1.25);
    ctx.shadowOffsetY = Math.max(0.8, depth * 0.52);
    ctx.fillStyle = `rgba(0, 14, 7, ${profile.shadowAlpha * 0.58})`;
    roundedRect(
      ctx,
      x + depth * 0.18,
      y + h - depth * 0.34,
      Math.max(1, w - depth * 0.1),
      Math.max(1.4, depth * 0.9),
      Math.max(1, depth * 0.5)
    );
    ctx.fill();
    ctx.restore();
  }

  function drawTilePoseDepth(ctx, x, y, w, h, _code, options = {}) {
    const profile = tileDepthProfile(options);
    if (!profile) return;
    markCanvasDraw("tilePoseDepthDraws");
    const depth = clamp(Math.min(w, h) * profile.depthRatio, 1.2, Math.max(2.8, Math.min(w, h) * 0.17));
    const edge = clamp(w * profile.edgeRatio, 1.1, Math.max(2.2, w * 0.16));
    const radius = Math.max(2.2, Math.min(w, h) * 0.12);
    const seat = String(options.seatClass || "bottom");
    const leftLit = seat === "right" || seat === "top";
    const rightLit = seat === "left" || seat === "bottom";
    ctx.save();
    roundedRect(ctx, x + 0.4, y + 0.4, w - 0.8, h - 0.8, radius);
    ctx.clip();

    const glaze = ctx.createLinearGradient(x, y, x + w, y + h);
    glaze.addColorStop(0, leftLit ? `rgba(255, 255, 232, ${profile.highlightAlpha})` : "rgba(0, 19, 11, 0.08)");
    glaze.addColorStop(0.48, "rgba(255, 255, 255, 0.018)");
    glaze.addColorStop(1, rightLit ? `rgba(255, 255, 232, ${profile.highlightAlpha * 0.82})` : "rgba(0, 0, 0, 0.17)");
    ctx.fillStyle = glaze;
    ctx.fillRect(x, y, w, h);

    ctx.fillStyle = "rgba(255, 255, 235, 0.34)";
    ctx.fillRect(x + edge, y + Math.max(0.8, depth * 0.18), Math.max(1, w - edge * 2), Math.max(1, depth * 0.34));

    ctx.fillStyle = leftLit ? "rgba(255, 252, 218, 0.22)" : "rgba(0, 31, 17, 0.16)";
    ctx.fillRect(x, y + depth * 0.55, edge, Math.max(1, h - depth * 1.4));
    ctx.fillStyle = rightLit ? "rgba(255, 252, 218, 0.22)" : "rgba(0, 23, 13, 0.2)";
    ctx.fillRect(x + w - edge, y + depth * 0.55, edge, Math.max(1, h - depth * 1.2));

    const lip = ctx.createLinearGradient(x, y + h - depth, x, y + h);
    lip.addColorStop(0, "rgba(0, 0, 0, 0.03)");
    lip.addColorStop(1, "rgba(75, 64, 42, 0.26)");
    ctx.fillStyle = lip;
    ctx.fillRect(x + edge * 0.45, y + h - depth, Math.max(1, w - edge * 0.9), depth);
    ctx.restore();

    ctx.save();
    ctx.lineWidth = Math.max(0.75, Math.min(w, h) * 0.028);
    ctx.strokeStyle = "rgba(255, 246, 205, 0.28)";
    roundedRect(ctx, x + 0.6, y + 0.6, w - 1.2, h - 1.2, radius);
    ctx.stroke();
    ctx.restore();
  }

  function drawTileBack(ctx, x, y, w, h, options = {}) {
    markCanvasDraw("tileBackDraws");
    ctx.save();
    ctx.shadowColor = options.shadow === false ? "transparent" : "rgba(0, 13, 8, 0.38)";
    ctx.shadowBlur = options.shadow === false ? 0 : Math.max(3, h * 0.08);
    ctx.shadowOffsetY = options.shadow === false ? 0 : Math.max(2, h * 0.08);
    roundedRect(ctx, x, y, w, h, Math.max(3, w * 0.12));
    const back = ctx.createLinearGradient(x, y, x, y + h);
    back.addColorStop(0, "#39d763");
    back.addColorStop(0.45, "#10a645");
    back.addColorStop(1, "#057337");
    ctx.fillStyle = back;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(246, 255, 220, 0.5)";
    ctx.lineWidth = Math.max(1, w * 0.04);
    ctx.stroke();
    ctx.globalAlpha = 0.38;
    ctx.fillStyle = "#ebffd7";
    roundedRect(ctx, x + w * 0.13, y + h * 0.1, w * 0.74, h * 0.08, 3);
    ctx.fill();
    ctx.globalAlpha = 0.18;
    ctx.fillStyle = "#044b29";
    roundedRect(ctx, x + w * 0.18, y + h * 0.28, w * 0.64, h * 0.48, Math.max(2, w * 0.1));
    ctx.fill();
    ctx.restore();
  }

  function drawTileSide(ctx, x, y, w, h, depth) {
    markCanvasDraw("tileSideDraws");
    ctx.save();
    ctx.fillStyle = "#d7d0ae";
    ctx.beginPath();
    ctx.moveTo(x + w, y + depth * 0.5);
    ctx.lineTo(x + w + depth, y);
    ctx.lineTo(x + w + depth, y + h - depth * 0.2);
    ctx.lineTo(x + w, y + h);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function drawHandWallBlockDepth(ctx, startX, y, width, tileW, tileH, seatClassName) {
    markCanvasDraw("handWallDepthDraws");
    const depth = Math.max(5, tileW * 0.28);
    const footY = y + tileH * 0.79;
    const footH = Math.max(8, tileH * 0.2);
    const lightFromRight = seatClassName === "left";
    ctx.save();

    ctx.shadowColor = "rgba(0, 8, 4, 0.34)";
    ctx.shadowBlur = Math.max(5, tileH * 0.11);
    ctx.shadowOffsetY = Math.max(2, tileH * 0.04);
    ctx.fillStyle = "rgba(0, 22, 12, 0.36)";
    roundedRect(ctx, startX - depth * 0.45, footY + footH * 0.22, width + depth * 0.9, footH * 0.8, footH * 0.35);
    ctx.fill();

    ctx.shadowBlur = 0;
    const base = ctx.createLinearGradient(startX, footY, startX + width, footY + footH);
    base.addColorStop(0, lightFromRight ? "rgba(17, 96, 49, 0.72)" : "rgba(3, 49, 28, 0.7)");
    base.addColorStop(0.48, "rgba(15, 125, 55, 0.7)");
    base.addColorStop(1, lightFromRight ? "rgba(3, 49, 28, 0.7)" : "rgba(17, 96, 49, 0.72)");
    roundedRect(ctx, startX - depth * 0.2, footY, width + depth * 0.4, footH, Math.max(4, footH * 0.25));
    ctx.fillStyle = base;
    ctx.fill();

    ctx.globalAlpha = 0.55;
    ctx.strokeStyle = "rgba(238, 249, 204, 0.55)";
    ctx.lineWidth = Math.max(1, tileW * 0.035);
    ctx.beginPath();
    ctx.moveTo(startX + 2, footY + 1);
    ctx.lineTo(startX + width - 2, footY + 1);
    ctx.stroke();

    ctx.globalAlpha = 0.42;
    ctx.fillStyle = lightFromRight ? "#d9d2b2" : "#a8a489";
    const sideX = lightFromRight ? startX + width - depth * 0.1 : startX - depth * 0.5;
    ctx.beginPath();
    ctx.moveTo(sideX, footY + 2);
    ctx.lineTo(sideX + (lightFromRight ? depth : -depth * 0.2), footY + footH * 0.28);
    ctx.lineTo(sideX + (lightFromRight ? depth * 0.86 : -depth * 0.34), footY + footH);
    ctx.lineTo(sideX, footY + footH * 0.86);
    ctx.closePath();
    ctx.fill();

    ctx.restore();
  }

  function drawStandingTileMaterialOverlay(ctx, x, y, w, h, seatClassName, index, count) {
    markCanvasDraw("standingTileOverlayDraws");
    const edge = Math.max(1.2, w * 0.08);
    const top = Math.max(1.4, h * 0.035);
    const leftLit = seatClassName === "right" || seatClassName === "top";
    const rightLit = seatClassName === "left";
    ctx.save();

    roundedRect(ctx, x + 0.4, y + 0.4, w - 0.8, h - 0.8, Math.max(3, w * 0.16));
    ctx.clip();

    const glaze = ctx.createLinearGradient(x, y, x + w, y + h);
    glaze.addColorStop(0, leftLit ? "rgba(255, 255, 226, 0.18)" : "rgba(0, 22, 12, 0.12)");
    glaze.addColorStop(0.48, "rgba(255, 255, 255, 0.02)");
    glaze.addColorStop(1, rightLit ? "rgba(255, 255, 226, 0.18)" : "rgba(0, 0, 0, 0.18)");
    ctx.fillStyle = glaze;
    ctx.fillRect(x, y, w, h);

    ctx.fillStyle = "rgba(255, 255, 230, 0.35)";
    ctx.fillRect(x + edge, y + top, w - edge * 2, Math.max(1, top));

    ctx.fillStyle = leftLit ? "rgba(255, 251, 214, 0.24)" : "rgba(0, 38, 18, 0.22)";
    ctx.fillRect(x, y + h * 0.08, edge, h * 0.74);
    ctx.fillStyle = rightLit ? "rgba(255, 251, 214, 0.24)" : "rgba(0, 24, 12, 0.26)";
    ctx.fillRect(x + w - edge, y + h * 0.1, edge, h * 0.78);

    ctx.fillStyle = "rgba(0, 0, 0, 0.2)";
    ctx.fillRect(x + edge * 0.5, y + h * 0.82, w - edge, Math.max(1.2, h * 0.035));
    ctx.restore();

    ctx.save();
    ctx.lineWidth = Math.max(0.8, w * 0.035);
    ctx.strokeStyle = "rgba(246, 255, 214, 0.32)";
    ctx.beginPath();
    ctx.moveTo(x + 0.7, y + 3);
    ctx.lineTo(x + 0.7, y + h - 4);
    ctx.stroke();
    ctx.strokeStyle = "rgba(0, 25, 12, 0.42)";
    ctx.beginPath();
    ctx.moveTo(x + w - 0.7, y + 4);
    ctx.lineTo(x + w - 0.7, y + h - 3);
    ctx.stroke();

    if (index === 0 || index === count - 1) {
      const capAlpha = index === 0 ? 0.28 : 0.38;
      ctx.fillStyle = `rgba(238, 232, 194, ${capAlpha})`;
      roundedRect(ctx, x - edge * 0.55, y + h * 0.12, edge * 0.95, h * 0.73, edge * 0.45);
      ctx.fill();
    }
    ctx.restore();
  }

  function remoteHandWallMaterialStyle() {
    const style = atlasPose("remote_hand_wall")?.material_overlay || {};
    return {
      topHighlightAlpha: styleNumber(style, "top_highlight_alpha", 0.3, 0, 0.8),
      seamAlpha: styleNumber(style, "seam_alpha", 0.18, 0, 0.65),
      sideShadeAlpha: styleNumber(style, "side_shade_alpha", 0.28, 0, 0.75),
      bottomShadeAlpha: styleNumber(style, "bottom_shade_alpha", 0.22, 0, 0.75),
      capAlpha: styleNumber(style, "cap_alpha", 0.34, 0, 0.85),
    };
  }

  function drawHandWallStripMaterialOverlay(ctx, startX, y, width, tileW, tileH, seatClassName, count, step) {
    if (!width || !tileH) return;
    markCanvasDraw("handWallStripOverlayDraws");
    const style = remoteHandWallMaterialStyle();
    const radius = Math.max(3, tileW * 0.16);
    const edge = Math.max(1.2, tileW * 0.08);
    const top = Math.max(1.4, tileH * 0.035);
    const leftLit = seatClassName === "right" || seatClassName === "top";
    const rightLit = seatClassName === "left";
    ctx.save();

    roundedRect(ctx, startX + 0.4, y + 0.4, width - 0.8, tileH - 0.8, radius);
    ctx.clip();

    const glaze = ctx.createLinearGradient(startX, y, startX + width, y + tileH);
    glaze.addColorStop(0, leftLit ? `rgba(255, 255, 226, ${style.topHighlightAlpha * 0.62})` : `rgba(0, 24, 12, ${style.sideShadeAlpha * 0.62})`);
    glaze.addColorStop(0.5, "rgba(255, 255, 255, 0.018)");
    glaze.addColorStop(1, rightLit ? `rgba(255, 255, 226, ${style.topHighlightAlpha * 0.62})` : `rgba(0, 0, 0, ${style.sideShadeAlpha})`);
    ctx.fillStyle = glaze;
    ctx.fillRect(startX, y, width, tileH);

    ctx.fillStyle = `rgba(255, 255, 235, ${style.topHighlightAlpha})`;
    ctx.fillRect(startX + edge, y + top, Math.max(1, width - edge * 2), Math.max(1, top));

    const bottom = ctx.createLinearGradient(startX, y + tileH * 0.68, startX, y + tileH);
    bottom.addColorStop(0, "rgba(0, 0, 0, 0)");
    bottom.addColorStop(1, `rgba(0, 0, 0, ${style.bottomShadeAlpha})`);
    ctx.fillStyle = bottom;
    ctx.fillRect(startX, y + tileH * 0.62, width, tileH * 0.38);

    const seamCount = Math.max(0, Math.min(16, Number(count) - 1));
    if (seamCount > 0 && style.seamAlpha > 0.01) {
      ctx.strokeStyle = `rgba(0, 24, 12, ${style.seamAlpha})`;
      ctx.lineWidth = Math.max(0.7, tileW * 0.025);
      for (let i = 1; i <= seamCount; i += 1) {
        const x = startX + i * step;
        ctx.beginPath();
        ctx.moveTo(x, y + tileH * 0.08);
        ctx.lineTo(x, y + tileH * 0.88);
        ctx.stroke();
      }
    }
    ctx.restore();

    ctx.save();
    ctx.fillStyle = `rgba(238, 232, 194, ${style.capAlpha})`;
    roundedRect(ctx, startX - edge * 0.55, y + tileH * 0.12, edge * 0.95, tileH * 0.73, edge * 0.45);
    ctx.fill();
    roundedRect(ctx, startX + width - edge * 0.4, y + tileH * 0.13, edge * 0.95, tileH * 0.72, edge * 0.45);
    ctx.fill();
    ctx.strokeStyle = `rgba(246, 255, 214, ${style.topHighlightAlpha * 0.92})`;
    ctx.lineWidth = Math.max(0.8, tileW * 0.035);
    ctx.beginPath();
    ctx.moveTo(startX + 0.7, y + 3);
    ctx.lineTo(startX + 0.7, y + tileH - 4);
    ctx.moveTo(startX + width - 0.7, y + 4);
    ctx.lineTo(startX + width - 0.7, y + tileH - 3);
    ctx.stroke();
    ctx.restore();
  }

  function transformToBlock(ctx, bbox, angle) {
    ctx.translate(bbox.x + bbox.w / 2, bbox.y + bbox.h / 2);
    ctx.rotate(angle || 0);
  }

  function clipBlockLocal(ctx, bbox, radius = 4) {
    void ctx;
    void bbox;
    void radius;
  }

  function localSizeForCommand(command) {
    const quarterTurns = Math.abs(Math.round((Number(command?.localAngle) || 0) / (Math.PI / 2))) % 2;
    return quarterTurns
      ? { w: command.bbox.h, h: command.bbox.w }
      : { w: command.bbox.w, h: command.bbox.h };
  }

  function clipCommandLocal(ctx, command, radius = 4) {
    void ctx;
    void command;
    void radius;
  }

  function clipLocalRect(ctx, r, radius = 4) {
    void ctx;
    void r;
    void radius;
  }

  function fitScaleToBox(contentW, contentH, boxW, boxH) {
    return Math.min(
      1,
      boxW > 0 ? boxW / Math.max(1, contentW) : 1,
      boxH > 0 ? boxH / Math.max(1, contentH) : 1
    );
  }

  function normalizedLayout(layout, fallbackAlign = "start") {
    const rawAlign = String(layout?.innerAlign || fallbackAlign || "start").toLowerCase();
    const innerAlign = rawAlign === "center" || rawAlign === "end" ? rawAlign : "start";
    const innerFlow = String(layout?.innerFlow || "forward").toLowerCase() === "reverse"
      ? "reverse"
      : "forward";
    return { innerAlign, innerFlow };
  }

  function contentOffset(boxSize, contentSize, align = "start") {
    const free = Math.max(0, Number(boxSize) - Number(contentSize));
    if (align === "center") return free / 2;
    if (align === "end") return free;
    return 0;
  }

  function centeredLocalY(boxH, contentH) {
    return -boxH / 2 + contentOffset(boxH, contentH, "center");
  }

  function alignedLocalStart(boxW, contentW, layout) {
    return -boxW / 2 + contentOffset(boxW, contentW, layout.innerAlign);
  }

  function lineFirstX(boxW, contentW, tileW, layout) {
    const left = alignedLocalStart(boxW, contentW, layout);
    return layout.innerFlow === "reverse" ? left + contentW - tileW : left;
  }

  function lineAdvance(step, layout) {
    return layout.innerFlow === "reverse" ? -step : step;
  }

  function gridColumnIndex(col, cols, layout) {
    return layout.innerFlow === "reverse" ? Math.max(0, cols - 1 - col) : col;
  }

  function rowContentOrigin(rowBox, contentW, contentH, layout) {
    const fitScale = fitScaleToBox(contentW, contentH, rowBox.w, rowBox.h);
    const effectiveW = rowBox.w / Math.max(0.001, fitScale);
    const effectiveH = rowBox.h / Math.max(0.001, fitScale);
    return {
      fitScale,
      x: contentOffset(effectiveW, contentW, layout.innerAlign),
      y: contentOffset(effectiveH, contentH, "center"),
    };
  }

  function drawHandWall(ctx, command, tableConfig) {
    const count = Math.max(0, Math.min(command.tileCount || 0, 17));
    if (!count) return;
    let tileW = Number(command.tileW) > 0 ? Number(command.tileW) : tableConfig.remoteHand.tileW;
    let tileH = Number(command.tileH) > 0 ? Number(command.tileH) : tableConfig.remoteHand.tileH;
    const step = Number(command.tileStep) > 0
      ? Number(command.tileStep)
      : command.mode === "revealed"
        ? tileW + Number(tableConfig.remoteHand.revealedGap || 1)
        : tileW - tableConfig.remoteHand.overlap;
    let tileStep = step;
    let width = tileW + Math.max(0, count - 1) * tileStep;
    const localBox = localSizeForCommand(command);
    const scale = fitScaleToBox(width, tileH, localBox.w, localBox.h);
    if (scale < 1) {
      tileW *= scale;
      tileH *= scale;
      tileStep *= scale;
      width = tileW + Math.max(0, count - 1) * tileStep;
    }
    ctx.save();
    transformToBlock(ctx, command.bbox, command.localAngle);
    clipCommandLocal(ctx, command, Math.max(3, tileW * 0.12));
    const layout = normalizedLayout(command.layout, "start");
    const startX = lineFirstX(localBox.w, width, tileW, layout);
    const stepX = lineAdvance(tileStep, layout);
    const y = centeredLocalY(localBox.h, tileH);
    if (command.mode === "revealed" && command.tiles.length) {
      command.tiles.slice(0, 17).forEach((code, idx) => {
        drawTileFace(ctx, startX + idx * stepX, y, tileW, tileH, code, command.labels, { shadow: true });
      });
    } else {
      const spriteName = command.backSprite || "tile_back_standing";
      for (let i = 0; i < count; i += 1) {
        const x = startX + i * stepX;
        drawTileBack(ctx, x, y, tileW, tileH, { shadow: true, spriteName });
      }
    }
    ctx.restore();
  }

  function drawRiver(ctx, command, tableConfig) {
    const dense = command.mode === "dense";
    let tileW = tableConfig.river.tileW * (dense ? 0.9 : 1);
    let tileH = tableConfig.river.tileH * (dense ? 0.9 : 1);
    let gap = tableConfig.river.gap;
    let width = command.cols * tileW + Math.max(0, command.cols - 1) * gap;
    let height = command.rows * tileH + Math.max(0, command.rows - 1) * gap;
    ctx.save();
    transformToBlock(ctx, command.bbox, command.localAngle);
    clipCommandLocal(ctx, command, 4);
    const localBox = localSizeForCommand(command);
    const fitScale = fitScaleToBox(width, height, localBox.w, localBox.h);
    if (fitScale < 1) {
      tileW *= fitScale;
      tileH *= fitScale;
      gap *= fitScale;
      width = command.cols * tileW + Math.max(0, command.cols - 1) * gap;
      height = command.rows * tileH + Math.max(0, command.rows - 1) * gap;
    }
    const layout = normalizedLayout(command.layout, "start");
    const startX = alignedLocalStart(localBox.w, width, layout);
    const startY = -localBox.h / 2 + contentOffset(localBox.h, height, layout.innerAlign);
    command.tiles.forEach((code, idx) => {
      const col = idx % command.cols;
      const row = Math.floor(idx / command.cols);
      const visualCol = gridColumnIndex(col, command.cols, layout);
      const x = startX + visualCol * (tileW + gap);
      const y = startY + row * (tileH + gap);
      const liveLatest = command.latestTile && idx === command.tiles.length - 1 && command.latestTile === code;
      if (liveLatest) {
        ctx.save();
        ctx.translate(x + tileW / 2, y + tileH / 2);
        ctx.scale(1.28, 1.28);
        drawTileFace(ctx, -tileW / 2, -tileH / 2, tileW, tileH, code, command.labels, {
          shadow: true,
          pose: "river",
          seatClass: command.seatClass,
        });
        ctx.restore();
        ctx.strokeStyle = "#ffd45d";
        ctx.lineWidth = 2.6;
        roundedRect(ctx, x - tileW * 0.15, y - tileH * 0.15, tileW * 1.3, tileH * 1.3, 5);
        ctx.stroke();
      } else {
        drawTileFace(ctx, x, y, tileW, tileH, code, command.labels, {
          shadow: true,
          pose: "river",
          seatClass: command.seatClass,
        });
      }
    });
    if (command.overflowCount) {
      ctx.fillStyle = "rgba(119, 26, 19, 0.92)";
      roundedRect(ctx, startX + width - 8, startY + height - 12, 28, 18, 8);
      ctx.fill();
      ctx.fillStyle = "#ffe8d0";
      ctx.font = "900 12px Microsoft YaHei, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(`+${command.overflowCount}`, startX + width + 6, startY + height - 3);
    }
    ctx.restore();
  }

  function drawMeldRow(ctx, melds, ownerSeat, labels, tileW, tileH, gap, seatClassName, layout = { innerFlow: "forward" }) {
    const reverse = layout.innerFlow === "reverse";
    let x = reverse ? meldRowWidth(melds, ownerSeat, tileW, tileH, gap) : 0;
    for (const meld of melds || []) {
      const entries = meldDisplayEntries(meld, ownerSeat);
      for (const entry of entries) {
        const w = entry.claimed ? tileH : tileW;
        if (reverse) x -= w;
        if (entry.claimed) {
          drawClaimedTileFace(ctx, x, 0, tileH, tileW, entry.code, labels, {
            shadow: true,
            pose: "public",
            seatClass: seatClassName,
          });
        } else {
          drawTileFace(ctx, x, 0, tileW, tileH, entry.code, labels, {
            shadow: true,
            pose: "public",
            seatClass: seatClassName,
          });
        }
        x += reverse ? -gap : w + gap;
      }
      x += reverse ? -gap : gap;
    }
  }

  function meldRowWidth(melds, ownerSeat, tileW, tileH, gap) {
    let x = 0;
    for (const meld of melds || []) {
      const entries = meldDisplayEntries(meld, ownerSeat);
      for (const entry of entries) {
        x += (entry.claimed ? tileH : tileW) + gap;
      }
      x += gap;
    }
    return Math.max(0, x - gap);
  }

  function drawFlowerStackBadge(ctx, x, y, w, h, hiddenCount, totalCount) {
    markCanvasDraw("flowerBadgeDraws");
    ctx.save();
    ctx.shadowColor = "rgba(0, 12, 7, 0.32)";
    ctx.shadowBlur = Math.max(2, h * 0.06);
    ctx.shadowOffsetY = Math.max(1, h * 0.05);
    for (let i = 2; i >= 0; i -= 1) {
      const offset = i * Math.max(2, w * 0.035);
      roundedRect(ctx, x + offset, y - offset * 0.45, w - offset, h, Math.max(4, h * 0.12));
      const body = ctx.createLinearGradient(x, y, x, y + h);
      body.addColorStop(0, i === 0 ? "#fff4cf" : "#ded7b9");
      body.addColorStop(1, i === 0 ? "#d9cfae" : "#b8af92");
      ctx.fillStyle = body;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = 1;
      ctx.strokeStyle = i === 0 ? "rgba(121, 102, 55, 0.62)" : "rgba(80, 70, 48, 0.45)";
      ctx.stroke();
    }
    ctx.fillStyle = "#7f1d17";
    ctx.font = `900 ${Math.max(11, Math.floor(h * 0.34))}px Microsoft YaHei, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("花", x + w * 0.42, y + h * 0.42);
    ctx.fillStyle = "#1d2119";
    ctx.font = `900 ${Math.max(10, Math.floor(h * 0.28))}px Microsoft YaHei, sans-serif`;
    ctx.fillText(`×${hiddenCount || totalCount}`, x + w * 0.63, y + h * 0.67);
    ctx.restore();
  }

  function drawPublic(ctx, command, tableConfig) {
    const metrics = command.metrics;
    const scale = metrics.scale || 1;
    const tileW = metrics.tileW || tableConfig.publicArea.tileW * scale;
    const tileH = metrics.tileH || tableConfig.publicArea.tileH * scale;
    const gap = metrics.gap || tableConfig.publicArea.gap * scale;
    const rowGap = tableConfig.publicArea.rowGap * scale;
    const drawRowInside = (rowBlock, contentW, contentH, drawFn) => {
      const box = rowBlock?.localBBox || rowBlock;
      if (!box || box.w <= 0 || box.h <= 0 || contentW <= 0 || contentH <= 0) return;
      const layout = normalizedLayout(rowBlock?.layout, "start");
      const placement = rowContentOrigin(box, contentW, contentH, layout);
      ctx.save();
      clipLocalRect(ctx, box, Math.max(3, Math.min(box.w, box.h) * 0.1));
      ctx.translate(box.x, box.y);
      if (placement.fitScale < 1) ctx.scale(placement.fitScale, placement.fitScale);
      ctx.translate(placement.x, placement.y);
      drawFn(placement.fitScale, layout);
      ctx.restore();
    };
    ctx.save();
    transformToBlock(ctx, command.bbox, command.localAngle);
    clipCommandLocal(ctx, command, 4);
    const startX = -metrics.width / 2;
    let y = -metrics.height / 2;
    if (command.flowers.length) {
      const flowerRow = command.rowBlocks?.flowers || { localBBox: { x: startX, y, w: metrics.width, h: tileH } };
      const flowerLayout = metrics.flowerLayout || {
        visibleCount: command.flowers.length,
        hiddenCount: 0,
        badgeUnits: 0,
      };
      const visibleCount = Math.min(command.flowers.length, flowerLayout.visibleCount);
      const visibleW = visibleCount > 0
        ? visibleCount * tileW + Math.max(0, visibleCount - 1) * gap
        : 0;
      const badgeW = flowerLayout.hiddenCount > 0
        ? flowerLayout.badgeUnits * tileW + Math.max(0, Math.ceil(flowerLayout.badgeUnits) - 1) * gap
        : 0;
      const contentW = visibleW + (badgeW > 0 ? (visibleCount > 0 ? gap : 0) + badgeW : 0);
      drawRowInside(flowerRow, contentW, tileH, (_fitScale, layout) => {
        const items = command.flowers.slice(0, visibleCount).map((code) => ({ type: "tile", code, w: tileW }));
        if (flowerLayout.hiddenCount > 0) items.push({ type: "badge", w: badgeW });
        let x = layout.innerFlow === "reverse" ? contentW : 0;
        items.forEach((item, idx) => {
          if (layout.innerFlow === "reverse") x -= item.w;
          if (item.type === "tile") {
            drawTileFace(ctx, x, 0, tileW, tileH, item.code, command.labels, {
              shadow: true,
              pose: "public",
              seatClass: command.seatClass,
            });
          } else {
            drawFlowerStackBadge(ctx, x, 0, item.w, tileH, flowerLayout.hiddenCount, flowerLayout.count);
          }
          x += layout.innerFlow === "reverse"
            ? (idx < items.length - 1 ? -gap : 0)
            : item.w + (idx < items.length - 1 ? gap : 0);
        });
      });
      y += tileH + rowGap;
    }
    if (command.meldRows.main.length) {
      const mainRow = command.rowBlocks?.main || { localBBox: { x: startX, y, w: metrics.width, h: tileH } };
      const contentW = meldRowWidth(command.meldRows.main, command.seat, tileW, tileH, gap);
      drawRowInside(mainRow, contentW, tileH, (_fitScale, layout) => {
        drawMeldRow(ctx, command.meldRows.main, command.seat, command.labels, tileW, tileH, gap, command.seatClass, layout);
      });
      y += tileH + rowGap;
    }
    if (command.meldRows.overflow.length) {
      const overflowRow = command.rowBlocks?.overflow || { localBBox: { x: startX, y, w: metrics.width, h: tileH } };
      const contentW = meldRowWidth(command.meldRows.overflow, command.seat, tileW, tileH, gap);
      drawRowInside(overflowRow, contentW, tileH, (_fitScale, layout) => {
        drawMeldRow(ctx, command.meldRows.overflow, command.seat, command.labels, tileW, tileH, gap, command.seatClass, layout);
      });
    }
    ctx.restore();
  }

  function ensureCanvasSize(canvas, table, options = {}) {
    const rect = canvas.getBoundingClientRect();
    const cssW = Math.max(1, Math.round(rect.width || canvas.parentElement?.clientWidth || table.width));
    const cssH = Math.max(1, Math.round(rect.height || canvas.parentElement?.clientHeight || table.height));
    const requestedDpr = Number(options.supersampleDpr);
    const dpr = Number.isFinite(requestedDpr)
      ? Math.min(4, Math.max(1, requestedDpr))
      : Math.min(3, Math.max(2, root.devicePixelRatio || 1));
    const pixelW = Math.round(cssW * dpr);
    const pixelH = Math.round(cssH * dpr);
    if (canvas.width !== pixelW || canvas.height !== pixelH) {
      canvas.width = pixelW;
      canvas.height = pixelH;
    }
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    const scale = pixelW / table.width;
    const logicalHeight = Math.max(
      Number(table.height) || 1,
      pixelH / Math.max(0.0001, scale)
    );
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.clearRect(0, 0, table.width, logicalHeight);
    ctx.__battleLogicalHeight = logicalHeight;
    ctx.__battleLayoutScaleY = logicalHeight / Math.max(1, Number(table.height) || logicalHeight);
    canvas.dataset.supersampleDpr = String(dpr);
    canvas.dataset.pixelWidth = String(pixelW);
    canvas.dataset.pixelHeight = String(pixelH);
    canvas.dataset.logicalHeight = String(Math.round(logicalHeight * 100) / 100);
    canvas.dataset.layoutScaleY = String(Math.round(ctx.__battleLayoutScaleY * 10000) / 10000);
    return ctx;
  }

  function displayBbox(ctx, bbox) {
    return bbox;
  }

  function renderMetricsFromPlan(plan) {
    return {
      version: "v7-render-performance-1",
      commandCount: plan.commands.length,
      hitBoxCount: plan.hitBoxes?.length || 0,
      canvasDrawCalls: 0,
      atlasDrawImageCalls: 0,
      tableDraws: 0,
      centerBaseDraws: 0,
      centerHudDraws: 0,
      centerPhysicalOverlayDraws: 0,
      badgeDraws: 0,
      tileDraws: 0,
      tileSvgImageDraws: 0,
      tileBackDraws: 0,
      claimedTileDraws: 0,
      tileSideDraws: 0,
      tileContactShadowDraws: 0,
      tilePoseDepthDraws: 0,
      poseSpriteDraws: 0,
      standingTileOverlayDraws: 0,
      handWallStripDraws: 0,
      handWallStripOverlayDraws: 0,
      tablePerspectiveOverlayDraws: 0,
      flowerBadgeDraws: 0,
      planMs: 0,
      drawMs: 0,
      totalMs: 0,
      firstFrameMs: 0,
    };
  }

  function writePerformanceDataset(canvas, metrics) {
    canvas.dataset.renderMs = String(metrics.totalMs);
    canvas.dataset.planMs = String(metrics.planMs);
    canvas.dataset.drawMs = String(metrics.drawMs);
    canvas.dataset.firstFrameMs = String(metrics.firstFrameMs);
    canvas.dataset.commandCount = String(metrics.commandCount);
    canvas.dataset.tableHitBoxCount = String(metrics.hitBoxCount);
    canvas.dataset.canvasDrawCalls = String(metrics.canvasDrawCalls);
    canvas.dataset.tileDraws = String(metrics.tileDraws);
    canvas.dataset.atlasDrawImageCalls = String(metrics.atlasDrawImageCalls);
  }

  function render(canvas, state, options = {}) {
    if (!canvas) return null;
    const totalStart = nowMs();
    ensureAtlas(options);
    tileImageState.lastRender = { canvas, state, options };
    ensureTileImages(options);
    atlasState.lastRender = { canvas, state, options };
    const planStart = nowMs();
    const plan = createRenderPlan(state, options);
    const planEnd = nowMs();
    const metrics = renderMetricsFromPlan(plan);
    metrics.planMs = roundedMs(planEnd - planStart);
    const previousMetrics = activeRenderMetrics;
    activeRenderMetrics = metrics;
    const drawStart = nowMs();
    const ctx = ensureCanvasSize(canvas, plan.model.table, options);
    try {
      drawTable(ctx, plan.model.table, options);
      if (options.drawCenter !== false) {
        for (const command of plan.commands) {
          if (command.type === "center") drawCenterBase(ctx, displayBbox(ctx, command.bbox));
        }
      }
      if (options.drawTiles !== false) {
        const tableConfig = plan.model.config;
        for (const command of plan.commands) {
          if (command.type === "hand") drawHandWall(ctx, { ...command, bbox: displayBbox(ctx, command.bbox) }, tableConfig);
        }
        for (const command of plan.commands) {
          if (command.type === "river") drawRiver(ctx, { ...command, bbox: displayBbox(ctx, command.bbox) }, tableConfig);
        }
        for (const command of plan.commands) {
          if (command.type === "public") drawPublic(ctx, { ...command, bbox: displayBbox(ctx, command.bbox) }, tableConfig);
        }
      }
      if (options.drawCenter !== false) {
        for (const command of plan.commands) {
          if (command.type === "center") drawCenterHud(ctx, { ...command, bbox: displayBbox(ctx, command.bbox) });
        }
      }
    } finally {
      activeRenderMetrics = previousMetrics;
    }
    const drawEnd = nowMs();
    metrics.drawMs = roundedMs(drawEnd - drawStart);
    metrics.totalMs = roundedMs(drawEnd - totalStart);
    if (!canvas.dataset.firstFrameMs || Number(canvas.dataset.firstFrameMs) <= 0) {
      metrics.firstFrameMs = roundedMs(drawEnd);
    } else {
      metrics.firstFrameMs = Number(canvas.dataset.firstFrameMs) || 0;
    }
    plan.performance = metrics;
    canvas.dataset.tableModelOk = plan.ok ? "1" : "0";
    canvas.dataset.diagnostics = String(plan.diagnostics.length);
    canvas.dataset.atlasReady = atlasState.ready ? "1" : "0";
    canvas.dataset.atlasError = atlasState.error || "";
    canvas.__battleTableHitBoxes = plan.hitBoxes || [];
    root.tableHitBoxes = plan.hitBoxes || [];
    writePerformanceDataset(canvas, metrics);
    return plan;
  }

  function renderInto(container, state, options = {}) {
    if (!container) return null;
    const canvas = container.querySelector("#tableCanvas");
    return canvas ? render(canvas, state, options) : null;
  }

  return {
    createRenderPlan,
    render,
    renderInto,
    ensureAtlas,
    __setAtlasManifestForTest: setAtlasManifestForTest,
    atlasStatus: () => ({
      url: atlasState.url,
      loading: atlasState.loading,
      ready: atlasState.ready,
      error: atlasState.error,
      spriteCount: Object.keys(atlasState.manifest?.sprites || {}).length,
      worldStyleVersion: atlasState.manifest?.world_style?.version || "",
      poseDepthStyles: {
        river: Boolean(atlasPose("river_tile")?.depth_style),
        public: Boolean(atlasPose("public_tile")?.depth_style),
        claimed: Boolean(atlasPose("public_tile")?.claimed_depth_style),
      },
      poseSpriteStyles: {
        river: Boolean(atlasPose("river_tile")?.directional_sprite_prefixes),
        public: Boolean(atlasPose("public_tile")?.directional_sprite_prefixes),
      },
      poseMaterialStyles: {
        remoteHandWall: Boolean(atlasPose("remote_hand_wall")?.material_overlay),
      },
    }),
    expandHand,
    meldDisplayEntries,
    splitMeldRows,
    tileLabel,
  };
});
