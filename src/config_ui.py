import os
import shutil
import configparser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pyodbc

CONFIG_PATH = "config.ini"
EXAMPLE_PATH = "config.ini.example"


def ensure_config_exists():
    if os.path.exists(CONFIG_PATH):
        return
    if os.path.exists(EXAMPLE_PATH):
        shutil.copyfile(EXAMPLE_PATH, CONFIG_PATH)
    else:
        # fallback mínimo
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write("[sql]\nserver=127.0.0.1\ndatabase=SEU_BANCO\ntrusted_connection=no\nuser=sa\npassword=\n")


def load_cfg() -> configparser.ConfigParser:
    ensure_config_exists()
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def save_cfg(cfg: configparser.ConfigParser):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)


def as_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "sim", "s")


def bool_to_ini(b: bool) -> str:
    return "yes" if b else "no"


def build_conn_str(cfg: configparser.ConfigParser) -> str:
    driver = cfg.get("sql", "driver", fallback="ODBC Driver 18 for SQL Server").strip()
    server = cfg.get("sql", "server", fallback="127.0.0.1").strip()
    database = cfg.get("sql", "database", fallback="").strip()
    trusted = as_bool(cfg.get("sql", "trusted_connection", fallback="no"))

    if trusted:
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )

    user = cfg.get("sql", "user", fallback="").strip()
    password = cfg.get("sql", "password", fallback="")
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )


class ConfigUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Configuração - Importador (XML/TXT)")
        self.geometry("820x560")
        self.resizable(False, False)

        self.cfg = load_cfg()

        self.vars = {}
        self.widgets = {}

        self._build()
        self._load_to_form()
        self._apply_states()

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        tab_sql = ttk.Frame(nb)
        tab_paths = ttk.Frame(nb)
        tab_input = ttk.Frame(nb)
        tab_app = ttk.Frame(nb)

        nb.add(tab_sql, text="SQL Server")
        nb.add(tab_paths, text="Pastas")
        nb.add(tab_input, text="Entrada (XML/TXT)")
        nb.add(tab_app, text="Aplicação")

        # ---- SQL
        fs = ttk.LabelFrame(tab_sql, text="Conexão")
        fs.pack(fill="x", padx=10, pady=10)

        self._entry(fs, "Driver ODBC", "sql.driver", 0)
        self._entry(fs, "Servidor (IP ou HOST\\INSTÂNCIA)", "sql.server", 1)
        self._entry(fs, "Banco", "sql.database", 2)

        self.vars["sql.trusted_connection"] = tk.BooleanVar()
        ttk.Checkbutton(
            fs,
            text="Usar autenticação do Windows (Trusted Connection)",
            variable=self.vars["sql.trusted_connection"],
            command=self._apply_states
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=8)

        self._entry(fs, "Usuário", "sql.user", 4)
        self._entry(fs, "Senha", "sql.password", 5, show="*")

        ttk.Button(tab_sql, text="Testar conexão", command=self._test_connection).pack(
            anchor="w", padx=20, pady=(0, 10)
        )

        # ---- Pastas
        fp = ttk.LabelFrame(tab_paths, text="Pastas monitoradas")
        fp.pack(fill="x", padx=10, pady=10)

        self._dir(fp, "Entrada", "watch.input_dir", 0)
        self._dir(fp, "Processados", "watch.processed_dir", 1)
        self._dir(fp, "Erros", "watch.error_dir", 2)
        self._dir(fp, "Duplicados", "watch.duplicate_dir", 3)

        fl = ttk.LabelFrame(tab_paths, text="Logs")
        fl.pack(fill="x", padx=10, pady=10)
        self._dir(fl, "Pasta de logs", "logging.log_dir", 0)
        self._entry(fl, "Nível (INFO/DEBUG)", "logging.level", 1)

        # ---- Input
        fi = ttk.LabelFrame(tab_input, text="Formato de entrada")
        fi.pack(fill="x", padx=10, pady=10)

        self.vars["input.format"] = tk.StringVar()
        ttk.Label(fi, text="Formato").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        cmb = ttk.Combobox(fi, textvariable=self.vars["input.format"], values=["xml", "txt"], state="readonly", width=20)
        cmb.grid(row=0, column=1, sticky="w", padx=8, pady=8)
        cmb.bind("<<ComboboxSelected>>", lambda e: self._apply_states())
        self.widgets["input.format"] = cmb

        ft = ttk.LabelFrame(tab_input, text="Config TXT (se formato=txt)")
        ft.pack(fill="x", padx=10, pady=10)

        self._entry(ft, "Delimitador", "txt.delimiter", 0)
        self._entry(ft, "Encoding (utf-8 / latin-1)", "txt.encoding", 1)

        self.vars["txt.has_header"] = tk.BooleanVar()
        chk_hdr = ttk.Checkbutton(ft, text="Primeira linha é cabeçalho", variable=self.vars["txt.has_header"])
        chk_hdr.grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=8)
        self.widgets["txt.has_header"] = chk_hdr

        # ---- App
        fa = ttk.LabelFrame(tab_app, text="Parâmetros")
        fa.pack(fill="x", padx=10, pady=10)
        self._entry(fa, "Status inicial (3 letras)", "app.status_inicial", 0)

        self.vars["app.group_items"] = tk.BooleanVar()
        chk_group = ttk.Checkbutton(
            fa,
            text="Agrupar itens iguais (somar quantidades)",
            variable=self.vars["app.group_items"]
        )
        chk_group.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=8)
        self.widgets["app.group_items"] = chk_group

        # ---- Bottom
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(bottom, text="Salvar", command=self._save).pack(side="right")
        ttk.Button(bottom, text="Fechar", command=self.destroy).pack(side="right", padx=(0, 8))

    def _entry(self, parent, label, key, row, show=None):
        self.vars[key] = tk.StringVar()
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
        ent = ttk.Entry(parent, textvariable=self.vars[key], width=65, show=show)
        ent.grid(row=row, column=1, sticky="w", padx=8, pady=6)
        parent.grid_columnconfigure(1, weight=1)
        self.widgets[key] = ent
        return ent

    def _dir(self, parent, label, key, row):
        self._entry(parent, label, key, row=row)
        btn = ttk.Button(parent, text="...", width=3, command=lambda: self._pick_dir(key))
        btn.grid(row=row, column=2, sticky="w", padx=8, pady=6)
        self.widgets[key + ".__btn"] = btn

    def _pick_dir(self, key):
        cur = self.vars[key].get().strip()
        initial = cur if os.path.isdir(cur) else os.getcwd()
        selected = filedialog.askdirectory(initialdir=initial)
        if selected:
            self.vars[key].set(selected)

    def _load_to_form(self):
        def g(section, option, fallback=""):
            return self.cfg.get(section, option, fallback=fallback)

        # SQL
        self.vars["sql.driver"].set(g("sql", "driver", "ODBC Driver 18 for SQL Server"))
        self.vars["sql.server"].set(g("sql", "server", "127.0.0.1"))
        self.vars["sql.database"].set(g("sql", "database", "SEU_BANCO_AQUI"))
        self.vars["sql.user"].set(g("sql", "user", "sa"))
        self.vars["sql.password"].set(g("sql", "password", ""))

        self.vars["sql.trusted_connection"].set(as_bool(g("sql", "trusted_connection", "no")))

        # Pastas
        self.vars["watch.input_dir"].set(g("watch", "input_dir", r"C:\MIS\entrada"))
        self.vars["watch.processed_dir"].set(g("watch", "processed_dir", r"C:\MIS\processados"))
        self.vars["watch.error_dir"].set(g("watch", "error_dir", r"C:\MIS\erros"))
        self.vars["watch.duplicate_dir"].set(g("watch", "duplicate_dir", r"C:\MIS\duplicados"))

        self.vars["logging.log_dir"].set(g("logging", "log_dir", r"C:\MIS\logs"))
        self.vars["logging.level"].set(g("logging", "level", "INFO"))

        # Input
        self.vars["input.format"].set(g("input", "format", "xml").strip().lower())

        # TXT
        self.vars["txt.delimiter"].set(g("txt", "delimiter", ","))
        self.vars["txt.encoding"].set(g("txt", "encoding", "utf-8"))
        self.vars["txt.has_header"].set(as_bool(g("txt", "has_header", "yes")))

        # App
        self.vars["app.status_inicial"].set(g("app", "status_inicial", "PEN"))
        self.vars["app.group_items"].set(as_bool(g("app", "group_items", "no")))

    def _apply_states(self):
        trusted = self.vars["sql.trusted_connection"].get()
        self.widgets["sql.user"].configure(state=("disabled" if trusted else "normal"))
        self.widgets["sql.password"].configure(state=("disabled" if trusted else "normal"))

        fmt = (self.vars["input.format"].get() or "xml").strip().lower()
        txt_state = "normal" if fmt == "txt" else "disabled"

        for k in ("txt.delimiter", "txt.encoding"):
            self.widgets[k].configure(state=txt_state)
        self.widgets["txt.has_header"].configure(state=txt_state)

    def _write_from_form(self):
        def setv(section, option, value):
            if section not in self.cfg:
                self.cfg[section] = {}
            self.cfg[section][option] = value

        # SQL
        setv("sql", "driver", self.vars["sql.driver"].get().strip())
        setv("sql", "server", self.vars["sql.server"].get().strip())
        setv("sql", "database", self.vars["sql.database"].get().strip())
        setv("sql", "trusted_connection", bool_to_ini(self.vars["sql.trusted_connection"].get()))
        setv("sql", "user", self.vars["sql.user"].get().strip())
        setv("sql", "password", self.vars["sql.password"].get())

        # Pastas
        setv("watch", "input_dir", self.vars["watch.input_dir"].get().strip())
        setv("watch", "processed_dir", self.vars["watch.processed_dir"].get().strip())
        setv("watch", "error_dir", self.vars["watch.error_dir"].get().strip())
        setv("watch", "duplicate_dir", self.vars["watch.duplicate_dir"].get().strip())

        # Input
        fmt = (self.vars["input.format"].get() or "xml").strip().lower()
        if fmt not in ("xml", "txt"):
            fmt = "xml"
        setv("input", "format", fmt)

        # TXT
        setv("txt", "delimiter", self.vars["txt.delimiter"].get())
        setv("txt", "encoding", self.vars["txt.encoding"].get().strip())
        setv("txt", "has_header", bool_to_ini(self.vars["txt.has_header"].get()))

        # App
        setv("app", "status_inicial", self.vars["app.status_inicial"].get().strip()[:3].upper())
        setv("app", "group_items", bool_to_ini(self.vars["app.group_items"].get()))

        # Logging
        setv("logging", "log_dir", self.vars["logging.log_dir"].get().strip())
        setv("logging", "level", self.vars["logging.level"].get().strip().upper())

    def _test_connection(self):
        try:
            self._write_from_form()
            conn_str = build_conn_str(self.cfg)
            conn = pyodbc.connect(conn_str, timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            conn.close()
            messagebox.showinfo("Teste de conexão", "Conexão OK com o SQL Server.")
        except Exception as e:
            messagebox.showerror("Teste de conexão", f"Falha na conexão:\n{e}")

    def _save(self):
        try:
            self._write_from_form()

            # cria pastas (se não existirem)
            for sec, opt in (
                ("watch", "input_dir"),
                ("watch", "processed_dir"),
                ("watch", "error_dir"),
                ("watch", "duplicate_dir"),
                ("logging", "log_dir"),
            ):
                p = self.cfg.get(sec, opt, fallback="").strip()
                if p:
                    os.makedirs(p, exist_ok=True)

            save_cfg(self.cfg)
            messagebox.showinfo("Salvar", f"Salvo em: {os.path.abspath(CONFIG_PATH)}")
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))


if __name__ == "__main__":
    app = ConfigUI()
    app.mainloop()