from pathlib import Path
import zipfile
root=Path(__file__).resolve().parent
module='mag_snap_3d'
(root/'dist').mkdir(exist_ok=True)
with zipfile.ZipFile(root/'dist'/f'{module}-1.1.0.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for name in ['__init__.py','common.py','LEEME.md']:
        archive.write(root/module/name,f'{module}/{name}')
print(root/'dist'/f'{module}-1.1.0.zip')
