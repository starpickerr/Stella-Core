(() => {
  const status = document.getElementById("status");
  const list = document.getElementById("list");
  const refreshBtn = document.getElementById("refresh");
  const params = new URLSearchParams(location.search);
  const identity = { pluginId: params.get("pluginId") || "stella.email", pageId: params.get("pageId") || "email.main", channelNonce: params.get("channelNonce") || "", generation: Number(params.get("generation") || "0") };
  function setStatus(text) { status.textContent = text; }

  async function bridgeInvoke(method, input) {
    if (!window.parent || window.parent === window) throw new Error("bridge host unavailable");
    const requestId = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { window.removeEventListener("message", onMessage); reject(new Error("bridge timeout")); }, 15000);
      function onMessage(event) {
        const data = event.data || {};
        if (data.type !== "stella-bridge-result" || data.requestId !== requestId) return;
        clearTimeout(timer); window.removeEventListener("message", onMessage);
        if (data.ok) resolve(data.value); else reject(new Error(data.error || "bridge invoke failed"));
      }
      window.addEventListener("message", onMessage);
      window.parent.postMessage({ type: "stella-bridge-invoke", requestId, ...identity, method, input: input || {} }, "*");
    });
  }

  async function refresh() {
    const rows = await bridgeInvoke("list_accounts", {});
    list.innerHTML = "";
    for (const row of rows || []) {
      const el = document.createElement("div"); el.className = "row";
      el.textContent = `${row.user || row.id} · ${row.host || ""}`;
      list.appendChild(el);
    }
  }
  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true; setStatus("加载中…");
    try { await refresh(); setStatus(""); } catch (err) { setStatus(String(err && err.message ? err.message : err)); }
    finally { refreshBtn.disabled = false; }
  });
  setStatus("正在加载邮箱账号…");
  refresh().then(() => setStatus("")).catch((err) => setStatus(String(err && err.message ? err.message : err)));
})();
