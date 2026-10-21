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

  describe('getDocumentPresence', () => {
    it('returns an empty presence for an unknown document', () => {
      expect(handler.getDocumentPresence('doc-none')).toEqual({
        documentId: 'doc-none',
        users: [],
        count: 0,
      });
    });

    it('returns the users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@example.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'bob@example.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'carol@example.com');

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
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', '');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', '');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', '');

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
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', '');
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
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('evicts stale users, notifies their sockets and reports empty documents', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', '');
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
      expect(socket.toEmit).toHaveBeenCalledWith('user-left', {
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

    it('still broadcasts presence when the evicted socket is no longer connected', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', '');
      const { io, roomEmit } = createMockIo();

      const timer = handler.startCleanupInterval(io, 1000, 500);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does not report a document as empty while active users remain', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', '');
      const { io } = createMockIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 500, onDocumentEmpty);
      jest.advanceTimersByTime(600);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', '');
      jest.advanceTimersByTime(400);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('does nothing when no users are stale', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', '');
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
