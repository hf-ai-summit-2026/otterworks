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

interface FakeSocket {
  emit: jest.Mock;
  leave: jest.Mock;
  to: jest.Mock;
  roomEmit: jest.Mock;
}

function createFakeSocket(): FakeSocket {
  const roomEmit = jest.fn();
  return {
    emit: jest.fn(),
    leave: jest.fn(),
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    roomEmit,
  };
}

function createFakeIo(sockets: Map<string, FakeSocket> = new Map()) {
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

    it('returns the users currently in the document', () => {
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
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@example.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'bob@example.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'carol@example.com');

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
    it('emits the document presence to the document room', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@example.com');
      const { io, to, roomEmit } = createFakeIo();

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts idle users, notifies their sockets and fires onDocumentEmpty', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@example.com');

      const evicted = createFakeSocket();
      const { io, to, roomEmit } = createFakeIo(new Map([['s1', evicted]]));
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 500, onDocumentEmpty);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

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
      expect(to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('still broadcasts presence when the evicted socket is no longer connected', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@example.com');
      const { io, roomEmit } = createFakeIo();

      const timer = handler.startCleanupInterval(io, 1000, 500);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does not evict active users or fire onDocumentEmpty while others remain', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@example.com');
      jest.advanceTimersByTime(600);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'bob@example.com');

      const { io } = createFakeIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 400, 500, onDocumentEmpty);
      jest.advanceTimersByTime(400);
      clearInterval(timer);

      expect(awareness.getDocumentUsers('doc-1').map((u) => u.userId)).toEqual(['u2']);
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('does nothing when no users are stale', () => {
      jest.useFakeTimers();
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'alice@example.com');
      const { io, to } = createFakeIo();
      const onDocumentEmpty = jest.fn();

      const timer = handler.startCleanupInterval(io, 1000, 60000, onDocumentEmpty);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(to).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
