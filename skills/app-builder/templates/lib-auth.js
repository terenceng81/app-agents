import { betterAuth } from 'better-auth';
import { Pool } from 'pg';

export const auth = betterAuth({
  database: new Pool({ connectionString: process.env.DATABASE_URL }),
  session: { expiresIn: 60 * 60 * 24 * 7 },
  emailAndPassword: { enabled: true },
  trustedOrigins: [process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'],
});
