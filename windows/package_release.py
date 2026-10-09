"""Distribute only the frozen runtime and public instructions, never local data."""
import hashlib
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def package():
    bundle=ROOT/"dist/TimesGateAI"
    for name in ("TimesGate.exe","TimesGateCLI.exe"):
        if not (bundle/name).is_file():
            raise ValueError(f"Built {name} not found.")
    shutil.copyfile(ROOT/"windows/PORTABLE-README.txt",bundle/"README.txt")
    paths=[]
    for path in bundle.rglob("*"):
        if not path.is_file():
            continue
        relative=path.relative_to(bundle)
        if relative.parts[0] not in ("_internal","TimesGate.exe","TimesGateCLI.exe","README.txt"):
            raise ValueError(f"Unexpected file in the release: {relative}")
        if path.name.endswith(".local.json") or any(part in ("output",".codex",".claude",".venv") for part in relative.parts):
            raise ValueError(f"Personal data must not be packaged: {relative}")
        paths.append(path)
    releases=ROOT/"releases"
    releases.mkdir(exist_ok=True)
    target=releases/"TimesGateAI-Windows-x64.zip"
    temporary=target.with_suffix(".tmp")
    with zipfile.ZipFile(temporary,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(paths):
            archive.write(path,Path("TimesGateAI")/path.relative_to(bundle))
    temporary.replace(target)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n",encoding="ascii")
    print(f"{target} ({target.stat().st_size/1048576:.1f} MB)")
    print(f"SHA256: {digest}")


if __name__=="__main__":
    package()
