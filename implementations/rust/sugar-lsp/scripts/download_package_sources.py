#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Download sources for a pip-installed distribution (Maven-class companion).

Part of #4106 / #4107 / #4007.

Resolution:
  1) importlib.metadata → name, version, Project-URL map, direct_url.json
  2) PyPI JSON for exact version → sdist (primary)
  3) unpack into cache_dir / name / version /
  4) print JSON: {ok, root, name, version, source_url, project_urls, via}

Opt-out is enforced by the Rust caller (SUGAR_LSP_DOWNLOAD_SOURCES).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


def _dist_for_module(module: str):
    import importlib.metadata as md

    # Prefer exact distribution name match, then packages_distributions.
    try:
        return md.distribution(module)
    except md.PackageNotFoundError:
        pass
    try:
        mapping = md.packages_distributions()
        names = mapping.get(module) or []
        if names:
            return md.distribution(names[0])
    except Exception:
        pass
    # stdlib / unknown
    return None


def _project_urls(dist) -> dict[str, str]:
    urls: dict[str, str] = {}
    meta = dist.metadata
    # email-message style multi headers
    if hasattr(meta, "get_all"):
        for item in meta.get_all("Project-URL") or []:
            if "," in item:
                label, url = item.split(",", 1)
                urls[label.strip().lower()] = url.strip()
    home = meta.get("Home-page") if meta else None
    if home:
        urls.setdefault("homepage", home)
    return urls


def _direct_url(dist) -> dict:
    try:
        raw = dist.read_text("direct_url.json")
        if raw:
            return json.loads(raw)
    except Exception:
        return None
    return None


def _pypi_sdist_url(name: str, version: str) -> tuple[str, str] | None:
    api = f"https://pypi.org/pypi/{name}/{version}/json"
    req = urllib.request.Request(api, headers={"User-Agent": "sugar-lsp-download-sources/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    for u in data.get("urls") or []:
        if u.get("packagetype") == "sdist" and u.get("url"):
            return u["url"], u.get("filename") or f"{name}-{version}.tar.gz"
    return None


def _extract_archive(blob: bytes, filename: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / ".extract-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    lower = filename.lower()
    if lower.endswith(".zip"):
        zpath = tmp / filename
        zpath.write_bytes(blob)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp)
    else:
        # tar.gz / tar.bz2 / tar
        with tarfile.open(fileobj=__import__("io").BytesIO(blob), mode="r:*") as tf:
            # Python 3.12+ filter; fall back for older
            try:
                tf.extractall(tmp, filter="data")
            except TypeError:
                tf.extractall(tmp)
    # single top-level directory preferred
    kids = [p for p in tmp.iterdir() if p.name != filename]
    if len(kids) == 1 and kids[0].is_dir():
        root = kids[0]
        final = dest / "src"
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(root), str(final))
        shutil.rmtree(tmp, ignore_errors=True)
        return final
    final = dest / "src"
    if final.exists():
        shutil.rmtree(final)
    shutil.move(str(tmp), str(final))
    return final


def download_sources(module: str, cache_dir: Path) -> dict:
    dist = _dist_for_module(module)
    if dist is None:
        return {"ok": False, "error": f"no distribution metadata for module {module!r} (stdlib?)"}

    name = dist.metadata.get("Name") or dist.name
    version = dist.version
    project_urls = _project_urls(dist)
    direct = _direct_url(dist)

    dest = cache_dir / _safe(name) / _safe(version)
    marker = dest / ".sugar-sources-ok"
    src_root = dest / "src"
    if marker.is_file() and src_root.is_dir():
        return {
            "ok": True,
            "root": str(src_root.resolve()),
            "name": name,
            "version": version,
            "via": "cache",
            "project_urls": project_urls,
            "direct_url": direct,
            "source_url": marker.read_text(encoding="utf-8").strip() or None,
        }

    # Prefer exact-version sdist from PyPI
    sdist = None
    try:
        sdist = _pypi_sdist_url(name, version)
    except Exception as e:
        sdist_err = str(e)
    else:
        sdist_err = None


    force_vcs = os.environ.get("SUGAR_LSP_DOWNLOAD_VCS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if sdist and not force_vcs:
        url, filename = sdist
        req = urllib.request.Request(
            url, headers={"User-Agent": "sugar-lsp-download-sources/0.1"}
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                blob = resp.read()
        except urllib.error.URLError as e:
            sdist = None
            sdist_err = f"download failed: {e}"
        else:
            root = _extract_archive(blob, filename, dest)
            marker.write_text(url + "\n", encoding="utf-8")
            (dest / "project_urls.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "version": version,
                        "source_url": url,
                        "project_urls": project_urls,
                        "direct_url": direct,
                        "via": "pypi-sdist",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return {
                "ok": True,
                "root": str(root.resolve()),
                "name": name,
                "version": version,
                "via": "pypi-sdist",
                "source_url": url,
                "project_urls": project_urls,
                "direct_url": direct,
            }

    # VCS fallback / forced clone from Project-URL Source (#4106 follow-up)
    vcs = _vcs_clone(name, version, project_urls, direct, dest)
    if vcs.get("ok"):
        return vcs

    return {
        "ok": False,
        "error": sdist_err
        or vcs.get("error")
        or "no sdist and VCS clone failed",
        "name": name,
        "version": version,
        "project_urls": project_urls,
        "direct_url": direct,
    }


def _pick_vcs_url(project_urls: dict, direct: dict) -> str | None:
    if direct and isinstance(direct, dict):
        url = (direct.get("url") or "").strip()
        if url.startswith("git+") or "github.com" in url or "gitlab" in url:
            return url.removeprefix("git+").split("#", 1)[0]
    for key in ("source", "repository", "code", "homepage"):
        u = (project_urls.get(key) or "").strip()
        if not u:
            continue
        if "github.com" in u or "gitlab.com" in u or u.endswith(".git"):
            return u.rstrip("/")
    return None


def _vcs_clone(name, version, project_urls, direct, dest: Path):
    import subprocess

    url = _pick_vcs_url(project_urls, direct)
    if not url:
        return {"ok": False, "error": "no VCS URL in Project-URL / direct_url"}
    # normalize github tree URLs
    if url.endswith("/"):
        url = url[:-1]
    if not url.endswith(".git") and "github.com" in url:
        url_git = url + ".git"
    else:
        url_git = url

    dest.mkdir(parents=True, exist_ok=True)
    final = dest / "src"
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True)
    # shallow clone; try version tag
    env = os.environ.copy()
    cmds = [
        ["git", "clone", "--depth", "1", "--branch", version, url_git, str(final)],
        ["git", "clone", "--depth", "1", "--branch", f"v{version}", url_git, str(final)],
        ["git", "clone", "--depth", "1", url_git, str(final)],
    ]
    last_err = None
    for cmd in cmds:
        if final.exists():
            shutil.rmtree(final)
            final.mkdir(parents=True)
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
            )
        except Exception as e:
            last_err = str(e)
            continue
        if r.returncode == 0:
            marker = dest / ".sugar-sources-ok"
            marker.write_text(url_git + "\n", encoding="utf-8")
            (dest / "project_urls.json").write_text(
                json.dumps(
                    {
                        "name": name,
                        "version": version,
                        "source_url": url_git,
                        "project_urls": project_urls,
                        "direct_url": direct,
                        "via": "vcs-clone",
                        "git_cmd": cmd,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            return {
                "ok": True,
                "root": str(final.resolve()),
                "name": name,
                "version": version,
                "via": "vcs-clone",
                "source_url": url_git,
                "project_urls": project_urls,
                "direct_url": direct,
            }
        last_err = (r.stderr or r.stdout or "")[-500:]
    return {
        "ok": False,
        "error": f"git clone failed: {last_err}",
        "name": name,
        "version": version,
        "project_urls": project_urls,
        "source_url": url,
    }



def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "usage: download_package_sources.py <module> <cache_dir>",
                }
            )
        )
        return 2
    module, cache = argv[1], Path(argv[2])
    try:
        result = download_sources(module, cache)
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
