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

function createMockIo(sockets: Record<string, unknown> = {}) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets: new Map(Object.entries(sockets)) },
  };
  return { io: io as never, to: io.to, roomEmit };
}

function createMockSocket() {
  const roomEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    roomEmit,
  };
}

describe('PresenceHandler', () => {
  let awareness: AwarenessService;
  let presence: PresenceHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    awareness = new AwarenessService(mockLogger);
    presence = new PresenceHandler(awareness, mockLogger);
  });

  describe('getDocumentPresence', () => {
    it('returns users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');

      const result = presence.getDocumentPresence('doc-1');

      expect(result.documentId).toBe('doc-1');
      expect(result.count).toBe(2);
      expect(result.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
    });

    it('returns an empty presence for an unknown document', () => {
      expect(presence.getDocumentPresence('missing')).toEqual({
        documentId: 'missing',
        users: [],
        count: 0,
      });
    });
  });

  describe('getActiveDocuments', () => {
    it('lists each active document with its user count', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'c@t.com');

      expect(presence.getActiveDocuments()).toEqual(
        expect.arrayContaining([
          { documentId: 'doc-1', userCount: 2 },
          { documentId: 'doc-2', userCount: 1 },
        ]),
      );
      expect(presence.getActiveDocuments()).toHaveLength(2);
    });

    it('returns an empty list when no documents are active', () => {
      expect(presence.getActiveDocuments()).toEqual([]);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('emits presence-update to the document room', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io, to, roomEmit } = createMockIo();

      presence.broadcastPresenceUpdate(io, 'doc-1');

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

    it('evicts stale users, notifies their sockets and fires onDocumentEmpty', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const socket = createMockSocket();
      const { io, to, roomEmit } = createMockIo({ s1: socket });
      const onDocumentEmpty = jest.fn();

      const timer = presence.startCleanupInterval(io, 1000, 500, onDocumentEmpty);
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

    it('does not fire onDocumentEmpty while active users remain', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io } = createMockIo();
      const onDocumentEmpty = jest.fn();

      const timer = presence.startCleanupInterval(io, 1000, 500, onDocumentEmpty);
      jest.advanceTimersByTime(900);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');
      jest.advanceTimersByTime(100);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('skips socket notification when the evicted socket is already gone', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io, roomEmit } = createMockIo();

      const timer = presence.startCleanupInterval(io, 1000, 500);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does nothing when no users are stale', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io, to } = createMockIo();

      const timer = presence.startCleanupInterval(io, 1000, 60000);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(to).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
