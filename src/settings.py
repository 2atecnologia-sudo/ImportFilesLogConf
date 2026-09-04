import os
import sys
import shutil
import configparser
from dataclasses import dataclass


if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.ini.example")


def ensure_config_exists():
    if os.path.exists(CONFIG_PATH):
        return
    if os.path.exists(EXAMPLE_PATH):
        shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
    else:
        raise FileNotFoundError("Não existe config.ini e nem config.ini.example para gerar um.")


def as_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "sim", "s")


@dataclass(frozen=True)
class SqlSettings:
    driver: str
    server: str
    database: str
    trusted_connection: bool
    user: str
    password: str


@dataclass(frozen=True)
class WatchSettings:
    input_dir: str
    processed_dir: str
    error_dir: str
    duplicate_dir: str


@dataclass(frozen=True)
class TxtSettings:
    delimiter: str
    encoding: str
    has_header: bool


@dataclass(frozen=True)
class AppSettings:
    status_inicial: str
    group_items: bool
    input_format: str  # "xml" ou "txt"


@dataclass(frozen=True)
class LoggingSettings:
    log_dir: str
    level: str


@dataclass(frozen=True)
class OutputSettings:
    output_dir: str
    export_numdoc: bool
    export_codigo: bool
    export_gtin: bool
    export_descricao: bool
    export_qtdeesperada: bool
    export_qtdelida: bool
    export_saldo: bool
    individual_file: bool
    daily_file: bool
    delimiter: str
    file_name_mode: str      # "numdoc", "numdoc_data" ou "numdoc_data_hora"


@dataclass(frozen=True)
class Settings:
    sql: SqlSettings
    watch: WatchSettings
    txt: TxtSettings
    app: AppSettings
    logging: LoggingSettings
    output: OutputSettings


def load_settings() -> Settings:
    ensure_config_exists()

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    sql = SqlSettings(
        driver=cfg.get("sql", "driver", fallback="ODBC Driver 18 for SQL Server").strip(),
        server=cfg.get("sql", "server", fallback="127.0.0.1").strip(),
        database=cfg.get("sql", "database", fallback="").strip(),
        trusted_connection=as_bool(cfg.get("sql", "trusted_connection", fallback="no")),
        user=cfg.get("sql", "user", fallback="").strip(),
        password=cfg.get("sql", "password", fallback=""),
    )

    watch = WatchSettings(
        input_dir=cfg.get("watch", "input_dir", fallback=r"C:\MIS\entrada").strip(),
        processed_dir=cfg.get("watch", "processed_dir", fallback=r"C:\MIS\processados").strip(),
        error_dir=cfg.get("watch", "error_dir", fallback=r"C:\MIS\erros").strip(),
        duplicate_dir=cfg.get("watch", "duplicate_dir", fallback=r"C:\MIS\duplicados").strip(),
    )

    txt = TxtSettings(
        delimiter=cfg.get("txt", "delimiter", fallback=","),
        encoding=cfg.get("txt", "encoding", fallback="utf-8").strip(),
        has_header=as_bool(cfg.get("txt", "has_header", fallback="yes")),
    )

    fmt = cfg.get("input", "format", fallback="xml").strip().lower()
    if fmt not in ("xml", "txt"):
        fmt = "xml"

    status_ini = cfg.get("app", "status_inicial", fallback="PEN").strip().upper()[:3]
    if len(status_ini) != 3:
        status_ini = "PEN"

    app = AppSettings(
        status_inicial=status_ini,
        group_items=as_bool(cfg.get("app", "group_items", fallback="no")),
        input_format=fmt,
    )

    logging = LoggingSettings(
        log_dir=cfg.get("logging", "log_dir", fallback=r"C:\MIS\logs").strip(),
        level=cfg.get("logging", "level", fallback="INFO").strip().upper(),
    )

    # Compatibilidade com config.ini de versões anteriores.
    product_id_antigo = cfg.get("output", "product_id", fallback="ambos").strip().lower()
    if product_id_antigo not in ("codigo", "gtin", "ambos"):
        product_id_antigo = "ambos"

    include_numdoc_antigo = as_bool(
        cfg.get("output", "include_numdoc", fallback="yes")
    )

    file_name_mode = cfg.get(
        "output",
        "file_name_mode",
        fallback="numdoc_data_hora",
    ).strip().lower()
    if file_name_mode not in ("numdoc", "numdoc_data", "numdoc_data_hora"):
        file_name_mode = "numdoc_data_hora"

    output = OutputSettings(
        output_dir=cfg.get("output", "output_dir", fallback=r"C:\MIS\saida").strip(),
        export_numdoc=as_bool(
            cfg.get(
                "output",
                "export_numdoc",
                fallback="yes" if include_numdoc_antigo else "no",
            )
        ),
        export_codigo=as_bool(
            cfg.get(
                "output",
                "export_codigo",
                fallback="yes" if product_id_antigo in ("codigo", "ambos") else "no",
            )
        ),
        export_gtin=as_bool(
            cfg.get(
                "output",
                "export_gtin",
                fallback="yes" if product_id_antigo in ("gtin", "ambos") else "no",
            )
        ),
        export_descricao=as_bool(
            cfg.get("output", "export_descricao", fallback="no")
        ),
        export_qtdeesperada=as_bool(
            cfg.get("output", "export_qtdeesperada", fallback="no")
        ),
        export_qtdelida=as_bool(
            cfg.get("output", "export_qtdelida", fallback="yes")
        ),
        export_saldo=as_bool(
            cfg.get("output", "export_saldo", fallback="no")
        ),
        individual_file=as_bool(cfg.get("output", "individual_file", fallback="yes")),
        daily_file=as_bool(cfg.get("output", "daily_file", fallback="yes")),
        delimiter=cfg.get("output", "delimiter", fallback=";") or ";",
        file_name_mode=file_name_mode,
    )

    return Settings(
        sql=sql,
        watch=watch,
        txt=txt,
        app=app,
        logging=logging,
        output=output,
    )