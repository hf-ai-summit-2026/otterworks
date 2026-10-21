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

function createMockIo(
  sockets: Map<string, ReturnType<typeof createMockSocket>> = new Map(),
) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, to: io.to, roomEmit };
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
      expect(handler.getDocumentPresence('doc-x')).toEqual({
        documentId: 'doc-x',
        users: [],
        count: 0,
      });
    });

    it('returns the users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'c@test.com');

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
      const { io, to, roomEmit } = createMockIo();

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(to).toHaveBeenCalledWith('doc:doc-1');
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
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const socket = createMockSocket();
      const { io, to, roomEmit } = createMockIo(new Map([['s1', socket]]));
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
      expect(to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('does not report a document as empty while active users remain', () => {
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      jest.setSystemTime(900);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');
      const { io, roomEmit } = createMockIo();
      const onDocumentEmpty = jest.fn();

      // Cleanup fires at t=1900: Alice idle 1900ms (stale), Bob idle 1000ms (active)
      const timer = handler.startCleanupInterval(io, 1000, 1500, onDocumentEmpty);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUsers('doc-1').map((u) => u.userId)).toEqual(['u2']);
    });

    it('does nothing when no users are stale', () => {
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, to } = createMockIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(to).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
