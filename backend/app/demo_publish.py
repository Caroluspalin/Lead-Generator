"""Demosivujen julkaisu Cloudflare R2:een (S3-yhteensopiva API) ja poisto.

Worker (worker/src/index.ts) palvelee objektit osoitteessa {DEMO_PUBLIC_BASE_URL}/{polku}.
Polku = demon slug (esim. taina-lantiainen-k7x2m) tai ennen slugeja luoduilla demoilla token.
Oman domainin käyttöönotto = DEMO_PUBLIC_BASE_URL-muutos + domain Workeriin Cloudflaressa.

Avaimet vain backend/.env:ssä. R2 API -token: Object Read & Write, vain tähän bucketiin.

Version 2 demoilla on myös erilliset CSS/JS/fonttitiedostot. Ne ladataan avaimella
assets/{ryhmä}/{tiiviste}/{tiedosto} ennen HTML:ää, eikä niitä koskaan poisteta: jo lähetetty
demo viittaa aina omaan versioonsa, vaikka pohjaa muokattaisiin myöhemmin. Worker palvelee
ne osoitteessa /a/{ryhmä}/{tiedosto}?v={tiiviste} ja valitsee demon CSP:n metadatan format-arvosta.
"""
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol

from .demo_site import DemoAsset

logger = logging.getLogger(__name__)

OBJECT_PREFIX = "demos/"
ASSET_PREFIX = "assets/"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


def object_key(public_path: str) -> str:
    return f"{OBJECT_PREFIX}{public_path}.html"


def asset_key(asset: DemoAsset) -> str:
    return f"{ASSET_PREFIX}{asset.group}/{asset.digest}/{asset.name}"


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
    def put(
        self,
        key: str,
        body: bytes,
        *,
        expires_at: Optional[datetime],
        content_type: str = HTML_CONTENT_TYPE,
        cache_control: str = "no-store",
        metadata: Optional[dict[str, str]] = None,
    ) -> None: ...
    def exists(self, key: str) -> bool: ...
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

    def put(
        self,
        key: str,
        body: bytes,
        *,
        expires_at: Optional[datetime],
        content_type: str = HTML_CONTENT_TYPE,
        cache_control: str = "no-store",
        metadata: Optional[dict[str, str]] = None,
    ) -> None:
        meta = dict(metadata or {})
        if expires_at:
            meta["expires-at"] = expires_at.isoformat()
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl=cache_control,
            Metadata=meta,
        )

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)


class PublishError(Exception):
    pass


# Tämän prosessin jo lataamat tiedostot: sama avain = sama sisältö, joten tarkistus riittää kerran
_uploaded_assets: set[str] = set()


def upload_assets(store: ObjectStore, assets: Sequence[DemoAsset]) -> None:
    for asset in assets:
        key = asset_key(asset)
        if key in _uploaded_assets:
            continue
        if not store.exists(key):
            store.put(key, asset.body, expires_at=None, content_type=asset.content_type,
                      cache_control=ASSET_CACHE_CONTROL)
        _uploaded_assets.add(key)


def publish_html(
    store: ObjectStore,
    public_path: str,
    html: str,
    expires_at: Optional[datetime],
    assets: Sequence[DemoAsset] = (),
) -> None:
    """Tiedostot ensin, sitten HTML: demo ei koskaan viittaa tiedostoon, jota ei vielä ole."""
    try:
        upload_assets(store, assets)
        store.put(
            object_key(public_path), html.encode("utf-8"), expires_at=expires_at,
            metadata={"format": "2"} if assets else None,
        )
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
