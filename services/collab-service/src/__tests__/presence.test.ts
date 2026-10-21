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
  return { io: io as unknown as SocketIOServer, to: io.to, roomEmit };
}

describe('PresenceHandler', () => {
  let awareness: AwarenessService;
  let presence: PresenceHandler;

  beforeEach(() => {
    jest.clearAllMocks();
    awareness = new AwarenessService(mockLogger);
    presence = new PresenceHandler(awareness, mockLogger);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('getDocumentPresence', () => {
    it('returns users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');

      const info = presence.getDocumentPresence('doc-1');

      expect(info.documentId).toBe('doc-1');
      expect(info.count).toBe(2);
      expect(info.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
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

      const active = presence.getActiveDocuments();

      expect(active).toHaveLength(2);
      expect(active).toEqual(
        expect.arrayContaining([
          { documentId: 'doc-1', userCount: 2 },
          { documentId: 'doc-2', userCount: 1 },
        ]),
      );
    });

    it('returns an empty list when no documents are active', () => {
      expect(presence.getActiveDocuments()).toEqual([]);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('emits presence-update to the document room', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io, to, roomEmit } = createMockIo(new Map());

      presence.broadcastPresenceUpdate(io, 'doc-1');

      expect(to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts stale users, notifies their sockets and fires onDocumentEmpty', () => {
      jest.useFakeTimers();
      jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');

      const socket = createMockSocket();
      const { io, to, roomEmit } = createMockIo(new Map([['s1', socket]]));
      const onDocumentEmpty = jest.fn();

      const timer = presence.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(6000);
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
      expect(onDocumentEmpty).toHaveBeenCalledTimes(1);
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('does not fire onDocumentEmpty while active users remain', () => {
      jest.useFakeTimers();
      jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      jest.advanceTimersByTime(4000);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');

      const { io } = createMockIo(new Map());
      const onDocumentEmpty = jest.fn();

      const timer = presence.startCleanupInterval(io, 2000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(2000);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(presence.getDocumentPresence('doc-1').users[0].userId).toBe('u2');
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('tolerates evicted sockets that are no longer connected', () => {
      jest.useFakeTimers();
      jest.setSystemTime(new Date('2026-01-01T00:00:00Z'));
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');

      const { io, roomEmit } = createMockIo(new Map());

      const timer = presence.startCleanupInterval(io, 1000, 500);
      expect(() => jest.advanceTimersByTime(1000)).not.toThrow();
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does nothing when no users are stale', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io, to } = createMockIo(new Map());
      const onDocumentEmpty = jest.fn();

      const timer = presence.startCleanupInterval(io, 1000, 60000, onDocumentEmpty);
      jest.advanceTimersByTime(3000);
      clearInterval(timer);

      expect(to).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
