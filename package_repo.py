"""Package a clean committed repository; never push or modify Git history.

Produces a source ZIP, full-history Git bundle, and SHA-256 manifest under dist/.
Requires only Python's standard library and Git. Excludes untracked/ignored files.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd).decode("utf-8").strip()


def package(output_dir):
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("Commit all intended tools and notes before packaging; working tree is not clean")
    revision = git("rev-parse", "HEAD")
    name = "astra-chess-" + revision[:12]
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".building-", dir=output_dir) as temporary:
        temporary = Path(temporary)
        archive = temporary / (name + ".zip")
        bundle = temporary / (name + ".bundle")
        git("archive", "--format=zip", "--prefix=" + name + "/",
            "--output=" + str(archive), revision)
        git("bundle", "create", str(bundle), "--all")
        git("bundle", "verify", str(bundle))
        files = []
        with zipfile.ZipFile(archive) as zipped:
            for info in zipped.infolist():
                if info.is_dir():
                    continue
                content = zipped.read(info)
                files.append({"path": info.filename.removeprefix(name + "/"),
                              "bytes": len(content),
                              "sha256": hashlib.sha256(content).hexdigest()})
        manifest = {
            "revision": revision,
            "branch": git("branch", "--show-current"),
            "commit_time": git("show", "-s", "--format=%cI", revision),
            "source_file_count": len(files),
            "source_bytes": sum(item["bytes"] for item in files),
            "source_files": files,
            "bundle_refs": git("bundle", "list-heads", str(bundle)).splitlines(),
            "artifacts": [{"file": path.name, "bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                          for path in (archive, bundle)],
        }
        manifest_path = temporary / (name + ".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        checksums = temporary / (name + ".sha256")
        checksums.write_text("".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (archive, bundle, manifest_path)), encoding="utf-8")
        for path in (archive, bundle, manifest_path, checksums):
            target = output_dir / path.name
            path.replace(target)
            print(target)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        package(args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Error: {error}\n")
