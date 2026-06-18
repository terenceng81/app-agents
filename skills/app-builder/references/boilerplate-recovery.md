# Boilerplate Recovery — Complete File Generation Reference

When the `frontend_coder` step skips required boilerplate files, generate all 15
from the templates below. This was proven working on 2026-06-08 for the Health Pulse app.

## Required Files Checklist

- [ ] `package.json`
- [ ] `jsconfig.json`
- [ ] `next.config.js`
- [ ] `middleware.js`
- [ ] `lib/auth.js`
- [ ] `lib/auth-client.js`
- [ ] `lib/db.js`
- [ ] `app/api/auth/[...all]/route.js`
- [ ] `app/layout.js`
- [ ] `app/globals.css`
- [ ] `app/page.js`
- [ ] `app/_client.js`
- [ ] `app/app/page.js`
- [ ] `app/app/_client.js`
- [ ] `app/app/actions.js`

## Step 1: Config files

### package.json
Pin versions exactly — these are battle-tested combos:
```json
{
  "name": "app-name",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "14.2.29",
    "react": "^18",
    "react-dom": "^18",
    "better-auth": "^1.2.7",
    "@neondatabase/serverless": "^0.10.4",
    "pg": "^8.13.3"
  }
}
```

### jsconfig.json
Required for `@/*` path alias — without this all `@/` imports fail at build:
```json
{
  "compilerOptions": {
    "paths": {
      "@/*": ["./*"]
    }
  }
}
```

### next.config.js
MUST use `experimental.serverComponentsExternalPackages` (Next.js 14 API — NOT
`serverExternalPackages` which is Next.js 15+). This prevents better-auth kysely
peer dep bundling errors:
```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    serverComponentsExternalPackages: ['better-auth', 'pg'],
  },
}
module.exports = nextConfig
```

### middleware.js
Protects `/app` route — unauthenticated users redirect to `/`:
```js
import { NextResponse } from 'next/server'
import { getSessionCookie } from 'better-auth/cookies'
export function middleware(request) {
  const session = getSessionCookie(request)
  if (!session && request.nextUrl.pathname.startsWith('/app')) {
    return NextResponse.redirect(new URL('/', request.url))
  }
  return NextResponse.next()
}
export const config = { matcher: ['/app/:path*'] }
```

## Step 2: Auth layer

### lib/auth.js
Better Auth with Pool (NOT neon HTTP — Pool is required for auth):
```js
import { betterAuth } from 'better-auth'
import { Pool } from 'pg'

export const auth = betterAuth({
  secret: process.env.AUTH_SECRET,
  database: new Pool({ connectionString: process.env.DATABASE_URL }),
  emailAndPassword: { enabled: true },
  trustedOrigins: [process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'],
})
```

### lib/auth-client.js
Browser-side Better Auth client:
```js
import { createAuthClient } from 'better-auth/react'

export const authClient = createAuthClient({
  baseURL: typeof window !== 'undefined'
    ? window.location.origin
    : process.env.NEXT_PUBLIC_APP_URL,
})
```

### lib/db.js
Neon HTTP SQL client for Server Actions:
```js
import { neon } from '@neondatabase/serverless'
export const sql = neon(process.env.DATABASE_URL)
```

### app/api/auth/[...all]/route.js
Better Auth HTTP handler:
```js
import { auth } from '@/lib/auth'
import { toNextJsHandler } from 'better-auth/next-js'
export const { GET, POST } = toNextJsHandler(auth)
```

## Step 3: App shell

### app/layout.js
Root layout with Google Fonts (NOT Inter/Roboto), theme FOUC prevention:
```js
import './globals.css'

export const metadata = {
  title: 'App Name',
  description: 'App description.',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet" />
        <script dangerouslySetInnerHTML={{
          __html: `(function(){try{var t=localStorage.getItem('theme');if(t==='dark'||(!t&&matchMedia('(prefers-color-scheme:dark)').matches))document.documentElement.classList.add('dark')}catch(e){}})()`,
        }} />
      </head>
      <body>{children}</body>
    </html>
  )
}
```

### app/globals.css
Full design system — CSS variables for light AND dark, all component classes.
Key rules:
- `:root` for light, `.dark` for dark — use CSS variables everywhere, never raw colors
- Include: auth-shell, app-shell, cards, forms, buttons, modal, tabs, severity track,
  tags, bottom-nav, sidebar, stat cards, medication list, settings, toggle, grid, responsive
- Mobile-first: `@media (min-width: 768px)` swaps bottom-nav → sidebar
- Touch targets: min 44px, bottom nav 64px with safe-area padding
- Animation: fadeIn for backdrop, slideUp for modal — single choreographed entry, not micro-interactions

For a complete working `globals.css`, see the Health Pulse implementation:
- Font: Outfit (headings/body) + DM Mono (data values)
- Palette: warm neutral base (`#f5f2ed` light / `#1a1a1a` dark), green accent (`#2d7d46` / `#4ade80`)
- Status colors: green/amber/red with matching light backgrounds
- CSS variables used for ALL colors — light/dark swap handled by `.dark` selector

## Step 4: Auth pages

### app/page.js
Thin server wrapper — NEVER put 'use client' here:
```js
import dynamic from 'next/dynamic'
const Page = dynamic(() => import('./_client'), { ssr: false, loading: () => null })
export default Page
```

CRITICAL: better-auth's React client (`authClient.useSession` → `react-store.mjs` → `useRef`)
crashes during Next.js SSR because `ReactCurrentDispatcher.current` is null server-side.
`force-dynamic` does NOT fix this — the component is still SSR'd. The ONLY fix is
`ssr: false` via `next/dynamic`. Put all actual auth logic in `app/_client.js`.

### app/_client.js
Actual auth page (login/signup):
- `'use client'` on line 1
- Use `authClient.useSession()` → `{ data: session, isPending }`
- If `isPending`: render spinner
- If `session`: `window.location.href = '/app'` (full redirect, not router.push)
- Form: email + password + login/signup toggle
- Sign up: `await authClient.signUp.email({ email, password, name: email.split('@')[0] })`
- Sign in: `await authClient.signIn.email({ email, password })`
- On success (no `result.error`): `window.location.href = '/app'`
- Show error message if `result.error`

## Step 5: App dashboard shell

### app/app/page.js
Thin server wrapper — same pattern as auth page:
```js
import dynamic from 'next/dynamic'
const AppPage = dynamic(() => import('./_client'), { ssr: false, loading: () => null })
export default AppPage
```

### app/app/_client.js
Main authenticated app shell:
- `'use client'` on line 1
- Use `authClient.useSession()` for user info and sign out
- Import the generated components from `@/components/`
- DESKTOP: `<aside className="app-sidebar">` with nav items
- MOBILE: `<nav className="bottom-nav">` at bottom of page
- Both navs render the same tabs — CSS shows/hides at breakpoints
- Theme toggle: read `localStorage.getItem('theme')`, toggle `document.documentElement.classList`
- Sign out: `await authClient.signOut()` then `window.location.href = '/'`
- Dashboard: load data via server actions, render summary stat cards + medication list
- Include a "Quick Log" button that opens the QuickLogModal component

## Step 6: Server actions

### app/app/actions.js
Scan the generated components for ALL imports from `@/app/app/actions`:
```bash
grep -oP "import \{[^}]+\} from ['\"]@/app/app/actions['\"]" <FINAL_DIR>/steps/2-frontend_coder.md
```

Then write `app/app/actions.js`:
```js
'use server'
import { auth } from '@/lib/auth'
import { headers } from 'next/headers'
import { sql } from '@/lib/db'

async function requireUser() {
  const session = await auth.api.getSession({ headers: await headers() })
  if (!session?.user) throw new Error('Unauthorized')
  return session.user
}

// Export one async function per action the components import.
// Match the DB schema that was deployed (check 1-db_architect.md).
// Use parameterized queries — sql`...` template literals.
```

Key patterns for each action type:
- **Add/insert:** `sql`INSERT INTO table (owner_id, …) VALUES (${user.id}, …) RETURNING id``
- **Query:** `sql`SELECT * FROM table WHERE owner_id = ${user.id} ORDER BY created_at DESC``
- **Update:** `sql`UPDATE table SET … WHERE id = ${id} AND owner_id = ${user.id} RETURNING …``
- **Delete:** `sql`DELETE FROM table WHERE id = ${id} AND owner_id = ${user.id}``
- **Prefs:** `ON CONFLICT (owner_id) DO UPDATE` for upsert pattern

## Step 7: Scan for missing dependencies

After writing everything, scan the frontend coder output for external libraries
not in `package.json`:
```bash
python3 -c "
import re
with open('<FINAL_DIR>/steps/2-frontend_coder.md') as f:
    content = f.read()
known = {'react','next','better-auth','recharts','@neondatabase','next-themes'}
for m in re.finditer(r\"from ['\\\"]([^'\\\"@.][^'\\\"]+)['\\\"]\", content):
    if m.group(1) not in known:
        print(f'ADD TO package.json: {m.group(1)}')
"
```

Common additions: `recharts` (charts), `next-themes` (dark mode), `date-fns` (dates).

## Step 8: Commit and push

```bash
cd /tmp/<REPO_NAME>
git add -A
git commit -m "Fix: add all boilerplate files (package.json, auth, app shell, server actions)"
git push origin main
```

Vercel auto-deploys on push to main. Wait ~60s then verify:
```bash
vercel inspect <URL> 2>&1 | grep status
# → status ● Ready
curl -s -o /dev/null -w "HTTP %{http_code}" "<URL>"
# → HTTP 200
```
