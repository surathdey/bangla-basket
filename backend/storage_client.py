"""MinIO (S3-compatible) object storage client.

Replaces the Emergent Managed Object Storage client with a self-hosted
MinIO bucket.  The interface is unchanged (``init_storage`` /
``put_object`` / ``get_object``), so server.py needs no changes:

* Objects are addressed by the same ``path`` keys as before, so the
  ``/api/files/{path}`` route and the migration script (which enumerates
  image paths from the database) keep working unchanged.
* There are no public URLs -- reads are streamed back through our own API
  (see the /api/files/{path} route in server.py).
* No ``list`` API is needed: the migration enumerates paths from DB rows.

Configuration (environment, placeholders in .env.example):
  MINIO_ENDPOINT    e.g. http://minio:9000 inside Docker, http://localhost:9000 locally
  MINIO_ACCESS_KEY / MINIO_SECRET_KEY / MINIO_BUCKET
"""
import logging
import os

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger("storage")

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "bangla-basket")

# Path prefix for uploaded catalog images (kept identical to the old client:
# uploads go to "<APP_NAME>/grocery/<file>", served as /api/files/<path>).
APP_NAME = "bongconnekt"

_s3 = None


def _get_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY or None,
            aws_secret_access_key=MINIO_SECRET_KEY or None,
            region_name="us-east-1",
            config=boto3.session.Config(signature_version="s3v4"),
        )
    return _s3


def init_storage():
    """Call once; idempotent. Ensures the bucket exists. Returns its name."""
    client = _get_client()
    try:
        client.head_bucket(Bucket=MINIO_BUCKET)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "404":
            client.create_bucket(Bucket=MINIO_BUCKET)
        else:
            raise
    return MINIO_BUCKET


def put_object(path: str, data: bytes, content_type: str) -> dict:
    """Upload bytes (overwrites silently). Returns {"path","size","etag"}."""
    init_storage()
    try:
        resp = _get_client().put_object(
            Bucket=MINIO_BUCKET, Key=path, Body=data,
            ContentType=content_type)
        return {"path": path, "size": len(data),
                "etag": resp.get("ETag", "").strip('"')}
    except Exception as e:
        log.warning(f"[storage] put failed for {path}: {e}")
        raise


def get_object(path: str):
    """Download. Returns (content_bytes, content_type)."""
    init_storage()
    resp = _get_client().get_object(Bucket=MINIO_BUCKET, Key=path)
    return resp["Body"].read(), resp.get(
        "ContentType", "application/octet-stream")
