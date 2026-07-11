(() => {
  "use strict";

  const PHOTON_BUDGETS = Object.freeze({
    desktop: Object.freeze({ particles: 220, maxLinks: 1100, movingLights: 2, pixelRatio: 1.5 }),
    mobile: Object.freeze({ particles: 110, maxLinks: 420, movingLights: 1, pixelRatio: 1.2 }),
    low: Object.freeze({ particles: 60, maxLinks: 160, movingLights: 0, pixelRatio: 1.0 }),
    canvas: Object.freeze({ particles: 60, mobileParticles: 36, maxLinks: 120, pixelRatio: 1.0 }),
    static: Object.freeze({ particles: 0, maxLinks: 0, movingLights: 0, pixelRatio: 1.0 }),
  });

  function selectInitialQuality({ width, coarse, reducedMotion, webgl2 }) {
    if (reducedMotion) return "static";
    if (!webgl2) return "canvas";
    return coarse || width <= 760 ? "mobile" : "desktop";
  }

  function nextQuality(current, averageFrameMs) {
    if ((current === "desktop" || current === "mobile") && averageFrameMs > 24) return "low";
    if (current === "low" && averageFrameMs > 32) return "canvas";
    return current;
  }

  function tileGroupPosition(page, viewportWidth) {
    if (page === "lobby") return [2.5, 0.25, 0];
    if (Number(viewportWidth) <= 760) return [0, 1.15, 0];
    return [-2.6, 0.25, 0];
  }

  const testExports = { PHOTON_BUDGETS, selectInitialQuality, nextQuality, tileGroupPosition };
  if (typeof module !== "undefined" && module.exports) {
    module.exports = testExports;
    return;
  }
  if (typeof window === "undefined" || typeof document === "undefined") return;

  const root = document.getElementById("photonSceneRoot");
  if (!root || (root.dataset.page !== "auth" && root.dataset.page !== "lobby")) return;

  const pendingTimers = new Map();
  let activeLayer = null;
  let destroyed = false;
  let effectBoostUntil = 0;

  function setRootMode(mode, quality = mode) {
    root.dataset.photonMode = mode;
    root.dataset.photonQuality = quality;
    root.setAttribute("data-photon-mode", mode);
  }

  function supportsWebGL2() {
    try {
      const canvas = document.createElement("canvas");
      return Boolean(canvas.getContext("webgl2"));
    } catch {
      return false;
    }
  }

  function scheduleTimer(callback, ms) {
    const timerId = window.setTimeout(() => {
      pendingTimers.delete(timerId);
      if (!destroyed) callback();
    }, ms);
    pendingTimers.set(timerId, null);
    return timerId;
  }

  function cancelTimer(timerId) {
    if (!pendingTimers.has(timerId)) return;
    const settle = pendingTimers.get(timerId);
    window.clearTimeout(timerId);
    pendingTimers.delete(timerId);
    settle?.();
  }

  function wait(ms) {
    if (destroyed) return Promise.resolve();
    return new Promise((resolve) => {
      const timerId = window.setTimeout(() => {
        pendingTimers.delete(timerId);
        resolve();
      }, ms);
      pendingTimers.set(timerId, resolve);
    });
  }

  function clearPendingTimers() {
    for (const [timerId, settle] of pendingTimers) {
      window.clearTimeout(timerId);
      settle?.();
    }
    pendingTimers.clear();
  }

  function sceneTransition(name, duration) {
    if (destroyed || root.dataset.photonMode === "static") return Promise.resolve();
    root.dataset.photonTransition = name;
    effectBoostUntil = performance.now() + duration;
    return wait(duration).finally(() => {
      if (root.dataset.photonTransition === name) delete root.dataset.photonTransition;
    });
  }

  function disposeActiveLayer() {
    if (!activeLayer) return;
    activeLayer.destroy();
    activeLayer = null;
  }

  function startStaticFallback() {
    disposeActiveLayer();
    setRootMode("static");
    root.replaceChildren();
  }

  function startCanvasFallback() {
    disposeActiveLayer();
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) return startStaticFallback();
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const count = coarse ? PHOTON_BUDGETS.canvas.mobileParticles : PHOTON_BUDGETS.canvas.particles;
    const points = Array.from({ length: count }, (_, index) => ({
      x: Math.random(), y: Math.random(),
      vx: (Math.random() - 0.5) * 0.00018,
      vy: (Math.random() - 0.5) * 0.00018,
      radius: index % 9 === 0 ? 1.8 : 0.8,
    }));
    let frameId = 0;
    let running = true;

    function resize() {
      canvas.width = Math.max(1, Math.round(root.clientWidth));
      canvas.height = Math.max(1, Math.round(root.clientHeight));
    }

    function render() {
      frameId = 0;
      if (!running || document.hidden) return;
      context.clearRect(0, 0, canvas.width, canvas.height);
      for (const point of points) {
        point.x = (point.x + point.vx + 1) % 1;
        point.y = (point.y + point.vy + 1) % 1;
        context.beginPath();
        context.arc(point.x * canvas.width, point.y * canvas.height, point.radius, 0, Math.PI * 2);
        context.fillStyle = "rgba(104, 245, 255, 0.62)";
        context.shadowBlur = point.radius > 1 ? 10 : 3;
        context.shadowColor = "#68f5ff";
        context.fill();
      }
      context.shadowBlur = 0;
      root.dataset.photonFrames = String(Number(root.dataset.photonFrames || "0") + 1);
      frameId = window.requestAnimationFrame(render);
    }

    function resume() {
      if (running && !frameId && !document.hidden) frameId = window.requestAnimationFrame(render);
    }

    resize();
    root.replaceChildren(canvas);
    setRootMode("canvas");
    window.addEventListener("resize", resize);

    activeLayer = {
      pause() { if (frameId) window.cancelAnimationFrame(frameId); frameId = 0; },
      resume,
      destroy() {
        running = false;
        if (frameId) window.cancelAnimationFrame(frameId);
        window.removeEventListener("resize", resize);
        canvas.remove();
      },
    };
    activeLayer.resume();
  }

  function startThreeLayer(THREE, quality) {
    disposeActiveLayer();
    const budget = PHOTON_BUDGETS[quality];
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: quality === "desktop", powerPreference: "high-performance" });
    const ownedGeometries = new Set();
    const ownedMaterials = new Set();
    const ownedTextures = new Set();
    const ownedCanvases = new Set();
    let resizeListening = false;
    let contextLossListening = false;
    let cleaned = false;
    let animationRunning = false;
    let qualityTimerId = null;
    let layer = null;
    let resizeCallback = null;
    let contextLossCallback = null;
    let timer = null;

    function safely(callback) {
      try { callback(); } catch { /* Continue releasing the remaining resources. */ }
    }

    function ownGeometry(geometry) {
      ownedGeometries.add(geometry);
      return geometry;
    }

    function ownMaterial(material) {
      ownedMaterials.add(material);
      return material;
    }

    function ownTexture(texture) {
      ownedTextures.add(texture);
      return texture;
    }

    function ownCanvas(canvas) {
      ownedCanvases.add(canvas);
      return canvas;
    }

    function cleanup() {
      if (cleaned) return;
      cleaned = true;
      animationRunning = false;
      safely(() => renderer.setAnimationLoop(null));
      if (contextLossListening) {
        safely(() => renderer.domElement.removeEventListener("webglcontextlost", contextLossCallback));
        contextLossListening = false;
      }
      if (resizeListening) {
        safely(() => window.removeEventListener("resize", resizeCallback));
        resizeListening = false;
      }
      for (const texture of ownedTextures) safely(() => texture.dispose?.());
      for (const material of ownedMaterials) safely(() => material.dispose?.());
      for (const geometry of ownedGeometries) safely(() => geometry.dispose?.());
      for (const canvas of ownedCanvases) {
        safely(() => canvas.remove?.());
        safely(() => { canvas.width = 0; canvas.height = 0; });
      }
      safely(() => timer?.dispose());
      timer = null;
      safely(() => renderer.dispose());
      safely(() => renderer.domElement.remove());
    }

    try {
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, budget.pixelRatio));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x04090b, 0);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x04090b, 0.065);
    const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 80);
    camera.position.set(0, 0, 12);

    const particleGeometry = ownGeometry(new THREE.BufferGeometry());
    const particlePositions = new Float32Array(budget.particles * 3);
    for (let i = 0; i < budget.particles; i += 1) {
      particlePositions[i * 3] = (Math.random() - 0.5) * 18;
      particlePositions[i * 3 + 1] = (Math.random() - 0.5) * 10;
      particlePositions[i * 3 + 2] = (Math.random() - 0.5) * 8;
    }
    particleGeometry.setAttribute("position", new THREE.BufferAttribute(particlePositions, 3));
    const particleMaterial = ownMaterial(new THREE.PointsMaterial({ color: 0x68f5ff, size: quality === "mobile" ? 0.055 : 0.045, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false }));
    const particles = new THREE.Points(particleGeometry, particleMaterial);
    scene.add(particles);

    const linkGeometry = ownGeometry(new THREE.BufferGeometry());
    const linkPositions = new Float32Array(budget.maxLinks * 6);
    linkGeometry.setAttribute("position", new THREE.BufferAttribute(linkPositions, 3));
    linkGeometry.setDrawRange(0, 0);
    const linkMaterial = ownMaterial(new THREE.LineBasicMaterial({ color: 0x4cb0be, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending }));
    const links = new THREE.LineSegments(linkGeometry, linkMaterial);
    scene.add(links);

    const ambient = new THREE.AmbientLight(0x8fdde2, 0.42);
    const keyLight = new THREE.DirectionalLight(0xdfffff, 2.2);
    keyLight.position.set(3, 5, 7);
    scene.add(ambient, keyLight);
    const movingLights = Array.from({ length: budget.movingLights }, (_, index) => {
      const light = new THREE.PointLight(index ? 0xffb85c : 0x68f5ff, 24, 16, 2);
      scene.add(light);
      return light;
    });
    if (quality !== "desktop") {
      const staticLight = new THREE.PointLight(0xffd08a, quality === "low" ? 14 : 18, 14, 2);
      staticLight.position.set(-3.2, 2.2, 3.5);
      scene.add(staticLight);
    }

    function tileTexture(glyph, glyphColor) {
      const canvas = ownCanvas(document.createElement("canvas"));
      canvas.width = 256;
      canvas.height = 320;
      const context = canvas.getContext("2d");
      context.fillStyle = "#eef9f6";
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.strokeStyle = "#79dfe3";
      context.lineWidth = 10;
      context.strokeRect(12, 12, canvas.width - 24, canvas.height - 24);
      context.fillStyle = glyphColor;
      context.font = "900 154px sans-serif";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(glyph, canvas.width / 2, canvas.height / 2 + 5);
      const texture = ownTexture(new THREE.CanvasTexture(canvas));
      texture.colorSpace = THREE.SRGBColorSpace;
      return texture;
    }

    const tileGroup = new THREE.Group();
    tileGroup.position.set(...tileGroupPosition(root.dataset.page, window.innerWidth));
    const tileGeometry = ownGeometry(new THREE.BoxGeometry(1.2, 1.6, 0.18));
    const glyphs = [
      ["發", "#167c61"],
      ["中", "#d44842"],
      ["白", "#173b3c"],
    ];
    const tiles = glyphs.map(([glyph, color], index) => {
      const front = ownMaterial(new THREE.MeshStandardMaterial({ map: tileTexture(glyph, color), roughness: 0.36, metalness: 0.06 }));
      const side = ownMaterial(new THREE.MeshStandardMaterial({ color: 0xc9f6ef, roughness: 0.42, metalness: 0.08 }));
      const back = ownMaterial(new THREE.MeshStandardMaterial({ color: 0x123f3d, emissive: 0x0b5f61, emissiveIntensity: 0.22 }));
      const mesh = new THREE.Mesh(tileGeometry, [side, side, side, side, front, back]);
      mesh.position.x = (index - 1) * 1.35;
      mesh.position.y = index === 1 ? 0.28 : 0;
      mesh.rotation.z = (index - 1) * 0.12;
      tileGroup.add(mesh);
      return mesh;
    });
    scene.add(tileGroup);

    const baseParticlePositions = particlePositions.slice();
    timer = new THREE.Timer();
    let sampleStartedAt = performance.now();
    let sampledFrames = 0;
    let restartScheduled = false;

    resizeCallback = function resize() {
      const width = Math.max(1, root.clientWidth);
      const height = Math.max(1, root.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };

    function updateLinks() {
      let linkCount = 0;
      const thresholdSquared = 1.45 * 1.45;
      for (let left = 0; left < budget.particles && linkCount < budget.maxLinks; left += 1) {
        const lx = particlePositions[left * 3];
        const ly = particlePositions[left * 3 + 1];
        const lz = particlePositions[left * 3 + 2];
        for (let right = left + 1; right < budget.particles && linkCount < budget.maxLinks; right += 1) {
          const rx = particlePositions[right * 3];
          const ry = particlePositions[right * 3 + 1];
          const rz = particlePositions[right * 3 + 2];
          const dx = lx - rx;
          const dy = ly - ry;
          const dz = lz - rz;
          if (dx * dx + dy * dy + dz * dz > thresholdSquared) continue;
          const offset = linkCount * 6;
          linkPositions.set([lx, ly, lz, rx, ry, rz], offset);
          linkCount += 1;
        }
      }
      linkGeometry.attributes.position.needsUpdate = true;
      linkGeometry.setDrawRange(0, linkCount * 2);
    }

    function scheduleQualityChange(next) {
      if (restartScheduled || next === quality) return;
      restartScheduled = true;
      renderer.setAnimationLoop(null);
      animationRunning = false;
      qualityTimerId = scheduleTimer(() => {
        qualityTimerId = null;
        if (destroyed || activeLayer !== layer) return;
        if (next === "canvas") startCanvasFallback();
        else startThreeLayerSafely(THREE, next);
      }, 0);
    }

    function renderFrame() {
      timer.update();
      const elapsed = timer.getElapsed();
      const now = performance.now();
      const boosted = now < effectBoostUntil;
      for (let index = 0; index < budget.particles; index += 1) {
        const offset = index * 3;
        particlePositions[offset] = baseParticlePositions[offset] + Math.sin(elapsed * 0.22 + index * 0.7) * 0.055;
        particlePositions[offset + 1] = baseParticlePositions[offset + 1] + Math.cos(elapsed * 0.18 + index * 0.51) * 0.05;
      }
      particleGeometry.attributes.position.needsUpdate = true;
      particleMaterial.opacity = boosted ? 0.96 : 0.78;
      particles.rotation.y = elapsed * 0.014;
      updateLinks();

      tiles.forEach((tile, index) => {
        tile.position.y = (index === 1 ? 0.28 : 0) + Math.sin(elapsed * 1.1 + index * 1.7) * (boosted ? 0.13 : 0.07);
        tile.rotation.y = Math.sin(elapsed * 0.55 + index) * 0.17;
      });
      tileGroup.rotation.y = Math.sin(elapsed * 0.24) * 0.08;
      movingLights.forEach((light, index) => {
        light.position.set(Math.sin(elapsed * 0.6 + index * Math.PI) * 5, Math.cos(elapsed * 0.47 + index) * 3, 4);
      });

      renderer.render(scene, camera);
      root.dataset.photonFrames = String(Number(root.dataset.photonFrames || "0") + 1);
      sampledFrames += 1;
      const sampleElapsed = now - sampleStartedAt;
      if (sampleElapsed >= 2000) {
        const averageFrameMs = sampleElapsed / Math.max(1, sampledFrames);
        const next = nextQuality(quality, averageFrameMs);
        sampleStartedAt = now;
        sampledFrames = 0;
        scheduleQualityChange(next);
      }
    }

    contextLossCallback = function onContextLost(event) {
      event.preventDefault();
      if (!destroyed) startCanvasFallback();
    };

    root.replaceChildren(renderer.domElement);
    setRootMode("three", quality);
    resizeCallback();
    window.addEventListener("resize", resizeCallback);
    resizeListening = true;
    renderer.domElement.addEventListener("webglcontextlost", contextLossCallback);
    contextLossListening = true;

    layer = {
      pause() {
        if (!animationRunning) return;
        renderer.setAnimationLoop(null);
        animationRunning = false;
      },
      resume() {
        if (animationRunning || restartScheduled || document.hidden || destroyed) return;
        timer.reset();
        sampleStartedAt = performance.now();
        sampledFrames = 0;
        animationRunning = true;
        renderer.setAnimationLoop(renderFrame);
      },
      destroy() {
        cancelTimer(qualityTimerId);
        qualityTimerId = null;
        cleanup();
      },
    };
    layer.resume();
    activeLayer = layer;
    } catch (error) {
      cleanup();
      throw error;
    }
  }

  function startThreeLayerSafely(THREE, quality) {
    try {
      startThreeLayer(THREE, quality);
    } catch (error) {
      console.warn("photon renderer unavailable; using canvas fallback", error);
      if (!destroyed) startCanvasFallback();
    }
  }

  async function boot() {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const quality = selectInitialQuality({
      width: window.innerWidth,
      coarse: window.matchMedia("(pointer: coarse)").matches,
      reducedMotion,
      webgl2: supportsWebGL2(),
    });
    if (quality === "static") return startStaticFallback();
    if (quality === "canvas") return startCanvasFallback();
    try {
      const THREE = await import("/vendor/three/three.module.min.js?v=0.185.1");
      if (!destroyed) startThreeLayerSafely(THREE, quality);
    } catch (error) {
      console.warn("photon scene unavailable; using canvas fallback", error);
      if (!destroyed) startCanvasFallback();
    }
  }

  function onVisibilityChange() {
    if (!activeLayer) return;
    if (document.hidden) activeLayer.pause();
    else activeLayer.resume();
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    disposeActiveLayer();
    document.removeEventListener("visibilitychange", onVisibilityChange);
    window.removeEventListener("pagehide", destroy);
    window.removeEventListener("beforeunload", destroy);
    clearPendingTimers();
    delete root.dataset.photonTransition;
    delete root.dataset.photonRoomChanges;
    effectBoostUntil = 0;
  }

  window.WenlingPhotonScene = {
    playAuthSuccess: () => destroyed ? Promise.resolve() : sceneTransition("auth-success", 650),
    playLobbyReveal: () => destroyed ? Promise.resolve() : sceneTransition("lobby-reveal", 620),
    notifyRoomChanges(changes) {
      if (destroyed) return;
      root.dataset.photonRoomChanges = JSON.stringify(changes || []);
      effectBoostUntil = performance.now() + 700;
      scheduleTimer(() => delete root.dataset.photonRoomChanges, 700);
    },
    setStatus(kind) {
      if (!destroyed) root.dataset.photonStatus = kind || "idle";
    },
    destroy,
  };

  document.addEventListener("visibilitychange", onVisibilityChange);
  window.addEventListener("pagehide", destroy, { once: true });
  window.addEventListener("beforeunload", destroy, { once: true });
  boot();
})();
