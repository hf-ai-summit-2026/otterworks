import type { IncomingMessage } from 'http';
import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import {
  authenticateUpgradeRequest,
  createAuthMiddleware,
  extractBearerToken,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';

const JWT_SECRET = 'test-secret-key-for-unit-tests';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function sign(payload: Record<string, unknown>): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

function fakeSocket(
  auth: Record<string, unknown> = {},
  headers: Record<string, string> = {},
): Socket {
  return { id: 'sock-1', handshake: { auth, headers } } as unknown as Socket;
}

function fakeRequest(url: string, headers: Record<string, string> = {}): IncomingMessage {
  return { url, headers: { host: 'localhost:8084', ...headers } } as IncomingMessage;
}

describe('extractBearerToken', () => {
  it('strips the Bearer prefix', () => {
    expect(extractBearerToken('Bearer abc.def')).toBe('abc.def');
  });

  it('returns undefined when no header is present', () => {
    expect(extractBearerToken(undefined)).toBeUndefined();
  });
});

describe('createAuthMiddleware', () => {
  const middleware = createAuthMiddleware(JWT_SECRET, mockLogger);

  it('rejects a handshake without a token', () => {
    const next = jest.fn();
    middleware(fakeSocket(), next);
    expect(next).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Authentication required' }),
    );
  });

  it('accepts a bearer token from the authorization header', () => {
    const next = jest.fn();
    const socket = fakeSocket({}, { authorization: `Bearer ${sign({ sub: 'u-1' })}` });
    middleware(socket, next);
    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('u-1');
  });

  it('falls back to display_name and fills defaults for missing claims', () => {
    const next = jest.fn();
    const socket = fakeSocket({ token: sign({ sub: 'u-2', display_name: 'Otter' }) });
    middleware(socket, next);
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'u-2',
      email: '',
      displayName: 'Otter',
      roles: [],
    });
  });

  it('uses Anonymous when no name claim is present', () => {
    const socket = fakeSocket({ token: sign({ sub: 'u-3' }) });
    middleware(socket, jest.fn());
    expect((socket as AuthenticatedSocket).user?.displayName).toBe('Anonymous');
  });

  it('rejects a token signed with another secret', () => {
    const next = jest.fn();
    const token = jwt.sign({ sub: 'u-4' }, 'other-secret'); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
    middleware(fakeSocket({ token }), next);
    expect(next).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Invalid or expired token' }),
    );
  });
});

describe('extractUserFromSocket', () => {
  it('returns an anonymous user for unauthenticated sockets', () => {
    expect(extractUserFromSocket(fakeSocket())).toEqual({
      userId: 'anon-sock-1',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});

describe('authenticateUpgradeRequest', () => {
  it('accepts a valid token from the query string', () => {
    const req = fakeRequest(`/doc-1?token=${sign({ sub: 'u-1' })}`);
    expect(authenticateUpgradeRequest(req, JWT_SECRET)).toBe('ok');
  });

  it('accepts a valid token from the authorization header', () => {
    const req = fakeRequest('/doc-1', {
      authorization: `Bearer ${sign({ sub: 'u-1' })}`,
    });
    expect(authenticateUpgradeRequest(req, JWT_SECRET)).toBe('ok');
  });

  it('reports a missing token', () => {
    expect(authenticateUpgradeRequest(fakeRequest('/doc-1'), JWT_SECRET)).toBe(
      'missing_token',
    );
  });

  it('reports an invalid token', () => {
    const req = fakeRequest('/doc-1?token=not-a-jwt');
    expect(authenticateUpgradeRequest(req, JWT_SECRET)).toBe('invalid_token');
  });

  it('does not throw on a malformed host header and still honours the bearer header', () => {
    const token = sign({ sub: 'u-1' });
    const bad = fakeRequest('/doc-1', {
      host: 'bad host[',
      authorization: `Bearer ${token}`,
    });
    expect(authenticateUpgradeRequest(bad, JWT_SECRET)).toBe('ok');
    const noAuth = fakeRequest('/doc-1', { host: 'bad host[' });
    expect(authenticateUpgradeRequest(noAuth, JWT_SECRET)).toBe('missing_token');
  });
});
