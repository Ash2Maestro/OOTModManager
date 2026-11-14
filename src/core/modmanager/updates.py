"""Read-only GitHub release tracking, separate from compatibility/install decisions."""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class UpdateSource:
    repository: str
    tag_prefix: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise ValueError("Dépôt GitHub attendu : propriétaire/dépôt")
        if not self.tag_prefix:
            raise ValueError("Un préfixe de tags propre au mod est nécessaire")


REXCRAFT = "REXCRAFT88/OOT-Mods-by-rexcraft88"
SOURCES = {slug: UpdateSource(REXCRAFT, prefix + "-v") for slug, prefix in (
    ("item-wheel", "item-wheel"), ("manual-shield", "manual-shield"),
    ("wheel-and-shield", "wheel-and-shield"), ("hero-unified", "hero-mode-unified"),
    ("hero-core", "hero-core"), ("hero-with-stamina", "hero-with-stamina"),
    ("hero-without-stamina", "hero-without-stamina"))}


def version_key(value):
    """Order the supported numeric/beta/rc versions, fail closed for other schemes."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?", value)
    if not match:
        return None
    major, minor, patch, channel, number = match.groups()
    return (int(major), int(minor), int(patch),
            {"alpha": 0, "beta": 1, "rc": 2, None: 3}[channel], int(number or 0))


def select_release(source, installed_version, releases, include_prereleases=False):
    current = version_key(installed_version)
    if current is None:
        raise ValueError("Version installée non comparable : " + installed_version)
    choices = []
    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft") or not tag.startswith(source.tag_prefix):
            continue
        version = tag[len(source.tag_prefix):]
        key = version_key(version)
        if key is None or (not include_prereleases and (release.get("prerelease") or key[3] < 3)):
            continue
        expected_url = "https://github.com/" + source.repository + "/releases/tag/"
        url = release.get("html_url", "")
        if not url.startswith(expected_url):
            continue
        choices.append((key, tag, version, release))
    if not choices:
        return {"status": "unknown", "installed": installed_version,
                "message": "Aucune release correspondante dans le canal choisi ; état inconnu."}
    key, tag, version, release = max(choices, key=lambda item: (item[0], item[1]))
    newer = key > current
    return {"status": "available" if newer else "current", "installed": installed_version,
            "version": version, "tag": tag, "url": release["html_url"],
            "notes": release.get("body") or "", "prerelease": bool(release.get("prerelease")) or key[3] < 3,
            "compatibility": "unverified" if newer else "unchanged",
            "message": ("Nouvelle release détectée — compatibilité Longshot à vérifier." if newer
                        else "Aucune version supérieure dans les releases consultées.")}


def fetch_releases(source):
    """Bounded pagination; no authentication, downloads, checkout changes or installation."""
    releases = []
    for page in range(1, 11):
        url = "https://api.github.com/repos/%s/releases?per_page=100&page=%d" % (source.repository, page)
        request = Request(url, headers={"Accept": "application/vnd.github+json",
                                       "User-Agent": "OOTModManager-release-check"})
        with urlopen(request, timeout=15) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Réponse GitHub trop volumineuse")
        batch = json.loads(raw)
        if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
            raise ValueError("Réponse GitHub inattendue")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
    raise ValueError("Trop de releases : vérification incomplète, consulter le dépôt")
