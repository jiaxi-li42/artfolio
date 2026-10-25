"""Build immutable, validated article details and media for external publication."""
import hashlib
import mimetypes
import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageOps
from bs4 import BeautifulSoup
from source_metadata import extract_metadata, extract_reading_body
from content_store import ContentIssue, json_bytes

ROOT = Path(__file__).resolve().parent.parent
LABELS = {'teeth': 'Teeth Magazine', 'aperture': 'Aperture', 'itsnicethat': 'It’s Nice That', 'c41': 'C41 Magazine', 'phroom': 'PHROOM'}
ORDER = list(LABELS)


def assign_slugs(summaries, previous):
    reserved = {'all', 'about', 'api', 'data', 'media', 'fonts', 'brand', '_next'}
    saved = {item['id']: item['slug'] for item in previous if item.get('slug')}
    if len(set(saved.values())) != len(saved) or any(not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value) or value in reserved for value in saved.values()):
        raise ContentIssue('Existing article URLs must be unique, valid and non-reserved')
    used = set(saved.values()) | reserved
    for item in summaries:
        if item['id'] in saved:
            item['slug'] = saved[item['id']]
            continue
        title = unicodedata.normalize('NFKD', item['title']).encode('ascii', 'ignore').decode().lower()
        base = re.sub(r'[^a-z0-9]+', '-', title).strip('-') or item['id']
        slug = f"{base}-{item['id']}" if base in used else base
        if slug in used:
            raise ContentIssue('Article URL collision: ' + slug)
        item['slug'] = slug
        used.add(slug)


def reading_body(article, record_path, metadata=None):
    soup = BeautifulSoup(record_path.with_name('article.html').read_text(encoding='utf-8'), 'html.parser')
    metadata = metadata or extract_metadata(article['site'], soup, article['url'])
    return extract_reading_body(article['site'], soup, metadata, {i['caption'] for i in article['images'] if i.get('caption')})


def build_article(article_id, source, batch_date, folder, output, store):
    from acquire_articles import verify_record
    article = verify_record(folder)
    if not re.fullmatch(r'[a-z0-9-]+', article_id):
        raise ContentIssue('Invalid article ID')
    output.mkdir(parents=True, exist_ok=True)
    images, uploads = [], {}
    for image in article['images']:
        original = folder / image['local_file']
        digest = image['sha256']
        key = f'media/{digest}{original.suffix.lower()}'
        uploads[key] = original
        preview_key = key
        if image.get('frames', 1) <= 1:
            preview = output / f'{digest}-preview.webp'
            with Image.open(original) as photo:
                photo = ImageOps.exif_transpose(photo).convert('RGB')
                photo.thumbnail((1600, 2000))
                photo.save(preview, 'WEBP', quality=88)
            preview_key = f"media/{hashlib.sha256(preview.read_bytes()).hexdigest()}-preview.webp"
            uploads[preview_key] = preview
        alt = image.get('alt', '').strip()
        if not alt or re.search(r'\.(?:png|jpe?g|tiff?|webp|gif)$', alt, re.I):
            alt = f"{article['title']} — image {image['position']}"
        images.append({'id': f"{article_id}-{image['position']}", 'position': image['position'],
            'src': store.url(key), 'preview': store.url(preview_key), 'width': image['width'], 'height': image['height'],
            'caption': image.get('caption', '').strip(), 'alt': alt, 'frames': image.get('frames', 1)})
    cover_digest = article['images'][0]['sha256']
    thumbnail = output / f'{cover_digest}-thumbnail.webp'
    with Image.open(folder / article['images'][0]['local_file']) as cover:
        ImageOps.fit(ImageOps.exif_transpose(cover).convert('RGB'), (160, 160)).save(thumbnail, 'WEBP', quality=85)
    thumbnail_key = f"media/{hashlib.sha256(thumbnail.read_bytes()).hexdigest()}-thumbnail.webp"
    uploads[thumbnail_key] = thumbnail
    soup = BeautifulSoup((folder / 'article.html').read_text(encoding='utf-8'), 'html.parser')
    metadata = extract_metadata(source, soup, article['url'])
    detail = {'id': article_id, 'title': article['title'], 'subtitle': metadata['subtitle'], 'sourceLabel': LABELS[source],
        'originalUrl': article['url'], 'batchDate': batch_date, 'publishedAt': article.get('published_at'),
        'fetchedAt': article['fetched_at'], 'images': images, 'bodyParagraphs': reading_body(article, folder / 'article.json', metadata),
        'credits': metadata['credits']}
    version = hashlib.sha256(json_bytes(detail)).hexdigest()
    summary = {'id': article_id, 'batchDate': batch_date, 'source': source, 'sourceLabel': LABELS[source], 'title': article['title'],
        'cover': {**images[0], 'thumbnail': store.url(thumbnail_key)},
        'detailUrl': f'/api/articles/{article_id}?version={version}'}
    for key, file in uploads.items():
        store.put_file(key, file, public=True, content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
    store.put_json(f'articles/{article_id}/{version}.json', detail, public=True, immutable=True)
    return summary, detail['fetchedAt']


if __name__ == '__main__':
    from run_daily import main
    raise SystemExit(main(['--publish-only']))
