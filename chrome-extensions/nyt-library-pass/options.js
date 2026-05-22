const cardEl = document.getElementById("card");
const pinEl = document.getElementById("pin");
const statusEl = document.getElementById("status");

chrome.storage.local.get(["libraryCard", "libraryPin"]).then(
  ({ libraryCard, libraryPin }) => {
    if (libraryCard) cardEl.value = libraryCard;
    if (libraryPin) pinEl.value = libraryPin;
  },
);

document.getElementById("save").addEventListener("click", async () => {
  await chrome.storage.local.set({
    libraryCard: cardEl.value.trim(),
    libraryPin: pinEl.value,
  });
  statusEl.textContent = "Saved.";
  setTimeout(() => (statusEl.textContent = ""), 2000);
});
