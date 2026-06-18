import { NextResponse } from 'next/server';

export default function middleware(request) {
  const { pathname } = request.nextUrl;
  // Allow public routes
  if (pathname === '/' || pathname.startsWith('/api/auth')) {
    return NextResponse.next();
  }
  // Allow static assets
  if (pathname.startsWith('/_next') || pathname.includes('.')) {
    return NextResponse.next();
  }
  // Check for session cookie (Better Auth sets this)
  const sessionToken = request.cookies.get('better-auth.session_token')?.value;
  if (!sessionToken) {
    return NextResponse.redirect(new URL('/', request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
