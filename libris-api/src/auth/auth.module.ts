import { Module } from '@nestjs/common';
import { UsersModule } from '../users/users.module.js';
import { AdminBootstrapService } from './admin-bootstrap.service.js';
import { AdminPolicy } from './admin.policy.js';
import { AuthController } from './auth.controller.js';
import { CredentialsService } from './credentials.service.js';
import { JwtAuth } from './jwt-auth.provider.js';
import './auth.types.js';

@Module({
  imports: [UsersModule],
  controllers: [AuthController],
  providers: [CredentialsService, JwtAuth, AdminPolicy, AdminBootstrapService],
  exports: [AdminPolicy],
})
export class AuthModule {}
