"""Unattended acquisition: private checkpoints, immutable assets, atomic releases."""
import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

import acquire_articles as acquisition
import extract_articles as parser
from content_store import ContentIssue, Lease, LeaseBusy, RetryableFetchError, S3Store, atomic_write, json_bytes, now, save
from prepare_data import ORDER, assign_slugs, build_article

VERSION = re.compile(r'[a-f0-9]{64}')


def snapshot(store, folder, namespace):
    """Content-address each file; incomplete uploads never replace an older checkpoint."""
    files = []
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ContentIssue('Archive contains a symlink')
        if not path.is_file() or path.name.endswith('.tmp'):
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        key = f'archives/{namespace}/{digest}/{path.name}'
        store.put_file(key, path)
        files.append({'path': path.relative_to(folder).as_posix(), 'key': key, 'sha256': digest, 'size': len(raw)})
    index = {'files': files}
    key = f'archives/{namespace}/snapshots/{hashlib.sha256(json_bytes(index)).hexdigest()}.json'
    store.put_json(key, index, immutable=True)
    return key


def restore(store, key, folder):
    index, _ = store.get_json(key)
    if not index or not isinstance(index.get('files'), list):
        raise ContentIssue('Missing archive index')
    total = 0
    for entry in index['files']:
        name = entry['path']
        path = PurePosixPath(name)
        target = (folder / name).resolve()
        size = entry['size']
        total += size
        if ('\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or
                not target.is_relative_to(folder.resolve()) or size < 0 or size > 30_000_000 or total > 2_000_000_000):
            raise ContentIssue('Unsafe or oversized archive entry')
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == entry['sha256']:
            continue
        raw, _ = store.get(entry['key'], limit=size)
        if raw is None or len(raw) != size or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ContentIssue('Private archive checksum mismatch')
        atomic_write(target, raw)


def read_release(store):
    pointer, etag = store.get_json('current.json', public=True)
    if pointer is None:
        return None, etag, {'fetchedAt': None, 'batchDates': [], 'articles': []}
    version = pointer.get('version', '')
    if not VERSION.fullmatch(version):
        raise ContentIssue('Invalid current release pointer')
    catalog, _ = store.get_json(f'releases/{version}/catalog.json', public=True)
    validate_catalog(catalog)
    if hashlib.sha256(json_bytes(catalog)).hexdigest() != version:
        raise ContentIssue('Release checksum mismatch')
    return pointer, etag, catalog


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or not isinstance(catalog.get('articles'), list):
        raise ContentIssue('Invalid release catalog')
    entries = catalog['articles']
    if len({a['id'] for a in entries}) != len(entries) or len({a['slug'] for a in entries}) != len(entries):
        raise ContentIssue('Duplicate article ID or URL')
    for entry in entries:
        if entry['source'] not in ORDER or not re.fullmatch(r'[a-z0-9-]+', entry['id']):
            raise ContentIssue('Invalid catalog article identity')
        date.fromisoformat(entry['batchDate'])
        if not re.fullmatch(r'/api/articles/[a-z0-9-]+\?version=[a-f0-9]{64}', entry['detailUrl']):
            raise ContentIssue('Invalid immutable article URL')


def plan_jobs(state, through):
    jobs = state.setdefault('jobs', {})
    first = date.fromisoformat(state.get('last_requested_date', through.isoformat()))
    if (through - first).days > 366:
        raise ContentIssue('More than one year of backlog; backfill in smaller date ranges')
    for offset in range(max(0, (through - first).days) + 1):
        day = min(first, through) + timedelta(days=offset)
        for source in parser.FEEDS:
            jobs.setdefault(f'{day.isoformat()}/{source}', {'date': day.isoformat(), 'source': source, 'status': 'pending', 'attempts': 0})
    state['last_requested_date'] = max(state.get('last_requested_date', through.isoformat()), through.isoformat())


def due(job, today, version, retry=False):
    status = job['status']
    if status == 'published':
        return False
    if status == 'ready':
        return False
    if status in {'quarantined', 'held'}:
        return retry or (status == 'quarantined' and job.get('adapter_version') != version)
    if status == 'no_new':
        return retry or job['date'] == today and time.time() >= job.get('next_retry', 0)
    return retry or time.time() >= job.get('next_retry', 0)


def failure(job, error, version):
    transient = isinstance(error, (RetryableFetchError, TimeoutError, ConnectionError))
    job.update(status='retry' if transient else 'quarantined', error=str(error)[:1500], checked_at=now(), adapter_version=version)
    job['attempts'] = job.get('attempts', 0) + 1
    job['next_retry'] = time.time() + max(min(21600, 1800 * 2 ** min(job['attempts'], 5)), getattr(error, 'retry_after', 0))


class Runner:
    def __init__(self, store, lease, run_id):
        self.store, self.lease, self.run_id = store, lease, run_id
        self.state, self.etag = store.get_json('state/manifest.json')
        missing_state = self.state is None
        if missing_state:
            self.state = {'schema_version': 1, 'jobs': {}, 'feeds': {}}
        if not isinstance(self.state, dict) or self.state.get('schema_version') != 1 or not isinstance(self.state.get('jobs'), dict) or not isinstance(self.state.get('feeds'), dict):
            raise ContentIssue('Unsupported state schema')
        self.pointer, self.pointer_etag, self.catalog = read_release(store)
        if missing_state and self.catalog['articles']:
            raise ContentIssue('A public release exists but private state is missing; restore a state backup')
        for key, job in self.state['jobs'].items():
            if job.get('source') not in ORDER or key != f"{job.get('date')}/{job.get('source')}" or job.get('status') not in {'pending', 'retry', 'no_new', 'ready', 'published', 'quarantined', 'held'}:
                raise ContentIssue('Invalid source/date job in state')
            date.fromisoformat(job['date'])
        published = {a['id'] for a in self.catalog['articles']}
        for job in self.state['jobs'].values():
            if job.get('id') in published:
                job.update(status='published')
        self.sequence = 0
        self.changed = False

    def checkpoint(self):
        self.lease.renew()
        self.sequence += 1
        self.state.update(updated_at=now(), last_run_id=self.run_id)
        self.store.put_json(f'runs/{self.run_id}/state-{self.sequence:04d}.json', self.state, immutable=True)
        self.etag = self.store.put_json('state/manifest.json', self.state, expected=self.etag)

    def collect(self, through, retry=False):
        plan_jobs(self.state, through)
        self.checkpoint()
        version = acquisition.adapter_version()
        today = datetime.now(ZoneInfo('Europe/London')).date().isoformat()
        feed_cache, feed_errors, source_seconds = {}, {}, {}
        run_deadline = parser.DEADLINE
        feed_issues = self.state.setdefault('feed_issues', {})
        for job in sorted(self.state['jobs'].values(), key=lambda row: (row['date'] != through.isoformat(), row['date'], ORDER.index(row['source']))):
            if job['date'] > through.isoformat() or not due(job, today, version, retry):
                continue
            if time.monotonic() >= run_deadline:
                break
            source = job['source']
            remaining = 360 - source_seconds.get(source, 0)
            if remaining <= 0:
                continue
            started = time.monotonic()
            parser.DEADLINE = min(run_deadline, started + remaining)
            try:
                if source not in feed_cache and source not in feed_errors:
                    try:
                        if self.state['feeds'].get(source):
                            restore(self.store, self.state['feeds'][source], acquisition.OUT / 'feeds' / source)
                        feed_cache[source], receipt = acquisition.feeds(source)
                        self.state['feeds'][source] = snapshot(self.store, acquisition.OUT / 'feeds' / source, 'feeds/' + source)
                        if receipt.get('invalid_count'):
                            feed_issues[source] = {'count': receipt['invalid_count'], 'checked_at': receipt.get('checked_at')}
                            print(f"::warning::{source}: {receipt['invalid_count']} malformed RSS entries isolated", flush=True)
                        else:
                            feed_issues.pop(source, None)
                    except (ContentIssue, RetryableFetchError, urllib.error.HTTPError, ValueError) as error:
                        feed_errors[source] = error
                if source in feed_errors:
                    failure(job, feed_errors[source], version)
                else:
                    try:
                        self.collect_job(job, feed_cache[source], version, retry)
                    except (ContentIssue, RetryableFetchError, urllib.error.HTTPError, ValueError) as error:
                        failure(job, error, version)
            finally:
                parser.DEADLINE = run_deadline
                source_seconds[source] = source_seconds.get(source, 0) + time.monotonic() - started
            self.checkpoint()
            print(json.dumps({'date': job['date'], 'source': source, 'status': job['status']}), flush=True)

    def collect_job(self, job, items, version, retry):
        source = job['source']
        used = {a['id'] for a in self.catalog['articles']} | {row.get('id') for row in self.state['jobs'].values() if row is not job}
        candidates = [item for item in items if datetime.fromisoformat(item['published_at']).astimezone(ZoneInfo('Europe/London')).date().isoformat() <= job['date']
            and acquisition.stable_id(source, item['url']) not in used]
        if job.get('selected_item'):
            candidates = [job['selected_item']] + [item for item in candidates if item['url'] != job['selected_item']['url']]
        if not candidates:
            job.update(status='no_new', checked_at=now(), next_retry=time.time() + 7200)
            job.pop('error', None)
            return
        if job.get('archive'):
            restore(self.store, job['archive'], acquisition.OUT / 'articles' / job['id'] / source)
        rejected = []
        for item in candidates[:6]:
            article_id = acquisition.stable_id(source, item['url'])
            if job.get('id') != article_id:
                job.pop('archive', None)
            job.update(id=article_id, selected_item=item)
            folder = acquisition.OUT / 'articles' / article_id / source
            try:
                _, folder, _ = acquisition.acquire(source, item, force=retry or job.get('adapter_version', version) != version)
            except (ContentIssue, RetryableFetchError, urllib.error.HTTPError, ValueError) as error:
                if folder.exists():
                    job['archive'] = snapshot(self.store, folder, article_id)
                if not isinstance(error, ContentIssue):
                    raise
                rejected.append({'id': article_id, 'error': str(error)[:1500], 'archive': job.get('archive')})
                job['rejected'] = rejected
                continue
            job['archive'] = snapshot(self.store, folder, article_id)
            summary, fetched = build_article(article_id, source, job['date'], folder, acquisition.OUT / 'build' / article_id, self.store)
            job.update(status='ready', summary=summary, fetched_at=fetched, adapter_version=version, checked_at=now(), attempts=0)
            job.pop('error', None)
            job.pop('next_retry', None)
            return
        raise ContentIssue('No candidate passed source validation: ' + json.dumps(rejected))

    def publish(self):
        ready = [row for row in self.state['jobs'].values() if row['status'] == 'ready']
        if not ready:
            return False
        articles = {entry['id']: entry for entry in self.catalog['articles']}
        for row in ready:
            articles[row['id']] = row['summary']
        summaries = sorted(articles.values(), key=lambda a: (a['batchDate'], -ORDER.index(a['source'])), reverse=True)
        assign_slugs(summaries, self.catalog['articles'])
        fetched = max(filter(None, [self.catalog.get('fetchedAt')] + [row['fetched_at'] for row in ready]))
        catalog = {'fetchedAt': fetched, 'batchDates': sorted({a['batchDate'] for a in summaries}, reverse=True), 'articles': summaries}
        validate_catalog(catalog)
        version = hashlib.sha256(json_bytes(catalog)).hexdigest()
        self.store.put_json(f'releases/{version}/catalog.json', catalog, public=True, immutable=True)
        # Read-back verifies the upload before the only mutable public object changes.
        stored, _ = self.store.get_json(f'releases/{version}/catalog.json', public=True)
        if stored != catalog:
            raise ContentIssue('Published catalog failed read-back verification')
        self.checkpoint()
        self.lease.renew()
        pointer = {'schemaVersion': 1, 'version': version, 'publishedAt': now(), 'previousVersion': (self.pointer or {}).get('version')}
        self.pointer_etag = self.store.put_json('current.json', pointer, public=True, expected=self.pointer_etag)
        self.pointer, self.catalog = pointer, catalog
        self.changed = True
        for row in ready:
            row['status'] = 'published'
        self.checkpoint()
        return True

    def rollback(self, version):
        if not VERSION.fullmatch(version):
            raise ContentIssue('Rollback requires a 64-character release hash')
        catalog, _ = self.store.get_json(f'releases/{version}/catalog.json', public=True)
        validate_catalog(catalog)
        if hashlib.sha256(json_bytes(catalog)).hexdigest() != version:
            raise ContentIssue('Rollback catalog checksum mismatch')
        kept = {a['id'] for a in catalog['articles']}
        for row in self.state['jobs'].values():
            if row.get('id') and row['id'] not in kept:
                row.update(status='held', error='Held after rollback; use --retry-quarantined after investigation')
        self.checkpoint()
        self.lease.renew()
        pointer = {'schemaVersion': 1, 'version': version, 'publishedAt': now(), 'previousVersion': (self.pointer or {}).get('version')}
        self.store.put_json('current.json', pointer, public=True, expected=self.pointer_etag)
        self.pointer, self.catalog = pointer, catalog
        self.changed = True

    def audit(self):
        for row in self.state['jobs'].values():
            if row['status'] != 'published':
                continue
            parser.check_deadline()
            folder = acquisition.OUT / 'articles' / row['id'] / row['source']
            restore(self.store, row['archive'], folder)
            acquisition.verify_record(folder)
            match = re.search(r'version=([a-f0-9]{64})$', row['summary']['detailUrl'])
            detail, _ = self.store.get_json(f"articles/{row['id']}/{match[1]}.json", public=True)
            if hashlib.sha256(json_bytes(detail)).hexdigest() != match[1]:
                raise ContentIssue('Published detail checksum mismatch')
            for image in detail['images']:
                key = image['src'].removeprefix(self.store.base_url)
                raw, _ = self.store.get(key, public=True, limit=25_000_000)
                if raw is None or hashlib.sha256(raw).hexdigest() not in key:
                    raise ContentIssue('Published image checksum mismatch')

    def report(self):
        jobs = list(self.state['jobs'].values())
        bad = [row for row in jobs if row['status'] in {'retry', 'quarantined'}]
        waiting = [row for row in jobs if row['status'] in {'pending', 'ready'}]
        current_ok = any(row['date'] == self.state.get('last_requested_date') and row['status'] in {'published', 'no_new'} for row in jobs)
        status = 'partial' if (bad or waiting) and current_ok else 'failed' if bad or waiting else 'success' if self.changed else 'no_new'
        self.state['failed_runs'] = self.state.get('failed_runs', 0) + 1 if status in {'partial', 'failed'} else 0
        report = {'runId': self.run_id, 'finishedAt': now(), 'status': status, 'release': (self.pointer or {}).get('version'),
            'counts': {name: sum(row['status'] == name for row in jobs) for name in ['published', 'no_new', 'retry', 'quarantined', 'pending', 'ready', 'held']},
            'issues': [{'date': row['date'], 'source': row['source'], 'status': row['status'], 'error': row.get('error', '')} for row in bad],
            'feedIssues': self.state.get('feed_issues', {})}
        self.store.put_json(f'runs/{self.run_id}/report.json', report, immutable=True)
        self.checkpoint()
        return report


def notify(report, state):
    """Optional generic webhook and external dead-man heartbeat; never hide job errors."""
    targets = []
    if report['status'] in {'success', 'no_new'} and os.environ.get('ARTFOLIO_HEARTBEAT_URL'):
        targets.append(urllib.request.Request(os.environ['ARTFOLIO_HEARTBEAT_URL'], method='GET'))
    if os.environ.get('ARTFOLIO_ALERT_WEBHOOK') and (state.get('failed_runs', 0) >= 3 or report['counts']['quarantined']):
        targets.append(urllib.request.Request(os.environ['ARTFOLIO_ALERT_WEBHOOK'], data=json_bytes({'text': f"ARTFOLIO {report['status']}: {json.dumps(report['counts'])}"}), headers={'Content-Type': 'application/json'}))
    for request in targets:
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read(1024)
        except Exception:
            print('::warning::Monitoring endpoint failed; check its configuration', flush=True)


def main(argv=None):
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--through', '--date', type=date.fromisoformat, default=datetime.now(ZoneInfo('Europe/London')).date())
    arguments.add_argument('--retry-quarantined', action='store_true')
    arguments.add_argument('--publish-only', action='store_true')
    arguments.add_argument('--audit', action='store_true')
    arguments.add_argument('--rollback')
    args = arguments.parse_args(argv)
    if sum([args.publish_only, args.audit, bool(args.rollback)]) > 1:
        arguments.error('Choose only one maintenance mode')
    if args.through > datetime.now(ZoneInfo('Europe/London')).date():
        arguments.error('Future batch dates are not accepted')
    run_id = datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    report, runner = None, None
    parser.DEADLINE = time.monotonic() + 2100
    try:
        store = S3Store()
        with Lease(store, run_id) as lease:
            runner = Runner(store, lease, run_id)
            if args.rollback:
                runner.rollback(args.rollback)
            elif args.audit:
                runner.audit()
            else:
                if not args.publish_only:
                    runner.collect(args.through, args.retry_quarantined)
                runner.publish()
            report = runner.report()
        notify(report, runner.state)
        return {'success': 0, 'no_new': 0, 'partial': 2, 'failed': 1}[report['status']]
    except LeaseBusy:
        report = {'runId': run_id, 'status': 'locked', 'finishedAt': now()}
        return 0
    except Exception as error:
        report = {'runId': run_id, 'status': 'failed', 'finishedAt': now(), 'error': str(error)[:1500]}
        if runner:
            try:
                store.put_json(f'runs/{run_id}/failure.json', report, immutable=True)
            except Exception:
                pass
        print('::error::Daily content run failed; previous release remains available', flush=True)
        return 1
    finally:
        if report:
            save(acquisition.ROOT / 'data' / 'last-run.json', report)
            print(json.dumps(report), flush=True)
            if os.environ.get('GITHUB_STEP_SUMMARY'):
                with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as handle:
                    handle.write('### ARTFOLIO content run\n\n```json\n' + json.dumps(report, indent=2) + '\n```\n')


if __name__ == '__main__':
    raise SystemExit(main())
