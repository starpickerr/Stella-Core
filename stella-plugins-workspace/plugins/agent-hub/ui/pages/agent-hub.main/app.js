(() => {
  const status = document.getElementById("status");
  const list = document.getElementById("list");
  const runs = document.getElementById("runs");
  const empty = document.getElementById("empty");
  const refreshBtn = document.getElementById("refresh");
  const defaultsBtn = document.getElementById("defaults");
  const params = new URLSearchParams(location.search);
  const identity = {
    pluginId: params.get("pluginId") || "stella.agent-hub",
    pageId: params.get("pageId") || "agent-hub.main",
    channelNonce: params.get("channelNonce") || "",
    generation: Number(params.get("generation") || "0"),
  };

  const AGENT_LABELS = {
    codex: "Codex",
    cursor: "Cursor",
    "claude-code": "Claude Code",
  };

  function setStatus(text) { status.textContent = text; }

  async function bridgeInvoke(method, input) {
    if (!window.parent || window.parent === window) throw new Error("bridge host unavailable");
    const requestId = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        window.removeEventListener("message", onMessage);
        reject(new Error("bridge timeout"));
      }, 20000);
      function onMessage(event) {
        const data = event.data || {};
        if (data.type !== "stella-bridge-result" || data.requestId !== requestId) return;
        clearTimeout(timer);
        window.removeEventListener("message", onMessage);
        if (data.ok) resolve(data.value);
        else reject(new Error(data.error || "bridge invoke failed"));
      }
      window.addEventListener("message", onMessage);
      window.parent.postMessage({
        type: "stella-bridge-invoke",
        requestId,
        ...identity,
        method,
        input: input || {},
      }, "*");
    });
  }

  function badge(probe) {
    const s = (probe && probe.status) || "unknown";
    const cls = s === "ready" ? "ready" : (s === "blocked" || s === "not_configured" ? "blocked" : "");
    return `<span class="badge ${cls}">${s}</span>`;
  }

  function groupByAgent(providers) {
    const groups = new Map();
    for (const row of providers || []) {
      const agentId = row.agentId || row.providerLocalId || "unknown";
      if (!groups.has(agentId)) groups.set(agentId, []);
      groups.get(agentId).push(row);
    }
    return groups;
  }

  async function probeOne(id) {
    setStatus(`正在探测 ${id}…`);
    await bridgeInvoke("probe_provider", { provider_config_id: id });
    await refresh();
  }

  async function enableOne(row, enabled) {
    await bridgeInvoke("upsert_provider", {
      provider: {
        providerConfigId: row.providerConfigId,
        providerLocalId: row.providerLocalId,
        agentId: row.agentId,
        accessMode: row.accessMode,
        displayName: row.displayName,
        binaryPath: row.binaryPath,
        enabled,
        settings: row.settings || {},
      },
    });
    await refresh();
  }

  function renderMode(row) {
    const mode = row.accessMode || "unknown";
    const el = document.createElement("div");
    el.className = "mode";
    el.innerHTML = `
      <h4>${row.displayName || mode}${badge(row.lastProbe)}</h4>
      <div class="meta">${mode} · ${row.providerLocalId} · ${row.enabled ? "已启用" : "未启用"} · ${row.binaryPath || "PATH 自动发现"}</div>
      <div style="margin-top:10px">
        <button type="button" data-act="enable">${row.enabled ? "停用" : "启用"}</button>
        <button type="button" class="secondary" data-act="probe">探测</button>
      </div>`;
    el.querySelector('[data-act="probe"]').addEventListener("click", () => {
      void probeOne(row.providerConfigId).catch((err) => setStatus(String(err.message || err)));
    });
    el.querySelector('[data-act="enable"]').addEventListener("click", () => {
      void enableOne(row, !row.enabled).catch((err) => setStatus(String(err.message || err)));
    });
    return el;
  }

  async function refresh() {
    const overview = await bridgeInvoke("status_overview", {});
    empty.style.display = overview.emptyState ? "block" : "none";
    list.innerHTML = "";
    const grouped = groupByAgent(overview.providers || []);
    for (const [agentId, rows] of grouped) {
      const wrap = document.createElement("div");
      wrap.className = "agent";
      const title = AGENT_LABELS[agentId] || agentId;
      const modes = rows.map((r) => r.accessMode || "?").join(" / ");
      wrap.innerHTML = `
        <h3>${title}</h3>
        <div class="meta">agentId=${agentId} · 接入：${modes}</div>
        <div class="modes"></div>`;
      const modesEl = wrap.querySelector(".modes");
      for (const row of rows) modesEl.appendChild(renderMode(row));
      list.appendChild(wrap);
    }
    const runRows = await bridgeInvoke("list_external_runs", { limit: 20 });
    runs.innerHTML = "";
    if (!runRows || !runRows.length) {
      runs.innerHTML = '<div class="meta">暂无委托记录</div>';
    } else {
      for (const row of runRows) {
        const el = document.createElement("div");
        el.className = "row";
        el.innerHTML = `<h3>${row.executionId}</h3><div class="meta">${row.status} · ${row.providerConfigId} · ${row.externalRunRef || "—"}</div>`;
        runs.appendChild(el);
      }
    }
  }

  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true;
    setStatus("加载中…");
    try { await refresh(); setStatus(""); }
    catch (err) { setStatus(String(err && err.message ? err.message : err)); }
    finally { refreshBtn.disabled = false; }
  });

  defaultsBtn.addEventListener("click", async () => {
    defaultsBtn.disabled = true;
    setStatus("正在初始化默认接入…");
    try {
      await bridgeInvoke("ensure_defaults", {});
      await refresh();
      setStatus("");
    } catch (err) {
      setStatus(String(err && err.message ? err.message : err));
    } finally {
      defaultsBtn.disabled = false;
    }
  });

  setStatus("正在加载智能体协作…");
  refresh().then(() => setStatus("")).catch((err) => setStatus(String(err && err.message ? err.message : err)));
})();
