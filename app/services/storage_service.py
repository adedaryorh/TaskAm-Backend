import boto3
from botocore.client import Config as BotoConfig

from app.core.config import settings

_s3_client = None


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint_url or None,
            aws_access_key_id=settings.storage_access_key_id or None,
            aws_secret_access_key=settings.storage_secret_access_key or None,
            region_name=settings.storage_region,
            config=BotoConfig(signature_version="s3v4"),
        )
    return _s3_client


def upload_bytes(key: str, data: bytes, content_type: str) -> str:
    """
    Backend-initiated upload (e.g. WhatsApp voice notes fetched server-side).
    NOT used for student deliverables — those go through presigned URLs
    (see generate_presigned_put_url in Phase 8) so the backend never proxies
    those binaries.
    """
    get_s3_client().put_object(
        Bucket=settings.storage_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def download_bytes(key: str) -> bytes:
    obj = get_s3_client().get_object(Bucket=settings.storage_bucket, Key=key)
    return obj["Body"].read()


def generate_presigned_put_url(key: str, content_type: str) -> str:
    return get_s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.storage_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=settings.presigned_url_expiry,
    )


def generate_presigned_get_url(key: str) -> str:
    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.storage_bucket, "Key": key},
        ExpiresIn=settings.presigned_url_expiry,
    )
