(async () => {
  const { libraryCard, libraryPin } = await chrome.storage.local.get([
    "libraryCard",
    "libraryPin",
  ]);

  if (!libraryCard || !libraryPin) return;

  const cardSelectors = [
    'input[name="user"]',
    'input[name="username"]',
    'input[name="barcode"]',
    'input[id="user"]',
    'input[id="username"]',
  ];
  const pinSelectors = [
    'input[name="pass"]',
    'input[name="password"]',
    'input[name="pin"]',
    'input[type="password"]',
  ];

  const pick = (selectors) => {
    for (const s of selectors) {
      const el = document.querySelector(s);
      if (el) return el;
    }
    return null;
  };

  const cardEl = pick(cardSelectors);
  const pinEl = pick(pinSelectors);

  if (!cardEl || !pinEl) {
    console.warn("[KC Library NYT Pass] Could not find login form fields.");
    return;
  }

  const setValue = (el, value) => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    ).set;
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  };

  setValue(cardEl, libraryCard);
  setValue(pinEl, libraryPin);

  const form = cardEl.closest("form");
  if (form) {
    form.submit();
  } else {
    const submitBtn = document.querySelector(
      'button[type="submit"], input[type="submit"]',
    );
    if (submitBtn) submitBtn.click();
  }
})();
