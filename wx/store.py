"""Where the textures go: a local folder (testing) or the twr-public R2 bucket (S3 API)."""
from __future__ import annotations

import json
import os
import pathlib

IMMUTABLE = "public, max-age=31536000, immutable"     # run paths never change
SHORT = "public, max-age=60"                           # latest.json


class Local:
    def __init__(self, root: str):
        self.root = pathlib.Path(root)

    def put(self, key: str, body: bytes, ctype: str, cache: str = IMMUTABLE):
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)

    def get_json(self, key: str):
        p = self.root / key
        return json.loads(p.read_text()) if p.exists() else None

    def runs(self, prefix: str) -> list[str]:
        p = self.root / prefix
        return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.exists() else []

    def delete_prefix(self, prefix: str):
        import shutil
        shutil.rmtree(self.root / prefix, ignore_errors=True)


class R2:
    """Needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY (an R2 API token scoped to the bucket)."""

    def __init__(self, bucket: str):
        import boto3
        from botocore.config import Config
        self.bucket = bucket
        self.s3 = boto3.client("s3", endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
                               aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                               region_name="auto", config=Config(retries={"max_attempts": 5, "mode": "standard"}, max_pool_connections=16))

    def put(self, key: str, body: bytes, ctype: str, cache: str = IMMUTABLE):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=ctype, CacheControl=cache)

    def get_json(self, key: str):
        try:
            return json.loads(self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read())
        except self.s3.exceptions.NoSuchKey:
            return None

    def runs(self, prefix: str) -> list[str]:
        out, tok = [], None
        while True:
            kw = dict(Bucket=self.bucket, Prefix=prefix.rstrip("/") + "/", Delimiter="/")
            if tok:
                kw["ContinuationToken"] = tok
            r = self.s3.list_objects_v2(**kw)
            out += [c["Prefix"].rstrip("/").split("/")[-1] for c in r.get("CommonPrefixes", [])]
            if not r.get("IsTruncated"):
                return sorted(out)
            tok = r["NextContinuationToken"]

    def delete_prefix(self, prefix: str):
        tok = None
        while True:
            kw = dict(Bucket=self.bucket, Prefix=prefix.rstrip("/") + "/")
            if tok:
                kw["ContinuationToken"] = tok
            r = self.s3.list_objects_v2(**kw)
            keys = [{"Key": o["Key"]} for o in r.get("Contents", [])]
            for i in range(0, len(keys), 1000):
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys[i:i + 1000]})
            if not r.get("IsTruncated"):
                return
            tok = r["NextContinuationToken"]


def open_store(local: str | None):
    return Local(local) if local else R2(os.environ.get("R2_BUCKET", "twr-public"))
