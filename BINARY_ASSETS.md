# Binary assets — not in this repo (push-tool limitation)

The GitHub push tool used for the initial commit accepts UTF-8 text files
only, so the following 9 binary files from the local refactor tree are NOT
in this repo. They are all non-critical for API function:

- `backend/catalogue.xlsx` — leftover upstream sample workbook. The admin
  template download (`GET /admin/grocery/template`) GENERATES its xlsx at
  request time via `grocery_template.build_template_xlsx()`; it does not
  serve this file.
- `backend/static/Ionicons.ttf`, `backend/web_dist/fonts/Ionicons.ttf` —
  icon font (UI icons).
- `backend/web_dist/favicon.ico` — favicon.
- `backend/web_dist/assets/assets/brand/hero-fresh.*.jpg`,
  `logo-circle.*.png`, `tile-grocery.*.jpg`, `tile-meal.*.jpg`,
  `tile-thali.*.jpg` — frontend brand images.

Effect: a fresh clone builds and runs the full API, but the web frontend
shows without brand images / icon font until these files are added back.
The parallel-test deployment on the AWS box DOES include them (deployed
from the full local bundle, not from this repo checkout), so the test URL
renders fully.

Follow-up to close the gap (one of): upload the 9 files via the GitHub
web UI, push them from a machine with git configured, or adopt Git LFS
for `backend/web_dist/**` and `backend/static/**`.

## 2026-10-30 — /shop routing fix: frontend source added (text only)

The `frontend/` source tree (Expo app, read-only copy from the upstream
repo — the old repo is never pushed to) is in this repo as TEXT files
only. Its 23 binary files are NOT in this repo (same push-tool limit):

- `frontend/assets/brand/` — adaptive-icon.png, hero-fresh.jpg,
  login-bg.png, logo-circle.png, logo-square.png, logo.png, mascot.png,
  notification-icon.png, splash.png, tile-grocery.jpg, tile-meal.jpg,
  tile-thali.jpg (brand + hero images used by the shop storefront).
- `frontend/assets/images/` — adaptive-icon.png, app-image.png,
  favicon.png, icon.png, partial-react-logo.png, react-logo.png,
  react-logo@2x.png, react-logo@3x.png, splash-image.png.
- `frontend/assets/fonts/SpaceMono-Regular.ttf`,
  `frontend/public/fonts/Ionicons.ttf` — fonts.

`frontend/dist/` (the Expo web export) is NOT pushed either — it is a
regenerable build artifact (`npm run build:web` in `frontend/`).
`backend/web_dist/` in this repo holds the CURRENT built bundle's text
files only (index.html, entry JS, metadata); its binary assets (brand
images, icon fonts, expo-router icons) are likewise excluded here.

Effect: a fresh clone can rebuild the full web frontend ONLY after these
binaries are restored (they are all present in the deployed test-stack
bundle, which is shipped from the full local tree, not from this repo
checkout — so the test URL renders fully). Same follow-up as above
(web-UI upload, git-equipped push, or Git LFS) closes the gap.
