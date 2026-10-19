(() => {
  const status = document.getElementById("status");
  const list = document.getElementById("list");
  const form = document.getElementById("create");
  const params = new URLSearchParams(location.search);
  const identity = {
    pluginId: params.get("pluginId") || "stella.tasks",
    pageId: params.get("pageId") || "tasks.main",
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

  function todayIso() {
    return new Date().toISOString().slice(0, 10);
  }

  async function refresh() {
    const rows = await bridgeInvoke("list_todos_focus", { today: todayIso() });
    list.innerHTML = "";
    for (const row of rows || []) {
      const el = document.createElement("div");
      el.className = "row";
      const title = document.createElement("span");
      title.textContent = row.title || row.id;
      const done = document.createElement("button");
      done.type = "button";
      done.textContent = "完成";
      done.addEventListener("click", async () => {
        try {
          await bridgeInvoke("complete_todo", { todo_id: row.id, completed: true });
          await refresh();
        } catch (err) {
          setStatus(String(err && err.message ? err.message : err));
        }
      });
      el.appendChild(title);
      el.appendChild(done);
      list.appendChild(el);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    form.querySelector("button").disabled = true;
    setStatus("保存中…");
    try {
      const title = String(data.get("title") || "").trim();
      const due = String(data.get("due") || "").trim();
      const payload = { title };
      if (due) payload.due_on = due;
      await bridgeInvoke("create_todo", { payload });
      form.reset();
      setStatus("已创建");
      await refresh();
    } catch (err) {
      setStatus(String(err && err.message ? err.message : err));
    } finally {
      form.querySelector("button").disabled = false;
    }
  });

  setStatus("正在加载今日焦点…");
  refresh()
    .then(() => setStatus(""))
    .catch((err) => setStatus(String(err && err.message ? err.message : err)));
})();
