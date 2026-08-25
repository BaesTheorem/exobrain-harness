import dotenv from 'dotenv';
import express, { Request, Response } from 'express';
import http from 'http';
import open from 'open';
import path from 'path';
import { AuthorizationCode, Token } from 'simple-oauth2';
import { fileURLToPath } from 'url';
import fs from 'fs/promises';
import { existsSync } from 'fs';
import { FITBIT_OAUTH_CONFIG } from './config.js';

// TypeScript interfaces for token data structures
// The Token interface from simple-oauth2 uses this structure
interface FitbitTokenData extends Token {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  expires_at?: string;
  scope: string;
  token_type: string;
  user_id: string;
}

interface FitbitOAuthErrorBody {
  // Structure of the error object returned by Fitbit API.
  // This is a placeholder. Update with specific fields if an example
  // of a Fitbit API error response becomes available.
  [key: string]: unknown;
}

interface FitbitOAuthError extends Error {
  message: string;
  response?: {
    text: () => Promise<string>;
    status?: number;
    body?: FitbitOAuthErrorBody; // More specific body
  };
  // simple-oauth2 might add other properties like 'context'
  context?: unknown; 
}

// Determine the directory of the current module (build/auth.js)
const currentFilename = fileURLToPath(import.meta.url);
const currentDirname = path.dirname(currentFilename);

// Load environment variables from .env file located in the project root
const envPath = path.resolve(currentDirname, '..', '.env');
dotenv.config({ path: envPath });

// Fitbit OAuth2 Configuration
const fitbitConfig = {
  client: {
    id: process.env.FITBIT_CLIENT_ID || '',
    secret: process.env.FITBIT_CLIENT_SECRET || '',
  },
  auth: {
    tokenHost: 'https://api.fitbit.com',
    authorizePath: 'https://www.fitbit.com/oauth2/authorize',
    tokenPath: 'https://api.fitbit.com/oauth2/token',
  },
  options: {
    authorizationMethod: 'header' as const,
  },
};

// OAuth2 Redirect URI and local server port
const REDIRECT_URI = 'http://localhost:3000/callback';
const PORT = 3000;

// --- State Management ---
// Storage for the access token and token data
let accessToken: string | null = null;
let tokenData: FitbitTokenData | null = null;
// Holds the temporary HTTP server instance used for the OAuth callback
let oauthServer: http.Server | null = null;

// --- File paths for token persistence ---
const TOKEN_FILE_PATH = path.resolve(
  currentDirname,
  '..',
  '.fitbit-token.json'
);

// --- OAuth Client Initialization ---
const oauthClient = new AuthorizationCode(fitbitConfig);

/**
 * Saves the token data to a file for persistence
 * @param tokenData The token data to save
 */
async function saveTokenToFile(tokenData: FitbitTokenData): Promise<void> {
  try {
    await fs.writeFile(
      TOKEN_FILE_PATH,
      JSON.stringify(tokenData, null, 2),
      'utf8'
    );
    console.error(`Token saved to ${TOKEN_FILE_PATH}`);
  } catch (error) {
    console.error(`Error saving token to file: ${error}`);
  }
}

/**
 * Loads the token data from file
 * @returns The token data or null if not found
 */
async function loadTokenFromFile(): Promise<FitbitTokenData | null> {
  try {
    if (!existsSync(TOKEN_FILE_PATH)) {
      console.error(`Token file not found at ${TOKEN_FILE_PATH}`);
      return null;
    }

    const data = await fs.readFile(TOKEN_FILE_PATH, 'utf8');
    const parsedData = JSON.parse(data);
    console.error('Token loaded from file successfully');
    return parsedData;
  } catch (error) {
    console.error(`Error loading token from file: ${error}`);
    return null;
  }
}

// --- Fitbit Authorization Flow ---

/**
 * Initiates the Fitbit OAuth2 authorization code flow.
 * Starts a temporary local web server to handle the redirect callback.
 * Opens the user's browser to the Fitbit authorization page.
 */
export function startAuthorizationFlow(): void {
  // Prevent multiple authorization flows from running simultaneously
  if (oauthServer) {
    console.error('OAuth server is already running.');
    return;
  }
  // Ensure Client ID and Secret are loaded before starting
  if (!fitbitConfig.client.id || !fitbitConfig.client.secret) {
    console.error(
      'Error: Fitbit Client ID or Secret not found. Check environment variables.'
    );
    return;
  }

  const app = express();

  // Generate the Fitbit authorization URL
  const authorizationUri = oauthClient.authorizeURL({
    redirect_uri: REDIRECT_URI,
    // Define necessary scopes required by the application
    scope: FITBIT_OAUTH_CONFIG.SCOPES,
  });

  // Route to initiate the authorization flow by redirecting the user to Fitbit
  app.get('/auth', (req: Request, res: Response) => {
    console.error('Redirecting to Fitbit for authorization...');
    res.redirect(authorizationUri);
  });

  // Callback route that Fitbit redirects to after user authorization
  app.get('/callback', async (req: Request, res: Response) => {
    const code = req.query.code as string;
    // Handle cases where the authorization code is missing
    if (!code) {
      console.error('Authorization code missing in callback.');
      res.status(400).send('Error: Authorization code missing.');
      // Attempt to close the server if it exists
      if (oauthServer) {
        oauthServer.close(() => {
          console.error('OAuth server closed due to missing code.');
        });
        oauthServer = null;
      }
      return;
    }

    console.error('Received authorization code. Exchanging for token...');
    const tokenParams = { code: code, redirect_uri: REDIRECT_URI };

    try {
      // Exchange the authorization code for an access token
      const tokenResult = await oauthClient.getToken(tokenParams);
      console.error('Access Token received successfully!');
      accessToken = tokenResult.token.access_token as string;
      tokenData = tokenResult.token as FitbitTokenData;

      // Persist token data to file
      if (tokenData) {
        await saveTokenToFile(tokenData);
        console.error('Token data has been persisted to file');
      }

      res.send(
        'Authorization successful! You can close this window. The MCP Server is now authenticated.'
      );
    } catch (error: unknown) { 
      // Handle errors during token exchange
      const typedError = error as FitbitOAuthError; 
      console.error('Error obtaining access token:', typedError.message || typedError);
      if (typedError.response) {
        try {
          const errorDetails = await typedError.response.text();
          console.error('Error details:', errorDetails);
          // Optionally parse errorDetails if it's JSON and log typedError.response.body
        } catch {
          console.error('Could not parse error response body.');
        }
      }
      res
        .status(500)
        .send('Error obtaining access token. Check MCP server logs.');
    } finally {
      // Ensure the temporary server is always shut down after handling the callback
      if (oauthServer) {
        console.error('Shutting down temporary OAuth server...');
        oauthServer.close(() => {
          console.error('OAuth server closed.');
          oauthServer = null;
        });
      }
    }
  });

  // Start the temporary local server
  oauthServer = app.listen(PORT, async () => {
    const authUrl = `http://localhost:${PORT}/auth`;
    console.error(
      `--------------------------------------------------------------------`
    );
    console.error(`ACTION REQUIRED: Fitbit Authorization Needed`);
    console.error(`Attempting to open authorization page in your browser:`);
    console.error(authUrl);
    console.error(
      `If the browser doesn't open, please navigate there manually.`
    );
    console.error(`Waiting for authorization callback...`);
    console.error(
      `--------------------------------------------------------------------`
    );
    // Attempt to automatically open the authorization URL in the default browser
    try {
      await open(authUrl);
      console.error(`Browser opened (or attempted).`);
    } catch (err) {
      console.error(`Failed to open browser automatically:`, err);
    }
  });

  // Handle potential errors during server startup
  oauthServer.on('error', (err) => {
    console.error('Error starting temporary OAuth server:', err);
    oauthServer = null;
  });
}

// Refresh this far ahead of the stated expiry instead of waiting for the token to
// actually lapse, so a call never lands on the boundary and fails once before
// recovering. Fitbit access tokens last eight hours, so five minutes costs nothing.
const REFRESH_SKEW_MS = 5 * 60 * 1000;

/** True when the token is missing, already expired, or inside the skew window. */
function needsRefresh(data: FitbitTokenData | null): boolean {
  if (!data || !data.access_token) return true;
  if (!data.expires_at) return false;
  return new Date(data.expires_at).getTime() - Date.now() < REFRESH_SKEW_MS;
}

/**
 * Retrieves the current Fitbit access token, refreshing shortly BEFORE expiry.
 *
 * Fitbit refresh tokens are single use: refreshing returns a new one and burns the
 * old, and the only grace is that identical retries inside a two-minute window get
 * the same response. Several instances of this server run at once here (one per
 * Claude session, plus whatever the launchd routines start) and they all boot from
 * the same token file, so a naive refresh has them racing to spend the same
 * single-use token. First one wins; the losers null out their auth and stay dead
 * until their session restarts.
 *
 * So the file is re-read before AND after refreshing. If another instance already
 * rotated the token, adopt its result rather than spending one that is already gone.
 */
export async function getAccessToken(): Promise<string | null> {
  // Return null if no token data exists
  if (!tokenData || !accessToken) {
    console.error('No valid access token found.');
    return null;
  }

  if (!needsRefresh(tokenData)) {
    return accessToken;
  }

  // Someone else may have refreshed since this instance loaded. Take theirs first.
  const current = tokenData;
  const onDisk = await loadTokenFromFile();
  if (onDisk && !needsRefresh(onDisk)) {
    console.error('Adopted a fresher token written by another instance.');
    tokenData = onDisk;
    accessToken = onDisk.access_token;
    return accessToken;
  }

  console.error('Token is expiring. Attempting to refresh...');
  try {
    // FitbitTokenData is compatible with the 'Token' type expected by createToken
    const accessTokenObj = oauthClient.createToken(onDisk ?? current);
    const refreshedToken = await accessTokenObj.refresh();
    accessToken = refreshedToken.token.access_token as string;
    tokenData = refreshedToken.token as FitbitTokenData;

    await saveTokenToFile(tokenData);
    console.error('Token refreshed and saved successfully.');
    return accessToken;
  } catch (refreshError) {
    console.error('Failed to refresh token:', refreshError);
    // A lost race outside Fitbit's two-minute retry grace looks exactly like this.
    // One more read: if another instance rotated it, that token is still good.
    const rescued = await loadTokenFromFile();
    if (rescued && !needsRefresh(rescued)) {
      console.error('Refresh lost a race; adopted the token another instance saved.');
      tokenData = rescued;
      accessToken = rescued.access_token;
      return accessToken;
    }
    accessToken = null;
    tokenData = null;
    return null;
  }
}

/**
 * Initializes the authentication module.
 * Loads persisted token from file storage if available.
 */
export async function initializeAuth(): Promise<void> {
  console.error('Auth initialized. Checking for persisted token...');

  try {
    // Load token data from file
    tokenData = await loadTokenFromFile();

    if (tokenData && tokenData.access_token) {
      accessToken = tokenData.access_token;
      console.error('Persisted access token loaded successfully.');

      // Deliberately no refresh here. Boot used to be a second, unprotected refresh
      // site, which meant every server that started against an expired token raced
      // the others for the single-use refresh token and could null out its own auth
      // before serving a single request. getAccessToken() now owns refreshing, with
      // the re-read-the-file guard, and it runs on the first actual tool call.
      if (needsRefresh(tokenData)) {
        console.error('Persisted token is expired or near expiry; it will be refreshed on first use.');
      }
    } else {
      console.error('No valid access token found.');
    }
  } catch (error) {
    console.error('Error during token initialization:', error);
  }
}
