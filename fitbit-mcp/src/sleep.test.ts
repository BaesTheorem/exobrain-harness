import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { registerSleepTool } from './sleep.js';
import * as utils from './utils.js';
import { CommonSchemas } from './utils.js';
import { FITBIT_API_VERSIONS, VALIDATION_MESSAGES } from './config.js';

// Mock the utils module
vi.mock('./utils.js', async () => {
  const actualUtils = await vi.importActual('./utils.js');
  return {
    ...actualUtils, // Import and retain actual CommonSchemas
    registerTool: vi.fn(),
    handleFitbitApiCall: vi.fn()
  };
});

// Mock the config module to control FITBIT_API_VERSIONS if needed for tests
// For now, we assume sleep.ts correctly imports and uses it.
vi.mock('./config.js', async () => {
  const actualConfig = await vi.importActual('./config.js');
  return {
    ...actualConfig,
    // If specific versions need to be mocked for testing, do it here.
  };
});

describe('Sleep Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockServer = {} as McpServer;
    mockGetAccessToken = vi.fn().mockResolvedValue('test_access_token');
    mockRegisterTool = vi.mocked(utils.registerTool);
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerSleepTool', () => {
    it('should register the get_sleep_by_date_range tool with correct configuration', () => {
      registerSleepTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      expect(mockRegisterTool).toHaveBeenCalledWith(mockServer, {
        name: 'get_sleep_by_date_range',
        description: `Get the raw JSON response for sleep logs from Fitbit for a specific date range. Requires 'startDate' and 'endDate' parameters in 'YYYY-MM-DD' format. ${VALIDATION_MESSAGES.MAX_RANGE_100_DAYS}.`,
        parametersSchema: {
          startDate: CommonSchemas.startDate,
          endDate: CommonSchemas.endDate,
        },
        handler: expect.any(Function)
      });
    });

    it('should call handler with correct endpoint, parameters, and options', async () => {
      const mockSleepData = { sleep: [{ logId: 123, dateOfSleep: '2025-05-25' }] };
      const testParams = { startDate: '2025-05-01', endDate: '2025-05-25' };

      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockSleepData.sleep) }]
      });

      registerSleepTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      const result = await handler(testParams);

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        `/sleep/date/${testParams.startDate}/${testParams.endDate}.json`,
        testParams,
        mockGetAccessToken,
        {
          apiBase: FITBIT_API_VERSIONS.V1_2,
          successDataExtractor: expect.any(Function),
          noDataMessage: `the date range '${testParams.startDate}' to '${testParams.endDate}'`,
          errorContext: `date range '${testParams.startDate}' to '${testParams.endDate}'`
        }
      );

      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockSleepData.sleep) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const errorMessage = 'Fitbit API error';
      const testParams = { startDate: '2025-05-01', endDate: '2025-05-25' };
      mockHandleFitbitApiCall.mockRejectedValue(new Error(errorMessage));

      registerSleepTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler(testParams)).rejects.toThrow(errorMessage);

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        `/sleep/date/${testParams.startDate}/${testParams.endDate}.json`,
        testParams,
        mockGetAccessToken,
        expect.objectContaining({
          apiBase: FITBIT_API_VERSIONS.V1_2,
        })
      );
    });

    it('should handle null access token', async () => {
      const testParams = { startDate: '2025-05-01', endDate: '2025-05-25' };
      mockGetAccessToken.mockResolvedValue(null);
      // Simulate the error that would be thrown by handleFitbitApiCall or its internals
      mockHandleFitbitApiCall.mockRejectedValue(new Error('No access token available')); 

      registerSleepTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler(testParams)).rejects.toThrow('No access token available');
    });

    it('should use correct endpoint URL structure', async () => {
      const testParams = { startDate: '2025-01-01', endDate: '2025-01-31' };
      registerSleepTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      // Catch expected error if API call fails, we only care about the endpoint arg
      await handler(testParams).catch(() => {}); 

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        `/sleep/date/${testParams.startDate}/${testParams.endDate}.json`,
        testParams,
        mockGetAccessToken,
        expect.any(Object) // Options object
      );
    });

    it('should have correct parameters schema', () => {
      registerSleepTool(mockServer, mockGetAccessToken);
      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      expect(registeredToolConfig.parametersSchema).toEqual({
        startDate: CommonSchemas.startDate,
        endDate: CommonSchemas.endDate,
      });
    });

    it('should correctly extract data with successDataExtractor', async () => {
      const rawApiResponse = { sleep: [{ logId: 789, dateOfSleep: '2025-05-20' }], summary: {} };
      const testParams = { startDate: '2025-05-20', endDate: '2025-05-20' };
      
      let successDataExtractor: (data: any) => any = (data) => data; // Default

      mockHandleFitbitApiCall.mockImplementation(async (endpoint, params, tokenFn, opts) => {
        if (opts && typeof opts.successDataExtractor === 'function') {
          successDataExtractor = opts.successDataExtractor;
        }
        return { content: [{ type: 'text', text: JSON.stringify(successDataExtractor(rawApiResponse)) }] };
      });
      
      registerSleepTool(mockServer, mockGetAccessToken);
      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;
      
      await handler(testParams); // Call handler to ensure opts are passed

      const extractedData = successDataExtractor(rawApiResponse);
      expect(extractedData).toEqual(rawApiResponse.sleep);

      const extractedDataEmpty = successDataExtractor({ 'otherKey': [] }); // No 'sleep' key
      expect(extractedDataEmpty).toEqual([]);
    });
  });
});
