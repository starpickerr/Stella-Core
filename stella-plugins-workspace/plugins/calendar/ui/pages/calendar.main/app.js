(() => {
  const status = document.getElementById("status");
  const events = document.getElementById("events");
  const form = document.getElementById("create");
  const params = new URLSearchParams(location.search);
  const identity = {
    pluginId: params.get("pluginId") || "stella.calendar",
    pageId: params.get("pageId") || "calendar.main",
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

  function dayBounds() {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 7);
    return { start: start.toISOString(), end: end.toISOString() };
  }

  async function refresh() {
    const range = dayBounds();
    const rows = await bridgeInvoke("list_events", range);
    events.innerHTML = "";
    for (const row of rows || []) {
      const el = document.createElement("div");
      el.className = "row";
      const when = (row.start_at || "").toString().slice(0, 16).replace("T", " ");
      el.textContent = `${when} · ${row.title || row.id}`;
      events.appendChild(el);
    }
  }

  function toIsoLocal(value) {
    if (!value) return value;
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return `${value}:00+08:00`;
    return d.toISOString();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    form.querySelector("button").disabled = true;
    setStatus("保存中…");
    try {
      await bridgeInvoke("create_event", {
        payload: {
          title: String(data.get("title") || "").trim(),
          start_at: toIsoLocal(String(data.get("start"))),
          end_at: toIsoLocal(String(data.get("end"))),
        },
      });
      form.reset();
      setStatus("已创建");
      await refresh();
    } catch (err) {
      setStatus(String(err && err.message ? err.message : err));
    } finally {
      form.querySelector("button").disabled = false;
    }
  });

  setStatus("正在加载近一周日程…");
  refresh()
    .then(() => setStatus(""))
    .catch((err) => setStatus(String(err && err.message ? err.message : err)));
})();
