import {
  Body,
  ConflictException,
  Controller,
  Get,
  NotFoundException,
  Param,
  Patch,
  Query,
} from '@nestjs/common';
import { Can } from '@nestjs/authorization';
import { z } from 'zod';
import { AdminPolicy } from '../auth/admin.policy.js';
import { UsersRepository } from './users.repository.js';

const listSchema = z.object({
  limit: z.coerce.number().int().min(1).max(100).default(50),
  after: z.uuid().optional(), // con trỏ: id cuối của trang trước
});
const roleSchema = z.object({ role: z.enum(['USER', 'ADMIN']) });

@Controller('admin/users')
@Can(AdminPolicy, 'manage')
export class AdminUsersController {
  constructor(private readonly users: UsersRepository) {}

  @Get()
  async list(@Query({ schema: listSchema }) query: z.infer<typeof listSchema>) {
    const items = await this.users.list(query.limit + 1, query.after);
    const hasMore = items.length > query.limit;
    const page = items.slice(0, query.limit);
    return { items: page, nextCursor: hasMore ? page.at(-1)?.id : null };
  }

  @Patch(':id/role')
  async setRole(
    @Param('id') id: string,
    @Body({ schema: roleSchema }) body: z.infer<typeof roleSchema>,
  ) {
    const result = await this.users.setRole(id, body.role);
    if (result === 'last-admin')
      throw new ConflictException('Không thể hạ quyền quản trị viên cuối cùng');
    if (!result) throw new NotFoundException('Không tìm thấy người dùng');
    return result;
  }
}
