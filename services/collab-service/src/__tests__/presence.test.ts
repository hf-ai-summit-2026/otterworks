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
    to: jest.fn(() => ({ emit: roomEmit })),
    roomEmit,
  };
}

function createMockIo(sockets: Map<string, MockSocket> = new Map()) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn(() => ({ emit: roomEmit })),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, ioTo: io.to, roomEmit };
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
      expect(handler.getDocumentPresence('missing')).toEqual({
        documentId: 'missing',
        users: [],
        count: 0,
      });
    });

    it('returns the users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');

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
      const { io, ioTo, roomEmit } = createMockIo();

      handler.broadcastPresenceUpdate(io, 'doc-1');

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

    it('evicts idle users, notifies their sockets and reports empty documents', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const evicted = createMockSocket();
      const { io, ioTo, roomEmit } = createMockIo(new Map([['s1', evicted]]));
      const onDocumentEmpty = jest.fn();

      timer = handler.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(6000);

      expect(evicted.emit).toHaveBeenCalledWith('session-expired', {
        documentId: 'doc-1',
        reason: 'idle_timeout',
      });
      expect(evicted.leave).toHaveBeenCalledWith('doc:doc-1');
      expect(evicted.to).toHaveBeenCalledWith('doc:doc-1');
      expect(evicted.roomEmit).toHaveBeenCalledWith('user-left', {
        socketId: 's1',
        userId: 'u1',
      });
      expect(ioTo).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledTimes(1);
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('does not report a document as empty while active users remain', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      jest.advanceTimersByTime(4000);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');
      const { io, roomEmit } = createMockIo();
      const onDocumentEmpty = jest.fn();

      timer = handler.startCleanupInterval(io, 2000, 5000, onDocumentEmpty);
      jest.advanceTimersByTime(2000);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(awareness.getDocumentUsers('doc-1')[0].userId).toBe('u2');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('skips socket notification when the evicted socket is no longer connected', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, roomEmit } = createMockIo();

      timer = handler.startCleanupInterval(io, 1000, 5000);
      expect(() => jest.advanceTimersByTime(6000)).not.toThrow();

      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does nothing when no users are idle', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, ioTo } = createMockIo();
      const onDocumentEmpty = jest.fn();

      timer = handler.startCleanupInterval(io, 1000, 60000, onDocumentEmpty);
      jest.advanceTimersByTime(3000);

      expect(ioTo).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
