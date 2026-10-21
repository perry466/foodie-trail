<div align="center">

# 🍜 Foodie Trail · 美食地图
### Every place you've eaten, on one map

> A local-first food journal: pin restaurants, rate them, filter by price / tag / status, and read your taste in a dashboard · FastAPI + Vue 3

[![简体中文](https://img.shields.io/badge/简体中文-查看中文文档-ff6b9d?style=for-the-badge)](./README_zh.md)
![Python](https://img.shields.io/badge/Python-3.10%2B-4a90d9?style=for-the-badge)
![No build step](https://img.shields.io/badge/Frontend-no_build_step-2ea44f?style=for-the-badge)

</div>

---

> 📘 **This guide is in English.** Prefer 中文? → **[查看中文文档 →](./README_zh.md)**

## 📸 Screenshots

<table>
  <tr>
    <td align="center" width="50%">
      <a href="./docs/screenshots/01-map.jpg"><img src="./docs/screenshots/01-map.jpg" alt="Map view" width="100%"/></a>
      <br/><b>🗺 Map</b> · pins colored by rating, clustering, hover preview
    </td>
    <td align="center" width="50%">
      <a href="./docs/screenshots/03-filter.jpg"><img src="./docs/screenshots/03-filter.jpg" alt="Filter panel" width="100%"/></a>
      <br/><b>🔍 Filters</b> · stars, price buckets, tags, status, drafts, viewport
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <a href="./docs/screenshots/04-dashboard.jpg"><img src="./docs/screenshots/04-dashboard.jpg" alt="Dashboard" width="100%"/></a>
      <br/><b>📊 Dashboard</b> · totals, rating / price distribution, 12-month trend
    </td>
    <td align="center" width="50%">
      <a href="./docs/screenshots/05-detail.jpg"><img src="./docs/screenshots/05-detail.jpg" alt="Record detail" width="100%"/></a>
      <br/><b>🍽 Detail</b> · one-tap status switch, photos, edit, navigate
    </td>
  </tr>
</table>

> 🔎 **Drill-down tip**: every chart in the dashboard is clickable — it jumps to the list with that filter already applied.

---

## ✨ Features

- 🗺 **Map-first recording** — click the map to drop a pin, right-click / long-press to add with coordinates prefilled, or search an address; "locate me" uses browser geolocation.
- 🏷 **Complete fields** — name, 1–5 stars, tags, weekly opening hours (multiple slots per day), average price per person, status (want / visited / favourite), note, up to 9 photos.
- 🔍 **Precise filters** — keyword, exact star range, price buckets (`<30 / 30–60 / 60–100 / 100–200 / ≥200`), tags (match all or any), check-in status, current viewport, drafts. Filters live in the URL, so refresh and back/forward keep them.
- 📋 **List that scales** — scroll-to-load (renders 60 at a time), sorting, keyboard `↑`/`↓` + `Enter`, multi-select with select-all / invert / clear, batch delete.
- 📊 **Dashboard** — totals, visited rate, pending spots, average & median price, rating and price distribution, top tags, 12-month trend, data-quality hints, and "what to eat next" lists. Every chart drills down.
- 🖼 **Photos** — EXIF orientation corrected, long edge resized to 1280 px and re-encoded as JPEG (target ≤ 500 KB), lightbox with arrow-key navigation.
- 📝 **Drafts** — save unfinished records as drafts with a badge; the add-form autosaves to `localStorage` so an accidental close doesn't lose typing.
- 💾 **Backup & restore** — JSON export (with or without photos) → import with **preview → confirm**, live progress, and per-record transactions.
- 🎨 **Light / dark theme**, keyboard shortcuts (`n` new, `/` search, `f` filter, `Esc` step back).
- 🔒 **Local only** — the server binds `127.0.0.1`, rejects cross-site origins, and Amap keys are encrypted at rest with Fernet.

> 💡 Day-to-day operations (adding a record, hours editor, import flow, shortcuts) are covered in the **[Usage Guide](./docs/USAGE.md)** · **[使用指南（中文）](./docs/USAGE_zh.md)**.

---

## 🚀 Quick Start (from scratch)

```bash
git clone https://github.com/perry466/foodie-trail.git
cd foodie-trail

# Windows
setup.bat          # creates venv + installs runtime & test deps
start.bat          # starts the server and opens the browser

# macOS / Linux
./setup.sh
./start.sh
```

That's it — **no Node.js, no build step, no database server**. The frontend ships as plain ES modules plus a vendored Vue 3, and SQLite is embedded.

> ⚠️ Start it with `python -m app.main` **from the repository root** — the backend uses package-relative imports, so `python app/main.py` will fail.

---

## 📑 Table of Contents

- [📋 1. Requirements](#1-requirements)
- [📁 2. Project Structure](#2-project-structure)
- [🚀 3. Running](#3-running)
- [🗺 4. Map Providers](#4-map-providers)
- [💾 5. Data and Backup](#5-data-and-backup)
- [🧪 6. Tests and Data Health](#6-tests-and-data-health)
- [💽 7. Data Model](#7-data-model)
- [🔌 8. API Reference](#8-api-reference)
- [⚙️ 9. Limits and Defaults](#9-limits-and-defaults)
- [❓ 10. FAQ](#10-faq)
- [🛠 11. Development](#11-development)

---

## 📋 1. Requirements

| Dependency | Version | Notes |
| --- | --- | --- |
| Python | 3.10+ | tested on 3.14; `setup.bat` / `setup.sh` create the venv for you |
| Node.js | 18+ | **optional** — only for `tests/front-check.js` |
| Git | any | to clone and update |
| Browser | modern | Chrome / Edge / Firefox / Safari |

No external services are required. Map tiles come from Amap's public raster endpoints when no key is configured; everything else is local.

---

## 📁 2. Project Structure

```
foodie-trail/
├── app/                        # FastAPI backend
│   ├── main.py                 # routes, request models, image pipeline, Amap proxy
│   ├── repository.py           # data access + dashboard aggregation + sort whitelist
│   ├── validate.py             # field normalisation & import validation (shared)
│   ├── db.py                   # schema, connections (WAL, foreign keys)
│   ├── crypto.py               # Fernet encryption for Amap keys (self-healing)
│   ├── coords.py               # WGS-84 ↔ GCJ-02, haversine distance
│   └── pathconf.py             # paths, port discovery, photo limits
├── static/                     # frontend (no build step)
│   ├── index.html              # page shell + all templates
│   ├── css/style.css           # styles, light & dark themes
│   ├── js/app.js               # map adapter + UI logic
│   └── lib/                    # vendored Vue, Leaflet, markercluster
├── docs/
│   ├── screenshots/            # README images
│   ├── USAGE.md                # usage guide (English)
│   └── USAGE_zh.md             # usage guide (Chinese)
├── tests/                      # pytest suite + Node front-end assertions
├── hooks/pre-commit            # optional guard: blocks data files on commit
├── health_check.py             # read-only data health check
├── repo_guard.py               # allow-by-default guard rules used by the hook
├── seed_demo.py                # demo data (direct DB, `demo-` ids, clearable)
├── seed_1000.py                # bulk demo data through the running API
├── setup.bat / setup.sh        # create venv + install dependencies
├── start.bat / start.sh        # probe interpreter, then start the app
├── data/                       # ← your data (git-ignored)
└── README.md / README_zh.md
```

---

## 🚀 3. Running

### 3.1 One-click (recommended)

| Platform | First time | Every time |
| --- | --- | --- |
| Windows | `setup.bat` | `start.bat` |
| macOS / Linux | `./setup.sh` | `./start.sh` |

`setup` creates `venv/` and installs `requirements.txt` + `requirements-dev.txt`.
`start` checks that the interpreter can really import `fastapi`, `uvicorn` and `PIL`, falls back to `py -3` / `python` if the venv is broken, and prints a clear fix hint instead of a traceback when nothing works.

On start the app:

1. picks a free port in `20000–65535` (reusing the last one saved in `data/.last_port`),
2. initialises the database and `data/photos/`,
3. opens the browser at `http://127.0.0.1:<port>` about 1.5 s later.

### 3.2 Manual

```bash
python -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m app.main
```

### 3.3 Ports and data location

| Variable | Default | Effect |
| --- | --- | --- |
| `PORT` | random free port in `20000–65535` | force a port; invalid values are ignored with a warning instead of crashing |
| `FOODMAP_DATA_DIR` | `<repo>/data` | move the whole data directory (portable use, tests, multiple libraries) |

```bash
# run a second, isolated instance
FOODMAP_DATA_DIR=/tmp/foodie-demo PORT=31200 python -m app.main
```

---

## 🗺 4. Map Providers

| Setup | Basemap | Address search | Route |
| --- | --- | --- | --- |
| No key | Leaflet + Amap raster tiles | ✗ (banner explains it) | ✗ |
| JS API key + security code | Amap JS API 2.0 | ✗ | ✗ |
| + Web-service key | Amap JS API 2.0 | ✓ POI autocomplete, geocoding | ✓ driving route |

Keys are entered in **Settings** inside the app — never in source files.

- Stored **Fernet-encrypted** in `data/foodmap.db`; the AES key lives in `data/.fernet.key`.
- Existing values are shown masked (`••••1234`); leaving the field empty **keeps** the stored value. Removing requires the explicit "clear" action.
- If `data/.fernet.key` is ever corrupted, the app renames it aside, generates a new one and keeps running — only previously saved Amap keys need re-entering; records and photos are untouched.

---

## 💾 5. Data and Backup

Everything lives in `data/`:

```
data/
├── foodmap.db        # SQLite (WAL) — records, photo rows, settings
├── foodmap.db-wal    # write-ahead log (merged automatically)
├── photos/           # JPEG files, one per photo
├── .fernet.key       # key for the encrypted Amap credentials
├── .last_port        # last used port
└── backups/          # optional manual snapshots
```

**Export** (More → Export backup) writes a JSON file:

| Mode | Contents | Use |
| --- | --- | --- |
| `full` | records **+ photos as base64** | real backup, moving machines |
| `meta` | records only, `photosIncluded: false` | quick data dump, no photos touched on import |

Drafts are included by default, and the current filters still apply — clear them if you want everything.

**Import** is intentionally cautious:

1. **Preview** — shows how many records will be added, updated or rejected, without writing anything.
2. **Confirm** — writes with live progress.
3. Per record: one transaction; photos are decoded, size-checked and re-encoded *before* the database is touched.
4. If any photo in a record is corrupt, that record keeps its **existing** photos instead of losing them.
5. Records whose `updatedAt` is not newer than the local copy are skipped and reported as **"already up to date"**.

**Moving to another machine**: copy the whole `data/` folder. Copying only `foodmap.db` loses `.fernet.key`, so saved Amap keys can't be decrypted (records are fine).

**Reset demo data**: `python seed_demo.py --clear --yes` removes every record with a `demo-` id together with its photo files. Real records are never touched.

---

## 🧪 6. Tests and Data Health

```bash
python -m pytest tests -q      # 133 backend cases
node tests/front-check.js      # 38 front-end assertions (Node 18+)
tests\run-tests.bat            # both, exit code 0 / 1 / 2 (2 = Node missing)
```

Coverage highlights: CRUD and validation, photo upload/read/delete, export → wipe → import round-trip (including photo bytes), corrupt-backup safety, draft scopes, encrypted-key semantics, week-schedule round-trip, import performance, startup robustness (corrupt `.fernet.key`, invalid `PORT`), and the commit guard.

**Data health check** (read-only, changes nothing):

```bash
python health_check.py          # integrity, schema, counts, field ranges, photos, demo data
python health_check.py --deep   # additionally decodes every JPEG
```

**Commit guard** — `data/` is git-ignored, and a hook adds a second line of defence:

```bash
# once per clone
cat hooks/pre-commit > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

It blocks staged `data/`, `*.db`, `*.key`/`*.pem`, `.env*`, backup JSON, `.tmp-*`, `venv/`, `dist/*.exe` and lists the offending files. Everything else — source, tests, docs, screenshots — passes. If the guard itself errors, the commit is allowed with a warning instead of locking you out.

---

## 💽 7. Data Model

| Table | Field | Type | Notes |
| --- | --- | --- | --- |
| `records` | `id` | TEXT PK | `[A-Za-z0-9_-]{1,64}`, generated uuid4 otherwise |
| | `name` | TEXT | required, ≤ 120 chars |
| | `lng` / `lat` | REAL | required, WGS-84 bounds checked |
| | `rating` | INTEGER | 1–5 |
| | `tags` | TEXT | JSON array, ≤ 32 tags × 24 chars |
| | `business_hours` | TEXT | weekly schedule JSON `{"mon":[{"s":"10:00","e":"22:00"}],…}` or legacy plain text |
| | `avg_price` | INTEGER | 0–100000; `0` is a valid price (free) |
| | `checkin_status` | TEXT | `want` / `visited` / `favorite` / NULL |
| | `note` | TEXT | ≤ 2000 chars |
| | `draft` | INTEGER | 0/1 |
| | `created_at` / `updated_at` | INTEGER | epoch milliseconds, 2000–2100 |
| `photos` | `id`, `record_id`, `path`, `thumb`, `created_at` | | `record_id` cascades on delete; `path` is `photos/<uuid>.jpg` |
| `settings` | `key`, `value` | TEXT | holds the encrypted Amap credentials |
| `meta` | `key`, `value` | TEXT | schema version |

---

## 🔌 8. API Reference

All endpoints are under `/api` on `127.0.0.1` only; requests from other origins are rejected with `403`.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/records` | list with filters: `keyword`, `ratingMin/Max`, `avgPriceMin/Max`, `checkinStatus`, `tags`, `tagsAny`, `includeDrafts`, `draftsOnly`, `swLng/swLat/neLng/neLat`, `sort`, `limit`, `offset` |
| GET | `/api/records/{id}` | single record **with photos** |
| POST | `/api/records` | create (`201`; `409` if the id exists) |
| PUT | `/api/records/{id}` | **full replace** — omitted optional fields are reset (see note below) |
| DELETE | `/api/records/{id}` | delete record; photo files removed after the DB commit |
| DELETE | `/api/records/batch` | body `{"ids": [...]}`; single transaction, then files |
| POST | `/api/records/{id}/photos` | upload one image (multipart `file`), max 9 per record |
| GET | `/api/photos/{id}` | raw JPEG |
| DELETE | `/api/photos/{id}` | delete photo row, then file |
| GET | `/api/config/amap` | which keys exist (`configured`, `webConfigured`), secret never returned |
| PUT | `/api/settings/amap` | save JS key / security code / web-service key (empty = keep) |
| DELETE | `/api/settings/amap/security` | clear only the security code |
| DELETE | `/api/settings/amap` | clear all Amap keys |
| POST | `/api/settings/test-connection` | verify the stored keys against Amap |
| GET | `/api/amap/poi` | POI autocomplete (`keywords`, optional `city`, `location`) |
| GET | `/api/amap/geocode` | address → coordinates |
| GET | `/api/amap/route` | driving route between two points |
| POST | `/api/coords/convert` | WGS-84 → GCJ-02 for browser geolocation |
| GET | `/api/recommend/nearby` | nearest records to a point (API only, not in the UI) |
| GET | `/api/recommend/similar/{id}` | similar records by tags / price (API only) |
| GET | `/api/dashboard` | aggregated statistics (excludes drafts) |
| GET | `/api/export` | streaming JSON backup: `mode=full\|meta`, `includeDrafts` |
| POST | `/api/import` | multipart `file`; `confirm=true` writes, `progress=1` streams NDJSON |

> ⚠️ **`PUT` is a full replace.** Fields you omit are reset (`tags → []`, `note → null`, `avgPrice → null`, `checkinStatus → null`, `draft → false`). The UI always sends the complete body; scripts must `GET` first, modify, then `PUT` the whole object.

---

## ⚙️ 9. Limits and Defaults

| Item | Limit |
| --- | --- |
| Photos per record | 9 |
| Upload size | 20 MB per file |
| Stored photo | long edge 1280 px, JPEG quality 82 → step down to 30, target ≤ 500 KB |
| Accepted formats | anything Pillow can decode (JPG / PNG / WebP / GIF / 8- & 16-bit greyscale …) |
| Backup file | ≤ 256 MB, ≤ 200 000 records |
| Photo inside a backup | ≤ 2 MB after decode, ≤ 64 megapixels |
| Name / note / tags | 120 chars / 2000 chars / 32 tags × 24 chars |
| Average price | 0 – 100 000 (`0` = free) |
| Network | listens on `127.0.0.1` only — no LAN or phone access by design |

---

## ❓ 10. FAQ

**Q1: The browser didn't open / the port is different every time**
The app prints the URL and saves it to `data/.last_port`. Open the printed URL manually, or force a fixed port with `PORT=31200 python -m app.main`.

**Q2: The map is blank but records load fine**
Basemap tiles need internet. Without an Amap key you'll also see a banner explaining that address search and routes are unavailable — that's expected, pins and filters still work.

**Q3: Address search says a key is required**
Search uses the **web-service** key (a different key type from the JS API key). Add it in Settings → Web service key. The JS key alone only loads the map.

**Q4: A photo won't upload**
Check the format (must be decodable by Pillow) and size (≤ 20 MB). Very large panoramas over 64 megapixels are rejected on purpose to avoid decompression bombs.

**Q5: Import finished with "written 0"**
That means every record in the file is the same age or older than your local copy — nothing was overwritten. The result also reports how many were counted as *already up to date*.

**Q6: Imported records lost their photos**
The backup was exported in `meta` mode (`photosIncluded: false`), which by design never touches existing photos. Export in `full` mode to include images.

**Q7: Nothing starts after moving the project / upgrading Python**
Run `setup.bat` (or `./setup.sh`) again — it rebuilds `venv`. `start.bat` will also fall back to the system interpreter and tell you what is missing.

**Q8: Can I open it from my phone or another PC?**
Not by design: the server binds `127.0.0.1` and rejects cross-origin requests, so your data never leaves the machine. To use it elsewhere, copy the `data/` folder.

**Q9: How do I wipe everything and start over?**
Stop the app, delete `data/` (or set `FOODMAP_DATA_DIR` to a fresh folder), start again. Back up first if you might want the data back.

**Q10: I see 100 "demo" records in the list**
They come from `seed_demo.py` and all carry a `demo-` id prefix. Remove them with `python seed_demo.py --clear --yes` (this also deletes their photos).

---

## 🛠 11. Development

- **Backend** — `app/main.py` holds routes and request models; `app/repository.py` is the only place that touches SQL; `app/validate.py` is shared by the write endpoints and the importer.
- **Frontend** — no bundler. Edit `static/js/app.js` / `static/index.html` / `static/css/style.css` and refresh; Vue is vendored in `static/lib/vue`.
- **Add a filter** — extend `list_records()` params → `repository.list()` → `_filterQuery()` / `_matchFilters()` in `app.js`; keep the API and the local preview counting identical.
- **Add a field** — `RecordIn` (with a validator) → `db.SCHEMA` + migration → `repository` read/write → form and detail templates → export/import payload.
- **Invariants worth keeping** (all covered by tests): `[min, max)` price buckets; drafts visible in both list and map through one scope; delete DB rows before deleting files; staged photo replacement on import; sort fields are whitelisted; `PUT` replaces everything; store photo paths with forward slashes.

Run the whole suite before committing — the pre-commit hook only guards data, not correctness:

```bash
tests\run-tests.bat      # Windows
python -m pytest tests -q && node tests/front-check.js
```

---

## 📄 License

Personal learning and use. No open-source licence file is bundled; add one if you plan to redistribute.
