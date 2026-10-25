"""Public article discovery, extraction and bounded image downloads."""
import argparse
import concurrent.futures
import hashlib
import io
import json
import re
import socket
import ipaddress
import random
import math
import time
import threading
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode, quote

from bs4 import BeautifulSoup
from PIL import Image
from source_metadata import extract_metadata, extract_reading_body
from content_store import ContentIssue, RetryableFetchError, atomic_write, save

OUT = Path(__file__).resolve().parent.parent / "data" / "sources"
AGENT = "Artfolio/0.1 (public article acquisition)"
FEEDS = {
    "teeth": ["https://www.teethmag.net/feed/"],
    "aperture": ["https://aperture.org/?feed=rss2"],
    "itsnicethat": ["https://feeds2.feedburner.com/itsnicethat/SlXC"],
    "c41": ["https://www.c41magazine.com/feed/"],
    "phroom": ["https://phroomplatform.com/feed/"],
}
POLICIES = {}
POLICY_LOCK = threading.Lock()
DEADLINE = float('inf')


def check_deadline():
    if time.monotonic() >= DEADLINE:
        raise RetryableFetchError('Run time budget reached; resume on the next run')


def inspect_image(raw):
    with Image.open(io.BytesIO(raw)) as photo:
        fmt, size = photo.format, photo.size
        if size[0] * size[1] > 40_000_000:
            raise ContentIssue('Image exceeds the 40 megapixel processing limit')
        if photo.getexif().get(274) in {5, 6, 7, 8}:
            size = size[::-1]
        frames = getattr(photo, 'n_frames', 1)
        photo.load()
    # PNG EXIF may load the image, so verify a freshly opened stream.
    with Image.open(io.BytesIO(raw)) as photo:
        photo.verify()
    return fmt, size, frames


def canonical(url):
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ""))


def check_target(url):
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Only public HTTPS targets accepted")
    addresses = {i[4][0] for i in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError("Non-public target rejected")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, robots=False):
        self.robots = robots

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_target(newurl)
        if self.robots:
            allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_url(url, limit=5_000_000, headers=None, robots=False):
    p = urlsplit(url)
    url = urlunsplit((p.scheme, p.netloc, quote(p.path, safe="/%:@+,-._~"),
                     quote(p.query, safe="=&%:+,/?@-._~"), ""))
    try:
        check_target(url)
    except OSError as error:
        raise RetryableFetchError('Target DNS resolution failed') from error
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept-Encoding": "identity", **(headers or {})})
    for attempt in range(3):
        check_deadline()
        try:
            with urllib.request.build_opener(SafeRedirect(robots)).open(req, timeout=25) as r:
                raw = r.read(limit + 1)
                if len(raw) > limit:
                    raise ContentIssue(f"Resource exceeds validation bound {limit}")
                return raw, {"url": url, "final_url": r.url, "status": r.status,
                    "content_type": r.headers.get("Content-Type", ""), "bytes": len(raw),
                    "etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified")}
        except urllib.error.HTTPError as error:
            if error.code == 304 and headers:
                error.close()
                return b"", {"status": 304, "final_url": error.url}
            if error.code not in {408, 429} and error.code < 500:
                error.close()
                raise
            retry_after = error.headers.get("Retry-After", "")
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    delay = 2 ** attempt
            if not math.isfinite(delay):
                delay = 2 ** attempt
            if delay > 60:
                error.close()
                raise RetryableFetchError('Server requested a longer Retry-After; deferred to next run', retry_after=delay) from error
            failure = error
            error.close()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            failure, delay = error, 2 ** attempt
        if attempt == 2:
            raise RetryableFetchError(str(failure)) from failure
        time.sleep(max(0, delay) + random.uniform(0, 0.5))


def allowed(url):
    p = urlsplit(url)
    origin = f"{p.scheme}://{p.netloc}"
    with POLICY_LOCK:
        if origin not in POLICIES:
            robot_url = origin + "/robots.txt"
            try:
                raw, meta = read_url(robot_url)
                body = raw.decode("utf-8", "replace")
                policy = urllib.robotparser.RobotFileParser()
                # RFC 9309 2.3.1.5: keep parseable rules even if other lines contain HTML.
                policy.parse(body.splitlines())
                POLICIES[origin] = (policy, {**meta, "text": body})
                if re.search(r"<html|<!doctype", body, re.I):
                    POLICIES[origin][1]["format_warning"] = "HTML in robots response; parsed directive lines per RFC 9309 2.3.1.5"
            except urllib.error.HTTPError as e:
                if not (400 <= e.code < 500 and e.code != 429):
                    raise
                # RFC 9309 2.3.1.3: unavailable robots is distinct from a denied image request.
                POLICIES[origin] = (None, {"url": robot_url, "status": e.code, "interpretation": "robots unavailable, ordinary public resource requests may proceed"})
        policy, _ = POLICIES[origin]
    if policy and not policy.can_fetch(AGENT, url):
        raise ValueError("robots disallows this target; no bypass attempted")


def public_read(url, limit=5_000_000, headers=None):
    allowed(url)
    raw, meta = read_url(url, limit, headers=headers, robots=True)
    # Fixed source targets only; check the returned CDN origin before retaining its data.
    allowed(meta["final_url"])
    return raw, meta


def feed_items(raw):
    try:
        root = ET.fromstring(raw.decode("utf-8-sig").lstrip())
    except (ET.ParseError, UnicodeError) as error:
        raise ContentIssue('Feed is not valid RSS/Atom XML') from error
    result, invalid = [], 0
    for item in root.iter():
        if item.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        parts = {}
        for e in item:
            key = e.tag.split("}")[-1]
            if key == "link" and e.get("href") and e.get("rel", "alternate") == "alternate":
                parts["link"] = e.get("href")
            elif key == "author":
                parts["feed_author"] = " ".join(t.strip() for t in e.itertext() if t.strip())
            elif key == "category":
                parts.setdefault("terms", []).append(e.text or e.get("term", ""))
            elif key not in parts:
                parts[key] = e.text or ""
        link = parts.get("origLink") or parts.get("link")
        if not link:
            continue
        stamp = parts.get("published") or parts.get("pubDate") or parts.get("updated", "")
        try:
            try:
                when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                when = parsedate_to_datetime(stamp)
            if when.tzinfo is None:
                raise ValueError('Feed date has no timezone')
            when = when.astimezone(timezone.utc)
            target = urlsplit(link)
            if target.scheme != 'https' or not target.hostname or target.username or target.password:
                raise ValueError('Invalid feed article URL')
        except (ValueError, TypeError, OverflowError):
            invalid += 1
            continue
        # Full RSS HTML stays in the private feed file, not in the growing job ledger.
        entry = {key: parts[key] for key in ['title', 'terms', 'creator', 'feed_author', 'guid', 'id'] if key in parts}
        entry.update(url=canonical(link), published_at=when.isoformat(), sort_at=when.timestamp())
        result.append(entry)
    if invalid:
        # Never turn an unparseable feed item into a silent "no new articles" result.
        raise ContentIssue(f'Feed has {invalid} invalid URL/date entries')
    if not result:
        raise ContentIssue('Feed contains no dated public article entries')
    return sorted(result, key=lambda x: x["sort_at"], reverse=True)


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def content_links(node, base):
    result = []
    for a in node.select("a[href]") if node else []:
        url = urljoin(base, a["href"])
        if urlsplit(url).scheme in {"http", "https"} and not re.search(r"\.(?:jpe?g|png|gif|webp|avif)(?:\?|$)", url, re.I):
            value = {"label": text(a), "url": url}
            if value not in result:
                result.append(value)
    return result


def discover(name):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    evidence, all_items = [], []
    for i, feed in enumerate(FEEDS[name]):
        time.sleep(1)
        raw, meta = public_read(feed)
        (folder / f"feed-{i}.xml").write_bytes(raw)
        items = feed_items(raw)
        evidence.append({**meta, "items": len(items)})
        all_items.extend(items)
    sample = max(all_items, key=lambda x: x["sort_at"])
    time.sleep(1)
    raw, meta = public_read(sample["url"])
    (folder / "article.html").write_bytes(raw)
    (folder / "selected-feed-item.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    soup = BeautifulSoup(raw.decode("utf-8"), "html.parser")
    summary = {"site": name, "feed_evidence": evidence, "article_evidence": meta,
               "title": text(soup.find("h1")), "selected_url": sample["url"],
               "feed_published_at": sample["published_at"],
               "metadata": {m.get("name") or m.get("property"): m.get("content") for m in soup.find_all("meta") if m.get("name") or m.get("property")},
               "article_containers": [{"tag": e.name, "class": e.get("class"), "id": e.get("id"), "text_length": len(text(e)), "images": len(e.find_all("img"))}
                                      for e in soup.select("article, main, [itemprop='articleBody'], .entry-content")],
               "image_count_page": len(soup.find_all("img")),
               "structured_data": [text(e) or e.string for e in soup.select('script[type="application/ld+json"]')],
               "credit_context": [text(e)[:650] for e in soup.find_all(["p", "figcaption", "div", "span"]) if re.search(r"credit|byline|author|caption", " ".join(e.get("class", [])), re.I) and len(text(e)) < 2000]}
    (folder / "discovery.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {k: summary[k] for k in ["site", "selected_url", "title", "feed_published_at", "article_containers", "image_count_page"]}


def image_url(im, base):
    for attr in ["data-orig-file", "data-image"]:
        if im.get(attr):
            return urljoin(base, im[attr])
    a = im.find_parent("a")
    if a and re.search(r"\.(?:jpe?g|png|gif|webp|avif)(?:\?|$)", a.get("href", ""), re.I):
        return urljoin(base, a["href"])
    srcset = im.get("data-lazy-srcset") or im.get("data-srcset") or im.get("srcset", "")
    matches = re.findall(r"((?:https?://|/)[^\s]+)\s+(\d+(?:\.\d+)?)([wx])", srcset)
    if matches:
        return urljoin(base, max(matches, key=lambda x: float(x[1]))[0])
    return urljoin(base, im.get("data-lazy-src") or im.get("data-src") or im.get("src", ""))


def image_key(url):
    p = urlsplit(url)
    path = p.path
    if "/wp-content/uploads/" in path:
        path = "/wp-content/uploads/" + path.split("/wp-content/uploads/", 1)[1]
        path = re.sub(r"-\d+x\d+(?=\.[^.]+$)", "", path)
    return p.netloc.lower() + path


def image_record(im, scope, soup, base):
    url = image_url(im, base)
    if not url.startswith("https://") or im.get("alt") == "Pin It":
        return None
    if im.get("width") == "1" and im.get("height") == "1":
        return None
    if "arrow-up-phroom" in url:
        return None
    caption = ""
    described = im.get("aria-describedby")
    if described:
        caption = text(soup.find(id=described))
    if not caption:
        wrapper = im.find_parent(["figure", "dl"]) or im.find_parent(class_="wp-caption")
        if wrapper:
            caption = text(wrapper.select_one("figcaption,.wp-caption-text,.gallery-caption"))
    if not caption:
        wrapper = im.find_parent(class_=re.compile(r"^gutenberg-(?:left|right)-column(?:-image)?$"))
        if wrapper:
            caption = text(wrapper.select_one("figcaption"))
    if not caption:
        column = im.find_parent(class_="elementor-column")
        notes = column.select(".elementor-widget-text-editor") if column else []
        if len(notes) == 1 and 0 < len(text(notes[0])) < 300:
            caption = text(notes[0])
    return {"url": url, "alt": im.get("alt", ""), "caption": caption or im.get("data-image-caption", ""),
            "scope": scope, "identity": image_key(url)}


def extract(name):
    folder = OUT / name
    soup = BeautifulSoup((folder / "article.html").read_text(encoding="utf-8"), "html.parser")
    selected = json.loads((folder / "selected-feed-item.json").read_text(encoding="utf-8"))
    saved = json.loads((folder / "article.json").read_text(encoding="utf-8")) if (folder / "article.json").exists() else {}
    url = selected["url"]
    metadata = extract_metadata(name, soup, url)
    authors = metadata["authors"]
    credits = [{"scope": "article", **credit} for credit in metadata["credits"]]
    images = []
    selectors = {
        "teeth": ".article__right__body", "aperture": ".post-content-column", "itsnicethat": "article",
        "c41": ".post-content", "phroom": '[data-elementor-type="wp-post"]',
    }
    body = soup.select_one(selectors[name])
    if body is None:
        raise ContentIssue("Article body selector no longer matches")
    title = text(soup.select_one("h1")) or selected["title"]
    if name == "teeth":
        image_nodes = body.find_all("img")
    elif name == "aperture":
        image_nodes = soup.select(".banner-editorial img") + body.find_all("img")
    elif name == "itsnicethat":
        body = BeautifulSoup(str(body), "html.parser")
        for e in body.select(".module-cluster,.module-newsletter,.extra-detail,.fullscreen-article-header"):
            e.decompose()
        image_nodes = soup.select(".fullscreen-article-header img") + body.find_all("img")
    elif name == "c41":
        image_nodes = soup.select(".post-thumbnail img") + body.find_all("img")
    elif name == "phroom":
        image_nodes = body.find_all("img")
    seen = {}
    for im in image_nodes:
        rec = image_record(im, "article", soup, url)
        if not rec:
            continue
        if rec["identity"] not in seen:
            seen[rec["identity"]] = rec
        elif not seen[rec["identity"]]["caption"] and rec["caption"]:
            seen[rec["identity"]]["caption"] = rec["caption"]
    images = [{**r, "position": i + 1} for i, r in enumerate(seen.values())]
    for r in images:
        previous = next((old for old in saved.get("images", []) if old["identity"] == r["identity"] and old["url"] == r["url"]), {})
        for key in ["local_file", "sha256", "width", "height", "frames", "response", "verification", "error"]:
            if key in previous:
                r[key] = previous[key]
        if r["caption"] or r.get("credit"):
            credits.append({"scope": "image", "position": r["position"], "text": " ".join(filter(None, [r["caption"], r.get("credit")]))})
    clean = BeautifulSoup(str(body), "html.parser")
    for e in clean.select("script,style,noscript"):
        e.decompose()
    paragraphs = [text(e) for e in clean.select("p,h1,h2,h3,h4,li,figcaption")
                  if text(e) and not e.select("p,h1,h2,h3,h4,li,figcaption")]
    body_text = "\n\n".join(paragraphs)
    cleaned = extract_reading_body(name, soup, metadata, {r['caption'] for r in images if r.get('caption')})
    if not title.strip() or not images or len(images) > 100:
        raise ContentIssue('Missing title/images or unexpected gallery size')
    if name in {'aperture', 'itsnicethat', 'c41'} and sum(map(len, cleaned)) < 80:
        raise ContentIssue('Expected editorial body is missing or unexpectedly short')
    if re.search(r'^(?:just a moment|access denied|verify you are human|sign in to continue)$', title, re.I):
        raise ContentIssue('Challenge or login page returned instead of article')
    meta = {e.get("property") or e.get("name"): e.get("content") for e in soup.find_all("meta")}
    taxonomies = []
    for item in feed_items((folder / "feed-0.xml").read_bytes()):
        if item["url"] == url:
            taxonomies.extend({"label": value, "kind": "unclassified feed term", "url": None} for value in item.get("terms", []) if value)
            break
    if name == "aperture":
        taxonomies.extend({**r, "kind": "category"} for r in content_links(soup.select_one(".single-post-date"), url))
    elif name == "itsnicethat":
        taxonomies.extend({"label": text(e), "url": urljoin(url,e.find_parent("a")["href"]), "kind": "source label"}
                          for e in soup.select(".fullscreen-article-header .tag") if e.find_parent("a"))
    elif name == "c41":
        taxonomies.extend({"label": text(e), "kind": "category", "url": None} for e in soup.select(".post-cat") if text(e))
    subtitle = metadata["subtitle"]
    details = {"taxonomies": taxonomies, "subtitle": subtitle,
               "work_details": [{"image_position": r["position"], "text": r["caption"]} for r in images if r["caption"]],
               "creative_team": [r for r in metadata["credits"] if r["label"] == "Creative team"],
               "rights": [r for r in metadata["credits"] if r["label"] == "Rights"],
               "profiles": metadata["profiles"],
               "further_info": [r for r in metadata["credits"] if r["label"] in {"Further info", "Project", "Publisher", "Image sources"}],
               "references": [r for r in metadata["credits"] if r["label"] in {"Notes", "References", "Bibliography"}],
               "metadata_provenance": metadata["provenance"]}
    data = {"site": name, "url": url, "title": title,
            "published_at": meta.get("article:published_time") or selected["published_at"],
            "modified_at": meta.get("article:modified_time"), "authors": authors,
            "description": meta.get("description") or meta.get("og:description"),
            "body_paragraphs": paragraphs, "body_text": body_text,
            "credits": credits, "images": images, "details": details,
            "feed_creator_raw": selected.get("creator") or selected.get("feed_author"),
            "missing_fields": [k for k,v in [("authors",authors),("credits",credits)] if not v],
            "captured_at": datetime.now(timezone.utc).isoformat()}
    data['quality'] = {'type': 'editorial' if cleaned else 'gallery', 'cleaned_paragraphs': len(cleaned)}
    save(folder / 'article.json', data)
    atomic_write(folder / 'body.txt', body_text.encode('utf-8'))
    return {"site": name, "title": title, "authors": authors, "images": len(images), "credits": len(credits), "text_characters": len(body_text), "missing_fields": data["missing_fields"]}


def download(name):
    folder = OUT / name
    data = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    (folder / "images").mkdir(exist_ok=True)
    start = time.monotonic()
    for rec in data["images"]:
        try:
            check_deadline()
            existing = folder / rec.get("local_file", "__not_downloaded__")
            if rec.get("sha256") and existing.is_file() and hashlib.sha256(existing.read_bytes()).hexdigest() == rec["sha256"]:
                rec["verification"] = "verified cached file"
                rec.pop('error', None)
                rec.pop('retryable', None)
                rec.pop('retry_after', None)
                continue
            time.sleep(1)
            raw, response = public_read(rec["url"], 25_000_000)
            if not response["content_type"].lower().startswith("image/"):
                raise ValueError("Response MIME is not an image")
            fmt, size, frames = inspect_image(raw)
            suffix = {"JPEG":"jpg","PNG":"png","WEBP":"webp","GIF":"gif","AVIF":"avif"}.get(fmt)
            if not suffix:
                raise ValueError(f"Format {fmt} needs additional validation; no silent omission")
            filename = f"images/{rec['position']:03d}.{suffix}"
            atomic_write(folder / filename, raw)
            rec.update(local_file=filename, sha256=hashlib.sha256(raw).hexdigest(),
                       width=size[0], height=size[1], frames=frames, response=response, verification="downloaded and decoded")
            if sum(r.get('response', {}).get('bytes', 0) for r in data['images']) > 250_000_000:
                raise ContentIssue('Article exceeds the 250 MB processing limit')
            rec.pop("error", None)
            rec.pop('retryable', None)
            rec.pop('retry_after', None)
        except Exception as e:
            rec["error"] = str(e)
            rec['retryable'] = isinstance(e, RetryableFetchError)
            rec['retry_after'] = getattr(e, 'retry_after', 0)
            rec["verification"] = "failed; retained for retry"
        save(folder / 'article.json', data)
        if time.monotonic() >= DEADLINE:
            break
    result = {"site": name, "expected": len(data["images"]), "downloaded": sum(bool(r.get("local_file")) and not r.get("error") for r in data["images"]),
              "bytes": sum(r.get("response", {}).get("bytes", 0) for r in data["images"]),
              "seconds": round(time.monotonic()-start, 2), "failures": [{"position":r["position"],"error":r["error"]} for r in data["images"] if r.get("error")]}
    save(folder / 'download-result.json', result)
    return result



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--site", choices=list(FEEDS))
    args = parser.parse_args()
    operation = download if args.download else extract if args.extract else discover
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(operation, name): name for name in ([args.site] if args.site else FEEDS)}
        for job in concurrent.futures.as_completed(jobs):
            try:
                result = job.result()
            except Exception as e:
                result = {"site": jobs[job], "error": str(e)}
            print(json.dumps(result, ensure_ascii=True), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"robots-observations-{operation.__name__}-{args.site or 'all'}.json").write_text(json.dumps({k:v[1] for k,v in POLICIES.items()},ensure_ascii=False,indent=2),encoding="utf-8")
