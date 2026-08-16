import os
import sys

# Em modo empacotado, queremos que config.ini fique ao lado do exe
if getattr(sys, "frozen", False):
    os.chdir(os.path.dirname(sys.executable))

# IMPORT estático (PyInstaller enxerga e empacota o pacote src)
from src.config_ui import ConfigUI

if __name__ == "__main__":
    app = ConfigUI()
    app.mainloop()