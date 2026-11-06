"""Demosivujen julkaisu Cloudflare R2:een (S3-yhteensopiva API) ja poisto.

Worker (worker/src/index.ts) palvelee objektit osoitteessa {DEMO_PUBLIC_BASE_URL}/{polku}.
Polku = demon slug (esim. taina-lantiainen-k7x2m) tai ennen slugeja luoduilla demoilla token.
Oman domainin käyttöönotto = DEMO_PUBLIC_BASE_URL-muutos + domain Workeriin Cloudflaressa.

Avaimet vain backend/.env:ssä. R2 API -token: Object Read & Write, vain tähän bucketiin.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

OBJECT_PREFIX = "demos/"


def object_key(public_path: str) -> str:
    return f"{OBJECT_PREFIX}{public_path}.html"


@dataclass(frozen=True)
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: str

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"

    def public_url(self, public_path: str) -> str:
        return f"{self.public_base_url}/{public_path}"


def load_r2_config() -> Optional[R2Config]:
    """None jos jokin asetus puuttuu -> julkaisu ei ole käytössä (503), esikatselu toimii silti."""
    values = {
        "account_id": os.getenv("R2_ACCOUNT_ID", "").strip(),
        "access_key_id": os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        "secret_access_key": os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        "bucket": os.getenv("R2_BUCKET", "").strip(),
        "public_base_url": os.getenv("DEMO_PUBLIC_BASE_URL", "").strip().rstrip("/"),
    }
    if not all(values.values()):
        return None
    if not values["public_base_url"].startswith("https://"):
        logger.warning("DEMO_PUBLIC_BASE_URL pitää olla https-osoite (Worker tai oma domain); julkaisu pois käytöstä")
        return None
    return R2Config(**values)


class ObjectStore(Protocol):
    def put(self, key: str, body: bytes, *, expires_at: Optional[datetime]) -> None: ...
    def delete(self, key: str) -> None: ...


class R2ObjectStore:
    """boto3 S3 -asiakas R2:lle. Luodaan laiskasti, jotta testit ja dev eivät tarvitse avaimia."""

    def __init__(self, config: R2Config) -> None:
        import boto3
        from botocore.config import Config

        self._bucket = config.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name="auto",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=20,
                # boto3 >= 1.36 lisää oletuksena CRC-tarkistussummat, joita R2 ei aina hyväksy
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def put(self, key: str, body: bytes, *, expires_at: Optional[datetime]) -> None:
        metadata = {"expires-at": expires_at.isoformat()} if expires_at else {}
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType="text/html; charset=utf-8",
            CacheControl="no-store",
            Metadata=metadata,
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


class PublishError(Exception):
    pass


def publish_html(store: ObjectStore, public_path: str, html: str, expires_at: Optional[datetime]) -> None:
    try:
        store.put(object_key(public_path), html.encode("utf-8"), expires_at=expires_at)
    except Exception as e:  # botocore-virheet, verkko
        raise PublishError(f"R2 upload failed: {e}") from e


def unpublish(store: ObjectStore, public_path: str) -> bool:
    """True jos poisto onnistui. Virhe vain lokiin: Worker palauttaa silti 410 expires-at-metadatan perusteella."""
    try:
        store.delete(object_key(public_path))
        return True
    except Exception as e:
        logger.error(f"R2-poisto epäonnistui ({object_key(public_path)}): {e}")
        return False
