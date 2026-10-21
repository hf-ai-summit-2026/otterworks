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

interface MockSocket {
  emit: jest.Mock;
  leave: jest.Mock;
  to: jest.Mock;
  roomEmit: jest.Mock;
}

function createMockSocket(): MockSocket {
  const roomEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    roomEmit,
  };
}

function createMockIo(sockets: Record<string, MockSocket> = {}) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets: new Map(Object.entries(sockets)) },
  };
  return { io: io as unknown as SocketIOServer, ioTo: io.to, roomEmit };
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
    it('should return users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');

      const info = presence.getDocumentPresence('doc-1');

      expect(info.documentId).toBe('doc-1');
      expect(info.count).toBe(2);
      expect(info.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
    });

    it('should return an empty presence for an unknown document', () => {
      expect(presence.getDocumentPresence('missing')).toEqual({
        documentId: 'missing',
        users: [],
        count: 0,
      });
    });
  });

  describe('getActiveDocuments', () => {
    it('should list each active document with its user count', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'c@t.com');

      const docs = presence.getActiveDocuments();

      expect(docs).toHaveLength(2);
      expect(docs).toEqual(
        expect.arrayContaining([
          { documentId: 'doc-1', userCount: 2 },
          { documentId: 'doc-2', userCount: 1 },
        ]),
      );
    });

    it('should return an empty list when no documents are active', () => {
      expect(presence.getActiveDocuments()).toEqual([]);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('should emit presence-update to the document room', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io, ioTo, roomEmit } = createMockIo();

      presence.broadcastPresenceUpdate(io, 'doc-1');

      expect(ioTo).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    let timer: NodeJS.Timeout | undefined;

    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      if (timer) clearInterval(timer);
      timer = undefined;
      jest.useRealTimers();
    });

    it('should evict stale sockets, notify the room and fire onDocumentEmpty', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.getDocumentUsers('doc-1')[0].lastActive = Date.now() - 10_000;

      const staleSocket = createMockSocket();
      const { io, ioTo, roomEmit } = createMockIo({ s1: staleSocket });
      const onDocumentEmpty = jest.fn();

      timer = presence.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(1000);

      expect(staleSocket.emit).toHaveBeenCalledWith('session-expired', {
        documentId: 'doc-1',
        reason: 'idle_timeout',
      });
      expect(staleSocket.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(staleSocket.to).toHaveBeenCalledWith('doc:doc-1');
      expect(staleSocket.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u1',
      });
      expect(ioTo).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('should not fire onDocumentEmpty while active users remain', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');
      const users = awareness.getDocumentUsers('doc-1');
      users.find((u) => u.userId === 'u1')!.lastActive = Date.now() - 10_000;

      const { io, roomEmit } = createMockIo();
      const onDocumentEmpty = jest.fn();

      timer = presence.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(1000);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('should tolerate stale entries whose socket is no longer connected', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.getDocumentUsers('doc-1')[0].lastActive = Date.now() - 10_000;

      const { io } = createMockIo();

      timer = presence.startCleanupInterval(io, 1000, 5000);

      expect(() => jest.advanceTimersByTime(1000)).not.toThrow();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('should do nothing when no users are stale', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const { io, ioTo } = createMockIo();
      const onDocumentEmpty = jest.fn();

      timer = presence.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(1000);

      expect(ioTo).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
