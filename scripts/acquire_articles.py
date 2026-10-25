"""Source acquisition helpers; the daily runner owns scheduling and publication."""
import hashlib
import importlib.util
import json
import time
from pathlib import Path

import extract_articles as parser
from content_store import ContentIssue, RetryableFetchError, atomic_write, now, save

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'acquisition'


def adapter_version():
    return hashlib.sha256(b''.join((ROOT / 'scripts' / name).read_bytes() for name in
        ['extract_articles.py', 'source_metadata.py', 'acquire_articles.py', 'prepare_data.py'])).hexdigest()[:16]


def stable_id(source, url):
    return source + '-' + hashlib.sha256(parser.canonical(url).encode()).hexdigest()[:16]


def verify_record(folder):
    raw = (folder / 'article.json').read_bytes()
    complete = folder / 'complete.json'
    if complete.exists() and hashlib.sha256(raw).hexdigest() != json.loads(complete.read_text())['article_sha256']:
        raise ContentIssue('Article checksum mismatch')
    data = json.loads(raw)
    if data['body_text'] != '\n\n'.join(data['body_paragraphs']) or data['body_text'] != (folder / 'body.txt').read_text(encoding='utf-8'):
        raise ContentIssue('Article text files disagree')
    if not data['images'] or len(data['images']) > 100:
        raise ContentIssue('A visual article needs between 1 and 100 content images')
    total_bytes = 0
    for position, rec in enumerate(data['images'], 1):
        target = (folder / rec.get('local_file', '__missing__')).resolve()
        if not target.is_relative_to(folder.resolve()) or not target.is_file() or rec.get('error') or rec['position'] != position:
            raise ContentIssue('Missing, unsafe or incomplete article image')
        total_bytes += target.stat().st_size
        if target.stat().st_size > 25_000_000 or total_bytes > 250_000_000:
            raise ContentIssue('Image/article byte limit exceeded')
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != rec['sha256']:
            raise ContentIssue('Image checksum mismatch')
        _, size, frames = parser.inspect_image(raw)
        if size != (rec['width'], rec['height']) or frames != rec['frames']:
            raise ContentIssue('Image dimensions/frames disagree')
    return data


def feeds(source):
    folder = OUT / 'feeds' / source
    receipt_path = folder / 'receipt.json'
    receipt = json.loads(receipt_path.read_bytes()) if receipt_path.exists() else {}
    raw_path = folder / 'feed-0.xml'
    if receipt and raw_path.exists() and time.time() - receipt.get('checked_epoch', 0) < 1800:
        return parser.feed_items(raw_path.read_bytes()), receipt
    headers = {}
    for header, field in [('If-None-Match', 'etag'), ('If-Modified-Since', 'last_modified')]:
        if receipt.get('response', {}).get(field) and raw_path.exists():
            headers[header] = receipt['response'][field]
    raw, response = parser.public_read(parser.FEEDS[source][0], headers=headers)
    if response['status'] == 304:
        if not raw_path.exists():
            raise ContentIssue('Feed returned 304 without a cached body')
        raw = raw_path.read_bytes()
    items = parser.feed_items(raw)
    if response['status'] != 304:
        atomic_write(raw_path, raw)
        receipt.update(fetched_at=now(), response=response, sha256=hashlib.sha256(raw).hexdigest())
    receipt.update(source=source, checked_at=now(), checked_epoch=time.time(), items=len(items))
    save(receipt_path, receipt)
    return items, receipt


def acquire(source, item, force=False):
    article_id = stable_id(source, item['url'])
    candidate = OUT / 'articles' / article_id
    folder = candidate / source
    complete_path = folder / 'complete.json'
    if complete_path.exists() and not force:
        return article_id, folder, verify_record(folder)
    complete_path.unlink(missing_ok=True)
    folder.mkdir(parents=True, exist_ok=True)
    raw_path, receipt_path = folder / 'article.html', folder / 'fetch-receipt.json'
    receipt = json.loads(receipt_path.read_bytes()) if receipt_path.exists() else {}
    if force or not raw_path.exists() or time.time() - receipt.get('fetched_epoch', 0) >= 86400:
        raw, response = parser.public_read(item['url'])
        if 'html' not in response['content_type'].lower():
            raise ContentIssue('Article response is not HTML')
        atomic_write(raw_path, raw)
        receipt = {'fetched_at': now(), 'fetched_epoch': time.time(), 'response': response,
            'sha256': hashlib.sha256(raw).hexdigest()}
        save(receipt_path, receipt)
    save(folder / 'selected-feed-item.json', item)
    atomic_write(folder / 'feed-0.xml', (OUT / 'feeds' / source / 'feed-0.xml').read_bytes())
    spec = importlib.util.spec_from_file_location('article_parser_' + article_id.replace('-', '_'), Path(parser.__file__))
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.OUT, worker.POLICIES, worker.POLICY_LOCK = candidate, parser.POLICIES, parser.POLICY_LOCK
    worker.DEADLINE = parser.DEADLINE
    worker.extract(source)
    result = worker.download(source)
    data = json.loads((folder / 'article.json').read_bytes())
    data.update(id=article_id, fetched_at=receipt['fetched_at'], feed_published_at=item['published_at'], adapter_version=adapter_version())
    save(folder / 'article.json', data)
    if result['failures'] or result['expected'] != result['downloaded']:
        exception = RetryableFetchError if any(r.get('retryable') for r in data['images']) or time.monotonic() >= parser.DEADLINE else ContentIssue
        message = 'Incomplete content images: ' + json.dumps(result['failures'])
        if exception is RetryableFetchError:
            raise exception(message, retry_after=max((r.get('retry_after', 0) for r in data['images']), default=0))
        raise exception(message)
    verify_record(folder)
    save(complete_path, {'verified_at': now(), 'article_sha256': hashlib.sha256((folder / 'article.json').read_bytes()).hexdigest()})
    return article_id, folder, data


if __name__ == '__main__':
    from run_daily import main
    raise SystemExit(main())
