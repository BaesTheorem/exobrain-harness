# HPMOR Dust Jackets

Generates Blurb-ready dust jacket PDFs for all 6 volumes of *Harry Potter and the Methods of Rationality*, using the cover art from [ianstormtaylor/hpmor](https://github.com/ianstormtaylor/hpmor).

The upstream repo targets **softcover paperback**. This project retargets the same cover art onto **Blurb Linen Hardcover with Dust Jacket** (6x9), pulling a background color from the cover edge to fill the jacket flaps.

## One-time setup

1. Fetch the source files from GitHub:
   ```bash
   python3 download.py
   ```
   Pulls `cover.png` and `contents.pdf` for each volume into `downloads/`. These are gitignored (copyrighted derivative content).

2. Pad each interior to a multiple of 4 pages (Blurb requirement):
   ```bash
   python3 pad_interiors.py
   ```
   Writes `volume-N-contents-padded.pdf` next to each original. Final counts: 352, 288, 400, 396, 232, 324.

3. **Spine widths in `config.json` were fetched from Blurb's spec calculator** on 2026-04-21 for Trade 6x9 Hardcover Dust Jacket with Standard Trade B&W Paper (matte). If the book PDFs change page count, re-fetch from <https://www.blurb.com/pdf_to_book/booksize_calculator>.

4. Build the jackets:
   ```bash
   python3 build_jackets.py
   ```
   Outputs `output/volume-N-jacket.pdf` — one flat spread per volume, 300 DPI, ready to upload.

## Order workflow (per volume)

- On blurb.com, create a new **Trade 6x9, Linen Hardcover with Dust Jacket, Economy B&W** book.
- Choose **"Create and Upload your PDF"**.
- Upload `downloads/volume-N-contents-padded.pdf` as the interior.
- Upload `output/volume-N-jacket.pdf` as the dust jacket.
- Use Blurb's free ISBN.
- **Set visibility to private (only you can see).**
- Order one proof copy.

## Cost

Estimated ~$35–40 per volume for Linen HC + dust jacket, Economy B&W at these page counts. Six volumes ≈ **$210–240 + shipping**.

## Why these files aren't committed

The repo root is public. HPMOR content + cover art is a copyrighted derivative (HP universe is Rowling's). The Python scripts are committed; the downloaded PDFs and generated jackets are not. Anyone cloning this can rebuild by running `download.py` + `build_jackets.py`.
