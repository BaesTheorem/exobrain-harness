/**
 * Centralized configuration for the MCP Fitbit server
 * Contains all constants, API URLs, and shared configurations
 */

// === API Configuration ===

export const FITBIT_API_VERSIONS = {
  V1: 'https://api.fitbit.com/1',
  V1_2: 'https://api.fitbit.com/1.2',
} as const;

export const FITBIT_OAUTH_CONFIG = {
  AUTHORIZE_URL: 'https://www.fitbit.com/oauth2/authorize',
  TOKEN_URL: 'https://api.fitbit.com/oauth2/token',
  CALLBACK_URI: 'http://localhost:3000/callback',
  SCOPES: [
    'weight',
    'sleep',
    'profile',
    'activity',
    'heartrate',
    'nutrition',
    'temperature',
    'respiratory_rate',
    'oxygen_saturation',
    'cardio_fitness'
  ].join(' ')
} as const;

// === Tool Configuration ===

// === Common Parameter Types ===

export const TIME_PERIODS = ['1d', '7d', '30d', '3m', '6m', '1y'] as const;
export type TimePeriod = typeof TIME_PERIODS[number];

export const DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;
export const DATE_FORMAT_ERROR = 'Date must be in YYYY-MM-DD format';

export const HEART_RATE_DETAIL_LEVELS = ['1sec', '1min', '15min'] as const;
export type HeartRateDetailLevel = typeof HEART_RATE_DETAIL_LEVELS[number];

// === Common Validation Messages ===

export const VALIDATION_MESSAGES = {
  DATE_FORMAT: DATE_FORMAT_ERROR,
  PERIOD_REQUIRED: 'The time period for which to retrieve data',
  START_DATE_REQUIRED: 'The start date for which to retrieve data (YYYY-MM-DD)',
  END_DATE_REQUIRED: 'The end date for which to retrieve data (YYYY-MM-DD)',
  DETAIL_LEVEL_REQUIRED: 'The granularity level of the data',
  MAX_RANGE_100_DAYS: 'Note: The API enforces a maximum range of 100 days',
  MAX_RANGE_31_DAYS: 'Note: The API enforces a maximum range of 31 days'
} as const;

// === HTTP Configuration ===

export const HTTP_CONFIG = {
  USER_AGENT: 'mcp-fitbit-server/1.0',
  TIMEOUT_MS: 30000,
  MAX_RETRIES: 3
} as const;

// === File Paths ===

export const FILE_PATHS = {
  TOKEN_STORAGE: '.fitbit-token.json'
} as const;

// === Error Messages ===

export const ERROR_MESSAGES = {
  NO_ACCESS_TOKEN: 'No Fitbit Access Token available. Please authorize first.',
  API_REQUEST_FAILED: 'Failed to retrieve data from Fitbit API',
  TOKEN_EXPIRED: 'Access token might be expired or invalid. Re-authorization may be needed.',
  NO_DATA_FOUND: 'No data found for the specified period/range',
  CHECK_TOKEN_PERMISSIONS: 'Check token and permissions'
} as const;