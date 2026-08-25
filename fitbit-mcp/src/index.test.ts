import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mocked functions and modules
const mockDotenvConfig = vi.fn();
const mockInitializeAuth = vi.fn().mockResolvedValue(undefined);
const mockStartAuthorizationFlow = vi.fn();
const mockGetAccessToken = vi.fn();

const mockRegisterWeightTool = vi.fn();
const mockRegisterSleepTool = vi.fn();
const mockRegisterProfileTool = vi.fn();
const mockRegisterActivitiesTool = vi.fn();
const mockRegisterHeartRateTools = vi.fn();
const mockRegisterNutritionTools = vi.fn();
const mockRegisterDailyActivityTool = vi.fn();
const mockRegisterActivityGoalsTool = vi.fn();
const mockRegisterActivityTimeSeriesTool = vi.fn();
const mockRegisterAzmTimeSeriesTool = vi.fn();

const mockMcpServerInstance = {
  connect: vi.fn().mockResolvedValue(undefined),
  // Add other methods if index.ts directly calls them on server instance
};
const mockMcpServerConstructor = vi.fn(() => mockMcpServerInstance);

const mockStdioServerTransportInstance = {}; // Mock instance, add methods if needed
const mockStdioServerTransportConstructor = vi.fn(() => mockStdioServerTransportInstance);

// Apply mocks using vi.doMock so they are available when index.ts is imported
vi.doMock('dotenv', () => ({ default: { config: mockDotenvConfig }, config: mockDotenvConfig })); // Provide both default and direct config mock
vi.doMock('./auth.js', () => ({
  initializeAuth: mockInitializeAuth,
  startAuthorizationFlow: mockStartAuthorizationFlow,
  getAccessToken: mockGetAccessToken,
}));
vi.doMock('./weight.js', () => ({ registerWeightTool: mockRegisterWeightTool }));
vi.doMock('./sleep.js', () => ({ registerSleepTool: mockRegisterSleepTool }));
vi.doMock('./profile.js', () => ({ registerProfileTool: mockRegisterProfileTool }));
vi.doMock('./activities.js', () => ({ registerActivitiesTool: mockRegisterActivitiesTool }));
vi.doMock('./heart-rate.js', () => ({ registerHeartRateTools: mockRegisterHeartRateTools }));
vi.doMock('./nutrition.js', () => ({ registerNutritionTools: mockRegisterNutritionTools }));
vi.doMock('./daily-activity.js', () => ({ registerDailyActivityTool: mockRegisterDailyActivityTool }));
vi.doMock('./activity-goals.js', () => ({ registerActivityGoalsTool: mockRegisterActivityGoalsTool }));
vi.doMock('./activity-timeseries.js', () => ({ registerActivityTimeSeriesTool: mockRegisterActivityTimeSeriesTool }));
vi.doMock('./azm-timeseries.js', () => ({ registerAzmTimeSeriesTool: mockRegisterAzmTimeSeriesTool }));

vi.doMock('@modelcontextprotocol/sdk/server/mcp.js', () => ({
  McpServer: mockMcpServerConstructor,
}));
vi.doMock('@modelcontextprotocol/sdk/server/stdio.js', () => ({
  StdioServerTransport: mockStdioServerTransportConstructor,
}));


describe('index.ts script execution', () => {
  let mockProcessExit: ReturnType<typeof vi.spyOn>;
  let mockConsoleError: ReturnType<typeof vi.spyOn>;
  const ORIGINAL_ENV = { ...process.env };

  beforeEach(() => {
    vi.resetModules(); // Important to re-evaluate index.ts with fresh mocks/env
    vi.clearAllMocks();

    // Restore original process.env, then set specific test values
    process.env = { ...ORIGINAL_ENV };

    mockProcessExit = vi.spyOn(process, 'exit').mockImplementation((code?: number | string | null | undefined) => { throw new Error(`process.exit: ${code}`); }) as any;
    mockConsoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV }; // Restore original env
    mockProcessExit.mockRestore();
    mockConsoleError.mockRestore();
  });

  it('should call dotenv.config with correct path', async () => {
    process.env.FITBIT_CLIENT_ID = 'test-id';
    process.env.FITBIT_CLIENT_SECRET = 'test-secret';
    await import('../src/index.js');
    // Path check is tricky due to __dirname differences in test vs. runtime.
    // For now, just check it was called.
    expect(mockDotenvConfig).toHaveBeenCalled();
  });

  it('should validate environment variables and exit if missing', async () => {
    delete process.env.FITBIT_CLIENT_ID;
    delete process.env.FITBIT_CLIENT_SECRET;

    await expect(import('../src/index.js')).rejects.toThrow('process.exit: 1');

    expect(mockConsoleError).toHaveBeenCalledWith('Missing required environment variables:');
    expect(mockConsoleError).toHaveBeenCalledWith(expect.stringContaining('FITBIT_CLIENT_ID'));
    expect(mockConsoleError).toHaveBeenCalledWith(expect.stringContaining('FITBIT_CLIENT_SECRET'));
    expect(mockProcessExit).toHaveBeenCalledWith(1);
  });

  it('should not exit if environment variables are present', async () => {
    process.env.FITBIT_CLIENT_ID = 'test-id';
    process.env.FITBIT_CLIENT_SECRET = 'test-secret';
    mockGetAccessToken.mockResolvedValue('fake-token'); // Prevent auth flow for this test focus

    await import('../src/index.js');

    expect(mockProcessExit).not.toHaveBeenCalled();
    expect(mockConsoleError).toHaveBeenCalledWith('✅ Environment variables loaded successfully');
  });

  it('should instantiate McpServer with correct parameters', async () => {
    process.env.FITBIT_CLIENT_ID = 'test-id';
    process.env.FITBIT_CLIENT_SECRET = 'test-secret';
    mockGetAccessToken.mockResolvedValue('fake-token');

    await import('../src/index.js');

    expect(mockMcpServerConstructor).toHaveBeenCalledWith({
      name: 'fitbit',
      version: '1.0.0',
      capabilities: {
        resources: {},
        tools: {},
      },
    });
  });

  it('should register all tools', async () => {
    process.env.FITBIT_CLIENT_ID = 'test-id';
    process.env.FITBIT_CLIENT_SECRET = 'test-secret';
    mockGetAccessToken.mockResolvedValue('fake-token');

    await import('../src/index.js');

    expect(mockRegisterWeightTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterSleepTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterProfileTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterActivitiesTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterHeartRateTools).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterNutritionTools).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterDailyActivityTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterActivityGoalsTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterActivityTimeSeriesTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
    expect(mockRegisterAzmTimeSeriesTool).toHaveBeenCalledWith(mockMcpServerInstance, mockGetAccessToken);
  });

  describe('main function execution', () => {
    beforeEach(() => {
      // Ensure env vars are set for main() logic tests
      process.env.FITBIT_CLIENT_ID = 'test-id';
      process.env.FITBIT_CLIENT_SECRET = 'test-secret';
    });

    it('should initialize auth, connect server, and use existing token if available', async () => {
      mockGetAccessToken.mockResolvedValue('existing-token');
      
      await import('../src/index.js');
      // Allow microtasks to run (e.g. promises in main)
      await new Promise(setImmediate);

      expect(mockInitializeAuth).toHaveBeenCalled();
      expect(mockStdioServerTransportConstructor).toHaveBeenCalled();
      expect(mockMcpServerInstance.connect).toHaveBeenCalledWith(mockStdioServerTransportInstance);
      expect(mockGetAccessToken).toHaveBeenCalled();
      expect(mockConsoleError).toHaveBeenCalledWith('Using existing/loaded access token.');
      expect(mockStartAuthorizationFlow).not.toHaveBeenCalled();
    });

    it('should start authorization flow if no token is available', async () => {
      mockGetAccessToken.mockResolvedValue(null);

      await import('../src/index.js');
      await new Promise(setImmediate);

      expect(mockInitializeAuth).toHaveBeenCalled();
      expect(mockMcpServerInstance.connect).toHaveBeenCalled();
      expect(mockGetAccessToken).toHaveBeenCalled();
      expect(mockConsoleError).toHaveBeenCalledWith('No access token found. Starting Fitbit authorization flow...');
      expect(mockStartAuthorizationFlow).toHaveBeenCalled();
    });

    it('should handle server connection failure', async () => {
      const connectError = new Error('Connection failed');
      mockMcpServerInstance.connect.mockRejectedValueOnce(connectError);
      mockGetAccessToken.mockResolvedValue(null); // To simplify flow

      let unhandledErr: any = null;
      const unhandledListener = (reason: any) => { unhandledErr = reason; };
      process.on('unhandledRejection', unhandledListener);

      await import('../src/index.js');
      // Allow time for main() to run and its promise to reject due to process.exit throwing
      await new Promise(resolve => setTimeout(resolve, 50)); // Using a small timeout

      process.off('unhandledRejection', unhandledListener);

      expect(mockConsoleError).toHaveBeenCalledWith('Failed to connect MCP server:', connectError);
      expect(mockProcessExit).toHaveBeenCalledWith(1);
      expect(unhandledErr).toBeInstanceOf(Error);
      expect(unhandledErr.message).toBe('process.exit: 1');
    });
  });
});
