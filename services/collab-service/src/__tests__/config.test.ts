import { loadConfig } from '../config';

describe('loadConfig', () => {
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
  });

  afterAll(() => {
    process.env = originalEnv;
  });

  it('applies defaults when no environment variables are set', () => {
    for (const key of [
      'HTTP_PORT',
      'REDIS_HOST',
      'REDIS_PORT',
      'REDIS_PASSWORD',
      'REDIS_DB',
      'REDIS_KEY_PREFIX',
      'JWT_SECRET',
      'CORS_ORIGINS',
      'PERSIST_INTERVAL_MS',
      'LOG_LEVEL',
      'OTEL_ENABLED',
    ]) {
      delete process.env[key];
    }

    const config = loadConfig();

    expect(config.httpPort).toBe(8084);
    expect(config.redis).toEqual({
      host: 'localhost',
      port: 6379,
      password: undefined,
      db: 0,
      keyPrefix: 'collab:',
    });
    expect(config.cors.origins).toEqual([
      'http://localhost:3000',
      'http://localhost:4200',
    ]);
    expect(config.persistence.intervalMs).toBe(30000);
    expect(config.logLevel).toBe('info');
    expect(config.otel.enabled).toBe(false);
  });

  it('reads overrides from the environment', () => {
    process.env.HTTP_PORT = '9000';
    process.env.REDIS_HOST = 'redis';
    process.env.REDIS_PASSWORD = 'pw';
    process.env.CORS_ORIGINS = 'https://a.example,https://b.example';
    process.env.MAX_SNAPSHOTS = '5';
    process.env.OTEL_ENABLED = 'true';

    const config = loadConfig();

    expect(config.httpPort).toBe(9000);
    expect(config.redis.host).toBe('redis');
    expect(config.redis.password).toBe('pw');
    expect(config.cors.origins).toEqual(['https://a.example', 'https://b.example']);
    expect(config.persistence.maxSnapshotsPerDocument).toBe(5);
    expect(config.otel.enabled).toBe(true);
  });
});
