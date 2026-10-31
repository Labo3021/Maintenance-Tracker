# Data

Owner: Kevin Koutang

Mock  DB JSON, test images, and manual PDFs.

## For the backend

Start the backend as usual. It seeds from `mock_inventory.json` with no code changes, as long as:

- It runs on Python 3.10 or newer (`backend/ai/manuals.py` won't import on 3.9).
- `backend/storage/` doesn't exist yet. If it does, delete it, or the old inventory is loaded instead.

The current `Asset` schema ignores the fields below, so the API won't return them until this patch is applied. Run it from the repo root:

```bash
git apply data/backend_fields.patch
```

| Field | Example |
|---|---|
| `severity` | `high` |
| `difficulty` | `easy` |
| `estimated_minutes` | `5` |
| `tools_needed` | `["Step Ladder"]` |
| `repair_steps` | `["Check the pressure gauge..."]` |
| `notes` | Free text |
| `video_url` | YouTube link |
| `purchase_url` | Store link |
| `image_url` | `/demo_assets/parts/task_406.jpg` |

The patch adds these fields to `AssetBase` and serves `data/demo_assets/` at `/demo_assets`. For the frontend, the image address is the API base URL plus `image_url`. It changes the shared schema, so agree on it with the team first. All 12 backend tests pass with and without it (tested on Python 3.12).

## Files

| File | Purpose | Edit by hand? |
|---|---|---|
| `items.json` | Source of truth for the 15 maintenance tasks | Yes |
| `tasks.json` | Schema example. Not used to build the inventory | Yes |
| `mock_inventory.json` | Generated file the backend seeds from | No |
| `demo_assets/parts/` | Part images, 800x800 JPEG, named by task ID | No |
| `demo_assets/parts/sources.json` | Where each image came from | Yes |
| `sources.md` | Where each maintenance frequency came from, and link checks | Yes |
| `backend_fields.patch` | Optional backend change described above | No |

## Updating the data

After editing `items.json`, rebuild the inventory:

```bash
python3 data/scripts/build_inventory.py
```

To add a task, give it a `task_<number>` ID, add its image to `sources.json`, and run these from the repo root:

```bash
pip install -r data/requirements.txt          # only needed for fetch_images.py
python3 data/scripts/fetch_images.py          # downloads and formats the images
python3 data/scripts/fetch_links.py --write   # finds links for tasks listed in the script
python3 data/scripts/build_inventory.py
python3 data/scripts/fetch_links.py --check   # tests every link
```

Delete `backend/storage/` afterward so the backend reseeds.

## How tasks become assets

| `items.json` | `mock_inventory.json` |
|---|---|
| `id` (`task_406`) | `id` (`asset-406`) |
| `title` | `name` |
| `category` | `category`, in lowercase |
| `itemModel` | `manufacturer` (first word), `model` (the rest), and `parts[0].name` |
| `installedDate` | `last_service_date` and `parts[0].installed_date` |
| `replaceEveryDays` | `service_interval_days` |

Each asset raises one alert, from its service interval. Its part has no `lifespan_days`, so it doesn't raise a second one.

## Image rights

The images are manufacturer and retailer product photos, kept for this demo. They aren't licensed for redistribution, so replace them or remove them from the repo if it's public or the project continues past the hackathon.
