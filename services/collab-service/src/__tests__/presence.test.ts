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

function createMockSocket() {
  const roomEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    roomEmit,
  };
}

function createMockIo(sockets: Map<string, ReturnType<typeof createMockSocket>>) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, ioMock: io, roomEmit };
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

    it('returns users and count for a document', () => {
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
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'c@test.com');

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
    it('emits presence-update to the document room', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, ioMock, roomEmit } = createMockIo(new Map());

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(ioMock.to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts stale users, notifies them, and reports empty documents', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');

      const socket = createMockSocket();
      const { io, ioMock, roomEmit } = createMockIo(new Map([['s1', socket]]));
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
      expect(socket.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u1',
      });
      expect(ioMock.to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('does not report a document as empty while active users remain', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      jest.setSystemTime(800);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');

      const { io } = createMockIo(new Map());
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 200, 500, onDocumentEmpty);
      jest.advanceTimersByTime(200);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(handler.getDocumentPresence('doc-1').users[0].userId).toBe('u2');
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('tolerates evicted sockets that are no longer connected', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');

      const { io, roomEmit } = createMockIo(new Map());

      const timer = handler.startCleanupInterval(io, 1000, 500);
      expect(() => jest.advanceTimersByTime(1000)).not.toThrow();
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does nothing when no users are stale', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');

      const { io, ioMock } = createMockIo(new Map());
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 100, 500, onDocumentEmpty);
      jest.advanceTimersByTime(100);
      clearInterval(timer);

      expect(ioMock.to).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
