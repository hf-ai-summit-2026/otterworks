"""Deterministic fixture dataset."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from .config import LIST_HANDLER, base_url, bearer, log

WORDS = (
    "otter river bank reed willow current eddy stone moss lodge kit whisker "
    "paddle splash dive pool ripple shoal salmon trout fern drift dusk dawn"
).split()


def _lorem(rng: random.Random, words: int) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(words))


async def seed(cat: dict[str, Any]) -> dict[str, int]:
    cfg = cat["seed"]
    owner = cfg["owner_id"]
    rng = random.Random(cfg["random_seed"])
    headers = bearer(owner)
    url = base_url(cat)
    created = versions = 0
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=60) as client:
        # title -> (id, current version). A document whose version count is short
        # (an earlier seed was interrupted mid-history) is resumed, not skipped, so
        # the fixture is always the full configured history regardless of retries.
        existing: dict[str, tuple[str, int]] = {}
        page = 1
        while True:
            r = await client.get(
                LIST_HANDLER, params={"owner_id": owner, "page": page, "size": 100}
            )
            r.raise_for_status()
            body = r.json()
            for item in body["items"]:
                existing[item["title"]] = (item["id"], int(item["version"]))
            if page * 100 >= body["total"]:
                break
            page += 1
        want_versions = int(cfg["versions_per_document"])
        partial = sum(1 for _, v in existing.values() if v < want_versions)
        log(
            f"seed: {len(existing)} of {cfg['documents']} documents already present "
            f"for owner {owner} ({partial} with an incomplete version history)"
        )

        sem = asyncio.Semaphore(16)

        async def make(i: int) -> None:
            nonlocal created, versions
            title = f"Incident fixture doc {i:04d}"
            doc_rng = random.Random(cfg["random_seed"] * 1000 + i)
            doc_id, have = existing.get(title, (None, 0))
            if doc_id is not None and have >= want_versions:
                return
            async with sem:
                if doc_id is None:
                    r = await client.post(
                        LIST_HANDLER,
                        json={
                            "title": title,
                            "content": _lorem(doc_rng, cfg["words_per_document"]),
                            "content_type": "text/markdown",
                            "owner_id": owner,
                            "folder_id": cfg["folder_id"],
                        },
                    )
                    if r.status_code != 201:
                        raise RuntimeError(f"seed create {title}: {r.status_code} {r.text[:200]}")
                    doc_id = r.json()["id"]
                    created += 1
                    have = 1
                else:
                    # Replay the deterministic content stream up to the version the
                    # document already has so the resumed history is byte-identical.
                    for _ in range(have):
                        _lorem(doc_rng, cfg["words_per_document"])
                for v in range(have + 1, want_versions + 1):
                    r = await client.put(
                        f"{LIST_HANDLER}{doc_id}",
                        json={
                            "title": title,
                            "content": _lorem(doc_rng, cfg["words_per_document"]),
                            "content_type": "text/markdown",
                            "folder_id": cfg["folder_id"],
                        },
                    )
                    if r.status_code != 200:
                        raise RuntimeError(
                            f"seed version {title} v{v}: {r.status_code} {r.text[:200]}"
                        )
                    versions += 1

        await asyncio.gather(*(make(i) for i in range(cfg["documents"])))
    rng.random()  # keep the seed RNG referenced for future deterministic extensions
    log(f"seed: created {created} documents, {versions} extra versions")
    return {"created": created, "versions": versions}
