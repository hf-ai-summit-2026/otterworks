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

function createMockIo(socketIds: string[] = []) {
  const roomEmit = jest.fn();
  const sockets = new Map(
    socketIds.map((id) => {
      const toEmit = jest.fn();
      return [
        id,
        {
          emit: jest.fn(),
          leave: jest.fn(),
          to: jest.fn().mockReturnValue({ emit: toEmit }),
          toEmit,
        },
      ];
    }),
  );
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets },
  };
  return { io: io as unknown as SocketIOServer, raw: io, roomEmit, sockets };
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
    it('returns an empty presence for an unknown document', () => {
      expect(presence.getDocumentPresence('doc-x')).toEqual({
        documentId: 'doc-x',
        users: [],
        count: 0,
      });
    });

    it('returns users and count for a document', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');

      const info = presence.getDocumentPresence('doc-1');
      expect(info.documentId).toBe('doc-1');
      expect(info.count).toBe(2);
      expect(info.users.map((u) => u.userId).sort()).toEqual(['u1', 'u2']);
    });
  });

  describe('getActiveDocuments', () => {
    it('lists each active document with its user count', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');
      awareness.addUser('doc-2', 's3', 'u3', 'Carol', 'c@test.com');

      expect(presence.getActiveDocuments()).toEqual(
        expect.arrayContaining([
          { documentId: 'doc-1', userCount: 2 },
          { documentId: 'doc-2', userCount: 1 },
        ]),
      );
      expect(presence.getActiveDocuments()).toHaveLength(2);
    });

    it('returns an empty list when nobody is connected', () => {
      expect(presence.getActiveDocuments()).toEqual([]);
    });
  });

  describe('broadcastPresenceUpdate', () => {
    it('emits presence-update to the document room', () => {
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, raw, roomEmit } = createMockIo();

      presence.broadcastPresenceUpdate(io, 'doc-1');

      expect(raw.to).toHaveBeenCalledWith('doc:doc-1');
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
    });
  });

  describe('startCleanupInterval', () => {
    it('evicts idle users, notifies sockets and reports empty documents', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, roomEmit, sockets } = createMockIo(['s1']);
      const onDocumentEmpty = jest.fn();

      const timer = presence.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.setSystemTime(10_000);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      const socket = sockets.get('s1')!;
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
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
      expect(onDocumentEmpty).toHaveBeenCalledWith('doc-1');
      expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
    });

    it('keeps active users and does not report the document as empty', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      awareness.addUser('doc-1', 's2', 'u2', 'Bob', 'b@test.com');
      const { io, roomEmit } = createMockIo(['s1', 's2']);
      const onDocumentEmpty = jest.fn();

      const timer = presence.startCleanupInterval(io, 1000, 5000, onDocumentEmpty);
      jest.setSystemTime(10_000);
      awareness.refreshActivity('s2');
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 1 }),
      );
      expect(onDocumentEmpty).not.toHaveBeenCalled();
    });

    it('tolerates evicted sockets that have already disconnected', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, roomEmit } = createMockIo([]);

      const timer = presence.startCleanupInterval(io, 1000, 5000);
      jest.setSystemTime(10_000);
      expect(() => jest.advanceTimersByTime(1000)).not.toThrow();
      clearInterval(timer);

      expect(roomEmit).toHaveBeenCalledWith(
        'presence-update',
        expect.objectContaining({ documentId: 'doc-1', count: 0 }),
      );
    });

    it('does nothing when no users are idle', () => {
      jest.useFakeTimers();
      jest.setSystemTime(0);
      awareness.addUser('doc-1', 's1', 'u1', 'Alice', 'a@test.com');
      const { io, raw } = createMockIo(['s1']);

      const timer = presence.startCleanupInterval(io, 1000, 5000);
      jest.advanceTimersByTime(1000);
      clearInterval(timer);

      expect(raw.to).not.toHaveBeenCalled();
      expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    });
  });
});
