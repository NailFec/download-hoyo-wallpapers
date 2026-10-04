#!/usr/bin/env python3
"""Download HoYoverse wallpaper zips and extract images named like 2560x1440.

Add links to links.txt, or pass them on the command line:

    python download.py
    python download.py https://hoyo.link/xxxxxxxx
    python download.py --title "Series Title" https://hoyo.link/xxxxxxxx
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
LINKS_FILE = ROOT / "links.txt"
MANIFEST_FILE = ROOT / "manifest.json"
ZIP_DIR = ROOT / "wallpapers"
IMG_DIR = ROOT / "2560x1440"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
REDIRECT_CODES = {301, 302, 303, 307, 308}
TARGET_IMAGE = re.compile(r"2560.+1440.+", re.IGNORECASE)

# Original posts, newest first. These seed links.txt the first time it is created.
ITEMS: list[tuple[str, str]] = [
    ("k4b2Cvwwm", "Everwinter Without Mercy"),
    ("SoTJzSTJH", "Sunny Summer Fontinalia"),
    ("5wzzwcszc", "Truth Amongst the Pages of Purana"),
    ("TJVFWWJzg", "Augured Homecoming"),
    ("1cMAfYot9", "Homeward, He Who Caught the Wind"),
    ("H5QjKg84Z", "A Traveler on a Winter's Night"),
    ("a7fOcP5k6", "A Nocturne of the Far North"),
    ("Cj9lcvs9p", "An Elegy for Faded Moonlight"),
    ("6gXO9zSm0", "A Dance of Snowy Tides and Hoarfrost Groves"),
    ("9cyuJ5jqq", "Sunspray Summer Resort"),
    ("291QJR0SS", "A Space and Time for You"),
    ("BGiaGoiD9", "Paralogism"),
    ("fYaLsFQK4", "Day of the Flame's Return"),
    ("HlZHg6tN2", "Moonlight Amidst Dreams"),
    ("QCHHmvq4v", "Incandescent Ode of Resurrection"),
    ("fW3lFBAL", "Tapestry of Spirit and Flame"),
    ("1PGlFBAL", "The Rainbow Destined to Burn"),
    ("cTgkFBAL", "Flowers Resplendent on the Sun-Scorched Sojourn"),
    ("eWLkFBAL", "Summertide Scales and Tales"),
    ("7c6jFBAL", "An Everlasting Dream Intertwined"),
    ("dWmiFBAL", "Two Worlds Aflame, the Crimson Night Fades"),
    ("7oyhFBAL", "Blades Weaving Betwixt Brocade"),
    ("adLhFBAL", "Vibrant Harriers Aloft in Spring Breeze"),
    ("0yPgFBAL", "Roses and Muskets"),
    ("6MbfFBAL", "Masquerade of the Guilty"),
    ("73reFBAL", "To the Stars Shining in the Depths"),
    ("brAeFBAL", "As Light Rain Falls Without Reason"),
    ("7dTEDBAd", "Duel! The Summoners' Summit!"),
    ("5dpjCEAd", "A Parade of Providence"),
    ("9cmWCBAd", "Windblume's Breath"),
    ("59ZlBBAd", "All Senses Clear, All Existence Void"),
    ("d568jBA6", "Summer Fantasia"),
]


@dataclass(frozen=True)
class Link:
    url: str
    title: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def safe_name(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned


def strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1].strip()
    return text


def normalize_url(raw: str) -> str:
    text = raw.strip().strip("<>").strip()
    if re.fullmatch(r"hoyo\.link/\S+", text):
        text = "https://" + text
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"not a link: {raw}")
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunparse(parsed._replace(path=path, fragment=""))


def slug_of(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    return safe_name(path.rsplit("/", 1)[-1]) or "wallpaper"


def default_links_text() -> str:
    header = """\
# One short link per line.
# An optional series title after the URL is used in the filenames.
# Blank lines and lines starting with # are ignored.
#
#   https://hoyo.link/xxxxxxxx Series Title
#
# Fetch every link in this file:
#   python download.py
#
"""
    body = "\n".join(f"https://hoyo.link/{slug} {title}" for slug, title in ITEMS)
    return header + body + "\n"


def write_default_links(path: Path | None = None) -> None:
    (path or LINKS_FILE).write_text(default_links_text(), encoding="utf-8")


def format_link(link: Link) -> str:
    if link.title:
        return f"{link.url} {link.title}"
    return link.url


def parse_link_lines(lines: list[str]) -> list[tuple[int, Link]]:
    entries: list[tuple[int, Link]] = []
    for number, line in enumerate(lines, start=1):
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        token, _, title = body.partition(" ")
        try:
            url = normalize_url(token)
        except ValueError as exc:
            raise ValueError(f"links.txt:{number}: {exc}") from exc
        entries.append((number, Link(url, strip_quotes(title.strip()))))
    return entries


def add_urls(
    lines: list[str],
    entries: list[tuple[int, Link]],
    urls: list[str],
    title: str,
) -> tuple[list[str], list[Link], bool]:
    by_url = {link.url: (number, link) for number, link in entries}
    chosen = strip_quotes(title.strip()) if title else ""
    to_process: list[Link] = []
    changed = False
    seen: set[str] = set()
    for raw in urls:
        url = normalize_url(raw)
        if url in seen:
            continue
        seen.add(url)
        if url in by_url:
            number, current = by_url[url]
            if chosen and chosen != current.title:
                current = Link(url, chosen)
                lines[number - 1] = format_link(current)
                by_url[url] = (number, current)
                changed = True
            to_process.append(current)
            continue
        created = Link(url, chosen)
        lines.append(format_link(created))
        by_url[url] = (len(lines), created)
        to_process.append(created)
        changed = True
    return lines, to_process, changed


def is_zip_file(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 4:
        return False
    with path.open("rb") as handle:
        return handle.read(2) == b"PK"


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0xD9):
            index += 2
            continue
        if index + 4 > len(data):
            return None
        segment_length = int.from_bytes(data[index + 2 : index + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2) and index + 9 <= len(data):
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        if segment_length < 2:
            return None
        index += 2 + segment_length
    return None


def resolve(url: str) -> str:
    """Follow short-link redirects until the response is a zip."""
    current = url
    for _ in range(10):
        request = urllib.request.Request(current, headers={"User-Agent": UA})
        try:
            with OPENER.open(request, timeout=60) as response:
                final = response.geturl()
                content_type = response.headers.get("Content-Type", "")
                if "zip" in content_type.lower() or final.lower().split("?", 1)[0].endswith(".zip"):
                    return final
                raise RuntimeError(
                    f"unexpected response {response.status} {content_type} for {final}"
                )
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code in REDIRECT_CODES and location:
                current = urllib.parse.urljoin(current, location)
                continue
            raise RuntimeError(f"HTTP {exc.code} for {current}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"could not open {current}: {exc.reason}") from exc
    raise RuntimeError(f"too many redirects for {url}")


def dest_for(final_url: str, title: str) -> Path:
    match = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", final_url)
    date = f"{match.group(1)}-{match.group(2)}-{match.group(3)} " if match else ""
    label = safe_name(title) if title else slug_of(final_url)
    return ZIP_DIR / f"{date}{label}.zip"


def download_zip(final_url: str, path: Path) -> None:
    partial = path.with_suffix(path.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(final_url, headers={"User-Agent": UA})
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} downloading zip") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not download zip: {exc.reason}") from exc
    with response:
        expected = int(response.headers.get("Content-Length") or 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with partial.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
    if expected and written != expected:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"short read {written}/{expected}")
    with partial.open("rb") as handle:
        magic = handle.read(2)
    if magic != b"PK":
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"download is not a zip (magic {magic!r})")
    partial.replace(path)


def target_members(names: list[str]) -> list[str]:
    found: list[str] = []
    for name in names:
        if name.endswith("/"):
            continue
        base = PurePosixPath(name.replace("\\", "/")).name
        if TARGET_IMAGE.fullmatch(base):
            found.append(name)
    return found


def variant_of(member: str) -> str:
    parent = PurePosixPath(member.replace("\\", "/")).parent.name
    if not parent or parent.lower() == "wallpaper":
        return ""
    return safe_name(parent)


def image_name(zip_path: Path, variant: str, suffix: str) -> str:
    if variant:
        return f"{zip_path.stem} - {variant}{suffix}"
    return f"{zip_path.stem}{suffix}"


def extract_images(zip_path: Path) -> tuple[list[Path], int, int, list[str]]:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    images: list[Path] = []
    wrote = 0
    skipped = 0
    used: set[Path] = set()
    with zipfile.ZipFile(zip_path) as archive:
        members = target_members(archive.namelist())
        if not members:
            return [], 0, 0, ["no image matching 2560.+1440.+"]
        for member in members:
            variant = variant_of(member)
            member_path = PurePosixPath(member.replace("\\", "/"))
            suffix = member_path.suffix or ".img"
            destination = IMG_DIR / image_name(zip_path, variant, suffix)
            copy = 2
            while destination in used:
                extra = f"{variant}-{copy}" if variant else str(copy)
                destination = IMG_DIR / image_name(zip_path, extra, suffix)
                copy += 1
            used.add(destination)
            if destination.is_file() and destination.stat().st_size > 0:
                images.append(destination)
                skipped += 1
                continue
            data = archive.read(member)
            destination.write_bytes(data)
            if data.startswith(b"\xff\xd8"):
                size = jpeg_size(data)
                if size is not None and size != (2560, 1440):
                    notes.append(f"{destination.name} is {size[0]}x{size[1]}")
            images.append(destination)
            wrote += 1
    return images, wrote, skipped, notes


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def load_manifest() -> dict:
    if not MANIFEST_FILE.exists():
        return {}
    try:
        data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_manifest(manifest: dict) -> None:
    payload = {key: manifest[key] for key in sorted(manifest)}
    temporary = MANIFEST_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(MANIFEST_FILE)


def status_line(link: Link, zip_path: Path, zip_word: str, wrote: int, skipped: int, notes: list[str]) -> str:
    label = link.title or link.url
    size = zip_path.stat().st_size / 1024 / 1024
    text = (
        f"ok    {label}  zip {zip_word} ({size:.1f} MB), "
        f"images {wrote + skipped} ({wrote} saved, {skipped} kept)"
    )
    if notes:
        text += f"  [{'; '.join(notes)}]"
    return text


def process(link: Link, manifest: dict, lock: threading.Lock) -> str:
    with lock:
        record = dict(manifest.get(link.url) or {})
    final_url = record.get("final_url") or ""
    remembered = ROOT / record["zip"] if record.get("zip") else None
    if remembered and is_zip_file(remembered):
        zip_path = remembered
        zip_word = "kept"
    else:
        final_url = final_url or resolve(link.url)
        zip_path = dest_for(final_url, link.title or slug_of(link.url))
        zip_word = "kept"
        if not is_zip_file(zip_path):
            download_zip(final_url, zip_path)
            zip_word = "saved"
    images, wrote, skipped, notes = extract_images(zip_path)
    updated = {
        "title": link.title,
        "final_url": final_url,
        "zip": relative(zip_path),
        "images": [relative(image) for image in images],
    }
    with lock:
        manifest[link.url] = updated
        save_manifest(manifest)
    return status_line(link, zip_path, zip_word, wrote, skipped, notes), wrote + skipped


def run(links: list[Link]) -> int:
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    lock = threading.Lock()
    failures: list[str] = []
    total_images = 0
    print(f"Fetching {len(links)} link(s).", flush=True)
    with ThreadPoolExecutor(max_workers=min(4, len(links))) as pool:
        futures = {pool.submit(process, link, manifest, lock): link for link in links}
        for future in as_completed(futures):
            link = futures[future]
            try:
                line, count = future.result()
                total_images += count
                print(line, flush=True)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{link.url}: {exc}")
                print(f"FAIL  {link.url}: {exc}", flush=True)
    print(f"\n{total_images} images.", flush=True)
    if failures:
        print(f"{len(failures)} failed.", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download wallpaper zips from short links and extract images matching 2560.+1440.+.",
        epilog=(
            "examples:\n"
            "  python download.py\n"
            "  python download.py https://hoyo.link/xxxxxxxx\n"
            "  python download.py --title \"Series Title\" https://hoyo.link/xxxxxxxx\n"
            "\n"
            "Links are stored in links.txt. See README.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="*", help="short link(s) to add, then download and extract")
    parser.add_argument("--title", help="series title for a single URL, used in the saved filenames")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.title is not None and len(args.urls) != 1:
        print("error: --title needs exactly one URL", file=sys.stderr)
        return 2
    if not LINKS_FILE.exists():
        write_default_links()
    lines = LINKS_FILE.read_text(encoding="utf-8").splitlines()
    try:
        entries = parse_link_lines(lines)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.urls:
        try:
            lines, selected, changed = add_urls(lines, entries, args.urls, args.title or "")
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        if changed:
            LINKS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        selected = [link for _, link in entries]
    if not selected:
        print("No links in links.txt.", file=sys.stderr)
        return 1
    return run(selected)


if __name__ == "__main__":
    raise SystemExit(main())
