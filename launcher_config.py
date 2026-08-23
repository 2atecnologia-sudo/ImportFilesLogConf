import sys
from src.config_ui import ConfigUI

if __name__ == "__main__":
    initial_tab = "status" if "--status" in sys.argv else "config"
    app = ConfigUI(initial_tab=initial_tab)
    app.mainloop()