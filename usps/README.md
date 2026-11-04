# usps

Tools that measure package loops in USPS tracking histories. A loop is a return to a processing plant that the item already left, for example the Kansas City MO and KS distribution centers in turn.

| Script | What it does |
| --- | --- |
| `bin/loopscan.py` | Reads one tracking history: text copied from USPS.com, an OCR of a screenshot, or a TSV. Prints JSON with the plant sequence, plant visits, returns to a plant, transit minutes between plants, dwell hours per visit, and the count of processing scans at plants. |
| `bin/harvest_reddit.py` | Collects r/kansascity threads about USPS since 2023 from the Arctic Shift archive (no Reddit login), and downloads the screenshots in their comments to `data/img/`. |
| `bin/ocr_histories.py` | Runs Tesseract on each screenshot in `data/img/` and measures the text with `loopscan.py`. Output: `data/histories.json`. |

```sh
usps/bin/loopscan.py history.txt      # or: pbpaste | usps/bin/loopscan.py -
python3 usps/bin/harvest_reddit.py    # 10 to 20 min, paced for the archive
python3 usps/bin/ocr_histories.py
```

`data/` is gitignored. It holds Reddit text and images that other people posted.

These tools never call USPS. The USPS API terms limit tracking data to your own shipping and mailing transactions and do not permit a database for third-party use. A survey must therefore use text that each person copies from their own tracking page.

Tests: `tests/test_usps_loopscan.py`.
