// season.js: live season odds from the outcome table (season_sim.outcome_table).
//
// The table holds every team's bye, playoff, title and 1-seed odds under each
// of the 2^G win/loss results of the week in hand (bit j of a cell index set
// = the home side of game j wins). A cell's weight is the product of the live
// win probabilities of the games that make it, so the mix moves with every
// score. The product is exact in the simulator: no two games of a week share
// a team. test_season.py checks this file against the Python mix and checks
// that the mix at the pregame chances gives the plain run back.

const METRICS = ["bye", "playoffs", "title", "seed1"];

function mix(table, p) {
  const n = table.ids.length, G = table.games.length;
  const odds = Object.fromEntries(METRICS.map(m => [m, new Array(n).fill(0)]));
  const all = 2 ** n - 1;   // bit masks: fine to 31 teams
  const lock = { clinch: { bye: all, playoffs: all }, out: { bye: all, playoffs: all } };
  for (let k = 0; k < table.cells.length; k++) {
    let w = 1;
    for (let j = 0; j < G; j++) w *= (k >> j) & 1 ? p[j] : 1 - p[j];
    if (w <= 0) continue;
    const c = table.cells[k];
    for (const m of METRICS) for (let i = 0; i < n; i++) odds[m][i] += w * c[m][i] / 10000;
    for (const f of ["clinch", "out"]) for (const s of ["bye", "playoffs"]) lock[f][s] &= c[f][s];
  }
  return { odds, lock };
}

// table: the outcome table. pHome: P(home side of table.games[j] wins), one
// per game; null where the game has no live number (then the pregame chance,
// then a coin). Returns per-team odds (0-1); `base`, the same cells at the
// pregame chances, so the change since kickoff carries no sampling noise;
// and the clinch and out flags that hold in every cell still possible.
export function seasonOdds(table, pHome) {
  const pre = table.games.map((_, j) => table.pre?.[j] ?? 0.5);
  const p = pre.map((x, j) => pHome[j] ?? x);
  const { odds, lock } = mix(table, p), base = mix(table, pre).odds;
  const flag = (mask, i) => Boolean((mask >> i) & 1);
  const teams = table.ids.map((id, i) => ({
    id, name: table.names[i],
    ...Object.fromEntries(METRICS.map(m => [m, odds[m][i]])),
    base: Object.fromEntries(METRICS.map(m => [m, base[m][i]])),
    clinch: { bye: flag(lock.clinch.bye, i), playoffs: flag(lock.clinch.playoffs, i) },
    out: { bye: flag(lock.out.bye, i), playoffs: flag(lock.out.playoffs, i) },
  }));
  return { week: table.week, weeks_played: table.weeks_played, p, teams };
}
