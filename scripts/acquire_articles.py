"""Acquire complete article batches from the configured public feeds."""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import extract_articles as parser

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "acquisition"
REQUESTED_DATES = [datetime.now(ZoneInfo("Europe/London")).date().isoformat()]


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def stable_id(source, url):
    return source + "-" + hashlib.sha256(parser.canonical(url).encode()).hexdigest()[:16]


def verify_record(folder):
    complete_path = folder / "complete.json"
    if complete_path.exists():
        complete = json.loads(complete_path.read_text(encoding="utf-8"))
        assert hashlib.sha256((folder / "article.json").read_bytes()).hexdigest() == complete["article_sha256"]
    data = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    assert data["body_text"] == "\n\n".join(data["body_paragraphs"])
    assert data["body_text"] == (folder / "body.txt").read_text(encoding="utf-8")
    assert data["images"], "A visual article needs content images"
    for position, rec in enumerate(data["images"], 1):
        assert rec["position"] == position and not rec.get("error")
        raw = (folder / rec["local_file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == rec["sha256"]
        with parser.Image.open(parser.io.BytesIO(raw)) as image:
            assert image.size == (rec["width"], rec["height"])
            assert getattr(image, "n_frames", 1) == rec["frames"]
            image.verify()
    return data


def feeds(source):
    folder = OUT / "feeds" / source
    receipt_path = folder / "receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        return source, parser.feed_items((folder / "feed-0.xml").read_bytes()), receipt
    folder.mkdir(parents=True, exist_ok=True)
    raw, response = parser.public_read(parser.FEEDS[source][0])
    items = parser.feed_items(raw)
    assert items, "RSS contains no items"
    (folder / "feed-0.xml").write_bytes(raw)
    receipt = {"source": source, "fetched_at": now(), "response": response,
               "items": len(items), "sha256": hashlib.sha256(raw).hexdigest()}
    save(receipt_path, receipt)
    save(folder / "items.json", items)
    return source, items, receipt


def acquire(source, item, mode="historical-backfill"):
    article_id = stable_id(source, item["url"])
    candidate = OUT / "articles" / article_id
    folder = candidate / source
    if (folder / "complete.json").exists():
        return article_id, folder, verify_record(folder)
    folder.mkdir(parents=True, exist_ok=True)
    raw_path = folder / "article.html"
    receipt_path = folder / "fetch-receipt.json"
    if not raw_path.exists() or not receipt_path.exists():
        time.sleep(1)
        raw, response = parser.public_read(item["url"])
        raw_path.write_bytes(raw)
        save(receipt_path, {"fetched_at": now(), "response": response,
                            "sha256": hashlib.sha256(raw).hexdigest()})
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    save(folder / "selected-feed-item.json", item)
    (folder / "feed-0.xml").write_bytes((OUT / "feeds" / source / "feed-0.xml").read_bytes())
    # Each worker gets its own OUT; the original parser and its proof stay untouched.
    spec = importlib.util.spec_from_file_location("article_parser_" + article_id.replace("-", "_"), Path(parser.__file__))
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.OUT = candidate
    worker.POLICIES = parser.POLICIES
    worker.POLICY_LOCK = parser.POLICY_LOCK
    worker.extract(source)
    result = worker.download(source)
    data = json.loads((folder / "article.json").read_text(encoding="utf-8"))
    data.update(id=article_id, fetched_at=receipt["fetched_at"],
                feed_published_at=item["published_at"], acquisition_mode=mode)
    save(folder / "article.json", data)
    if result["failures"] or result["expected"] != result["downloaded"]:
        raise ValueError("Incomplete content images: " + json.dumps(result["failures"]))
    verify_record(folder)
    save(folder / "complete.json", {"verified_at": now(), "images": len(data["images"]),
                                   "article_sha256": hashlib.sha256((folder / "article.json").read_bytes()).hexdigest()})
    return article_id, folder, data


def acquire_source(source, items, on_ready, mode="historical-backfill"):
    ready, failures, seen = [], [], set()
    for batch_date in REQUESTED_DATES:
        # A historical batch includes only articles available by that date.
        candidates = [item for item in items if item["published_at"][:10] <= batch_date
                      and parser.canonical(item["url"]) not in seen]
        for item in candidates[:6]:
            seen.add(parser.canonical(item["url"]))
            try:
                article_id, folder, data = acquire(source, item, mode)
                record = {"id": article_id, "batch_date": batch_date, "source": source,
                          "record_path": (folder / "article.json").relative_to(ROOT).as_posix()}
                ready.append(record)
                on_ready(record)
                print(json.dumps({"ready": source, "batch": batch_date, "title": data["title"],
                                  "published_at": data["published_at"], "images": len(data["images"])}), flush=True)
                break
            except Exception as exc:
                failure = {"source": source, "batch_date": batch_date, "url": item["url"],
                           "at": now(), "stage": "article", "error": str(exc)}
                failures.append(failure)
                print(json.dumps(failure), flush=True)
        else:
            failures.append({"source": source, "batch_date": batch_date, "stage": "batch",
                             "at": now(), "error": "No remaining complete public article in bounded RSS candidates"})
    return ready, failures


def main(feeds_only=False):
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    if manifest_path.exists() and not feeds_only:
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("summary", {}).get("complete"):
            for record in previous["articles"]:
                verify_record((ROOT / record["record_path"]).parent)
            print(json.dumps({"cached": True, "summary": previous["summary"]}), flush=True)
            return
    available, failures, feed_receipts = {}, [], {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(feeds, source): source for source in parser.FEEDS}
        for job in concurrent.futures.as_completed(jobs):
            source = jobs[job]
            try:
                _, items, receipt = job.result()
                available[source], feed_receipts[source] = items, receipt
                print(json.dumps({"feed": source, "items": len(items), "dates": sorted({x["published_at"][:10] for x in items}, reverse=True)[:10]}), flush=True)
            except Exception as exc:
                failures.append({"source": source, "stage": "feed", "at": now(), "error": str(exc)})
                print(json.dumps(failures[-1]), flush=True)
    if feeds_only:
        save(OUT / "feed-failures.json", failures)
        save(OUT / "robots-observations.json", {k: v[1] for k, v in parser.POLICIES.items()})
        return
    articles, manifest_lock = [], threading.Lock()
    def on_ready(record):
        with manifest_lock:
            articles.append(record)
            write_manifest(articles, failures, feed_receipts, "collecting")
    write_manifest(articles, failures, feed_receipts, "collecting")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(acquire_source, source, items, on_ready): source for source, items in available.items()}
        for job in concurrent.futures.as_completed(jobs):
            records, errors = job.result()
            failures.extend(errors)
    summary = write_manifest(articles, failures, feed_receipts, "complete")
    save(OUT / "robots-observations.json", {k: v[1] for k, v in parser.POLICIES.items()})
    print(json.dumps(summary), flush=True)


def write_manifest(articles, failures, feed_receipts, status):
    manifest_path = OUT / "manifest.json"
    articles.sort(key=lambda row: (row["batch_date"], row["source"]), reverse=True)
    records = [json.loads((ROOT / row["record_path"]).read_text(encoding="utf-8")) for row in articles]
    published_dates = sorted({row["published_at"][:10] for row in records}, reverse=True)
    batch_dates = sorted({row["batch_date"] for row in articles}, reverse=True)
    summary = {"complete": status == "complete" and bool(articles),
               "articles": len(articles), "images": sum(len(row["images"]) for row in records),
               "bytes": sum(image["response"]["bytes"] for row in records for image in row["images"]),
               "published_dates": published_dates, "batch_dates": batch_dates,
               "per_batch": {day: sum(row["batch_date"] == day for row in articles) for day in batch_dates},
               "available_sources": sorted({row["source"] for row in articles}),
               "unavailable_sources": sorted(set(parser.FEEDS) - {row["source"] for row in articles}),
               "timestamp_semantics": "Batch dates are content grouping cutoffs, not fetch times; article fetched_at is the actual HTML response time in UTC; manifest fetched_at is this run's actual completion time."}
    save(manifest_path, {"schema_version": 1, "mode": "historical-backfill", "status": status, "fetched_at": now(),
                         "requested_batch_dates": REQUESTED_DATES, "batch_dates": batch_dates,
                         "articles": articles, "failures": failures, "feed_receipts": feed_receipts,
                         "summary": summary})
    return summary


if __name__ == "__main__":
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--feeds-only", action="store_true")
    main(arguments.parse_args().feeds_only)
