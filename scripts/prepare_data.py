"""Export acquired content into local website data and media."""
import hashlib
import json
import re
import shutil
import unicodedata
from pathlib import Path

from PIL import Image, ImageOps
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
from source_metadata import extract_metadata, extract_reading_body

PUBLIC = ROOT / "public"
LABELS = {"teeth": "Teeth Magazine", "aperture": "Aperture", "itsnicethat": "It’s Nice That", "c41": "C41 Magazine", "phroom": "PHROOM"}
ORDER = list(LABELS)


def assign_slugs(summaries, previous):
    reserved = {"all", "about", "api", "data", "media", "fonts", "brand", "_next"}
    saved = {item["id"]: item["slug"] for item in previous if item.get("slug")}
    if len(set(saved.values())) != len(saved) or any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) or value in reserved for value in saved.values()):
        raise ValueError("Existing article URLs must be unique, valid and non-reserved")
    used = set(saved.values()) | reserved
    for item in summaries:
        if item["id"] in saved:
            item["slug"] = saved[item["id"]]
            continue
        title = unicodedata.normalize("NFKD", item["title"]).encode("ascii", "ignore").decode().lower()
        base = re.sub(r"[^a-z0-9]+", "-", title).strip("-") or item["id"]
        slug = f"{base}-{item['id']}" if base in used else base
        if slug in used:
            raise ValueError(f"Article URL collision: {slug}")
        item["slug"] = slug
        used.add(slug)


def trusted_file(path):
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or not resolved.is_file():
        raise ValueError(f"Missing or out-of-workspace data file: {path}")
    return resolved


def reading_body(article, record_path, metadata=None):
    soup = BeautifulSoup(record_path.with_name("article.html").read_text(encoding="utf-8"), "html.parser")
    metadata = metadata or extract_metadata(article["site"], soup, article["url"])
    return extract_reading_body(article["site"], soup, metadata, {i["caption"] for i in article["images"] if i.get("caption")})


def export():
    manifest = json.loads(trusted_file(ROOT / "data/acquisition/manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete", "Wait for the real acquisition to finish"
    data_dir = PUBLIC / "data"
    (data_dir / "articles").mkdir(parents=True, exist_ok=True)
    summaries = []
    total_images = 0
    for item in manifest["articles"]:
        article_id = item["id"]
        assert re.fullmatch(r"[a-z0-9-]+", article_id)
        record_path = trusted_file(ROOT / item["record_path"])
        article = json.loads(record_path.read_text(encoding="utf-8"))
        media_dir = PUBLIC / "media" / article_id
        media_dir.mkdir(parents=True, exist_ok=True)
        images = []
        for image in article["images"]:
            original = trusted_file(record_path.parent / image["local_file"])
            assert not image.get("error")
            assert hashlib.sha256(original.read_bytes()).hexdigest() == image["sha256"]
            destination = media_dir / original.name
            if not destination.exists():
                shutil.copyfile(original, destination)
            assert hashlib.sha256(destination.read_bytes()).hexdigest() == image["sha256"]
            preview = destination
            if image.get("frames", 1) <= 1:
                preview = media_dir / f"{original.stem}-preview.webp"
                if not preview.exists():
                    with Image.open(original) as source:
                        photo = ImageOps.exif_transpose(source).convert("RGB")
                        photo.thumbnail((1600, 2000))
                        photo.save(preview, "WEBP", quality=88)
            alt = image.get("alt", "").strip()
            if not alt or re.search(r"\.(?:png|jpe?g|tiff?|webp|gif)$", alt, re.I):
                alt = f"{article['title']} — image {image['position']}"
            images.append({"id": f"{article_id}-{image['position']}", "position": image["position"],
                           "src": f"/media/{article_id}/{destination.name}",
                           "preview": f"/media/{article_id}/{preview.name}",
                           "width": image["width"], "height": image["height"],
                           "caption": image.get("caption", "").strip(), "alt": alt,
                           "frames": image.get("frames", 1)})
        assert images and article["body_paragraphs"]
        thumbnail = media_dir / "thumbnail.webp"
        if not thumbnail.exists():
            with Image.open(record_path.parent / article["images"][0]["local_file"]) as cover:
                thumb = ImageOps.fit(ImageOps.exif_transpose(cover).convert("RGB"), (160, 160))
                thumb.save(thumbnail, "WEBP", quality=85)
        soup = BeautifulSoup(record_path.with_name("article.html").read_text(encoding="utf-8"), "html.parser")
        metadata = extract_metadata(article["site"], soup, article["url"])
        detail = {"id": article_id, "title": article["title"], "subtitle": metadata["subtitle"], "sourceLabel": LABELS[item["source"]],
                  "originalUrl": article["url"], "batchDate": item["batch_date"],
                  "publishedAt": article.get("published_at"), "fetchedAt": article.get("fetched_at", manifest["fetched_at"]),
                  "images": images, "bodyParagraphs": reading_body(article, record_path, metadata), "credits": metadata["credits"]}
        (data_dir / "articles" / f"{article_id}.json").write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
        summaries.append({"id": article_id, "batchDate": item["batch_date"], "source": item["source"],
                          "sourceLabel": LABELS[item["source"]], "title": article["title"],
                          "cover": {**images[0], "thumbnail": f"/media/{article_id}/thumbnail.webp"},
                          "detailUrl": f"/data/articles/{article_id}.json"})
        total_images += len(images)
    summaries.sort(key=lambda a: (-int(a["batchDate"].replace("-", "")), ORDER.index(a["source"])))
    catalog_path = data_dir / "catalog.json"
    previous = json.loads(catalog_path.read_text(encoding="utf-8"))["articles"] if catalog_path.exists() else []
    assign_slugs(summaries, previous)
    catalog = {"fetchedAt": manifest["fetched_at"], "batchDates": sorted({a["batchDate"] for a in summaries}, reverse=True), "articles": summaries}
    assert len({a["id"] for a in summaries}) == len(summaries)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"checks": "passed", "articles": len(summaries), "images": total_images,
                      "batches": catalog["batchDates"], "last_fetched_at": catalog["fetchedAt"]}))


if __name__ == "__main__":
    export()
