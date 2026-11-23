import { validateEnv } from './env.js';

const base = { DATABASE_URL: 'postgresql://x', JWT_SECRET: 'x'.repeat(32) };

describe('validateEnv', () => {
  it('applies defaults and treats empty values as unset', () => {
    const env = validateEnv({ ...base, ADMIN_EMAIL: '', ADMIN_PASSWORD: '' });
    expect(env).toMatchObject({
      PORT: 4000,
      JWT_TTL: '2h',
      AI_SERVICE_URL: 'http://localhost:8000',
    });
    expect(env.ADMIN_EMAIL).toBeUndefined();
  });

  it('rejects a JWT secret shorter than 32 bytes', () => {
    expect(() => validateEnv({ ...base, JWT_SECRET: 'short' })).toThrow(
      /JWT_SECRET.*32 byte/,
    );
    expect(() => validateEnv({ JWT_SECRET: 'x'.repeat(32) })).toThrow(
      /DATABASE_URL/,
    );
  });
});
