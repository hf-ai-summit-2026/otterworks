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

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('getDocumentPresence', () => {
    it('returns the users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');

      const presence = handler.getDocumentPresence('doc-1');

      expect(presence.documentId).toBe('doc-1');
      expect(presence.count).toBe(2);
      expect(presence.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
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
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@t.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'c@t.com');

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
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
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
    it('evicts idle sockets, notifies the room and reports empty documents', () => {
      jest.useFakeTimers();
      const socket = createMockSocket();
      const { io, ioTo, roomEmit } = createMockIo(new Map([['s1', socket]]));
      const onDocumentEmpty = jest.fn();

      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
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
      expect(ioTo).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('does not report a document as empty while active users remain', () => {
      jest.useFakeTimers();
      const { io } = createMockIo();
      const onDocumentEmpty = jest.fn();

      awareness.addUser('doc-1', 'idle', 'u1', 'Alice', 'a@t.com');
      jest.advanceTimersByTime(800);
      awareness.addUser('doc-1', 'active', 'u2', 'Bob', 'b@t.com');

      const timer = handler.startCleanupInterval(io, 200, 500, onDocumentEmpty);
      jest.advanceTimersByTime(200);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(awareness.getDocumentUsers('doc-1')[0].userId).toBe('u2');
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('skips socket notifications when the evicted socket is already gone', () => {
      jest.useFakeTimers();
      const { io } = createMockIo();

      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@t.com');
      const timer = handler.startCleanupInterval(io, 1000, 500);

      expect(() => jest.advanceTimersByTime(1000)).not.toThrow();
      clearInterval(timer);
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });
  });
});
