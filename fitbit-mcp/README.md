> **This is a patched fork.** Local changes (a wellness-tools module, extra OAuth
> scopes, and a refresh-token race fix) are documented in [FORK.md](FORK.md).
> Read that before editing or rebasing onto upstream.

# Fitbit MCP Connector for AI

[![Fitbit API](https://img.shields.io/badge/Fitbit-00B0B9?logo=fitbit&logoColor=white)](https://dev.fitbit.com/)
[![CI](https://github.com/TheDigitalNinja/mcp-fitbit/actions/workflows/ci.yml/badge.svg)](https://github.com/TheDigitalNinja/mcp-fitbit/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/TheDigitalNinja/mcp-fitbit/badge.svg?branch=main)](https://coveralls.io/github/TheDigitalNinja/mcp-fitbit?branch=main)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![npm version](https://badge.fury.io/js/mcp-fitbit.svg)](https://badge.fury.io/js/mcp-fitbit)
[![npm downloads](https://img.shields.io/npm/dm/mcp-fitbit.svg)](https://www.npmjs.com/package/mcp-fitbit)

> Connect AI assistants to your Fitbit health data

Give your AI assistant access to your Fitbit data for personalized health insights, trend analysis, and automated tracking. Works with Claude Desktop and other MCP-compatible AI tools.

## What it does

🏃 **Exercise & Activities** - Get detailed workout logs and activity data  
😴 **Sleep Analysis** - Retrieve sleep patterns and quality metrics  
⚖️ **Weight Tracking** - Access weight trends over time  
❤️ **Heart Rate Data** - Monitor heart rate patterns and zones  
🍎 **Nutrition Logs** - Review food intake, calories, and macros  
👤 **Profile Info** - Access basic Fitbit profile details

*Ask your AI things like: "Show me my sleep patterns this week" or "What's my average heart rate during workouts?"*

## Quick Start

**🚀 Want to test the tools right away?**

### Option 1: Install from npm (Recommended)
1. [Get Fitbit API credentials](https://dev.fitbit.com/)
   - Create an app with OAuth 2.0 Application Type: `Personal`
   - Set Callback URL: `http://localhost:3000/callback`
   - Note your **Client ID** and **Client Secret**

2. Install the package globally:
```bash
npm install -g mcp-fitbit
```

3. Add to your Claude Desktop config file:
```json
{
  "mcpServers": {
    "fitbit": {
      "command": "mcp-fitbit",
      "args": [],
      "env": {
        "FITBIT_CLIENT_ID": "your_client_id_here",
        "FITBIT_CLIENT_SECRET": "your_client_secret_here"
      }
    }
  }
}
```
 - Config file location:
   - Windows: %AppData%\Claude\claude_desktop_config.json
   - macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
   - Linux: ~/.config/Claude/claude_desktop_config.json

4. Restart Claude Desktop and ask about your Fitbit data!



### Option 2: Development Setup
1. [Get Fitbit API credentials](https://dev.fitbit.com/) (see Installation below)
2. Then run:

```bash
git clone https://github.com/TheDigitalNinja/mcp-fitbit
cd mcp-fitbit
npm install
# Create .env with your Fitbit credentials
npm run dev
```

Both options open the **MCP Inspector** at `http://localhost:5173` where you can test all tools interactively and handle the OAuth flow.

## Installation

### For End Users (npm package)

1. **Get Fitbit API credentials** at [dev.fitbit.com](https://dev.fitbit.com/)
   - Set **OAuth 2.0 Application Type** to `Personal`  
   - Set **Callback URL** to `http://localhost:3000/callback`

2. **Install the package:**
   ```bash
   npm install -g mcp-fitbit
   ```

3. **Create `.env` file in the package directory:**
   
   When you run `mcp-fitbit` for the first time, it will tell you exactly where to create the `.env` file. It will look something like:
   ```
   C:\Users\YourName\AppData\Roaming\npm\node_modules\mcp-fitbit\.env
   ```

4. **Add your credentials to the `.env` file:**
   ```bash
   FITBIT_CLIENT_ID=your_client_id_here
   FITBIT_CLIENT_SECRET=your_client_secret_here
   ```

5. **Run the server:**
   ```bash
   mcp-fitbit
   ```

### For Developers (from source)

1. **Get Fitbit API credentials** at [dev.fitbit.com](https://dev.fitbit.com/)
   - Set **OAuth 2.0 Application Type** to `Personal`
   - Set **Callback URL** to `http://localhost:3000/callback`

2. **Clone and setup:**
   ```bash
   git clone https://github.com/TheDigitalNinja/mcp-fitbit
   cd mcp-fitbit
   npm install
   ```

3. **Create `.env` file:**
   ```bash
   FITBIT_CLIENT_ID=your_client_id_here
   FITBIT_CLIENT_SECRET=your_client_secret_here
   ```

4. **Build the server:**
   ```bash
   npm run build
   ```


## Available Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `get_weight` | Weight data over time periods | `period`: `1d`, `7d`, `30d`, `3m`, `6m`, `1y` |
| `get_sleep_by_date_range` | Sleep logs for date range (max 100 days) | `startDate`, `endDate` (YYYY-MM-DD) |
| `get_exercises` | Activity/exercise logs after date | `afterDate` (YYYY-MM-DD), `limit` (1-100) |
| `get_daily_activity_summary` | Daily activity summary with goals | `date` (YYYY-MM-DD) |
| `get_activity_goals` | User's activity goals (daily/weekly) | `period`: `daily`, `weekly` |
| `get_activity_timeseries` | Activity time series data (max 30 days) | `resourcePath`, `startDate`, `endDate` (YYYY-MM-DD) |
| `get_azm_timeseries` | Active Zone Minutes time series (max 1095 days) | `startDate`, `endDate` (YYYY-MM-DD) |
| `get_heart_rate` | Heart rate for time period | `period`: `1d`, `7d`, `30d`, `1w`, `1m`, optional `date` |
| `get_heart_rate_by_date_range` | Heart rate for date range (max 1 year) | `startDate`, `endDate` (YYYY-MM-DD) |
| `get_food_log` | Complete nutrition data for a day | `date` (YYYY-MM-DD or "today") |
| `get_nutrition` | Individual nutrient over time | `resource`, `period`, optional `date` |
| `get_nutrition_by_date_range` | Individual nutrient for date range | `resource`, `startDate`, `endDate` |
| `get_profile` | User profile information | None |

**Nutrition resources:** `caloriesIn`, `water`, `protein`, `carbs`, `fat`, `fiber`, `sodium`

**Activity time series resources:** `steps`, `distance`, `calories`, `activityCalories`, `caloriesBMR`, `tracker/activityCalories`, `tracker/calories`, `tracker/distance`

### Claude Desktop

**Using npm package (recommended):**

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "fitbit": {
      "command": "mcp-fitbit",
      "args": []
    }
  }
}
```

**Using local development version:**

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "fitbit": {
      "command": "node",
      "args": ["C:\\path\\to\\mcp-fitbit\\build\\index.js"]
    }
  }
}
```

**Config file locations:**
- Windows: `%AppData%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

### First Run Authorization

When you first ask your AI assistant to use Fitbit data:
1. The server opens your browser to `http://localhost:3000/auth`
2. Log in to Fitbit and grant permissions
3. You'll be redirected to a success page
4. Your AI can now access your Fitbit data!

## Development

```bash
npm run lint          # Check code quality
npm run format        # Fix formatting
npm run build         # Compile TypeScript
npm run dev           # Run with MCP inspector
```

**Architecture:** See [TASKS.md](TASKS.md) for improvement opportunities and technical details.

