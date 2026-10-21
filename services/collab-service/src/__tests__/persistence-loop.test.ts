import * as Y from 'yjs';
import { CollaborationManager, PERSIST_CONCURRENCY } from '../handlers/collaboration';
import { MetricsCollector } from '../metrics';

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function makeManager(
  store: Record<string, jest.Mock>,
  docCount: number,
): CollaborationManager {
  const manager = new CollaborationManager({
    io: {} as never,
    documentStore: store as never,
    awareness: {} as never,
    presenceHandler: {} as never,
    metrics: new MetricsCollector(),
    logger: mockLogger,
    persistIntervalMs: 600000,
    snapshotIntervalMs: 600000,
  });
  const docs = (manager as unknown as { documents: Map<string, Y.Doc> }).documents;
  for (let i = 0; i < docCount; i++) docs.set(`doc-${i}`, new Y.Doc());
  return manager;
}

async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

describe('CollaborationManager periodic persistence', () => {
  beforeEach(() => jest.clearAllMocks());

  it('persists documents in parallel batches bounded by PERSIST_CONCURRENCY', async () => {
    const pending: Array<() => void> = [];
    let inFlight = 0;
    let maxInFlight = 0;
    const saveDocumentState = jest.fn(async () => {
      inFlight++;
      maxInFlight = Math.max(maxInFlight, inFlight);
      const d = deferred();
      pending.push(d.resolve);
      await d.promise;
      inFlight--;
    });
    const total = PERSIST_CONCURRENCY * 2 + 3;
    const manager = makeManager({ saveDocumentState }, total);

    const pass = manager.persistAllDocuments();
    await flush();
    expect(saveDocumentState).toHaveBeenCalledTimes(PERSIST_CONCURRENCY);

    while (pending.length) {
      pending.splice(0).forEach((resolve) => resolve());
      await flush();
    }
    await pass;

    expect(saveDocumentState).toHaveBeenCalledTimes(total);
    expect(maxInFlight).toBe(PERSIST_CONCURRENCY);
  });

  it('keeps persisting the rest of a batch when one document fails', async () => {
    const saveDocumentState = jest.fn(async (id: string) => {
      if (id === 'doc-1') throw new Error('redis down');
    });
    const manager = makeManager({ saveDocumentState }, 3);

    await manager.persistAllDocuments();

    expect(saveDocumentState).toHaveBeenCalledTimes(3);
    expect((mockLogger as { error: jest.Mock }).error).toHaveBeenCalledWith(
      expect.objectContaining({ documentId: 'doc-1' }),
      'periodic_persistence_failed',
    );
  });

  it('skips a pass while the previous one is still running', async () => {
    const d = deferred();
    const saveDocumentState = jest.fn(() => d.promise);
    const manager = makeManager({ saveDocumentState }, 1);

    const first = manager.persistAllDocuments();
    await manager.persistAllDocuments();
    expect(saveDocumentState).toHaveBeenCalledTimes(1);

    d.resolve();
    await first;
  });

  it('snapshots every document with bounded concurrency', async () => {
    const createSnapshot = jest.fn().mockResolvedValue({});
    const manager = makeManager({ createSnapshot }, PERSIST_CONCURRENCY + 1);

    await manager.snapshotAllDocuments();

    expect(createSnapshot).toHaveBeenCalledTimes(PERSIST_CONCURRENCY + 1);
    expect(createSnapshot).toHaveBeenCalledWith(
      'doc-0',
      expect.any(Buffer),
      'system',
      'auto-snapshot',
    );
  });
});
