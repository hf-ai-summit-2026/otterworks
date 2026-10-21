import type { Server as SocketIOServer } from 'socket.io';
import { PresenceHandler } from '../handlers/presence';
import { AwarenessService } from '../services/awareness';

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
  return { io: io as unknown as SocketIOServer, roomEmit, raw: io };
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
    jest.useFakeTimers();
    awareness = new AwarenessService(mockLogger);
    handler = new PresenceHandler(awareness, mockLogger);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('getDocumentPresence', () => {
    it('returns users and count for a document', () => {
      awareness.addUser('doc-1', 'socket-1', 'user-1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'socket-2', 'user-2', 'Bob', 'b@test.com');

      const presence = handler.getDocumentPresence('doc-1');

      expect(presence.documentId).toBe('doc-1');
      expect(presence.count).toBe(2);
      expect(presence.users.map((u) => u.userId).sort()).toEqual(['user-1', 'user-2']);
    });

    it('returns an empty presence for an unknown document', () => {
      expect(handler.getDocumentPresence('missing')).toEqual({
        documentId: 'missing',
        users: [],
        count: 0,
      });
    });
  });

  describe('getActiveDocuments', () => {
    it('lists each active document with its user count', () => {
      awareness.addUser('doc-1', 'socket-1', 'user-1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 'socket-2', 'user-2', 'Bob', 'b@test.com');
      awareness.addUser('doc-2', 'socket-3', 'user-3', 'Carol', 'c@test.com');

      expect(handler.getActiveDocuments()).toEqual(
        expect.arrayContaining([
          { documentId: 'doc-1', userCount: 2 },
          { documentId: 'doc-2', userCount: 1 },
        ]),
      );
      expect(handler.getActiveDocuments()).toHaveLength(2);
    });

    it('returns an empty list when no documents are active', () => {
      expect(handler.getActiveDocuments()).toEqual([]);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('emits presence-update to the document room', () => {
      awareness.addUser('doc-1', 'socket-1', 'user-1', 'Alice', 'a@test.com');
      const { io, roomEmit, raw } = createMockIo();

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(raw.to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts idle users, notifies their sockets and fires onDocumentEmpty', () => {
      awareness.addUser('doc-1', 'socket-1', 'user-1', 'Alice', 'a@test.com');
      const socket = createMockSocket();
      const { io, roomEmit, raw } = createMockIo(new Map([['socket-1', socket]]));
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
        socketId: 'socket-1',
        userId: 'user-1',
      });
      expect(raw.to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('does not fire onDocumentEmpty while active users remain', () => {
      awareness.addUser('doc-1', 'socket-1', 'user-1', 'Alice', 'a@test.com');
      const { io } = createMockIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 800, onDocumentEmpty);
      jest.advanceTimersByTime(400);
      awareness.addUser('doc-1', 'socket-2', 'user-2', 'Bob', 'b@test.com');
      jest.advanceTimersByTime(600);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(awareness.getDocumentUsers('doc-1')[0].userId).toBe('user-2');
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('still updates presence when the evicted socket is already gone', () => {
      awareness.addUser('doc-1', 'socket-1', 'user-1', 'Alice', 'a@test.com');
      const { io, roomEmit } = createMockIo();

      const timer = handler.startCleanupInterval(io, 1000, 500);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does nothing when no users are idle', () => {
      awareness.addUser('doc-1', 'socket-1', 'user-1', 'Alice', 'a@test.com');
      const { io, raw } = createMockIo();

      const timer = handler.startCleanupInterval(io, 1000, 5000);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(raw.to).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
