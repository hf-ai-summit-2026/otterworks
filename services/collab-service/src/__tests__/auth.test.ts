import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
  fatal: jest.fn(),
  trace: jest.fn(),
  child: jest.fn().mockReturnThis(),
  level: 'info',
} as never;

const SECRET = 'test-secret';

function makeSocket(
  auth: Record<string, unknown> = {},
  headers: Record<string, string> = {},
): Socket {
  return { id: 'socket-1', handshake: { auth, headers } } as unknown as Socket;
}

describe('createAuthMiddleware', () => {
  const middleware = createAuthMiddleware(SECRET, mockLogger);

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should reject connections without a token', () => {
    const next = jest.fn();
    middleware(makeSocket(), next);

    expect(next).toHaveBeenCalledWith(expect.any(Error));
    expect(next.mock.calls[0][0].message).toBe('Authentication required');
  });

  it('should reject an invalid token', () => {
    const next = jest.fn();
    middleware(makeSocket({ token: 'not-a-jwt' }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
  });

  it('should reject a token signed with a different secret', () => {
    const token = jwt.sign({ sub: 'user-1' }, 'other-secret');
    const next = jest.fn();
    middleware(makeSocket({ token }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
  });

  it('should reject an expired token', () => {
    const token = jwt.sign(
      { sub: 'user-1', exp: Math.floor(Date.now() / 1000) - 60 },
      SECRET,
    );
    const next = jest.fn();
    middleware(makeSocket({ token }), next);

    expect(next.mock.calls[0][0].message).toBe('Invalid or expired token');
  });

  it('should attach the user from a valid handshake auth token', () => {
    const token = jwt.sign(
      { sub: 'user-1', email: 'a@example.com', name: 'Alice', roles: ['editor'] },
      SECRET,
    );
    const socket = makeSocket({ token });
    const next = jest.fn();
    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-1',
      email: 'a@example.com',
      displayName: 'Alice',
      roles: ['editor'],
    });
  });

  it('should accept a Bearer token from the authorization header', () => {
    const token = jwt.sign({ sub: 'user-2', display_name: 'Bob' }, SECRET);
    const socket = makeSocket({}, { authorization: `Bearer ${token}` });
    const next = jest.fn();
    middleware(socket, next);

    expect(next).toHaveBeenCalledWith();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-2',
      email: '',
      displayName: 'Bob',
      roles: [],
    });
  });

  it('should default displayName to Anonymous when no name claims exist', () => {
    const token = jwt.sign({ sub: 'user-3' }, SECRET);
    const socket = makeSocket({ token });
    middleware(socket, jest.fn());

    expect((socket as AuthenticatedSocket).user?.displayName).toBe('Anonymous');
  });
});

describe('extractUserFromSocket', () => {
  it('should return the authenticated user when present', () => {
    const socket = makeSocket() as AuthenticatedSocket;
    socket.user = { userId: 'u', email: 'e', displayName: 'd', roles: ['r'] };

    expect(extractUserFromSocket(socket)).toBe(socket.user);
  });

  it('should return an anonymous user keyed by socket id otherwise', () => {
    expect(extractUserFromSocket(makeSocket())).toEqual({
      userId: 'anon-socket-1',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
