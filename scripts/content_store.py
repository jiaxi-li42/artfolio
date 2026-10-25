"""Atomic local checkpoints and conditional S3 state/release writes."""
import base64
import hashlib
import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class ContentIssue(ValueError):
    """Content cannot be published safely with the current source adapter."""


class RetryableFetchError(OSError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class Conflict(RuntimeError):
    pass


class LeaseBusy(Conflict):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def atomic_write(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save(path, value):
    atomic_write(path, json_bytes(value))


class S3Store:
    def __init__(self):
        import boto3
        from botocore.config import Config
        required = ["ARTFOLIO_STATE_BUCKET", "ARTFOLIO_PUBLIC_BUCKET", "ARTFOLIO_CONTENT_BASE_URL", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise ValueError("Missing configuration: " + ", ".join(missing))
        self.private = os.environ["ARTFOLIO_STATE_BUCKET"]
        self.public = os.environ["ARTFOLIO_PUBLIC_BUCKET"]
        if self.private == self.public:
            raise ValueError("Private archives/state and public releases require separate buckets")
        self.base_url = os.environ["ARTFOLIO_CONTENT_BASE_URL"].rstrip("/") + "/"
        endpoint = os.environ.get("ARTFOLIO_S3_ENDPOINT") or None
        for url in [self.base_url, endpoint]:
            if url:
                parts = urlsplit(url)
                if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                    raise ValueError("Storage endpoint and content base must be plain HTTPS URLs")
        self.prefix = os.environ.get("ARTFOLIO_S3_PREFIX", "artfolio").strip("/")
        if not self.prefix or any(part in {"", ".", ".."} for part in self.prefix.split("/")) or "\\" in self.prefix:
            raise ValueError("Invalid S3 prefix")
        self.client = boto3.client("s3", endpoint_url=endpoint, region_name=os.environ.get("ARTFOLIO_S3_REGION", "auto"),
            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
            aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
            config=Config(connect_timeout=10, read_timeout=30, retries={"mode": "standard", "total_max_attempts": 3},
                request_checksum_calculation="when_required", response_checksum_validation="when_required"))

    def key(self, key):
        if key.startswith("/") or "\\" in key or any(part in {"", ".", ".."} for part in key.split("/")):
            raise ValueError("Invalid object key")
        return self.prefix + "/" + key

    def get(self, key, public=False, limit=16_000_000):
        from botocore.exceptions import ClientError
        try:
            result = self.client.get_object(Bucket=self.public if public else self.private, Key=self.key(key))
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                return None, None
            raise
        with result["Body"] as body:
            raw = body.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Stored object exceeds its read bound")
        return raw, result["ETag"]

    def get_json(self, key, public=False):
        raw, etag = self.get(key, public)
        return (json.loads(raw) if raw is not None else None), etag

    def put(self, key, raw, public=False, expected=None, immutable=False, content_type="application/json"):
        from botocore.exceptions import ClientError
        arguments = {"Bucket": self.public if public else self.private, "Key": self.key(key), "Body": raw,
            "ContentType": content_type, "ContentMD5": base64.b64encode(hashlib.md5(raw).digest()).decode(),
            "CacheControl": "public,max-age=31536000,immutable" if immutable else "no-store"}
        if immutable or expected is None:
            arguments["IfNoneMatch"] = "*"
        else:
            arguments["IfMatch"] = expected
        try:
            return self.client.put_object(**arguments)["ETag"]
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] in {409, 412}:
                if immutable:
                    previous, etag = self.get(key, public, max(len(raw), 16_000_000))
                    if previous == raw:
                        return etag
                raise Conflict("Object changed concurrently: " + key) from error
            raise

    def put_json(self, key, value, **kwargs):
        return self.put(key, json_bytes(value), **kwargs)

    def put_file(self, key, path, public=False, content_type="application/octet-stream"):
        from botocore.exceptions import ClientError
        path = Path(path)
        sha, md5 = hashlib.sha256(), hashlib.md5()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
                md5.update(chunk)
        checksum = sha.hexdigest()
        arguments = {"Bucket": self.public if public else self.private, "Key": self.key(key)}
        try:
            previous = self.client.head_object(**arguments)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
        else:
            if previous.get("Metadata", {}).get("sha256") == checksum and previous["ContentLength"] == path.stat().st_size:
                return checksum
            raise Conflict("Immutable file already exists with different content: " + key)
        with path.open("rb") as handle:
            try:
                self.client.put_object(**arguments, Body=handle, ContentLength=path.stat().st_size,
                    ContentMD5=base64.b64encode(md5.digest()).decode(), Metadata={"sha256": checksum},
                    ContentType=content_type, CacheControl="public,max-age=31536000,immutable" if public else "no-store", IfNoneMatch="*")
            except ClientError as error:
                if error.response["ResponseMetadata"]["HTTPStatusCode"] not in {409, 412}:
                    raise
        stored = self.client.head_object(**arguments)
        if stored.get("Metadata", {}).get("sha256") != checksum or stored["ContentLength"] != path.stat().st_size:
            raise Conflict("Uploaded file failed verification: " + key)
        return checksum

    def url(self, key):
        return self.base_url + key


class Lease:
    """Renewed lease; stale owners cannot renew or release another owner's lock."""
    def __init__(self, store, owner, ttl=600):
        self.store, self.owner, self.ttl = store, owner, ttl
        self.etag = None
        self.expires = 0
        self.error = None
        self.stop = threading.Event()
        self.mutex = threading.Lock()

    def __enter__(self):
        previous, etag = self.store.get_json("state/lease.json")
        if previous and previous.get("expires", 0) > time.time():
            raise LeaseBusy("Another collection run holds the storage lease")
        try:
            self.etag = self.store.put_json("state/lease.json", {"owner": self.owner, "expires": time.time() + self.ttl}, expected=etag)
        except Conflict as error:
            raise LeaseBusy('Another run acquired the storage lease') from error
        self.expires = time.time() + self.ttl
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()
        return self

    def renew(self):
        with self.mutex:
            if self.error or time.time() >= self.expires:
                raise Conflict("Storage lease was lost") from self.error
            self.etag = self.store.put_json("state/lease.json", {"owner": self.owner, "expires": time.time() + self.ttl}, expected=self.etag)
            self.expires = time.time() + self.ttl

    def ensure(self):
        if self.error or time.time() >= self.expires:
            raise Conflict("Storage lease was lost") from self.error

    def _heartbeat(self):
        while not self.stop.wait(self.ttl / 6):
            try:
                self.renew()
            except Exception as error:
                self.error = error
                return

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=35)
        with self.mutex:
            if self.error is None:
                try:
                    self.store.put_json("state/lease.json", {"owner": self.owner, "expires": 0}, expected=self.etag)
                except Exception:
                    pass  # Expiry recovers a failed release; never delete a newer owner's lock.
