import { ConflictException, Injectable } from '@nestjs/common';
import {
  DatabaseService,
  isUniqueViolation,
} from '../database/database.service.js';
import type { Role, User } from './user.model.js';

interface UserRow {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  created_at: Date;
}

const COLUMNS = 'id, email, full_name, role, is_active, created_at';

function toUser(row: UserRow): User {
  return {
    id: row.id,
    email: row.email,
    fullName: row.full_name,
    role: row.role,
    isActive: row.is_active,
    createdAt: row.created_at,
  };
}

/** Mọi truy vấn bảng users; password_hash không rời khỏi lớp này trừ findCredentials(). */
@Injectable()
export class UsersRepository {
  constructor(private readonly db: DatabaseService) {}

  /** Tạo người dùng; email trùng (không phân biệt hoa thường) -> 409. */
  async create(input: {
    email: string;
    passwordHash: string;
    fullName?: string | null;
    role?: Role;
  }): Promise<User> {
    try {
      const { rows } = await this.db.query<UserRow>(
        `INSERT INTO users (email, password_hash, full_name, role)
         VALUES ($1, $2, $3, $4) RETURNING ${COLUMNS}`,
        [
          input.email.trim(),
          input.passwordHash,
          input.fullName ?? null,
          input.role ?? 'USER',
        ],
      );
      return toUser(rows[0]);
    } catch (error) {
      if (isUniqueViolation(error))
        throw new ConflictException('Email đã được đăng ký');
      throw error;
    }
  }

  /** Người dùng đang hoạt động; null nếu không có hoặc đã bị khóa. */
  async findById(id: string): Promise<User | null> {
    if (!isUuid(id)) return null;
    const { rows } = await this.db.query<UserRow>(
      `SELECT ${COLUMNS} FROM users WHERE id = $1 AND is_active`,
      [id],
    );
    return rows[0] ? toUser(rows[0]) : null;
  }

  async findCredentials(
    email: string,
  ): Promise<{ user: User; passwordHash: string } | null> {
    const { rows } = await this.db.query<UserRow & { password_hash: string }>(
      `SELECT ${COLUMNS}, password_hash FROM users WHERE lower(email) = lower($1) AND is_active`,
      [email.trim()],
    );
    return rows[0]
      ? { user: toUser(rows[0]), passwordHash: rows[0].password_hash }
      : null;
  }

  async updatePasswordHash(id: string, passwordHash: string): Promise<void> {
    await this.db.query('UPDATE users SET password_hash = $2 WHERE id = $1', [
      id,
      passwordHash,
    ]);
  }

  async existsByEmail(email: string): Promise<boolean> {
    const { rowCount } = await this.db.query(
      'SELECT 1 FROM users WHERE lower(email) = lower($1)',
      [email.trim()],
    );
    return (rowCount ?? 0) > 0;
  }

  async list(limit: number, after?: string): Promise<User[]> {
    const { rows } = await this.db.query<UserRow>(
      `SELECT ${COLUMNS} FROM users WHERE ($2::uuid IS NULL OR id > $2) ORDER BY id LIMIT $1`,
      [limit, after ?? null],
    );
    return rows.map(toUser);
  }

  /**
   * Đổi vai trò. Không cho hạ quyền admin cuối cùng (kiểm tra và ghi trong cùng transaction,
   * khóa các dòng admin để hai yêu cầu đồng thời không cùng vượt qua).
   */
  async setRole(id: string, role: Role): Promise<User | null | 'last-admin'> {
    if (!isUuid(id)) return null;
    return this.db.transaction(async (tx) => {
      if (role !== 'ADMIN') {
        const admins = await tx.query<{ id: string }>(
          "SELECT id FROM users WHERE role = 'ADMIN' AND is_active FOR UPDATE",
        );
        if (admins.rows.length === 1 && admins.rows[0].id === id)
          return 'last-admin';
      }
      const { rows } = await tx.query<UserRow>(
        `UPDATE users SET role = $2 WHERE id = $1 RETURNING ${COLUMNS}`,
        [id, role],
      );
      return rows[0] ? toUser(rows[0]) : null;
    });
  }
}

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}
