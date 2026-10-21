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
  return { io: io as unknown as SocketIOServer, raw: io, roomEmit };
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

      const presence = handler.getDocumentPresence('doc-1');
      expect(presence.documentId).toBe('doc-1');
      expect(presence.count).toBe(2);
      expect(presence.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
    });
  });

  describe('getActiveDocuments', () => {
    it('lists each active document with its user count', () => {
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
      const { io, raw, roomEmit } = createMockIo(new Map());

      handler.broadcastPresenceUpdate(io, 'doc-1');

      expect(raw.to).toHaveBeenCalledWith('doc:doc-1');
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

    it('evicts idle users, notifies their socket and triggers onDocumentEmpty', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const socket = createMockSocket();
      const { io, roomEmit } = createMockIo(new Map([['s1', socket]]));
      const onDocumentEmpty = jest.fn();

      timer = handler.startCleanupInterval(io, 1000, 500, onDocumentEmpty);
      jest.advanceTimersByTime(1000);

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
      const [expiredAt] = socket.emit.mock.invocationCallOrder;
      const [leftRoomAt] = socket.leave.mock.invocationCallOrder;
      const [userLeftAt] = socket.roomEmit.mock.invocationCallOrder;
      expect(expiredAt).toBeLessThan(leftRoomAt);
      expect(leftRoomAt).toBeLessThan(userLeftAt);
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('still broadcasts presence when the evicted socket is already gone', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, roomEmit } = createMockIo(new Map());

      timer = handler.startCleanupInterval(io, 1000, 500);
      jest.advanceTimersByTime(1000);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does not call onDocumentEmpty while other users remain active', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      jest.advanceTimersByTime(800);
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');
      const { io } = createMockIo(new Map());
      const onDocumentEmpty = jest.fn();

      timer = handler.startCleanupInterval(io, 300, 1000, onDocumentEmpty);
      jest.advanceTimersByTime(300);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(awareness.getDocumentUsers('doc-1')[0].userId).toBe('u2');
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('does nothing when no users are idle', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, raw } = createMockIo(new Map());
      const onDocumentEmpty = jest.fn();

      timer = handler.startCleanupInterval(io, 1000, 60000, onDocumentEmpty);
      jest.advanceTimersByTime(1000);

      expect(raw.to).not.toHaveBeenCalled();
      expect(onDocumentEmpty).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
