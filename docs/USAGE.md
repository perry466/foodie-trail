# 🍜 Foodie Trail — Usage Guide (English)

> 📘 This guide is in English. Prefer 中文? → **[使用指南（中文）](./USAGE_zh.md)**
> 🏠 Back to **[README](../README.md)** · **[中文说明](../README_zh.md)**

This guide walks through the app screen by screen: where to click, what each field does, and what happens to your data.

---

## 🚀 1. Start it

```bash
# Windows: setup.bat  →  start.bat
# macOS/Linux: ./setup.sh  →  ./start.sh
```

The browser opens by itself at `http://127.0.0.1:<port>`. The port is random by default and remembered in `data/.last_port`; force one with `PORT=31200 python -m app.main`.

First launch creates `data/` with the database and a photo folder. Nothing leaves your machine.

> 🖥 **Installed / portable build**: if you downloaded a Release instead of the source, you don't need
> any of the above — double-click `FoodieTrail.exe` (or the desktop shortcut). No console appears; the
> app opens the browser and lives in the tray, with `data/` next to the exe. Same UI, same data format.

---

## 🧭 2. The three views

The top bar switches between **Map · List · Dashboard**, followed by search, **Add**, and **More**.

| View | What it's for |
| --- | --- |
| 🗺 **Map** | Browse spatially: clusters, pins colored by rating, hover previews |
| 📋 **List** | Filter, sort, compare, batch-delete |
| 📊 **Dashboard** | See your taste in aggregate, then drill into any chart |

---

## 🗺 3. Map

- **Pins** are colored by rating (grey ≤ 2, blue = 3, orange-red ≥ 4); zooming out merges nearby pins into clusters.
- **Hover** a pin or a list row → a small card shows name, stars, status, price and up to three tags. On the list side, hovering a card spotlights it on the map.
- **Click** a pin → opens the record detail and flies the map to it.
- **Click** a cluster → a popup lists the restaurants in that area (first 60); clicking a row opens its detail.
- **Right-click** the map (desktop) or **long-press** (mobile) → opens the add form with those coordinates already filled in.
- **Locate me** (in the add form) asks the browser for your position, converts WGS-84 → GCJ-02 on the backend, and drops a temporary marker.

> No Amap key? You get Leaflet with Amap raster tiles and a banner saying address search is unavailable. Pins, filters and editing work the same.

---

## 📋 4. List

- **Search box** — matches name, note and tags; debounced by 250 ms.
- **Filter bar** — status chips, sort, a filter button with a count badge, and removable chips for every active condition.
- **Sort** — last updated / highest rated / lowest price / name.
- **Scroll to load** — 60 records per batch, appended as you approach the bottom; 1 000 records never hit the DOM at once.
- **Hover** a card → the pin preview appears on the map (the map does not move, so it never fights your cursor).
- **Multi-select** — enter select mode from *More*, then *select all* (current filtered result, not just the visible 60), *invert*, or *clear*; **delete** removes the selection in one request.
- **Keyboard** — `↑`/`↓` move the highlight, `Enter` opens the record, `Esc` closes the list.

---

## 📊 5. Dashboard

Twelve aggregates in one screen: total records, visited rate, pending places, average & median price, status split, rating distribution, price buckets, top tags, a 12-month trend, photo coverage, data-quality hints, and two "what to eat next" lists.

**Every chart is a filter.** Click:

| Chart | Result |
| --- | --- |
| Status slice | list filtered to that status |
| A star bar | exact star range (4★ means 4, not ≥ 4) |
| A price bucket | that bucket, upper bound exclusive |
| A tag bar | that single tag |
| A record in the action list | its detail |

Drilling clears any leftover keyword / tag / draft / viewport filters first, and switches the draft scope to *exclude drafts* — because the dashboard itself never counts drafts. That keeps "4★ = 42" consistent with what you see after clicking.

---

## ➕ 6. Add / edit a record

### 6.1 Required

- **Name** and **location**. Location can come from: clicking the map in pick mode, right-click / long-press, address search, or *locate me*. Coordinates `0,0` are accepted as a real place.

### 6.2 Optional (under "more")

| Field | Notes |
| --- | --- |
| Stars | 1–5, drives pin color |
| Tags | type + `Enter`; up to 32, 24 chars each; duplicates ignored |
| Opening hours | per weekday, up to 6 slots per day; empty = closed; the editor writes a structured JSON |
| Average price | integer, `0` means free (not "unknown") |
| Status | want / visited / favourite |
| Note | free text |
| Photos | up to 9; pick several at once |

### 6.3 Photos

Each image is EXIF-rotated, resized so the long edge is 1280 px, and re-encoded as JPEG (quality 82, stepped down to 30 until ≤ 500 KB). The original file is not kept — this is a personal journal, not an archive.

### 6.4 Saving and failure handling

- The form validates locally first (name, location, photo count) and shows the reason inline.
- Saving is a single request for the record, then one request per photo. **If a photo fails, the record stays saved, the failed photo stays in the form, and the form does not close** — press save again to retry just that photo.
- Removing an existing photo marks it for deletion; if that delete fails it stays in the list so you can retry, instead of silently keeping a photo you thought you removed.
- New records get a toast with **"Add another"** so a food crawl doesn't need extra clicks.

### 6.5 Drafts

- Ticking *Save as draft* keeps the record out of the dashboard and behind a badge in the list.
- The add form also autosaves unfinished input to `localStorage` (debounced 400 ms); closing the tab and reopening restores it, including a note about how many photos need re-picking.
- Draft visibility is one setting with three states: **all / hide / only**, applied identically to the list and the map.

---

## 🍽 7. Record detail

- Opens as a card anchored above the map; the list scrolls the matching row into view.
- **Status segmented control** — want / visited / favourite. One tap saves immediately (optimistically, rolled back on failure).
- **Navigate** opens Amap's marker page in a new tab (works without any key).
- **Edit** loads the full record first (the list only carries a cover thumbnail) so photos never appear to vanish.
- **Photos** open a lightbox: `←` / `→` to page, `Esc` to close, click the backdrop to dismiss.
- **Delete** asks for confirmation, then removes the record and its photo files.

---

## 🔍 8. Filters in depth

| Condition | Semantics |
| --- | --- |
| Keyword | name / note / tags, `%` and `_` treated literally |
| Stars | exact range when you pick 4–4; "≥ N" when only the lower bound is set |
| Price | `<30`, `30–60`, `60–100`, `100–200`, `≥200`; **lower bound inclusive, upper exclusive** |
| Tags | match **all** (default) or **any** |
| Status | want / visited / favourite |
| Viewport | only what's currently on screen; the bounds refresh when you pan or zoom |
| Drafts | all / hide / only |

Details worth knowing:

- The filter panel is a **draft**: changes only update a local copy and show "N places match" as an estimate; nothing is fetched until you press **Apply**.
- Applied conditions appear as chips; each chip can be removed individually, and *Clear all* resets everything including the keyword.
- Conditions are written to the URL (`?rating=4&tags=火锅&drafts=hide`), so refresh, bookmarks and back/forward all preserve the state.
- `Esc` closes the topmost layer (confirm dialog → map picker → select mode → filter panel → detail → list) and keeps the URL in sync.

---

## 💾 9. Export / import

### 9.1 Export

*More → Export backup*. Two JSON flavours are produced by the backend:

| Mode | Photos | When to use |
| --- | --- | --- |
| `full` | inline base64 | real backup, moving machines |
| `meta` | none, `photosIncluded: false` | data-only dump |

Drafts are included, and the current filters still apply — clear the search box and filters first if you want everything.

### 9.2 Import

1. **Choose the file** → the backend validates it and returns a preview: *add N, update M, invalid K*.
2. **Confirm** → writes with a live progress bar (upload stage is indeterminate, then 60 %→100 % by record count).
3. Result line reports: written, **already up to date**, failed, invalid, skipped photos, kept photos, renamed ids.

Safety rules built in:

- Each record is written in its own transaction; a failure is counted and the batch continues.
- Photos inside the backup are decoded, size- and pixel-checked, then re-encoded **before** the database is touched. If any photo in a record is bad, the record keeps its existing photos.
- A backup that carries no photos (`meta`) never clears photos already in the database.
- Records with an older `updatedAt` are skipped and reported — "written 0" is a legitimate result, not an error.
- Ids that cannot live in a URL (`a/b`, spaces) are rebuilt deterministically, so importing the same file twice does not duplicate records.

---

## ⚙️ 10. Settings

*More → Settings* manages the optional Amap integration:

| Field | Purpose |
| --- | --- |
| JS API key + security code | browser map SDK |
| Web-service key | backend proxy: POI search, geocoding, driving route |

- Saved values come back masked; leaving a field empty keeps the stored value.
- *Test connection* asks Amap whether the stored keys are valid.
- *Clear security code* removes only `securityJsCode`; *Clear all* removes every key. Both ask for confirmation.
- Saving a key reloads the page, because the map SDK can only be initialised once per page load.

### 10.1 Checking for updates

*More → Settings → ④ About & updates* shows the current version, how this copy was installed, and whether a newer release exists.

- **Auto check on start** is on by default. It asks GitHub once per launch (cached for 30 minutes) and shows a non-blocking bar under the toolbar when a new version exists. *✕* on that bar ignores the version until the next one is released.
- The check sends your IP address to GitHub. Turn the switch off if that matters to you; manual *Check for updates* still works.
- The bar never interrupts: if GitHub is unreachable you get one grey line in Settings, nothing else. Nothing is shown at startup.
- Networking tries a **direct connection first, then the Windows system proxy** (read from the registry, not just environment variables), whichever works. Direct-only fails on networks that can only leave through a proxy (corporate or campus networks); proxy-only makes `api.github.com` return 403 quite often, because the proxy exit is a shared IP whose 60/hour quota other people consume. Set `FOODMAP_UPDATE_NO_PROXY=1` to force direct when a corporate proxy intercepts.

**Installer build** — *Download and install* fetches the `setup.exe` in the background, verifies its size and SHA-256 from the release metadata, then quits the app, runs the installer silently, and reopens it. `data/` is never touched. The installer is unsigned, so Windows SmartScreen may ask once: *More info → Run anyway*. A failed download retries over the other network path; if both fail, use *Copy download link* and fetch the file with a browser or download manager.

**Portable / source build** — auto-install is disabled on purpose: running `setup.exe` there would install a **second copy** under `%LOCALAPPDATA%` instead of upgrading the one you are using. You get *Go to release page* instead; unzip over `FoodieTrail.exe` and `_internal\`, and never overwrite `data\`.

---

## ⌨️ 11. Keyboard shortcuts

| Key | Action |
| --- | --- |
| `n` | New record |
| `/` | Focus search |
| `f` | Open list + filter panel |
| `↑` `↓` | Move through the list |
| `Enter` | Open the highlighted record |
| `→` `←` | Next / previous photo (lightbox open) |
| `Esc` | Step back one layer, close the lightbox, cancel pick mode |

Shortcuts are ignored while typing in an input.

---

## 🩺 12. Keeping your data healthy

```bash
python health_check.py          # read-only report
python health_check.py --deep   # also decodes every JPEG
```

It checks SQLite integrity, the schema, field ranges, missing or empty photo files, orphan files, the encryption key, the WAL size, and whether demo data is present. Exit code 0 = no fatal problem, 1 = something needs attention.

Before any bulk change, copy `data/` somewhere safe — that single folder is the whole app.

---

## ❓ 13. FAQ

**The map is blank.** Basemap tiles need internet; without an Amap key address search is unavailable by design.

**Address search is disabled.** That feature needs the *web-service* key, which is a different key type from the JS API key.

**A record disappeared.** Check the active chips — search, tag, status, viewport and draft filters combine. `Esc` or *Clear all* resets them. The URL shows exactly which filters are on.

**Editing changed fields I didn't touch.** The update API replaces the whole record; the UI always sends every field, so this only affects hand-written scripts. Use `GET` → modify → `PUT`.

**Photos look softer than the original.** By design: long edge 1280 px, ≤ 500 KB. Raise `PHOTO_MAX_EDGE` / `PHOTO_QUALITY` in `app/pathconf.py` before importing if you want more detail.

**The dashboard count differs from the list.** The dashboard never counts drafts; the list follows your draft scope. Drilling from a chart sets the scope to *exclude drafts* so the numbers match.
