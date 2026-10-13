# DataNexus Pro 2.0

Mobile-first shipment, inventory and customer management — an installable, offline-capable PWA.
Plain HTML/CSS/JavaScript: **no build step, no dependencies, no API keys.**

It preserves everything from the original Python/mobile DataNexus Pro (shipment registration, status updates,
unique cities, inventory, low-stock ≤ 5, search, summary report, backup, login/sign-up, developer dashboard) and
extends it. The original JSON backup format and the earlier single-file app's local data/accounts are imported
automatically if they exist on the same origin.

---

## 1. Files

```
index.html               App entry point (loads scripts in order)
manifest.webmanifest     PWA manifest (name, icons, shortcuts)
sw.js                    Service worker (offline app shell, update prompt)
css/styles.css           Five themes, glass UI, responsive layout, print + reduced-motion rules
icons/                   icon.svg, 192/512 PNG, maskable-512, apple-touch-icon, favicon
js/db.js                 IndexedDB wrapper (+ in-memory fallback in private mode)
js/crypto.js             PBKDF2-SHA256 password hashing, recovery codes (Web Crypto)
js/ui.js                 Icons, dialogs, validated forms, toasts, toolbar, CSV, tooltips
js/store.js              Data rules: CRUD, unique IDs, statuses, stock alerts, notifications, import/export, analytics maths
js/auth.js               Browser-local accounts, sessions, local roles and recovery reset
js/particles.js          Animated particle background (pauses when hidden, respects reduced motion)
js/charts.js             Dependency-free SVG/HTML charts (line, donut, bars)
js/views/*.js            One file per screen: auth, dashboard, shipments (+tracking), inventory, customers,
                         analytics, notifications, profile, settings, help, dev
js/app.js                Shell, router, theme + motion preferences, global search, install + update flow
tools/make-icons.py      Regenerates PNG icons (Pillow)
tools/build-standalone.js  Builds dist/DataNexus_Pro_Standalone.html (single file)
dist/DataNexus_Pro_Standalone.html   Ready-made single-file build
```

## 2. Run it

A service worker (offline + install) requires **HTTPS or `localhost`**. Any static server works:

```bash
cd datanexus-pro
python3 -m http.server 8080        # or:  npx serve .
# open http://localhost:8080
```

* **First account created becomes the administrator.** Save the recovery code it shows.
* **No server at all?** Open `dist/DataNexus_Pro_Standalone.html` directly. Everything works (accounts, data, themes)
  except install-to-home-screen and the offline app-shell cache, which browsers only allow over HTTPS.
  Rebuild it any time with `node tools/build-standalone.js`.
* Want sample records to explore? Dashboard → **Load sample data** (the original three shipments and items, labelled
  *Sample*, removable in Settings → Data). Nothing is pre-filled otherwise — every number comes from your records.

## 3. Deploy (all free static hosts)

Upload the folder **as-is** (everything except `tools/` and `dist/` is needed). Serve over HTTPS.

| Host | Steps |
|---|---|
| **GitHub Pages** | Push to a repo → Settings → Pages → deploy from branch `/ (root)`. |
| **Netlify** | Drag the folder onto app.netlify.com/drop (publish dir = the folder, no build command). |
| **Cloudflare Pages** | Create project → Direct Upload (or connect repo), build command empty, output dir `/`. |
| **Firebase Hosting** | `firebase init hosting` (public dir `.`, single-page: *No*) → `firebase deploy`. |

After deploying: open the URL once online → "Ready to work offline" appears → it now opens with no connection.
**Releasing an update:** change `VERSION` in `sw.js` (e.g. `dnx-2.0.1`) and redeploy; users get a "Reload" prompt.
If the app lives in a sub-folder (e.g. `/app/`), everything already uses relative paths.

## 4. Install on a phone / desktop

* **Android (Chrome):** ⋮ → *Install app*.  **iPhone/iPad (Safari):** Share → *Add to Home Screen*.
* **Desktop (Chrome/Edge):** install icon in the address bar, or Settings → App → *Install*.

## 5. What works immediately

| Area | Details |
|---|---|
| **Accounts** | Register, log in/out, profile edit, password change, recovery-code password reset, roles (admin / staff / viewer), disable/delete users, 5-try lock-out with growing delay |
| **Dashboard** | Animated counters, 14-day trend, status donut, recent shipments, stock alerts, top cities, notifications — all computed from stored data |
| **Shipments** | Create / edit / delete, unique IDs (auto `SHP###` or custom, duplicates blocked), statuses Pending → In Transit → Delivered / Cancelled, per-shipment history with notes, search, filter by status & city, 6 sort orders, confirm-before-delete |
| **Tracking** | Look up by ID, progress stepper, timeline, one-tap "Mark In Transit / Delivered", active-deliveries list |
| **Inventory** | CRUD, ± stock buttons, set quantity, per-item alert level, Low / Out states, **notification when stock crosses the alert level**, search / category / stock filters / sort |
| **Customers** | CRUD, auto-created from shipments, linked shipment counts, search / sort, rename propagates |
| **Analytics & reports** | 7/30/90-day/all-time range, delivery rate, cancellation rate, average delivery time, charts, CSV export (shipments, inventory, customers), print-to-PDF report |
| **Notifications** | In-app list, unread badge, mark read/unread, open related record, delete/clear |
| **Data** | JSON backup & restore (merge or replace; accepts the original format), CSV export, sample-data load/remove, wipe (type DELETE) |
| **Themes** | Cyber Neon, Midnight Luxury, Ocean Blue, Clean Light, Emerald Tech — live switching (palette button or Settings), saved per device, applied before first paint |
| **Motion** | Particle background + count-up numbers + animated charts; off automatically for "reduce motion" and via Settings toggle |
| **PWA** | Manifest, icons (any + maskable + Apple), service worker, offline indicator, update prompt, install button |
| **Developer dashboard** | Password-gated: users (role / reset password / disable / delete), activity log, user CSV export |
| **Accessibility** | Skip link, labelled controls, native modal dialogs with focus handling, `aria-live` toasts, keyboard-focusable chart points, visible focus rings, `/` for global search |

## 6. What needs external services (NOT included / NOT live)

| Feature | Why | What you'd add |
|---|---|---|
| Sync across devices / shared team data | Data lives in each browser's IndexedDB | Supabase or Firebase backend (see §8) |
| Server-enforced auth & roles | Local auth runs in the user's own browser | Supabase Auth / Firebase Auth + database rules |
| Email password reset, email verification | No mail server | Auth provider's email, or SendGrid/Resend via a server function |
| Email / SMS / push notifications | Needs a provider and a server | Web Push + backend, Twilio, etc. Notifications are **in-app only** today |
| Live courier or GPS tracking | Needs a courier API / GPS hardware | Courier webhooks → backend |
| Automatic backup to the cloud | None configured | Backend, or manual JSON backups |

No external integration is claimed or faked anywhere in the UI. The Help screen shows this same table.

## 7. Security model — read this

* Passwords are **never stored in plain text**: PBKDF2-SHA256 (200 000 iterations, random 16-byte salt) via Web Crypto.
  Recovery codes are hashed the same way. Compare is constant-time. Inputs are HTML-escaped; CSV export neutralises
  spreadsheet-formula injection; no `eval`, no third-party scripts, no secrets or API keys in the code.
* **Local-only auth has a hard limit:** because accounts and data sit in the user's own browser, someone with
  technical skill and access to that browser profile can read or alter them with dev-tools. It protects against
  casual access and shared-device snooping, **not** against a determined attacker on the same device.
  For real multi-user security you need a server-side backend (§8).
* **Developer Console:** production access uses the separate backend API and server-enforced Owner/Developer permissions. Browser-local accounts are not production security boundaries. See `DEPLOYMENT.md`.
* Forgot **both** password and recovery code and no admin exists → the only recovery is clearing the site's data
  (which erases that device's records), so download backups regularly.
* Settings → *Protect data from automatic clean-up* asks the browser for persistent storage.

## 8. Backend upgrade

1. Create a Supabase project. Tables: `profiles(id, name, role)`, `customers`, `shipments`, `shipment_events`, `inventory`, `notifications`
   with an `org_id` column on each.
2. Enable **Row Level Security** on every table; policies check `auth.uid()` membership of the row's `org_id` and the role
   (`viewer` read-only, `staff` write, `admin` all).
3. Replace `js/auth.js` with Supabase Auth (email/password, password reset emails) and replace the `db.*` calls in
   `js/store.js` with Supabase queries — the views only talk to `D.store`/`D.data`, so they stay unchanged. Keep IndexedDB as an
   offline cache and sync on reconnect.
4. Only the **anon public key** may appear in frontend code; never ship the `service_role` key.

## 9. Testing notes

Verified in headless Chromium against this code: first-run registration and validation, recovery-code reset, login/logout,
password change, role enforcement (viewer is read-only), shipment CRUD with duplicate-ID blocking, status history, stock-alert
notification on crossing the threshold, search / filter / sort, charts render, all five themes persist across reload, IndexedDB
persistence, JSON backup contains no password hashes, developer console preview, service worker control and a full
offline reload, no horizontal overflow at 390 / 820 / 1366 px widths, no console errors. Real-device checks on iOS Safari and
Android Chrome are still worth doing before you ship.

## 10. Troubleshooting

* **"This browser can't secure passwords"** – open over HTTPS or `localhost` (Web Crypto needs a secure context).
* **No install button / no offline** – needs HTTPS; the single-file build can't register a service worker.
* **Data vanished** – browser site data was cleared, or you used a private window. Restore from a JSON backup.
* **Stuck on an old version** – bump `VERSION` in `sw.js`, redeploy, reload twice (accept the "Reload" prompt).
