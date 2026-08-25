import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { registerActivitiesTool } from './activities.js';
import * as utils from './utils.js';
import { ERROR_MESSAGES } from './config.js'; // Import ERROR_MESSAGES

// Mock the utils module
vi.mock('./utils.js', async (importOriginal) => {
  const actual = await importOriginal() as typeof utils;
  return {
    ...actual, // Spread actual module exports
    registerTool: vi.fn(),
    // makeFitbitRequest: vi.fn(), // activities.ts uses handleFitbitApiCall
    handleFitbitApiCall: vi.fn(), // Mock handleFitbitApiCall instead
    // CommonSchemas will be spread from actual
  };
});

describe('Activities Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  // let mockMakeFitbitRequest: ReturnType<typeof vi.fn>; // Not needed directly
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;


  beforeEach(() => {
    mockServer = {} as McpServer;
    mockGetAccessToken = vi.fn().mockResolvedValue('test_access_token');
    mockRegisterTool = vi.mocked(utils.registerTool);
    // mockMakeFitbitRequest = vi.mocked(utils.makeFitbitRequest); // Not needed
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerActivitiesTool', () => {
    it('should register the get_exercises tool with correct configuration', () => {
      registerActivitiesTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      const registeredConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredConfig.name).toBe('get_exercises');
      expect(registeredConfig.description).toBe("Get the raw JSON response for exercise and activity logs from Fitbit after a specific date. Requires 'afterDate' parameter in 'YYYY-MM-DD' format. Retrieves a detailed list of logged exercises and activities.");
      // Access CommonSchemas from the actual utils module as it's not mocked away
      expect(registeredConfig.parametersSchema).toEqual({
        afterDate: utils.CommonSchemas.afterDate,
        limit: utils.CommonSchemas.limit,
      });
      expect(registeredConfig.handler).toBeInstanceOf(Function);
    });

    describe('Handler Logic', () => {
      const mockActivityData = { activities: [{ activityId: 1, name: 'Running' }] };
      const mockApiResponse = { content: [{ type: 'text', text: JSON.stringify(mockActivityData.activities) }] };

      beforeEach(() => {
        // mockMakeFitbitRequest.mockResolvedValue(mockActivityData); // Not needed
        mockHandleFitbitApiCall.mockResolvedValue(mockApiResponse);
      });

      it('should call handleFitbitApiCall with correct endpoint and parameters', async () => {
        registerActivitiesTool(mockServer, mockGetAccessToken);
        const handler = mockRegisterTool.mock.calls[0][1].handler;
        const params = { afterDate: '2024-01-15', limit: 15 };
        
        const result = await handler(params);

        expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
          'activities/list.json?afterDate=2024-01-15&sort=asc&offset=0&limit=15',
          params, // The handler passes the validated params object
          mockGetAccessToken,
          expect.objectContaining({
            successDataExtractor: expect.any(Function),
            noDataMessage: "after date '2024-01-15'",
            errorContext: "after date '2024-01-15'"
          })
        );
        expect(result).toEqual(mockApiResponse);
      });
      
      it('should use default limit if not provided', async () => {
        registerActivitiesTool(mockServer, mockGetAccessToken);
        const handler = mockRegisterTool.mock.calls[0][1].handler;
        const params = { afterDate: '2024-01-01' }; // limit defaults to 20
        
        await handler(params);
        
        expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
          'activities/list.json?afterDate=2024-01-01&sort=asc&offset=0&limit=20',
          { afterDate: '2024-01-01', limit: 20 }, // Handler will add default limit
          mockGetAccessToken,
          expect.any(Object) // Simplified expectation for options object
        );
      });

      it('should handle API errors gracefully (as handled by handleFitbitApiCall)', async () => {
        const errorMessage = 'Fitbit API error';
        const errorResponse = { content: [{ type: 'text', text: errorMessage }], isError: true };
        mockHandleFitbitApiCall.mockResolvedValue(errorResponse); // Simulate error from handleFitbitApiCall
        
        registerActivitiesTool(mockServer, mockGetAccessToken);
        const handler = mockRegisterTool.mock.calls[0][1].handler;
        const params = { afterDate: '2024-01-15' };

        const result = await handler(params);
        expect(result).toEqual(errorResponse);
      });

      it('should handle null access token (as handled by handleFitbitApiCall)', async () => {
        const noTokenMessage = ERROR_MESSAGES.NO_ACCESS_TOKEN; // Use imported ERROR_MESSAGES
        const errorResponse = { content: [{ type: 'text', text: noTokenMessage }], isError: true };
        mockGetAccessToken.mockResolvedValue(null);
        mockHandleFitbitApiCall.mockImplementation(async (_endpoint, _params, getAccessTokenFn) => {
            const token = await getAccessTokenFn();
            if (!token) {
                return { content: [{ type: 'text', text: ERROR_MESSAGES.NO_ACCESS_TOKEN }], isError: true }; // Use imported ERROR_MESSAGES
            }
            return { content: [{ type: 'text', text: 'Unexpected success' }] }; 
        });

        registerActivitiesTool(mockServer, mockGetAccessToken);
        const handler = mockRegisterTool.mock.calls[0][1].handler;
        const params = { afterDate: '2024-01-15' };

        const result = await handler(params);
        expect(result).toEqual(errorResponse);
      });

      // Parameter validation tests (Zod handles this before the handler is called)
      // These tests ensure the schema is correctly defined in registerTool
      it('should have correct Zod schema for afterDate', () => {
        registerActivitiesTool(mockServer, mockGetAccessToken);
        const schema = mockRegisterTool.mock.calls[0][1].parametersSchema;
        expect(() => schema.afterDate.parse('2024-12-31')).not.toThrow();
        expect(() => schema.afterDate.parse('invalid-date')).toThrow(z.ZodError);
      });

      it('should have correct Zod schema for limit', () => {
        registerActivitiesTool(mockServer, mockGetAccessToken);
        const schema = mockRegisterTool.mock.calls[0][1].parametersSchema;
        expect(() => schema.limit.parse(10)).not.toThrow();
        expect(() => schema.limit.parse(0)).toThrow(z.ZodError); // Assuming limit must be > 0 based on CommonSchemas.limit
        expect(() => schema.limit.parse(101)).toThrow(z.ZodError); // Assuming limit has a max based on CommonSchemas.limit
        expect(() => schema.limit.parse('abc')).toThrow(z.ZodError);
      });
    });
  });
});
