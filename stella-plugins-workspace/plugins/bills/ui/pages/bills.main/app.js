(() => {
  const status = document.getElementById("status");
  const ledger = document.getElementById("ledger");
  const form = document.getElementById("create");
  const params = new URLSearchParams(location.search);
  const identity = {
    pluginId: params.get("pluginId") || "stella.bills",
    pageId: params.get("pageId") || "bills.main",
    channelNonce: params.get("channelNonce") || "",
    generation: Number(params.get("generation") || "0"),
  };

  function setStatus(text) {
    status.textContent = text;
  }

  async function bridgeInvoke(method, input) {
    if (!window.parent || window.parent === window) {
      throw new Error("bridge host unavailable");
    }
    const requestId = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        window.removeEventListener("message", onMessage);
        reject(new Error("bridge timeout"));
      }, 15000);
      function onMessage(event) {
        const data = event.data || {};
        if (data.type !== "stella-bridge-result" || data.requestId !== requestId) return;
        clearTimeout(timer);
        window.removeEventListener("message", onMessage);
        if (data.ok) resolve(data.value);
        else reject(new Error(data.error || "bridge invoke failed"));
      }
      window.addEventListener("message", onMessage);
      window.parent.postMessage(
        {
          type: "stella-bridge-invoke",
          requestId,
          ...identity,
          method,
          input: input || {},
        },
        "*"
      );
    });
  }

  async function refresh() {
    const now = new Date();
    const rows = await bridgeInvoke("list_ledger", {
      year: now.getFullYear(),
      month: now.getMonth() + 1,
    });
    ledger.innerHTML = "";
    for (const row of rows || []) {
      const el = document.createElement("div");
      el.className = "row";
      const yuan = ((row.amount_minor || 0) / 100).toFixed(2);
      el.textContent = `${(row.occurred_at || "").slice(0, 10)} · ¥${yuan} · ${row.name || ""}`;
      ledger.appendChild(el);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    form.querySelector("button").disabled = true;
    setStatus("保存中…");
    try {
      const amount = Number(data.get("amount"));
      const day = String(data.get("date"));
      const note = String(data.get("note") || "支出");
      await bridgeInvoke("create_ledger", {
        name: note,
        category: "消费",
        entry_type: "expense",
        amount_minor: Math.round(amount * 100),
        occurred_at: `${day}T12:00:00+08:00`,
        note,
      });
      form.reset();
      const dateInput = form.elements.namedItem("date");
      if (dateInput) dateInput.value = new Date().toISOString().slice(0, 10);
      setStatus("已记账");
      await refresh();
    } catch (err) {
      setStatus(String(err && err.message ? err.message : err));
    } finally {
      form.querySelector("button").disabled = false;
    }
  });

  const dateInput = form.elements.namedItem("date");
  if (dateInput && !dateInput.value) {
    dateInput.value = new Date().toISOString().slice(0, 10);
  }
  setStatus("正在加载本月账单…");
  refresh()
    .then(() => setStatus(""))
    .catch((err) => setStatus(String(err && err.message ? err.message : err)));
})();
