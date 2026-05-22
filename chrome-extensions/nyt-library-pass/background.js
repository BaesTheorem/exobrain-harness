const REDEEM_URL =
  "https://kclibrary.idm.oclc.org/login?url=http://ezmyaccount.nytimes.com/grouppass/redir";

chrome.action.onClicked.addListener(async () => {
  const { libraryCard, libraryPin } = await chrome.storage.local.get([
    "libraryCard",
    "libraryPin",
  ]);

  if (!libraryCard || !libraryPin) {
    chrome.runtime.openOptionsPage();
    return;
  }

  chrome.tabs.create({ url: REDEEM_URL });
});
