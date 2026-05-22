const toggle = document.getElementById("toggle");
const status = document.getElementById("status");
const muted = document.getElementById("muted");
const saved = document.getElementById("saved");

function render(enabled) {
  toggle.checked = enabled;
  status.textContent = enabled ? "Blocking" : "Off";
  status.className = "status " + (enabled ? "on" : "off");
}

chrome.storage.local.get({ enabled: true, muted: [] }, ({ enabled, muted: list }) => {
  render(enabled);
  muted.value = (list || []).join("\n");
});

toggle.addEventListener("change", () => {
  const enabled = toggle.checked;
  render(enabled);
  chrome.storage.local.set({ enabled });
});

let saveTimer = null;
function flashSaved() {
  saved.classList.add("show");
  clearTimeout(saved._t);
  saved._t = setTimeout(() => saved.classList.remove("show"), 1200);
}

muted.addEventListener("input", () => {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const list = muted.value
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    chrome.storage.local.set({ muted: list }, flashSaved);
  }, 400);
});
