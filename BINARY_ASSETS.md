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
