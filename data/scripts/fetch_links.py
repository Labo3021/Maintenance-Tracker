#!/usr/bin/env python3
"""Find real videos and purchase links for data/items.json and check every link in it.

Uses only the standard library and needs no API key.

    python3 data/scripts/fetch_links.py            # show the best links for each task
    python3 data/scripts/fetch_links.py --write    # fill in links that don't work yet
    python3 data/scripts/fetch_links.py --check    # test every videoURL and purchaseURL
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ITEMS_PATH = Path(__file__).resolve().parents[1] / "items.json"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
MAX_VIDEO_MINUTES = 25
# These sites refuse all scripts, so a failed check says nothing about the link.
BLOCKS_SCRIPTS = {"www.dyson.com"}

# Search phrase, plus word groups the video title must match. Each group is a list of
# alternatives, so [["vent"], ["clean", "cleaning"]] means vent AND (clean OR cleaning).
VIDEO_SEARCHES = {
    "task_202": ("how to change 9V battery smoke detector", [["smoke"], ["battery", "batteries"]]),
    "task_303": ("how to clean Bosch dishwasher filter", [["bosch"], ["filter"]]),
    "task_401": ("how to replace Samsung DA29-00020B HAF-CIN water filter",
                 [["samsung"], ["filter"]]),
    "task_402": ("how to clean dryer vent with brush kit", [["dryer"], ["vent"]]),
    "task_403": ("how to test a sump pump", [["sump"], ["test", "testing", "check"]]),
    "task_404": ("how to add salt to water softener", [["softener"], ["salt"]]),
    "task_405": ("Lowe's how to clean an air conditioner",
                 [["condenser", "ac", "air conditioner"], ["clean", "cleaning"]]),
    "task_406": ("how to inspect home fire extinguisher", [["extinguisher"], ["inspect", "inspection", "check"]]),
    "task_407": ("This Old House how to clean gutters", [["gutter", "gutters"], ["clean", "cleaning"]]),
    "task_408": ("how to replace toilet flapper Korky", [["flapper"], ["replace", "replacing", "install", "change"]]),
    "task_409": ("how to wash Dyson V11 filter", [["dyson"], ["filter"]]),
    "task_410": ("how to change batteries August Wi-Fi Smart Lock", [["august"], ["battery", "batteries"]]),
    "task_411": ("how to clean refrigerator condenser coils", [["refrigerator", "fridge"], ["coil", "coils"]]),
    "task_412": ("fix squeaky door hinge silicone lubricant", [["hinge", "hinges", "squeaky door"]]),
    "task_413": ("how to flush tank water heater sediment", [["water heater"], ["flush", "flushing", "drain"]]),
}

# Same idea for Amazon. The word groups must match the product title. task_303 and
# task_409 aren't here because they link to the genuine part on the manufacturer's site.
PURCHASE_SEARCHES = {
    "task_202": ("Energizer MAX 9V batteries 4 pack", [["energizer"], ["9v"], ["4 pack"]]),
    "task_401": ("Samsung HAF-CIN/EXP genuine water filter", [["samsung"], ["genuine"], ["haf-cin"]]),
    "task_402": ("dryer vent cleaning brush kit", [["dryer"], ["vent"], ["brush", "cleaner", "cleaning"]]),
    "task_403": ("Zoeller M53 Mighty-Mate submersible sump pump", [["zoeller"], ["m53"], ["sump pump"]]),
    "task_404": ("Morton Clean and Protect water softener salt pellets", [["morton"], ["salt", "pellets"]]),
    "task_405": ("air conditioner condenser coil cleaning brush", [["coil", "condenser", "fin"], ["brush", "comb"]]),
    "task_406": ("Kidde fire extinguisher Pro 210", [["kidde"], ["pro 210"]]),
    "task_407": ("gutter cleaning scoop", [["gutter"], ["scoop"]]),
    "task_408": ("Korky Ultra universal flapper", [["korky"], ["universal"], ["flapper"]]),
    "task_410": ("CR123A lithium batteries", [["cr123", "cr123a"], ["lithium"]]),
    "task_411": ("refrigerator condenser coil brush", [["coil"], ["brush"]]),
    "task_412": ("WD-40 Specialist Silicone", [["wd-40"], ["silicone"]]),
    "task_413": ("water heater flushing tool", [["water heater"], ["flushing", "flush"], ["tool", "kit"]]),
}


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "replace")


def walk(node):
    if isinstance(node, dict):
        if "videoRenderer" in node:
            yield node["videoRenderer"]
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def search_youtube(query):
    # YouTube sometimes answers in a layout this parser can't read, so try a few times.
    for attempt in range(4):
        page = fetch("https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query}))
        marker = page.find("var ytInitialData = ")
        if marker != -1:
            data, _ = json.JSONDecoder().raw_decode(page, marker + len("var ytInitialData = "))
            videos = [{
                "id": renderer.get("videoId"),
                "title": "".join(run.get("text", "") for run in renderer.get("title", {}).get("runs", [])),
                "channel": "".join(run.get("text", "") for run in renderer.get("ownerText", {}).get("runs", [])),
                "length": renderer.get("lengthText", {}).get("simpleText", ""),
            } for renderer in walk(data)]
            if videos:
                return videos
        time.sleep(1 + attempt)
    return []


def search_amazon(query):
    # Amazon serves an empty page when it rate-limits, so back off and try again.
    tag = re.compile(r'<div[^>]*data-asin="([A-Z0-9]{10})"[^>]*data-component-type="s-search-result"[^>]*>')
    matches = []
    for attempt in range(5):
        page = fetch("https://www.amazon.com/s?" + urllib.parse.urlencode({"k": query}))
        matches = list(tag.finditer(page))
        if matches:
            break
        time.sleep(5 * (attempt + 1))
    products = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page)
        block = page[match.start():end]
        if "AdHolder" in match.group(0) or "Sponsored" in block:
            continue
        # Amazon puts the brand and the product name in separate headings.
        headings = [re.sub(r"<[^>]+>", "", text).strip() for text in re.findall(r"<h2[^>]*>(.*?)</h2>", block, re.S)]
        if headings:
            products.append({"asin": match.group(1), "title": html.unescape(" ".join(headings))})
    return products


def minutes(length):
    parts = [int(part) for part in length.split(":")] if length else []
    if not 2 <= len(parts) <= 3:
        return None
    return parts[0] * 60 + parts[1] if len(parts) == 3 else parts[0]


def title_matches(title, groups):
    title = title.lower()
    return all(
        any(re.search(r"\b" + re.escape(word) + r"\b", title) for word in group)
        for group in groups
    )


def pick_video(query, groups):
    for video in search_youtube(query):
        length = minutes(video["length"])
        if length is None or length >= MAX_VIDEO_MINUTES:
            continue
        if title_matches(video["title"], groups):
            return video
    return None


def pick_product(query, groups):
    for product in search_amazon(query):
        if title_matches(product["title"], groups):
            return product
    return None


def video_exists(url):
    """oEmbed returns 200 only for a real, embeddable video."""
    try:
        fetch("https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": url, "format": "json"}))
        return True
    except urllib.error.HTTPError:
        return False


def link_status(url):
    # Amazon returns 503 at random to automated requests, so only trust a repeated answer.
    status = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status
        except urllib.error.HTTPError as error:
            status = error.code
        except urllib.error.URLError as error:
            status = str(error.reason)
        if status != 503:
            break
        time.sleep(2 + attempt)
    return status


def replace_field(text, task_id, field, value):
    """Change one field in place, so the file's hand formatting is kept."""
    start = text.index(f'"id": "{task_id}"')
    pattern = re.compile(rf'"{field}": (null|"[^"]*")')
    match = pattern.search(text, start)
    return text[:match.start()] + f'"{field}": {json.dumps(value)}' + text[match.end():]


def find_links(tasks, write):
    text = ITEMS_PATH.read_text()
    for task in tasks:
        task_id = task["id"]
        current = task.get("videoURL")
        if write and current and video_exists(current):
            print(f"{task_id} video: keeping {current}")
        elif task_id in VIDEO_SEARCHES:
            video = pick_video(*VIDEO_SEARCHES[task_id])
            url = f"https://www.youtube.com/watch?v={video['id']}" if video else None
            if url and video_exists(url):
                print(f"{task_id} video: {url} [{video['length']}] {video['title']} ({video['channel']})")
                if write:
                    text = replace_field(text, task_id, "videoURL", url)
            else:
                print(f"{task_id} video: NO MATCH")

        current = task.get("purchaseURL")
        if write and current and link_status(current) == 200:
            print(f"{task_id} purchase: keeping {current}")
        elif task_id in PURCHASE_SEARCHES:
            product = pick_product(*PURCHASE_SEARCHES[task_id])
            url = f"https://www.amazon.com/dp/{product['asin']}" if product else None
            if url and link_status(url) == 200:
                print(f"{task_id} purchase: {url} {product['title']}")
                if write:
                    text = replace_field(text, task_id, "purchaseURL", url)
            else:
                print(f"{task_id} purchase: NO MATCH")
    if write:
        ITEMS_PATH.write_text(text)


def check_links(tasks):
    failed = 0
    for task in tasks:
        video, purchase = task.get("videoURL"), task.get("purchaseURL")
        if video:
            ok = video_exists(video)
            failed += not ok
            print(f"{task['id']} video    {'ok' if ok else 'FAILED'} {video}")
        if purchase and urllib.parse.urlparse(purchase).netloc in BLOCKS_SCRIPTS:
            print(f"{task['id']} purchase unconfirmed (site blocks scripts) {purchase}")
        elif purchase:
            status = link_status(purchase)
            ok = status == 200
            failed += not ok
            print(f"{task['id']} purchase {'ok' if ok else f'FAILED ({status})'} {purchase}")
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="save found links to items.json")
    parser.add_argument("--check", action="store_true", help="test every link in items.json")
    args = parser.parse_args()

    tasks = json.loads(ITEMS_PATH.read_text())
    if args.check:
        sys.exit(1 if check_links(tasks) else 0)
    find_links(tasks, args.write)


if __name__ == "__main__":
    main()
