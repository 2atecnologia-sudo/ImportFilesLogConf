import os
import sys
import configparser
import tkinter as tk
from tkinter import ttk, messagebox

import pyodbc


APP_TITLE = " "


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.dirname(__file__))


BASE_DIR = base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")


def resource_path(relative_path: str) -> str:
    """Retorna o caminho correto de recursos no .py e no PyInstaller."""
    base = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base, relative_path)


def load_cfg():
    cfg = configparser.ConfigParser()
    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError(f"Arquivo config.ini não encontrado em:\n{CONFIG_PATH}")
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y", "sim", "s")


def build_conn_str(cfg, database):
    driver = cfg.get("sql", "driver", fallback="ODBC Driver 17 for SQL Server").strip()
    server = cfg.get("sql", "server", fallback="127.0.0.1").strip()
    trusted = as_bool(cfg.get("sql", "trusted_connection", fallback="no"))

    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
        "TrustServerCertificate=yes",
    ]

    if trusted:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={cfg.get('sql', 'user', fallback='').strip()}")
        parts.append(f"PWD={cfg.get('sql', 'password', fallback='')}")

    return ";".join(parts) + ";"


class MovimentosViewer(tk.Tk):
    def __init__(self, num_documento=None):
        super().__init__()
        self.num_documento = str(num_documento or "").strip()

        self.title("")
        try:
            icone = resource_path(os.path.join("assets", "transparent.ico"))
            self.wm_iconbitmap(bitmap=icone, default=icone)
        except Exception:
            pass
        self.geometry("1180x620")
        self.minsize(980, 500)
        self.configure(bg="#f2f2f2")

        self._all_rows = []

        self._build_ui()

        # Centraliza a janela na tela onde ela for aberta.
        self.update_idletasks()
        largura = 1180
        altura = 620
        x = max(0, (self.winfo_screenwidth() - largura) // 2)
        y = max(0, (self.winfo_screenheight() - altura) // 2)
        self.geometry(f"{largura}x{altura}+{x}+{y}")

        self.after(120, self.refresh)


    def _build_ui(self):
        topbar = tk.Frame(self, bg="#d0d0d0", height=18)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        header = tk.Frame(self, bg="#ffffff")
        header.pack(fill="x", padx=0, pady=(0, 0))

        title_area = tk.Frame(header, bg="#e6e6e6")
        title_area.pack(side="left", fill="both", expand=True)

        self.cliente_var = tk.StringVar(value="Movimentações de Estoque")
        tk.Label(
            title_area,
            textvariable=self.cliente_var,
            bg="#e6e6e6",
            fg="#111111",
            font=("Arial", 9, "normal"),
            padx=8,
            pady=5,
        ).pack(side="left")

        refresh_path = resource_path(os.path.join("assets", "refresh_transparent.png"))
        try:
            self.refresh_image = tk.PhotoImage(file=refresh_path)
            refresh_btn = tk.Label(
                header,
                image=self.refresh_image,
                bg="#e6e6e6",
                bd=0,
                highlightthickness=0,
                padx=0,
                pady=0,
                cursor="hand2",
            )
        except Exception:
            refresh_btn = tk.Label(
                header,
                text="↻",
                bg="#e6e6e6",
                fg="#111111",
                font=("Arial", 18, "normal"),
                bd=0,
                highlightthickness=0,
                padx=3,
                pady=0,
                cursor="hand2",
            )

        refresh_btn.pack(side="right", padx=(0, 8), pady=0)
        refresh_btn.bind("<Button-1>", lambda _event: self.refresh())

        search_bar = tk.Frame(self, bg="#e6e6e6")
        search_bar.pack(fill="x", padx=10, pady=(0, 3))

        tk.Label(
            search_bar,
            text="Buscar:",
            bg="#e6e6e6",
            fg="#111111",
            font=("Arial", 8, "normal"),
        ).pack(side="left", padx=(0, 5))

        self.search_var = tk.StringVar(value="")
        self.search_entry = tk.Entry(
            search_bar,
            textvariable=self.search_var,
            font=("Arial", 8, "normal"),
            relief="solid",
            bd=1,
            width=26,
        )
        self.search_entry.pack(side="left", ipady=1)
        self.search_entry.bind("<KeyRelease>", lambda _event: self._apply_filter())

        grid_frame = tk.Frame(self, bg="#f2f2f2")
        grid_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = [
            ("documento", "Documento", 90),
            ("cliente", "Cliente", 155),
            ("codprod", "Código", 105),
            ("gtin", "GTIN", 125),
            ("descricao", "Descrição", 280),
            ("qtd_antes", "Qtde Antes", 95),
            ("qtd_mov", "Qtde Movimentada", 120),
            ("qtd_depois", "Qtde Depois", 95),
            ("saldo", "Saldo Atualizado", 110),
            ("datahora", "Data/Hora", 145),
            ("operacao", "Operação", 115),
            ("terminal", "Terminal", 100),
            ("resultado", "Resultado", 90),
            ("detalhe", "Detalhe", 300),
        ]

        ids = [c[0] for c in columns]

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "Mov.Treeview",
            background="#ffffff",
            fieldbackground="#ffffff",
            foreground="#111111",
            rowheight=25,
            font=("Arial", 8, "normal"),
            borderwidth=0,
        )
        style.configure(
            "Mov.Treeview.Heading",
            background="#08a9e6",
            foreground="#ffffff",
            font=("Arial", 8, "bold"),
            relief="flat",
        )
        style.map("Mov.Treeview.Heading", background=[("active", "#08a9e6")])

        self.tree = ttk.Treeview(
            grid_frame,
            columns=ids,
            show="headings",
            selectmode="browse",
            style="Mov.Treeview",
        )

        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=65, anchor="w", stretch=False)

        y_scroll = ttk.Scrollbar(grid_frame, orient="vertical", command=self.tree.yview)
        x_scroll = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        grid_frame.grid_rowconfigure(0, weight=1)
        grid_frame.grid_columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="Consultando movimentações...")
        tk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            bg="#f2f2f2",
            fg="#444444",
            font=("Arial", 9),
        ).pack(fill="x", padx=12, pady=(0, 8))

    def _clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    @staticmethod
    def _fmt_num(value):
        if value is None:
            return ""
        try:
            return f"{float(value):.3f}"
        except Exception:
            return str(value)

    @staticmethod
    def _fmt_dt(value):
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            try:
                return value.strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                pass
        return str(value)

    @staticmethod
    def _descricao_from_detalhe(detalhe):
        texto = str(detalhe or "").strip()
        if not texto:
            return ""
        partes = [p.strip() for p in texto.split("|")]
        if len(partes) >= 2:
            return partes[1]
        return ""

    def _apply_filter(self):
        termo = str(self.search_var.get() or "").strip().lower()

        self._clear()

        if not termo:
            linhas = self._all_rows
        else:
            linhas = [
                values
                for values in self._all_rows
                if termo in str(values[0] or "").lower()
                or termo in str(values[1] or "").lower()
            ]

        for values in linhas:
            self.tree.insert("", "end", values=values)

        if termo:
            self.status_var.set(
                f"{len(linhas)} movimentação(ões) encontrada(s) para '{self.search_var.get()}'."
            )
        else:
            self.status_var.set(
                f"{len(linhas)} movimentação(ões) carregada(s)."
                if linhas else
                "Nenhuma movimentação encontrada."
            )

    def refresh(self):
        self._clear()
        self.status_var.set("Consultando movimentações...")
        self.update_idletasks()

        conn_mov = None
        conn_local = None

        try:
            cfg = load_cfg()

            conn_mov = pyodbc.connect(
                build_conn_str(cfg, "est_ambTestes"),
                timeout=5,
            )
            cur_mov = conn_mov.cursor()

            sql = """
                SELECT
                    ID_MOVIMENTO,
                    NUM_DOCUMENTO,
                    COD_ITEM,
                    COD_BARRAS,
                    QTD_MOVIMENTADA,
                    SALDO_ANTERIOR,
                    SALDO_POSTERIOR,
                    IDENT_TERMINAL,
                    TIPO_OPERACAO,
                    DATA_MOVIMENTO,
                    RESULTADO,
                    DETALHE
                FROM dbo.movEstambTeste
            """
            params = []

            if self.num_documento:
                sql += " WHERE LTRIM(RTRIM(ISNULL(NUM_DOCUMENTO, ''))) = ? "
                params.append(self.num_documento)

            sql += " ORDER BY ID_MOVIMENTO DESC "
            cur_mov.execute(sql, tuple(params))
            rows = cur_mov.fetchall()

            clientes = {}
            banco_local = cfg.get("sql", "database", fallback="logConf").strip() or "logConf"
            conn_local = pyodbc.connect(build_conn_str(cfg, banco_local), timeout=5)
            cur_local = conn_local.cursor()

            if self.num_documento:
                cur_local.execute(
                    """
                    SELECT TOP 1 NumNF, NomeCli
                    FROM dbo.logConf
                    WHERE CAST(NumNF AS VARCHAR(50)) = ?
                    """,
                    (self.num_documento,),
                )
                r = cur_local.fetchone()
                if r:
                    clientes[str(r[0] or "").strip()] = str(r[1] or "").strip()
            else:
                cur_local.execute("SELECT NumNF, NomeCli FROM dbo.logConf")
                for r in cur_local.fetchall():
                    doc = str(r[0] or "").strip()
                    if doc and doc not in clientes:
                        clientes[doc] = str(r[1] or "").strip()

            nomes_encontrados = set()
            self._all_rows = []

            for r in rows:
                doc = str(r[1] or "").strip()
                cliente = clientes.get(doc, "")
                if cliente:
                    nomes_encontrados.add(cliente)

                detalhe = str(r[11] or "").strip()
                descricao = self._descricao_from_detalhe(detalhe)

                values = [
                    doc,
                    cliente,
                    str(r[2] or "").strip(),
                    str(r[3] or "").strip(),
                    descricao,
                    self._fmt_num(r[5]),
                    self._fmt_num(r[4]),
                    self._fmt_num(r[6]),
                    self._fmt_num(r[6]),
                    self._fmt_dt(r[9]),
                    str(r[8] or "").strip(),
                    str(r[7] or "").strip(),
                    str(r[10] or "").strip(),
                    detalhe,
                ]
                self._all_rows.append(values)

            if self.num_documento:
                nome = clientes.get(self.num_documento, "")
                self.cliente_var.set(nome if nome else f"Documento {self.num_documento}")
            elif len(nomes_encontrados) == 1:
                self.cliente_var.set(next(iter(nomes_encontrados)))
            else:
                self.cliente_var.set("Movimentações de Estoque")

            self._apply_filter()

        except Exception as exc:
            self.status_var.set("Falha ao consultar movimentações.")
            messagebox.showerror(
                APP_TITLE,
                f"Não foi possível consultar as movimentações.\n\n{exc}",
                parent=self,
            )
        finally:
            for conn in (conn_mov, conn_local):
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass


def main():
    num_documento = sys.argv[1] if len(sys.argv) > 1 else None
    app = MovimentosViewer(num_documento=num_documento)
    app.mainloop()


if __name__ == "__main__":
    main()
