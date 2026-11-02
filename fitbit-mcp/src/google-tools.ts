/**
 * MCP tools backed by the Google Health API v4.
 *
 * The tool names and arguments are the ones the Fitbit-backed server exposed,
 * because a dozen harness skills call `mcp__fitbit__<name>` directly. The
 * responses are Google's raw JSON (data points or daily roll-ups), not Fitbit's
 * old shapes: a tool proxies the API and does not reshape the data.
 *
 * INVARIANTS
 * - Every tool returns { api, dataType(s), range, ... } plus the raw payload,
 *   so a caller can see which Google data type answered.
 * - API errors come back as isError text, never as a thrown exception.
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import {
  HealthApiError,
  NoTokenError,
  addDays,
  dailyRollUp,
  identity,
  listByDates,
  listDataPoints,
  pairedDevices,
  profile,
  settings,
  today,
} from './google-health.js';

type Text = { type: 'text'; text: string };
type Result = { content: Text[]; isError?: boolean };

const API = 'google-health v4';
const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Date must be in YYYY-MM-DD format');
const dateOrToday = z.string().regex(/^\d{4}-\d{2}-\d{2}$|^today$/, "Date must be YYYY-MM-DD or 'today'");

function ok(data: unknown): Result {
  return { content: [{ type: 'text', text: JSON.stringify({ api: API, ...(data as object) }, null, 2) }] };
}

function fail(err: unknown): Result {
  const msg =
    err instanceof HealthApiError || err instanceof NoTokenError
      ? err.message
      : `Unexpected error: ${(err as Error)?.message ?? String(err)}`;
  return { content: [{ type: 'text', text: msg }], isError: true };
}

async function run(fn: () => Promise<unknown>): Promise<Result> {
  try {
    return ok(await fn());
  } catch (err) {
    return fail(err);
  }
}

/** Inclusive date range of a Fitbit-style period that ends on `end`. */
export function periodRange(period: string, end: string): { startDate: string; endDate: string } {
  const days: Record<string, number> = { '1d': 1, '7d': 7, '1w': 7, '30d': 30, '1m': 30, '3m': 90, '6m': 182, '1y': 365 };
  const n = days[period];
  if (!n) throw new Error(`unknown period '${period}'`);
  return { startDate: addDays(end, -(n - 1)), endDate: end };
}

const resolve = (d?: string) => (!d || d === 'today' ? today() : d);

/** Settles each call on its own so one missing data type does not hide the rest. */
async function settle(calls: Record<string, () => Promise<unknown>>): Promise<Record<string, unknown>> {
  const keys = Object.keys(calls);
  const results = await Promise.allSettled(keys.map((k) => calls[k]()));
  return Object.fromEntries(
    results.map((r, i) => [keys[i], r.status === 'fulfilled' ? r.value : { error: (r.reason as Error).message }])
  );
}

const rangeArgs = { startDate: date.describe('Start date, YYYY-MM-DD (inclusive)'), endDate: date.describe('End date, YYYY-MM-DD (inclusive)') };

/** Fitbit activity resource -> Google data type and whether the API can roll it up per day. */
const ACTIVITY_RESOURCES: Record<string, { type: string; rollup: boolean }> = {
  steps: { type: 'steps', rollup: true },
  distance: { type: 'distance', rollup: true },
  calories: { type: 'total-calories', rollup: true },
  activityCalories: { type: 'active-energy-burned', rollup: true },
  caloriesBMR: { type: 'basal-energy-burned', rollup: false },
  'tracker/activityCalories': { type: 'active-energy-burned', rollup: true },
  'tracker/calories': { type: 'total-calories', rollup: true },
  'tracker/distance': { type: 'distance', rollup: true },
};

const NUTRITION_RESOURCES = ['caloriesIn', 'water', 'protein', 'carbs', 'fat', 'fiber', 'sodium'] as const;
const nutritionType = (resource: string) => (resource === 'water' ? 'hydration-log' : 'nutrition-log');

const WELLNESS: [string, string, string][] = [
  ['get_hrv_by_date_range', 'daily-heart-rate-variability', 'Nightly heart rate variability (RMSSD, deep-sleep RMSSD, entropy, non-REM heart rate)'],
  ['get_spo2_by_date_range', 'daily-oxygen-saturation', 'Nightly blood oxygen saturation (average, lower and upper bound, standard deviation)'],
  ['get_breathing_rate_by_date_range', 'daily-respiratory-rate', 'Nightly breathing rate in breaths per minute'],
  ['get_temp_skin_by_date_range', 'daily-sleep-temperature-derivations', 'Nightly skin temperature: nightly value, personal baseline and 30-day variation, in Celsius'],
];

export function registerGoogleHealthTools(server: McpServer): void {
  server.tool(
    'get_profile',
    'Google Health profile, settings (units, time zone), identity and paired devices.',
    {},
    () => run(() => settle({ profile, settings, identity, pairedDevices }))
  );

  server.tool(
    'get_sleep_by_date_range',
    'Sleep sessions with stages, summary and awakenings for nights that ENDED on dates in the range (Fitbit dateOfSleep semantics). Max 25 per page; pages are followed.',
    rangeArgs,
    ({ startDate, endDate }) =>
      run(async () => ({ dataType: 'sleep', startDate, endDate, ...(await listByDates('sleep', startDate, endDate, { pageSize: 25 })) }))
  );

  for (const [name, type, what] of WELLNESS) {
    server.tool(name, `${what}, one data point per day, from Google Health '${type}'.`, rangeArgs, ({ startDate, endDate }) =>
      run(async () => ({ dataType: type, startDate, endDate, ...(await listByDates(type, startDate, endDate)) }))
    );
  }

  const heartRate = (startDate: string, endDate: string) =>
    run(async () => ({
      startDate,
      endDate,
      ...(await settle({
        restingHeartRate: () => listByDates('daily-resting-heart-rate', startDate, endDate),
        heartRateZones: () => listByDates('daily-heart-rate-zones', startDate, endDate),
      })),
    }));

  server.tool(
    'get_heart_rate',
    'Daily resting heart rate and heart rate zones for a period ending on a date (default today).',
    {
      period: z.enum(['1d', '7d', '30d', '1w', '1m']).describe('Period that ends on `date`'),
      date: dateOrToday.optional().describe("End date, YYYY-MM-DD or 'today' (default)"),
    },
    ({ period, date: d }) => {
      const { startDate, endDate } = periodRange(period, resolve(d));
      return heartRate(startDate, endDate);
    }
  );

  server.tool('get_heart_rate_by_date_range', 'Daily resting heart rate and heart rate zones for a date range.', rangeArgs, ({ startDate, endDate }) =>
    heartRate(startDate, endDate)
  );

  server.tool(
    'get_daily_activity_summary',
    'One day of activity: steps, distance, floors, active zone minutes, active minutes, active and total calories (daily roll-ups), plus resting heart rate.',
    { date: date.describe('The date, YYYY-MM-DD') },
    ({ date: d }) =>
      run(async () => ({
        date: d,
        ...(await settle({
          steps: () => dailyRollUp('steps', d, d),
          distance: () => dailyRollUp('distance', d, d),
          floors: () => dailyRollUp('floors', d, d),
          activeZoneMinutes: () => dailyRollUp('active-zone-minutes', d, d),
          activeMinutes: () => dailyRollUp('active-minutes', d, d),
          activeEnergyBurned: () => dailyRollUp('active-energy-burned', d, d),
          totalCalories: () => dailyRollUp('total-calories', d, d),
          restingHeartRate: () => listByDates('daily-resting-heart-rate', d, d),
        })),
      }))
  );

  server.tool(
    'get_activity_timeseries',
    "Daily activity totals over a date range. 'calories' maps to Google 'total-calories', 'activityCalories' to 'active-energy-burned'; 'caloriesBMR' returns raw 'basal-energy-burned' points because the API cannot roll it up.",
    {
      resourcePath: z.enum(Object.keys(ACTIVITY_RESOURCES) as [string, ...string[]]).describe('Activity resource'),
      ...rangeArgs,
    },
    ({ resourcePath, startDate, endDate }) =>
      run(async () => {
        const { type, rollup } = ACTIVITY_RESOURCES[resourcePath];
        return rollup
          ? { dataType: type, startDate, endDate, rollupDataPoints: await dailyRollUp(type, startDate, endDate) }
          : { dataType: type, startDate, endDate, ...(await listByDates(type, startDate, endDate)) };
      })
  );

  server.tool('get_azm_timeseries', 'Daily Active Zone Minutes (by heart rate zone) over a date range.', rangeArgs, ({ startDate, endDate }) =>
    run(async () => ({ dataType: 'active-zone-minutes', startDate, endDate, rollupDataPoints: await dailyRollUp('active-zone-minutes', startDate, endDate) }))
  );

  server.tool(
    'get_activity_goals',
    'NOT AVAILABLE: the Google Health API has no activity-goals endpoint (Fitbit had one). Kept so callers get a clear answer.',
    { period: z.enum(['daily', 'weekly']).describe('Goal period') },
    () =>
      Promise.resolve({
        content: [{ type: 'text' as const, text: 'Activity goals are not exposed by the Google Health API v4 (no goals resource in its discovery document). Read goals in the Fitbit or Google Health app.' }],
        isError: true,
      })
  );

  server.tool(
    'get_exercises',
    'Exercise sessions (type, duration, metrics summary, splits) that started on or after a date, newest first.',
    {
      afterDate: date.describe('Return sessions that started on or after this date, YYYY-MM-DD'),
      limit: z.number().min(1).max(100).optional().describe('Maximum sessions (default 20)'),
    },
    ({ afterDate, limit }) =>
      run(async () => {
        const max = limit ?? 20;
        const r = await listDataPoints('exercise', `exercise.interval.civil_start_time >= "${afterDate}"`, { pageSize: 25, maxPoints: max });
        return { dataType: 'exercise', afterDate, dataPoints: r.dataPoints.slice(0, max), truncated: r.truncated || r.dataPoints.length > max };
      })
  );

  server.tool(
    'get_weight',
    'Weight and body-fat measurements for a period ending today. Weight is in grams (weightGrams).',
    { period: z.enum(['1d', '7d', '30d', '3m', '6m', '1y']).describe('Period that ends today') },
    ({ period }) => {
      const { startDate, endDate } = periodRange(period, today());
      return run(async () => ({
        startDate,
        endDate,
        ...(await settle({ weight: () => listByDates('weight', startDate, endDate), bodyFat: () => listByDates('body-fat', startDate, endDate) })),
      }));
    }
  );

  server.tool(
    'get_food_log',
    'Every food and drink logged on one date: nutrition-log entries (food, meal type, energy, macros, nutrients) and hydration-log entries.',
    { date: dateOrToday.describe("The date, YYYY-MM-DD or 'today'") },
    ({ date: d }) => {
      const day = resolve(d);
      return run(async () => ({
        date: day,
        ...(await settle({ nutrition: () => listByDates('nutrition-log', day, day), hydration: () => listByDates('hydration-log', day, day) })),
      }));
    }
  );

  const nutritionArgs = { resource: z.enum(NUTRITION_RESOURCES).describe("Nutrient of interest. 'water' reads hydration-log; the others read the nutrition-log roll-up, which carries every nutrient") };

  server.tool(
    'get_nutrition',
    'Daily nutrition roll-ups (energy, macros, nutrients) or water totals for a period ending on a date.',
    {
      ...nutritionArgs,
      period: z.enum(['1d', '7d', '30d', '1w', '1m', '3m', '6m', '1y']).describe('Period that ends on `date`'),
      date: dateOrToday.optional().describe("End date, YYYY-MM-DD or 'today' (default)"),
    },
    ({ resource, period, date: d }) => {
      const { startDate, endDate } = periodRange(period, resolve(d));
      const type = nutritionType(resource);
      return run(async () => ({ resource, dataType: type, startDate, endDate, rollupDataPoints: await dailyRollUp(type, startDate, endDate) }));
    }
  );

  server.tool('get_nutrition_by_date_range', 'Daily nutrition roll-ups (energy, macros, nutrients) or water totals for a date range.', { ...nutritionArgs, ...rangeArgs }, ({ resource, startDate, endDate }) => {
    const type = nutritionType(resource);
    return run(async () => ({ resource, dataType: type, startDate, endDate, rollupDataPoints: await dailyRollUp(type, startDate, endDate) }));
  });

  // Raw access, for anything the named tools do not cover (intraday heart rate, steps by minute, VO2 max).
  server.tool(
    'get_data_points',
    "Raw Google Health data points of any type for a civil date range. Types include heart-rate (per-second samples, large), heart-rate-variability, oxygen-saturation, steps, distance, activity-level, sedentary-period, daily-vo2-max, vo2-max, run-vo2-max, height, body-fat, respiratory-rate-sleep-summary, time-in-heart-rate-zone.",
    {
      dataType: z.string().describe("Google data type id in kebab-case, for example 'heart-rate'"),
      ...rangeArgs,
      maxPoints: z.number().min(1).max(100000).optional().describe('Stop after this many points (default 5000)'),
    },
    ({ dataType, startDate, endDate, maxPoints }) =>
      run(async () => ({ dataType, startDate, endDate, ...(await listByDates(dataType, startDate, endDate, { pageSize: 10000, maxPoints: maxPoints ?? 5000 })) }))
  );

  server.tool(
    'get_daily_rollup',
    'Raw Google Health daily roll-ups for a civil date range. Supported types: steps, distance, floors, altitude, active-minutes, active-zone-minutes, active-energy-burned, total-calories, heart-rate, time-in-heart-rate-zone, calories-in-heart-rate-zone, sedentary-period, activity-level, nutrition-log, hydration-log, weight, body-fat, run-vo2-max.',
    { dataType: z.string().describe("Google data type id in kebab-case, for example 'steps'"), ...rangeArgs },
    ({ dataType, startDate, endDate }) => run(async () => ({ dataType, startDate, endDate, rollupDataPoints: await dailyRollUp(dataType, startDate, endDate) }))
  );
}
