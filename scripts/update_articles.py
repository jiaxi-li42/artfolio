"""Append missing daily batches without replacing verified historical evidence."""
import argparse
import concurrent.futures
import json
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import acquire_articles as acquisition

ROOT = acquisition.ROOT
BASE = acquisition.OUT


def missing_dates(manifest, through):
    if not manifest["requested_batch_dates"]:
        return [through.isoformat()]
    first = date.fromisoformat(max(manifest["requested_batch_dates"])) + timedelta(days=1)
    return [(first + timedelta(days=offset)).isoformat()
            for offset in reversed(range((through - first).days + 1))]


def update(through):
    today = datetime.now(ZoneInfo("Europe/London")).date()
    if through > today:
        raise ValueError("Cannot collect future batches")
    manifest_path = BASE / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "status": "complete", "requested_batch_dates": [], "articles": [], "failures": [], "summary": {},
    }
    assert previous["status"] == "complete"
    seen = set()
    for entry in previous["articles"]:
        record = acquisition.verify_record((ROOT / entry["record_path"]).parent)
        seen.add(acquisition.parser.canonical(record["url"]))
    dates = missing_dates(previous, through)
    if not dates:
        print("No missing batches; existing selection retained.", flush=True)
        return
    run = BASE / "updates" / through.isoformat()
    if not (run / "manifest-before.json").exists():
        acquisition.save(run / "manifest-before.json", previous)
    acquisition.OUT = run
    acquisition.REQUESTED_DATES = dates
    available, receipts, failures = {}, {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {pool.submit(acquisition.feeds, source): source for source in acquisition.parser.FEEDS}
        for job in concurrent.futures.as_completed(jobs):
            source = jobs[job]
            try:
                _, items, receipt = job.result()
                available[source] = [item for item in items
                                     if acquisition.parser.canonical(item["url"]) not in seen]
                receipts[source] = receipt
                print(json.dumps({"feed": source, "unseen": len(available[source])}), flush=True)
            except Exception as exc:
                failures.append({"source": source, "stage": "feed", "at": acquisition.now(), "error": str(exc)})
                print(json.dumps(failures[-1]), flush=True)
    articles, lock = [], threading.Lock()

    def on_ready(record):
        with lock:
            articles.append(record)
            acquisition.save(run / "progress.json", articles)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(acquisition.acquire_source, source, items, on_ready, "daily-backfill")
                for source, items in available.items()]
        for job in concurrent.futures.as_completed(jobs):
            _, errors = job.result()
            failures.extend(errors)
    acquisition.save(run / "robots-observations.json", {key: value[1] for key, value in acquisition.parser.POLICIES.items()})
    report = {"mode": "daily-backfill", "fetched_at": acquisition.now(), "requested_batch_dates": dates,
              "articles": articles, "feed_receipts": receipts, "failures": failures}
    acquisition.save(run / "report.json", report)
    if not articles:
        raise ValueError("No complete new articles; existing catalog left unchanged")
    combined = previous["articles"] + articles
    combined.sort(key=lambda entry: (entry["batch_date"], entry["source"]), reverse=True)
    records = [acquisition.verify_record((ROOT / entry["record_path"]).parent) for entry in combined]
    assert len({entry["id"] for entry in combined}) == len(combined)
    assert len({(entry["source"], entry["batch_date"]) for entry in combined}) == len(combined)
    batches = sorted({entry["batch_date"] for entry in combined}, reverse=True)
    summary = {**previous["summary"], "articles": len(combined),
               "images": sum(len(record["images"]) for record in records),
               "bytes": sum(image["response"]["bytes"] for record in records for image in record["images"]),
               "published_dates": sorted({record["published_at"][:10] for record in records}, reverse=True),
               "batch_dates": batches, "per_batch": {day: sum(entry["batch_date"] == day for entry in combined) for day in batches},
               "available_sources": sorted({entry["source"] for entry in combined}),
               "unavailable_sources": sorted(set(acquisition.parser.FEEDS) - {entry["source"] for entry in combined}),
               "timestamp_semantics": "Batch dates are backfill grouping cutoffs, not fetch times. Article fetched_at is the actual HTML response time; manifest fetched_at is actual acquisition completion. Old evidence and timestamps remain unchanged."}
    acquisition.save(manifest_path, {**previous, "mode": "historical-backfill-and-daily-updates",
                     "fetched_at": report["fetched_at"], "requested_batch_dates": dates + previous["requested_batch_dates"],
                     "batch_dates": batches, "articles": combined, "failures": previous["failures"] + failures,
                     "updates": previous.get("updates", []) + [(run / "report.json").relative_to(ROOT).as_posix()],
                     "summary": summary})
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--through", required=True, type=date.fromisoformat)
    update(arguments.parse_args().through)
