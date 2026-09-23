// Builds an MD3 dark scheme from an image's pixels with the vendored
// material-color-utilities. Reads a JSON array of ARGB ints on stdin and
// prints {role: "#rrggbb"} for every MaterialDynamicColors role.
import {readFileSync} from 'node:fs';
import {
  Hct, MaterialDynamicColors, QuantizerCelebi, SchemeTonalSpot, Score, hexFromArgb,
} from '../../material-design/material-color-utilities/typescript/index.ts';

const pixels: number[] = JSON.parse(readFileSync(0, 'utf8'));
const seed = Score.score(QuantizerCelebi.quantize(pixels, 128))[0];
const scheme = new SchemeTonalSpot(Hct.fromInt(seed), true, 0);
const out: Record<string, string> = {seed: hexFromArgb(seed)};
for (const [name, value] of Object.entries(MaterialDynamicColors)) {
  if (value && typeof value === 'object' && 'getArgb' in value && !name.endsWith('PaletteKeyColor')) {
    out[name] = hexFromArgb((value as {getArgb: (s: SchemeTonalSpot) => number}).getArgb(scheme));
  }
}
console.log(JSON.stringify(out));
