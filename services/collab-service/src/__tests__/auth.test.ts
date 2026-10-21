import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  extractUserFromSocket,
  type AuthenticatedSocket,
} from '../middleware/auth';

const JWT_SECRET = 'unit-test-secret';

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

function makeSocket(handshake: {
  auth?: Record<string, unknown>;
  headers?: Record<string, string>;
}): Socket {
  return {
    id: 'socket-1',
    handshake: { auth: handshake.auth ?? {}, headers: handshake.headers ?? {} },
  } as unknown as Socket;
}

function runMiddleware(socket: Socket): Error | undefined {
  const middleware = createAuthMiddleware(JWT_SECRET, mockLogger);
  const next = jest.fn();
  middleware(socket, next);
  expect(next).toHaveBeenCalledTimes(1);
  return next.mock.calls[0][0];
}

describe('createAuthMiddleware', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('accepts a valid token from handshake.auth and attaches the user', () => {
    const token = jwt.sign(
      { sub: 'user-1', email: 'a@test.com', name: 'Alice', roles: ['editor'] },
      JWT_SECRET,
    );
    const socket = makeSocket({ auth: { token } });

    expect(runMiddleware(socket)).toBeUndefined();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-1',
      email: 'a@test.com',
      displayName: 'Alice',
      roles: ['editor'],
    });
  });

  it('accepts a Bearer token from the Authorization header', () => {
    const token = jwt.sign({ sub: 'user-2' }, JWT_SECRET);
    const socket = makeSocket({ headers: { authorization: `Bearer ${token}` } });

    expect(runMiddleware(socket)).toBeUndefined();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('user-2');
  });

  it('prefers handshake.auth.token over the Authorization header', () => {
    const authToken = jwt.sign({ sub: 'from-auth' }, JWT_SECRET);
    const headerToken = jwt.sign({ sub: 'from-header' }, JWT_SECRET);
    const socket = makeSocket({
      auth: { token: authToken },
      headers: { authorization: `Bearer ${headerToken}` },
    });

    expect(runMiddleware(socket)).toBeUndefined();
    expect((socket as AuthenticatedSocket).user?.userId).toBe('from-auth');
  });

  it('falls back to display_name when name is absent', () => {
    const token = jwt.sign({ sub: 'user-3', display_name: 'Bob' }, JWT_SECRET);
    const socket = makeSocket({ auth: { token } });

    expect(runMiddleware(socket)).toBeUndefined();
    expect((socket as AuthenticatedSocket).user?.displayName).toBe('Bob');
  });

  it('defaults optional claims when they are missing', () => {
    const token = jwt.sign({ sub: 'user-4' }, JWT_SECRET);
    const socket = makeSocket({ auth: { token } });

    expect(runMiddleware(socket)).toBeUndefined();
    expect((socket as AuthenticatedSocket).user).toEqual({
      userId: 'user-4',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });

  it('rejects a connection with no token', () => {
    const socket = makeSocket({});

    expect(runMiddleware(socket)?.message).toBe('Authentication required');
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
  });

  it('rejects a token signed with a different secret', () => {
    const token = jwt.sign({ sub: 'user-5' }, 'some-other-secret');
    const socket = makeSocket({ auth: { token } });

    expect(runMiddleware(socket)?.message).toBe('Invalid or expired token');
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
  });

  it('rejects an expired token', () => {
    const token = jwt.sign(
      { sub: 'user-6', exp: Math.floor(Date.now() / 1000) - 60 },
      JWT_SECRET,
    );
    const socket = makeSocket({ auth: { token } });

    expect(runMiddleware(socket)?.message).toBe('Invalid or expired token');
    expect((socket as AuthenticatedSocket).user).toBeUndefined();
  });
});

describe('extractUserFromSocket', () => {
  it('returns the authenticated user when present', () => {
    const socket = makeSocket({}) as AuthenticatedSocket;
    socket.user = {
      userId: 'user-1',
      email: 'a@test.com',
      displayName: 'Alice',
      roles: [],
    };

    expect(extractUserFromSocket(socket)).toBe(socket.user);
  });

  it('returns an anonymous user keyed by socket id when unauthenticated', () => {
    const socket = makeSocket({});

    expect(extractUserFromSocket(socket)).toEqual({
      userId: 'anon-socket-1',
      email: '',
      displayName: 'Anonymous',
      roles: [],
    });
  });
});
