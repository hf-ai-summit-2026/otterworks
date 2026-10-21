import { RedisAdapter } from '../services/redis-adapter';

type Handler = (...args: unknown[]) => void;

const instances: MockRedis[] = [];

class MockRedis {
  options: Record<string, unknown>;
  handlers: Record<string, Handler[]> = {};
  connect = jest.fn().mockResolvedValue(undefined);
  disconnect = jest.fn();
  getBuffer = jest.fn().mockResolvedValue(Buffer.from('state'));
  set = jest.fn().mockResolvedValue('OK');
  setex = jest.fn().mockResolvedValue('OK');
  del = jest.fn().mockResolvedValue(1);
  hset = jest.fn().mockResolvedValue(1);
  hget = jest.fn().mockResolvedValue('v');
  hgetall = jest.fn().mockResolvedValue({ a: '1' });
  hdel = jest.fn().mockResolvedValue(1);
  hincrby = jest.fn().mockResolvedValue(2);
  lpush = jest.fn().mockResolvedValue(1);
  lrange = jest.fn().mockResolvedValue(['x']);
  ltrim = jest.fn().mockResolvedValue('OK');
  llen = jest.fn().mockResolvedValue(3);
  expire = jest.fn().mockResolvedValue(1);
  publish = jest.fn().mockResolvedValue(1);
  subscribe = jest.fn().mockResolvedValue(1);
  ping = jest.fn().mockResolvedValue('PONG');

  constructor(options: Record<string, unknown>) {
    this.options = options;
    instances.push(this);
  }

  on(event: string, handler: Handler): this {
    (this.handlers[event] ||= []).push(handler);
    return this;
  }

  fire(event: string, ...args: unknown[]): void {
    for (const h of this.handlers[event] || []) h(...args);
  }
}

jest.mock('ioredis', () => ({
  __esModule: true,
  default: jest.fn().mockImplementation((opts) => new MockRedis(opts)),
}));

const mockLogger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

describe('RedisAdapter', () => {
  let adapter: RedisAdapter;
  let client: MockRedis;
  let subscriber: MockRedis;

  beforeEach(() => {
    instances.length = 0;
    adapter = new RedisAdapter(
      { host: 'redis', port: 6380, password: 'pw', keyPrefix: 'collab:' },
      mockLogger,
    );
    [client, subscriber] = instances;
  });

  it('creates lazily-connecting client and subscriber with the given options', () => {
    expect(instances).toHaveLength(2);
    expect(client.options).toMatchObject({
      host: 'redis',
      port: 6380,
      password: 'pw',
      db: 0,
      lazyConnect: true,
      maxRetriesPerRequest: 3,
    });
    const retry = client.options.retryStrategy as (n: number) => number;
    expect(retry(1)).toBe(200);
    expect(retry(100)).toBe(5000);
  });

  it('connects both connections', async () => {
    await adapter.connect();
    expect(client.connect).toHaveBeenCalled();
    expect(subscriber.connect).toHaveBeenCalled();
  });

  it('exposes the underlying connections', () => {
    expect(adapter.getClient()).toBe(client);
    expect(adapter.getSubscriber()).toBe(subscriber);
  });

  it('logs connection events', () => {
    client.fire('error', new Error('boom'));
    subscriber.fire('error', new Error('sub-boom'));
    client.fire('connect');
    expect((mockLogger as unknown as { error: jest.Mock }).error).toHaveBeenCalledTimes(
      2,
    );
    expect((mockLogger as unknown as { info: jest.Mock }).info).toHaveBeenCalledWith(
      'redis_client_connected',
    );
  });

  it('prefixes keys for all key-based commands', async () => {
    await expect(adapter.get('k')).resolves.toEqual(Buffer.from('state'));
    await adapter.del('k');
    await adapter.hset('h', 'f', 'v');
    await expect(adapter.hget('h', 'f')).resolves.toBe('v');
    await expect(adapter.hgetall('h')).resolves.toEqual({ a: '1' });
    await adapter.hdel('h', 'f');
    await expect(adapter.hincrby('h', 'f', 1)).resolves.toBe(2);
    await adapter.lpush('l', 'v');
    await expect(adapter.lrange('l', 0, -1)).resolves.toEqual(['x']);
    await adapter.ltrim('l', 0, 9);
    await expect(adapter.llen('l')).resolves.toBe(3);
    await adapter.expire('k', 60);

    expect(client.getBuffer).toHaveBeenCalledWith('collab:k');
    expect(client.del).toHaveBeenCalledWith('collab:k');
    expect(client.hset).toHaveBeenCalledWith('collab:h', 'f', 'v');
    expect(client.hget).toHaveBeenCalledWith('collab:h', 'f');
    expect(client.hgetall).toHaveBeenCalledWith('collab:h');
    expect(client.hdel).toHaveBeenCalledWith('collab:h', 'f');
    expect(client.hincrby).toHaveBeenCalledWith('collab:h', 'f', 1);
    expect(client.lpush).toHaveBeenCalledWith('collab:l', 'v');
    expect(client.lrange).toHaveBeenCalledWith('collab:l', 0, -1);
    expect(client.ltrim).toHaveBeenCalledWith('collab:l', 0, 9);
    expect(client.llen).toHaveBeenCalledWith('collab:l');
    expect(client.expire).toHaveBeenCalledWith('collab:k', 60);
  });

  it('uses SETEX when a TTL is given and SET otherwise', async () => {
    const value = Buffer.from('v');
    await adapter.set('k', value, 30);
    await adapter.set('k2', value);
    expect(client.setex).toHaveBeenCalledWith('collab:k', 30, value);
    expect(client.set).toHaveBeenCalledWith('collab:k2', value);
  });

  it('publishes and subscribes without key prefixing', async () => {
    await adapter.publish('chan', 'msg');
    expect(client.publish).toHaveBeenCalledWith('chan', 'msg');

    const callback = jest.fn();
    await adapter.subscribe('chan', callback);
    expect(subscriber.subscribe).toHaveBeenCalledWith('chan');
    subscriber.fire('message', 'other', 'ignored');
    subscriber.fire('message', 'chan', 'hello');
    expect(callback).toHaveBeenCalledTimes(1);
    expect(callback).toHaveBeenCalledWith('hello');
  });

  it('reports ping health', async () => {
    await expect(adapter.ping()).resolves.toBe(true);
    client.ping.mockResolvedValueOnce('NOPE');
    await expect(adapter.ping()).resolves.toBe(false);
    client.ping.mockRejectedValueOnce(new Error('down'));
    await expect(adapter.ping()).resolves.toBe(false);
  });

  it('disconnects both connections', () => {
    adapter.disconnect();
    expect(client.disconnect).toHaveBeenCalled();
    expect(subscriber.disconnect).toHaveBeenCalled();
  });

  it('works without a logger or key prefix', async () => {
    instances.length = 0;
    const bare = new RedisAdapter({ host: 'h', port: 1, db: 2 });
    const [bareClient] = instances;
    expect(bareClient.options.db).toBe(2);
    bareClient.fire('error', new Error('ignored'));
    await bare.del('k');
    expect(bareClient.del).toHaveBeenCalledWith('k');
  });
});
