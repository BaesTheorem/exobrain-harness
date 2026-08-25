# GitHub Copilot Instructions

## Project Overview
MCP server for Fitbit API integration providing health data access (weight, sleep, activities, profile).

**Design Philosophy:** This MCP server acts as a 1:1 JSON proxy to the Fitbit API. Tools should match the underlying API parameters and limitations exactly, without adding abstraction layers or client-side data manipulation. Return raw JSON responses from Fitbit API calls.

## Development Commands
- `npm run build` - Compile TypeScript to build/ directory
- `npm run start` - Run the built MCP server
- `npm run dev` - Build and run with MCP inspector for testing/debugging
- `npm run lint` - Check code quality and style issues
- `npm run format` - Auto-fix code formatting
- `npm test` - No tests configured yet

## Project Structure
- `src/index.ts` - Main MCP server entry point, registers all tools
- `src/auth.ts` - OAuth2 flow with token persistence
- `src/utils.ts` - Shared Fitbit API request utilities  
- `src/weight.ts` - Weight data tool (time series)
- `src/sleep.ts` - Sleep data tool (date range)
- `src/activities.ts` - Exercise/activity data tool (date range)
- `src/profile.ts` - User profile tool
- `src/heart-rate.ts` - Heart rate data tools (time series and date range)
- `src/nutrition.ts` - Nutrition data tools (comprehensive food log with macros, plus time series for individual nutrients)
- `build/` - Compiled JavaScript output
- `.env` - Environment variables (FITBIT_CLIENT_ID, FITBIT_CLIENT_SECRET)

## Code Conventions
- TypeScript with ES modules
- Zod for parameter validation
- All tools return raw JSON from Fitbit API
- Error handling with console.error for debugging
- Use makeFitbitRequest utility for API calls
- **API Fidelity:** Tool parameters must exactly match Fitbit API requirements - no client-side workarounds or data filtering
- **No Abstraction:** If Fitbit API only supports `afterDate`, the tool should only accept `afterDate` (not `startDate`/`endDate`)
- **Documentation First:** Always check the official Fitbit API documentation at https://dev.fitbit.com/build/reference/ when adding new endpoints to ensure proper parameters, authentication scopes, and response formats
- **CRITICAL: Endpoint URL Construction:** The `makeFitbitRequest` utility automatically adds `/user/-/` to all endpoint paths. When constructing endpoints, DO NOT include `user/-/` in the path - start directly with the resource path (e.g., `foods/log/caloriesIn/date/today/1d.json` NOT `user/-/foods/log/caloriesIn/date/today/1d.json`)

## Testing the Server
**Development mode (with inspector):**
1. `npm run dev` - Builds and opens MCP inspector web UI
2. Test tools interactively at http://localhost:5173
3. OAuth flow - server opens browser for authorization

**Production mode:**
1. `npm run build` - Compile TypeScript
2. `npm run start` - Run server directly
3. Tools available after auth: get_weight, get_sleep_by_date_range, get_exercises, get_profile, get_heart_rate, get_heart_rate_by_date_range, get_food_log, get_nutrition, get_nutrition_by_date_range

## Environment Setup
Requires `.env` file with:
```
FITBIT_CLIENT_ID=your_client_id
FITBIT_CLIENT_SECRET=your_client_secret
```

## API Notes
- Fitbit API uses different base URLs per endpoint (v1, v1.2)
- Activities tool has custom request handler due to different URL structure
- All dates in YYYY-MM-DD format
- Token persisted to `.fitbit-token.json`
- OAuth scopes: weight, sleep, profile, activity, heartrate, nutrition

## Contributing & Improvements

When working on this codebase:
1. Follow the existing code style and patterns
2. Update relevant documentation 
3. Test changes thoroughly with the MCP inspector
4. Ensure backward compatibility with existing tools
5. **VERY IMPORTANT:** When you have completed a task, you MUST run both build, test, and lint commands (`npm run build` then `npm run test:coverage` then  `npm run lint`) to ensure your code is correct
6. Update documentation when making changes

**For identified improvement opportunities, see [TASKS.md](../TASKS.md)** - this file contains a comprehensive analysis of refactoring opportunities, code quality improvements, and architectural enhancements prioritized by impact and effort.
