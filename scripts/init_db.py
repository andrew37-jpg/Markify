from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.main import startup

if __name__=='__main__':
    startup(); print('Markify database is ready.')
