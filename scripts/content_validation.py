"""Validate display fields before any public object is uploaded."""
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from content_store import ContentIssue


def published_date(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContentIssue('Publication date must be an ISO date or timestamp')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value).isoformat()
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Missing timezone')
        return stamp.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError) as error:
        raise ContentIssue('Invalid publication date or missing timezone') from error


def require_text(value, field, empty=False):
    if not isinstance(value, str) or len(value) > 200_000 or (not empty and not value.strip()):
        raise ContentIssue('Invalid text field: ' + field)


def require_url(value, field, https=False):
    require_text(value, field)
    try:
        url = urlsplit(value)
        valid = url.scheme in ({'https'} if https else {'https', 'http'}) and url.hostname and not url.username and not url.password and not re.search(r'\s', value)
        url.port  # Reject malformed ports before publishing a browser-facing URL.
    except ValueError:
        valid = False
    if not valid:
        raise ContentIssue('Invalid URL field: ' + field)


def validate_detail(detail):
    if not isinstance(detail, dict) or not isinstance(detail.get('id'), str) or not re.fullmatch(r'[a-z0-9-]{1,100}', detail['id']):
        raise ContentIssue('Invalid article identity')
    for field in ['title', 'sourceLabel']:
        require_text(detail.get(field), field)
    if detail.get('subtitle') is not None:
        require_text(detail['subtitle'], 'subtitle', empty=True)
    require_url(detail.get('originalUrl'), 'originalUrl', https=True)
    try:
        if date.fromisoformat(detail['batchDate']).isoformat() != detail['batchDate']:
            raise ValueError('Invalid batch date')
    except (KeyError, TypeError, ValueError) as error:
        raise ContentIssue('Invalid batch date') from error
    published_date(detail.get('publishedAt'))
    require_text(detail.get('fetchedAt'), 'fetchedAt')
    if 'T' not in detail['fetchedAt']:
        raise ContentIssue('Missing capture timestamp')
    published_date(detail['fetchedAt'])
    images = detail.get('images')
    if not isinstance(images, list) or not 1 <= len(images) <= 100:
        raise ContentIssue('Invalid image collection')
    identifiers = set()
    for position, image in enumerate(images, 1):
        if not isinstance(image, dict) or not isinstance(image.get('id'), str) or not re.fullmatch(r'[a-z0-9-]{1,120}', image['id']) or image['id'] in identifiers:
            raise ContentIssue('Invalid or duplicate image identity')
        identifiers.add(image['id'])
        if type(image.get('position')) is not int or image['position'] != position:
            raise ContentIssue('Invalid image order')
        for field in ['width', 'height', 'frames']:
            if type(image.get(field)) is not int or image[field] <= 0:
                raise ContentIssue('Invalid image ' + field)
        if image['width'] * image['height'] > 40_000_000:
            raise ContentIssue('Image exceeds processing limit')
        if 'previewWidth' in image and (type(image['previewWidth']) is not int or not 0 < image['previewWidth'] <= image['width']):
            raise ContentIssue('Invalid preview width')
        for field in ['src', 'preview']:
            require_url(image.get(field), field, https=True)
        for field in ['caption', 'alt']:
            require_text(image.get(field), field, empty=True)
    body = detail.get('bodyParagraphs')
    if not isinstance(body, list) or len(body) > 10_000:
        raise ContentIssue('Invalid reading body')
    for paragraph in body:
        require_text(paragraph, 'paragraph')
    credits = detail.get('credits')
    if not isinstance(credits, list) or len(credits) > 500:
        raise ContentIssue('Invalid credits')
    for credit in credits:
        if not isinstance(credit, dict):
            raise ContentIssue('Invalid credit entry')
        require_text(credit.get('label'), 'credit label')
        require_text(credit.get('text'), 'credit text', empty=True)
        links = credit.get('links', [])
        if not isinstance(links, list) or len(links) > 500:
            raise ContentIssue('Invalid credit links')
        for link in links:
            if not isinstance(link, dict):
                raise ContentIssue('Invalid credit link')
            require_text(link.get('label'), 'link label')
            require_url(link.get('url'), 'credit link')
