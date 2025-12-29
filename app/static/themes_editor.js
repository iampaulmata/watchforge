const allowedTokens = [
  // colors
  "--bg","--surface","--surface-2","--text","--muted","--border",
  "--accent","--accent-2","--good","--warn","--bad",
  // typography
  "--ui-font","--mono-font","--text-size","--title-size",
  // shape/glass
  "--radius","--shadow","--blur","--glass",
  // spacing
  "--pad","--gap","--compact",
  // thresholds
  "--warn-pct","--danger-pct"
];

const colorTokens = new Set([
  "--bg","--text","--accent","--accent-2","--good","--warn","--bad"
]);

function getState() {
  const meta = {
    name: document.getElementById("name").value.trim(),
    author: document.getElementById("author").value.trim(),
    description: document.getElementById("desc").value.trim(),
    mode: document.getElementById("mode").value,
    is_public: document.getElementById("is_public").checked
  };

  const tokens = {};
  for (const t of allowedTokens) {
    const el = document.querySelector(`[data-token="${CSS.escape(t)}"]`);
    if (!el) continue;
    const v = el.value.trim();
    if (v !== "") tokens[t] = v;
  }
  return { meta, tokens };
}

function applyPreview(tokens) {
  const root = document.documentElement;
  for (const t of allowedTokens) {
    root.style.removeProperty(t);
  }
  for (const [k, v] of Object.entries(tokens)) {
    root.style.setProperty(k, v);
  }

  // compact hint as data attribute too
  const compact = tokens["--compact"];
  document.body.dataset.compact = (compact === "1" || compact === 1) ? "1" : "0";
}

function makeField(token, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "field";

  const label = document.createElement("label");
  label.textContent = token;
  label.title = token;

  const right = document.createElement("div");
  right.style.display = "grid";
  right.style.gridTemplateColumns = colorTokens.has(token) ? "120px 1fr" : "1fr";
  right.style.gap = "10px";
  right.style.justifyItems = "end";

  if (colorTokens.has(token)) {
    const color = document.createElement("input");
    color.type = "color";
    color.className = "input";
    // best-effort: if value is rgba, we can't set it; leave it.
    if (/^#([0-9a-f]{6}|[0-9a-f]{3})$/i.test(value)) color.value = value;
    color.addEventListener("input", () => {
      text.value = color.value;
      applyPreview(getState().tokens);
    });
    right.appendChild(color);
  }

  const text = document.createElement("input");
  text.className = "input";
  text.value = value || "";
  text.setAttribute("data-token", token);
  text.placeholder = token;
  text.addEventListener("input", () => applyPreview(getState().tokens));
  right.appendChild(text);

  wrapper.appendChild(label);
  wrapper.appendChild(right);

  return wrapper;
}

function renderTokens(initialTokens) {
  const grid = document.getElementById("tokens-grid");
  grid.innerHTML = "";

  for (const t of allowedTokens) {
    const v = (initialTokens && initialTokens[t]) ? String(initialTokens[t]) : "";
    grid.appendChild(makeField(t, v));
  }
}

async function postJSON(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }
  return await res.json().catch(()=> ({}));
}

document.getElementById("compact").addEventListener("change", (e) => {
  const el = document.querySelector('[data-token="--compact"]');
  if (el) el.value = e.target.value;
  applyPreview(getState().tokens);
});

document.getElementById("btn-save").addEventListener("click", async () => {
  const { meta, tokens } = getState();
  if (!meta.name) return alert("Theme name is required.");

  const id = window.THEME_EDITOR.themeId;
  if (!id) return alert("No theme loaded. Use 'Save as New'.");

  try {
    await postJSON(`/themes/${id}/update`, { meta, tokens });
    alert("Saved.");
  } catch (e) {
    alert(`Save failed: ${e.message}`);
  }
});

document.getElementById("btn-save-as").addEventListener("click", async () => {
  const { meta, tokens } = getState();
  if (!meta.name) return alert("Theme name is required.");
  try {
    const out = await postJSON(`/themes/create`, { meta, tokens });
    if (out && out.id) {
      window.location.href = `/themes/${out.id}/edit`;
    } else {
      alert("Created, but missing id response.");
    }
  } catch (e) {
    alert(`Create failed: ${e.message}`);
  }
});

document.getElementById("btn-import").addEventListener("click", async () => {
  const raw = document.getElementById("import_json").value.trim();
  if (!raw) return alert("Paste a theme JSON first.");
  try {
    const obj = JSON.parse(raw);
    const out = await postJSON(`/themes/import`, obj);
    if (out && out.id) window.location.href = `/themes/${out.id}/edit`;
    else alert("Imported.");
  } catch (e) {
    alert(`Import failed: ${e.message}`);
  }
});

// boot
(() => {
  const initial = window.THEME_EDITOR.initialTokens || {};
  renderTokens(initial);
  applyPreview(initial);

  // keep compact dropdown in sync
  const compact = initial["--compact"];
  document.getElementById("compact").value = (compact === "1" || compact === 1) ? "1" : "0";
})();
