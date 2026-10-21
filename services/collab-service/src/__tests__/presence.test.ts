import type { Server as SocketIOServer } from 'socket.io';
import { AwarenessService } from '../services/awareness';
import { PresenceHandler } from '../handlers/presence';

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

function createMockIo(sockets: Map<string, unknown> = new Map()) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, ioMock: io, roomEmit };
}

function createMockSocket() {
  const toEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn().mockReturnValue({ emit: toEmit }),
    toEmit,
  };
}

describe('PresenceHandler', () => {
  let awareness: AwarenessService;
  let handler: PresenceHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    awareness = new AwarenessService(mockLogger);
    handler = new PresenceHandler(awareness, mockLogger);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('getDocumentPresence', () => {
    it('returns an empty presence for an unknown document', () => {
      expect(handler.getDocumentPresence('missing')).toEqual({
        documentId: 'missing',
        users: [],
        count: 0,
      });
    });

    it('returns the users in a document with their count', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'bob@test.com');

      const presence = handler.getDocumentPresence('doc-1');
      expect(presence.documentId).toBe('doc-1');
      expect(presence.count).toBe(2);
      expect(presence.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
    });
  });

  describe('getActiveDocuments', () => {
    it('returns an empty list when no documents are active', () => {
      expect(handler.getActiveDocuments()).toEqual([]);
    });

    it('returns each active document with its user count', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'bob@test.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'carol@test.com');

      expect(handler.getActiveDocuments()).toEqual(
        expect.arrayContaining([
          { documentId: 'doc-1', userCount: 2 },
          { documentId: 'doc-2', userCount: 1 },
        ]),
      );
      expect(handler.getActiveDocuments()).toHaveLength(2);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('emits the current presence to the document room', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@test.com');
      const { io, ioMock, roomEmit } = createMockIo();

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(ioMock.to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts idle users, notifies their sockets and fires onDocumentEmpty', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@test.com');
      const socket = createMockSocket();
      const { io, roomEmit } = createMockIo(new Map([['s1', socket]]));
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 500, onDocumentEmpty);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(socket.emit).toHaveBeenCalledWith('session-expired', {
        documentId: 'doc-1',
        reason: 'idle_timeout',
      });
      expect(socket.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(socket.to).toHaveBeenCalledWith('doc:doc-1');
      expect(socket.toEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u1',
      });
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('still cleans up when the evicted socket is no longer connected', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@test.com');
      const { io, roomEmit } = createMockIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 500, onDocumentEmpty);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
    });

    it('does not fire onDocumentEmpty while active users remain', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@test.com');
      jest.advanceTimersByTime(600);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'bob@test.com');
      const { io, roomEmit } = createMockIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 400, 500, onDocumentEmpty);
      jest.advanceTimersByTime(400);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(awareness.getDocumentUsers('doc-1')[0].userId).toBe('u2');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('does nothing when no users are idle', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@test.com');
      const { io, ioMock } = createMockIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 60000, onDocumentEmpty);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(ioMock.to).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
