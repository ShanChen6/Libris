import { Policy } from '@nestjs/authorization';
import type { User } from '../users/user.model.js';

/** Quyền quản trị: quản lý kho văn bản luật và người dùng. */
@Policy()
export class AdminPolicy {
  manage(user: User | null) {
    return user?.role === 'ADMIN';
  }
}
