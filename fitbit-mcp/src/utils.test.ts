import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import {
  makeFitbitRequest,
  createErrorResponse,
  createSuccessResponse,
  createNoDataResponse,
  registerTool,
  handleFitbitApiCall,
  type ToolConfig,
  type ToolResponseStructure
} from './utils.js';
import { FITBIT_API_VERSIONS, ERROR_MESSAGES } from './config.js';

// Mock global fetch
global.fetch = vi.fn();

describe('Utility Functions', () => {
  let mockGetAccessTokenFn: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockGetAccessTokenFn = vi.fn();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('makeFitbitRequest', () => {
    it('should make a successful request and return JSON data', async () => {
      const mockData = { foo: 'bar' };
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => mockData,
        status: 200
      });

      const result = await makeFitbitRequest('test/endpoint', mockGetAccessTokenFn);
      expect(result).toEqual(mockData);
      expect(fetch).toHaveBeenCalledWith(
        `${FITBIT_API_VERSIONS.V1}/user/-/test/endpoint`,
        expect.any(Object)
      );
    });

    it('should handle endpoint with leading slash', async () => {
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({}),
        status: 200
      });

      await makeFitbitRequest('/test/endpoint', mockGetAccessTokenFn);
      expect(fetch).toHaveBeenCalledWith(
        `${FITBIT_API_VERSIONS.V1}/user/-/test/endpoint`,
        expect.any(Object)
      );
    });

    it('should return null if no access token is available', async () => {
      mockGetAccessTokenFn.mockResolvedValue(null);
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const result = await makeFitbitRequest('test/endpoint', mockGetAccessTokenFn);
      expect(result).toBeNull();
      expect(fetch).not.toHaveBeenCalled();
      expect(consoleErrorSpy).toHaveBeenCalledWith(`Error: ${ERROR_MESSAGES.NO_ACCESS_TOKEN}`);
      consoleErrorSpy.mockRestore();
    });

    it('should return null and log error on API error (non-2xx status)', async () => {
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => 'Internal Server Error'
      });
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const result = await makeFitbitRequest('test/endpoint', mockGetAccessTokenFn);
      expect(result).toBeNull();
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Fitbit API Error! Status: 500')
      );
      consoleErrorSpy.mockRestore();
    });
    
    it('should log token expired message on 401 error', async () => {
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: false,
        status: 401,
        text: async () => 'Unauthorized'
      });
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      await makeFitbitRequest('test/endpoint', mockGetAccessTokenFn);
      expect(consoleErrorSpy).toHaveBeenCalledWith(ERROR_MESSAGES.TOKEN_EXPIRED);
      consoleErrorSpy.mockRestore();
    });

    it('should return an empty object for 204 No Content response', async () => {
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        status: 204,
        json: async () => null, // Should not be called
        text: async () => ''
      });

      const result = await makeFitbitRequest('test/endpoint', mockGetAccessTokenFn);
      expect(result).toEqual({});
    });

    it('should return null and log error on network error (fetch throws)', async () => {
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('Network failure'));
      const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const result = await makeFitbitRequest('test/endpoint', mockGetAccessTokenFn);
      expect(result).toBeNull();
      expect(consoleErrorSpy).toHaveBeenCalledWith(
        expect.stringContaining('Error making Fitbit request'),
        expect.any(Error)
      );
      consoleErrorSpy.mockRestore();
    });

    it('should use provided apiBase', async () => {
      const mockData = { foo: 'bar' };
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => mockData,
        status: 200
      });
      const customApiBase = 'https://api.fitbit.com/1.2';

      await makeFitbitRequest('test/endpoint', mockGetAccessTokenFn, customApiBase);
      expect(fetch).toHaveBeenCalledWith(
        `${customApiBase}/user/-/test/endpoint`,
        expect.any(Object)
      );
    });
  });

  describe('Response Helper Functions', () => {
    it('createErrorResponse should format error message correctly', () => {
      const message = 'Test error';
      const response = createErrorResponse(message);
      expect(response).toEqual({
        content: [{ type: 'text', text: message }],
        isError: true
      });
    });

    it('createSuccessResponse should format success data correctly', () => {
      const data = { result: 'success' };
      const response = createSuccessResponse(data);
      expect(response).toEqual({
        content: [{ type: 'text', text: JSON.stringify(data, null, 2) }]
      });
    });

    it('createNoDataResponse should format no data message correctly', () => {
      const context = 'test context';
      const response = createNoDataResponse(context);
      expect(response).toEqual({
        content: [{ type: 'text', text: `${ERROR_MESSAGES.NO_DATA_FOUND} ${context}.` }]
      });
    });
  });

  describe('registerTool', () => {
    it('should call server.tool with correct parameters', () => {
      const mockServer = { tool: vi.fn() } as unknown as McpServer;
      const mockHandler = vi.fn();
      const toolConfig: ToolConfig = {
        name: 'test_tool',
        description: 'A test tool',
        parametersSchema: {},
        handler: mockHandler
      };

      registerTool(mockServer, toolConfig);

      expect(mockServer.tool).toHaveBeenCalledWith(
        toolConfig.name,
        toolConfig.description,
        toolConfig.parametersSchema,
        toolConfig.handler
      );
    });
  });

  describe('handleFitbitApiCall', () => {
    let mockMakeFitbitRequest: ReturnType<typeof vi.fn>;
    
    // We need to mock makeFitbitRequest from the same module.
    // This is a bit tricky with ES modules and Vitest.
    // A common way is to re-import the module and spy on the specific function.
    // However, for simplicity here, we'll assume makeFitbitRequest is tested
    // and focus on handleFitbitApiCall's logic around it.
    // For a more robust test, you might need `vi.unstable_mockModule` or similar.

    beforeEach(() => {
      // This direct mock won't work as expected due to ESM module caching.
      // We'll rely on the global fetch mock for makeFitbitRequest's behavior.
      // This means these tests are more integration-like for handleFitbitApiCall + makeFitbitRequest.
    });

    it('should return success response when makeFitbitRequest succeeds', async () => {
      const mockApiData = { data: 'some data' };
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => mockApiData,
        status: 200
      });

      const result = await handleFitbitApiCall('test/endpoint', {}, mockGetAccessTokenFn);
      expect(result).toEqual(createSuccessResponse(mockApiData));
    });

    it('should return error response when makeFitbitRequest returns null', async () => {
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ // Simulate makeFitbitRequest failure
        ok: false,
        status: 500,
        text: async () => 'API Error'
      });
      const params = { date: '2024-01-01' };
      const errorContext = JSON.stringify(params);

      const result = await handleFitbitApiCall('test/endpoint', params, mockGetAccessTokenFn);
      expect(result).toEqual(
        createErrorResponse(
          `${ERROR_MESSAGES.API_REQUEST_FAILED} for ${errorContext}. ${ERROR_MESSAGES.CHECK_TOKEN_PERMISSIONS}.`
        )
      );
    });

    it('should use successDataExtractor and return success if data exists', async () => {
      const mockApiData = { items: [{ id: 1 }, { id: 2 }] };
      const successDataExtractor = vi.fn((data: typeof mockApiData) => data.items);
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => mockApiData,
        status: 200
      });

      const result = await handleFitbitApiCall(
        'test/endpoint',
        {},
        mockGetAccessTokenFn,
        { successDataExtractor }
      );
      expect(successDataExtractor).toHaveBeenCalledWith(mockApiData);
      expect(result).toEqual(createSuccessResponse(mockApiData));
    });

    it('should use successDataExtractor and return noDataResponse if extracted data is empty', async () => {
      const mockApiData = { items: [] };
      const successDataExtractor = vi.fn((data: typeof mockApiData) => data.items);
      const noDataMessage = 'custom no data message';
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => mockApiData,
        status: 200
      });

      const result = await handleFitbitApiCall(
        'test/endpoint',
        {},
        mockGetAccessTokenFn,
        { successDataExtractor, noDataMessage }
      );
      expect(successDataExtractor).toHaveBeenCalledWith(mockApiData);
      expect(result).toEqual(createNoDataResponse(noDataMessage));
    });
    
    it('should use default noDataMessage if extractor returns empty and noDataMessage is not provided', async () => {
      const mockApiData = { items: [] };
      const successDataExtractor = vi.fn((data: typeof mockApiData) => data.items);
      const params = { query: 'test' };
      const errorContext = JSON.stringify(params);
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => mockApiData,
        status: 200
      });

      const result = await handleFitbitApiCall(
        'test/endpoint',
        params,
        mockGetAccessTokenFn,
        { successDataExtractor }
      );
      expect(result).toEqual(createNoDataResponse(errorContext));
    });

    it('should use custom apiBase if provided', async () => {
      const customApiBase = 'https://custom.api.fitbit.com/v2';
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
        ok: true,
        json: async () => ({}),
        status: 200
      });

      await handleFitbitApiCall('test/endpoint', {}, mockGetAccessTokenFn, { apiBase: customApiBase });
      expect(fetch).toHaveBeenCalledWith(
        `${customApiBase}/user/-/test/endpoint`,
        expect.any(Object)
      );
    });
    
    it('should use custom errorContext if provided', async () => {
      mockGetAccessTokenFn.mockResolvedValue('test_token');
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ 
        ok: false,
        status: 500,
        text: async () => 'API Error'
      });
      const customErrorContext = 'my specific operation';

      const result = await handleFitbitApiCall('test/endpoint', {}, mockGetAccessTokenFn, { errorContext: customErrorContext });
      expect(result.content[0].text).toContain(`${ERROR_MESSAGES.API_REQUEST_FAILED} for ${customErrorContext}`);
    });
  });
});
