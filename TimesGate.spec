# Both executables share the same Python, Pillow and Tcl/Tk runtime directory.
from pathlib import Path
import sys
from importlib.metadata import distribution

project=Path(SPECPATH)
licenses=[]
python_license=Path(sys.base_prefix)/"LICENSE.txt"
if python_license.is_file():
    licenses.append((str(python_license),"licenses/Python"))
pillow=distribution("Pillow")
for item in pillow.files or []:
    if "licenses" in item.parts and Path(pillow.locate_file(item)).is_file():
        licenses.append((str(pillow.locate_file(item)),"licenses/Pillow"))

a=Analysis([str(project/"portable_entry.py")],pathex=[str(project)],binaries=[],datas=licenses,
           hiddenimports=[],hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[],noarchive=False)
pyz=PYZ(a.pure)
desktop=EXE(pyz,a.scripts,[],exclude_binaries=True,name="TimesGate",debug=False,
            bootloader_ignore_signals=False,strip=False,upx=False,console=False)
helper=EXE(pyz,a.scripts,[],exclude_binaries=True,name="TimesGateCLI",debug=False,
           bootloader_ignore_signals=False,strip=False,upx=False,console=True)
bundle=COLLECT(desktop,helper,a.binaries,a.datas,strip=False,upx=False,name="TimesGateAI")
