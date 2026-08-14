import os
import configparser
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=["txt", "xml"], default="txt")
    args = parser.parse_args()

    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config_path = os.path.join(base, "config.ini")

    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")

    if "watch" not in cfg: cfg["watch"] = {}
    if "logging" not in cfg: cfg["logging"] = {}
    if "input" not in cfg: cfg["input"] = {}

    cfg["watch"]["input_dir"] = os.path.join(base, "data", "entrada")
    cfg["watch"]["processed_dir"] = os.path.join(base, "data", "processados")
    cfg["watch"]["error_dir"] = os.path.join(base, "data", "erros")
    cfg["watch"]["duplicate_dir"] = os.path.join(base, "data", "duplicados")

    cfg["logging"]["log_dir"] = os.path.join(base, "logs")

    cfg["input"]["format"] = args.format

    # cria as pastas
    os.makedirs(cfg["watch"]["input_dir"], exist_ok=True)
    os.makedirs(cfg["watch"]["processed_dir"], exist_ok=True)
    os.makedirs(cfg["watch"]["error_dir"], exist_ok=True)
    os.makedirs(cfg["watch"]["duplicate_dir"], exist_ok=True)
    os.makedirs(cfg["logging"]["log_dir"], exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        cfg.write(f)

    print(f"OK: config.ini ajustado para pastas locais | format={args.format}")

if __name__ == "__main__":
    main()