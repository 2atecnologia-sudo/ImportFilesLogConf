import sys
from src.config_ui import ConfigUI

if __name__ == "__main__":
    if "--about" in sys.argv:
        initial_tab = "about"
    elif "--status" in sys.argv:
        initial_tab = "status"
    else:
        initial_tab = "config"

    app = ConfigUI(initial_tab=initial_tab)
    app.mainloop()