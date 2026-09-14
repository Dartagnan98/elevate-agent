"""Deploy a local UI overlay compatible with the packaged desktop launcher.

The desktop's stale-server check looks for its packaged asset references in
served HTML. Keep those exact assets available for existing windows and declare
them as compatibility metadata, while executing only the new UI entry point.
This does not modify the signed application or load a second React application.
Run this after building the UI, instead of copying web_dist directly.
"""

import argparse
import hashlib
import html
from pathlib import Path
import re
import shutil


def deploy(built: Path, overlay: Path, packaged: Path) -> None:
    built, overlay, packaged = (p.resolve() for p in (built, overlay, packaged))
    if len({built, overlay, packaged}) != 3:
        raise ValueError("Build, overlay and packaged directories must be distinct")
    index = (built / "index.html").read_text()
    packaged_index = (packaged / "index.html").read_text()
    pattern = r"assets/[A-Za-z0-9_.-]+\.(?:js|css)"
    refs = sorted(set(re.findall(pattern, packaged_index)))
    for root, document in ((built, index), (packaged, packaged_index)):
        for ref in set(re.findall(pattern, document)):
            # Some installed versions keep their entry chunk only in an
            # existing overlay. Preserve that known asset when redeploying.
            if not (root / ref).is_file() and not (root == packaged and (overlay / ref).is_file()):
                raise ValueError(f"Incomplete dashboard build: {root / ref}")
    if "</head>" not in index:
        raise ValueError("Dashboard index is missing its head element")
    # Local hotfixes have previously changed imports without renaming their
    # hashed chunks. Electron can then reuse an old cached hook with a different
    # React instance. Namespace the entire graph by its actual final bytes, so
    # even unchanged filenames cannot cross build generations in the cache.
    assets = sorted(p for p in (built / "assets").rglob("*") if p.is_file())
    digest = hashlib.sha256(b"elevate-overlay-v1\0" + index.encode())
    for source in assets:
        digest.update(source.relative_to(built).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(source.read_bytes()).digest())
    namespace = "build-" + digest.hexdigest()[:20]
    asset_refs = {"assets/" + p.relative_to(built / "assets").as_posix() for p in assets}
    asset_pattern = re.compile(r"assets/[A-Za-z0-9_./-]+")

    def version_references(text):
        return asset_pattern.sub(
            lambda match: match[0].replace("assets/", f"assets/{namespace}/", 1)
            if match[0] in asset_refs else match[0],
            text,
        )

    for source in assets:
        target = overlay / "assets" / namespace / source.relative_to(built / "assets")
        payload = source.read_bytes()
        if source.suffix in {".js", ".css"}:
            payload = version_references(payload.decode()).encode()
        if target.exists() and target.read_bytes() != payload:
            raise ValueError(f"Asset URL collision: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    # Retain old chunks for existing windows and desktop compatibility checks.
    for root in (packaged, built):
        for source in root.rglob("*"):
            if not source.is_file() or source.relative_to(root) == Path("index.html"):
                continue
            if root == built and source.is_relative_to(built / "assets"):
                continue
            target = overlay / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if root == built or not target.exists():
                shutil.copy2(source, target)
    metadata = '<meta name="elevate-desktop-compatible-assets" content="' + html.escape(" ".join(refs), quote=True) + '">\n'
    index = version_references(index).replace("</head>", metadata + "</head>", 1)
    # Switch the entry point only after every referenced file is available.
    temporary = overlay / ".index.html.deploying"
    temporary.write_text(index)
    temporary.replace(overlay / "index.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--built", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--packaged", type=Path, required=True)
    args = parser.parse_args()
    deploy(args.built, args.overlay, args.packaged)
    print("Installed UI overlay with packaged asset compatibility.")
