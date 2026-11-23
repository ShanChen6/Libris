export type Role = 'USER' | 'ADMIN';

/** Người dùng trả ra ngoài: không bao giờ chứa password_hash. */
export interface User {
  id: string;
  email: string;
  fullName: string | null;
  role: Role;
  isActive: boolean;
  createdAt: Date;
}
