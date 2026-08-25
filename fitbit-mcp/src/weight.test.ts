import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { registerWeightTool } from './weight.js';
import * as utils from './utils.js';
import { CommonSchemas } from './utils.js';

// Mock the utils module
vi.mock('./utils.js', async () => {
  const actualUtils = await vi.importActual('./utils.js');
  return {
    ...actualUtils, // Import and retain actual CommonSchemas
    registerTool: vi.fn(),
    handleFitbitApiCall: vi.fn()
  };
});

describe('Weight Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockServer = {} as McpServer;
    mockGetAccessToken = vi.fn();
    mockRegisterTool = vi.mocked(utils.registerTool);
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerWeightTool', () => {
    it('should register the get_weight tool with correct configuration', () => {
      registerWeightTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      expect(mockRegisterTool).toHaveBeenCalledWith(mockServer, {
        name: 'get_weight',
        description: "Get the raw JSON response for weight entries from Fitbit for a specified period ending today. Requires a 'period' parameter such as '1d', '7d', '30d', '3m', '6m', '1y'",
        parametersSchema: {
          period: CommonSchemas.period,
        },
        handler: expect.any(Function)
      });
    });

    it('should call handler with correct endpoint and parameters', async () => {
      const mockWeightData = { 'body-weight': [{ dateTime: '2024-05-25', value: '70' }] };
      const testParams = { period: '7d' };

      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockWeightData['body-weight']) }]
      });

      registerWeightTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      const result = await handler(testParams);

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        `/body/weight/date/today/${testParams.period}.json`,
        testParams,
        mockGetAccessToken,
        {
          successDataExtractor: expect.any(Function),
          noDataMessage: `the period '${testParams.period}'`,
          errorContext: `period '${testParams.period}'`
        }
      );

      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockWeightData['body-weight']) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const errorMessage = 'API rate limit exceeded';
      const testParams = { period: '30d' };
      mockHandleFitbitApiCall.mockRejectedValue(new Error(errorMessage));

      registerWeightTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler(testParams)).rejects.toThrow(errorMessage);

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        `/body/weight/date/today/${testParams.period}.json`,
        testParams,
        mockGetAccessToken,
        expect.any(Object)
      );
    });

    it('should handle null access token', async () => {
      const testParams = { period: '1m' };
      mockGetAccessToken.mockResolvedValue(null);
      mockHandleFitbitApiCall.mockRejectedValue(new Error('No access token available'));

      registerWeightTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler(testParams)).rejects.toThrow('No access token available');
    });

    it('should use correct endpoint URL structure', async () => {
      const testParams = { period: '1y' };
      registerWeightTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await handler(testParams).catch(() => {}); // Ignore errors, just test the call

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        `/body/weight/date/today/${testParams.period}.json`,
        expect.any(Object),
        expect.any(Function),
        expect.any(Object)
      );
    });

    it('should have correct parameters schema', () => {
      registerWeightTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.parametersSchema).toEqual({
        period: CommonSchemas.period,
      });
    });

    it('should correctly extract data with successDataExtractor', async () => {
      const rawApiResponse = { 'body-weight': [{ dateTime: '2024-01-01', value: '75' }] };
      const testParams = { period: '1d' };
      
      // Capture the successDataExtractor
      let successDataExtractor: (data: any) => any = (data) => data; // Default passthrough

      mockHandleFitbitApiCall.mockImplementation(async (endpoint, params, tokenFn, opts) => {
        if (opts && typeof opts.successDataExtractor === 'function') {
          successDataExtractor = opts.successDataExtractor;
        }
        // Simulate a successful API call that returns the raw data
        return { content: [{ type: 'text', text: JSON.stringify(successDataExtractor(rawApiResponse)) }] };
      });
      
      registerWeightTool(mockServer, mockGetAccessToken);
      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;
      
      await handler(testParams); // Call handler to ensure opts are passed

      // Now test the captured extractor
      const extractedData = successDataExtractor(rawApiResponse);
      expect(extractedData).toEqual(rawApiResponse['body-weight']);

      const extractedDataEmpty = successDataExtractor({ 'some-other-key': [] });
      expect(extractedDataEmpty).toEqual([]);
    });
  });
});
