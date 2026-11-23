import { AdminPolicy } from './admin.policy.js';
import type { User } from '../users/user.model.js';

const user = (role: User['role']): User => ({
  id: '1',
  email: 'a@b.c',
  fullName: null,
  role,
  isActive: true,
  createdAt: new Date(),
});

describe('AdminPolicy', () => {
  it('allows only admins to manage', () => {
    const policy = new AdminPolicy();
    expect(policy.manage(user('ADMIN'))).toBe(true);
    expect(policy.manage(user('USER'))).toBe(false);
    expect(policy.manage(null)).toBe(false);
  });
});
