import type { Server as SocketIOServer } from 'socket.io';
import { PresenceHandler } from '../handlers/presence';
import { AwarenessService } from '../services/awareness';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function fakeIo(sockets: Map<string, unknown> = new Map()) {
  const roomEmit = jest.fn();
  const io = {
    to: jest.fn().mockReturnValue({ emit: roomEmit }),
    sockets: { sockets },
  } as unknown as SocketIOServer;
  return { io, roomEmit };
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

  it('reports presence for a document', () => {
    awareness.addUser('doc-1', 's1', 'u1', 'User One', 'u1@test.com');
    const presence = handler.getDocumentPresence('doc-1');
    expect(presence.documentId).toBe('doc-1');
    expect(presence.count).toBe(1);
    expect(presence.users[0].userId).toBe('u1');
  });

  it('lists active documents with user counts', () => {
    awareness.addUser('doc-1', 's1', 'u1', 'A', '');
    awareness.addUser('doc-1', 's2', 'u2', 'B', '');
    awareness.addUser('doc-2', 's3', 'u3', 'C', '');
    expect(handler.getActiveDocuments()).toEqual([
      { documentId: 'doc-1', userCount: 2 },
      { documentId: 'doc-2', userCount: 1 },
    ]);
  });

  it('broadcasts presence to the document room', () => {
    const { io, roomEmit } = fakeIo();
    awareness.addUser('doc-1', 's1', 'u1', 'A', '');
    handler.broadcastPresenceUpdate(io, 'doc-1');
    expect(io.to).toHaveBeenCalledWith('doc:doc-1');
    expect(roomEmit).toHaveBeenCalledWith(
      'presence-update',
      expect.objectContaining({ documentId: 'doc-1', count: 1 }),
    );
  });

  it('evicts idle users, notifies their socket and reports empty documents', () => {
    jest.useFakeTimers();
    const roomEmit = jest.fn();
    const evicted = {
      emit: jest.fn(),
      leave: jest.fn(),
      to: jest.fn().mockReturnValue({ emit: roomEmit }),
    };
    const { io } = fakeIo(new Map([['s1', evicted]]));
    const onEmpty = jest.fn();

    awareness.addUser('doc-1', 's1', 'u1', 'A', '');
    const timer = handler.startCleanupInterval(io, 1000, 500, onEmpty);

    jest.advanceTimersByTime(1000);
    clearInterval(timer);

    expect(evicted.emit).toHaveBeenCalledWith('session-expired', {
      documentId: 'doc-1',
      reason: 'idle_timeout',
    });
    expect(evicted.leave).toHaveBeenCalledWith('doc:doc-1');
    expect(roomEmit).toHaveBeenCalledWith('user-left', { socketId: 's1', userId: 'u1' });
    expect(onEmpty).toHaveBeenCalledWith('doc-1');
    expect(awareness.getDocumentUserCount('doc-1')).toBe(0);
  });

  it('does not report a document as empty while active users remain', () => {
    jest.useFakeTimers();
    const { io } = fakeIo();
    const onEmpty = jest.fn();

    awareness.addUser('doc-1', 'idle', 'u1', 'A', '');
    jest.advanceTimersByTime(600);
    awareness.addUser('doc-1', 'active', 'u2', 'B', '');

    const timer = handler.startCleanupInterval(io, 100, 500, onEmpty);
    jest.advanceTimersByTime(100);
    clearInterval(timer);

    expect(awareness.getDocumentUserCount('doc-1')).toBe(1);
    expect(onEmpty).not.toHaveBeenCalled();
  });
});
