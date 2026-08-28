import os
import shutil
import configparser
import csv
import subprocess
import sys
import uuid
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pyodbc
from PIL import Image, ImageTk

from .runtime_status import read_runtime_status
import re

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

APP_VERSION = "1.0.1"
BUILD_DATE = "27/08/2026 11:23"

CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.ini.example")


def resource_path(relative_path: str) -> str:
    """Retorna o caminho de um recurso tanto em desenvolvimento quanto no PyInstaller."""
    base = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base, relative_path)


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
    def __init__(self, initial_tab="config"):
        super().__init__()
        self.title("Gestor de Dados - 2A Tecnologia")

        # Ícone da janela. Salvar como assets/gestor_dados_icon.png
        try:
            icon_path = resource_path(os.path.join("assets", "gestor_dados_icon.png"))
            self._window_icon = tk.PhotoImage(file=icon_path)
            self.iconphoto(True, self._window_icon)
        except Exception:
            pass

        # Janela mais compacta e centralizada na tela.
        window_width = 900
        window_height = 540
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        pos_x = max(0, (screen_width - window_width) // 2)
        pos_y = max(0, (screen_height - window_height) // 2)
        self.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")
        self.minsize(900, 540)
        self.resizable(True, True)

        self._normal_geometry = self.geometry()
        self._test_env_maximized = False

        self.initial_tab = initial_tab

        self.cfg = load_cfg()

        self.vars = {}
        self.widgets = {}

        self._build()
        self._load_to_form()
        self._apply_states()
        self._select_initial_tab()

        # Qualquer forma de fechar a janela salva todas as configurações.
        self.protocol("WM_DELETE_WINDOW", self._save_and_close)

        # Atualiza a aba de Status/Logs periodicamente enquanto a janela estiver aberta.
        self.after(300, self._status_auto_refresh)

    def _build(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.nb.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        tab_sql = ttk.Frame(self.nb)
        tab_paths = ttk.Frame(self.nb)
        tab_input = ttk.Frame(self.nb)
        tab_app = ttk.Frame(self.nb)
        tab_output = ttk.Frame(self.nb)
        tab_connector = ttk.Frame(self.nb)
        self.tab_connector = tab_connector
        self.tab_test_environment = ttk.Frame(self.nb)
        self.tab_status = ttk.Frame(self.nb)

        self.nb.add(tab_sql, text="Banco Local logConf")
        self.nb.add(tab_paths, text="Pastas")
        self.nb.add(tab_input, text="Entrada (XML/TXT)")
        self.nb.add(tab_app, text="Aplicação")
        self.nb.add(tab_output, text="Arquivos de Saída")
        self.nb.add(tab_connector, text="Conexões Externas")
        self.nb.add(self.tab_test_environment, text="Ambiente de Testes")
        self.nb.add(self.tab_status, text="Status / Logs")

        self.tab_about = ttk.Frame(self.nb)
        self.nb.add(self.tab_about, text="Sobre")

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

        # ---- Arquivos de Saída
        fo = ttk.LabelFrame(tab_output, text="Configuração dos arquivos de saída")
        fo.pack(fill="x", padx=10, pady=10)

        self._dir(fo, "Pasta de saída", "output.output_dir", 0)

        campos = ttk.LabelFrame(fo, text="Campos a exportar")
        campos.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(8, 10))

        self.vars["output.export_numdoc"] = tk.BooleanVar()
        self.vars["output.export_codigo"] = tk.BooleanVar()
        self.vars["output.export_gtin"] = tk.BooleanVar()
        self.vars["output.export_descricao"] = tk.BooleanVar()
        self.vars["output.export_qtdeesperada"] = tk.BooleanVar()
        self.vars["output.export_qtdelida"] = tk.BooleanVar()
        self.vars["output.export_saldo"] = tk.BooleanVar()

        ttk.Checkbutton(
            campos,
            text="NumDoc",
            variable=self.vars["output.export_numdoc"],
        ).grid(row=0, column=0, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Código interno",
            variable=self.vars["output.export_codigo"],
        ).grid(row=0, column=1, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="GTIN / EAN",
            variable=self.vars["output.export_gtin"],
        ).grid(row=0, column=2, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Descrição",
            variable=self.vars["output.export_descricao"],
        ).grid(row=0, column=3, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Qtde Esperada",
            variable=self.vars["output.export_qtdeesperada"],
        ).grid(row=1, column=0, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Qtde Lida",
            variable=self.vars["output.export_qtdelida"],
        ).grid(row=1, column=1, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Saldo",
            variable=self.vars["output.export_saldo"],
        ).grid(row=1, column=2, sticky="w", padx=10, pady=6)

        ttk.Label(
            fo,
            text=(
                "Ordem das colunas: NumDoc, Código interno, GTIN/EAN, "
                "Descrição, Qtde Esperada, Qtde Lida, Saldo."
            ),
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        self.vars["output.individual_file"] = tk.BooleanVar()
        ttk.Checkbutton(fo, text="Gerar arquivo individual por conferência",
                        variable=self.vars["output.individual_file"]).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=8, pady=6)

        self.vars["output.daily_file"] = tk.BooleanVar()
        ttk.Checkbutton(fo, text="Gerar arquivo diário acumulado",
                        variable=self.vars["output.daily_file"]).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=8, pady=6)

        self.vars["output.delimiter"] = tk.StringVar()
        ttk.Label(fo, text="Separador").grid(
            row=5, column=0, sticky="w", padx=8, pady=6
        )
        ent_sep = ttk.Entry(
            fo,
            textvariable=self.vars["output.delimiter"],
            width=8,
        )
        ent_sep.grid(
            row=5, column=1, sticky="w", padx=8, pady=6
        )
        self.widgets["output.delimiter"] = ent_sep

        self.vars["output.file_name_mode"] = tk.StringVar()
        ttk.Label(fo, text="Nome do arquivo individual").grid(
            row=6, column=0, sticky="w", padx=8, pady=6
        )
        cmb_file_name = ttk.Combobox(
            fo,
            textvariable=self.vars["output.file_name_mode"],
            values=[
                "Só número do documento",
                "Número do documento + data",
                "Número do documento + data + hora",
            ],
            state="readonly",
            width=36,
        )
        cmb_file_name.grid(row=6, column=1, sticky="w", padx=8, pady=6)
        self.widgets["output.file_name_mode"] = cmb_file_name

        # ---- Conexões Externas - Etapa 2.4
        # Mostra permanentemente a conexão atual.
        # Nova conexão reinicia o assistente; Editar abre a conexão atual preenchida.
        manager = ttk.LabelFrame(tab_connector, text="Conexão Externa Atual")
        manager.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            manager,
            text=(
                "A conexão atualmente configurada é exibida abaixo. "
                "Nenhum dado do ERP é alterado nesta etapa."
            ),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 10))

        self.current_external_vars = {
            "name": tk.StringVar(),
            "type": tk.StringVar(),
            "driver": tk.StringVar(),
            "server": tk.StringVar(),
            "port": tk.StringVar(),
            "database": tk.StringVar(),
            "auth": tk.StringVar(),
            "user": tk.StringVar(),
            "password": tk.StringVar(),
            "status": tk.StringVar(),
        }

        labels = [
            ("Nome da conexão", "name", 42),
            ("Tipo de banco", "type", 34),
            ("Driver ODBC", "driver", 42),
            ("Servidor (IP ou HOST\\INSTÂNCIA)", "server", 42),
            ("Porta", "port", 12),
            ("Banco", "database", 36),
            ("Autenticação", "auth", 34),
            ("Usuário", "user", 30),
            ("Senha", "password", 30),
            ("Status", "status", 24),
        ]

        self.external_detail_widgets = []

        for row, (label, key, field_width) in enumerate(labels, start=1):
            lbl = ttk.Label(manager, text=label)
            lbl.grid(row=row, column=0, sticky="w", padx=10, pady=5)

            value_lbl = ttk.Label(
                manager,
                textvariable=self.current_external_vars[key],
                relief="sunken",
                anchor="w",
                width=field_width,
            )
            value_lbl.grid(row=row, column=1, sticky="w", padx=10, pady=5)

            self.external_detail_widgets.extend([lbl, value_lbl])

        # Estado visual quando não existe conexão configurada.
        self.external_empty_frame = ttk.Frame(manager)
        self.external_empty_frame.grid(
            row=1, column=0, columnspan=3, rowspan=10,
            sticky="nsew", padx=10, pady=(18, 12)
        )

        ttk.Label(
            self.external_empty_frame,
            text="Nenhuma conexão externa configurada",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="center", pady=(45, 10))

        ttk.Label(
            self.external_empty_frame,
            text=(
                "Clique em “Nova conexão” para iniciar o assistente e configurar "
                "o banco de dados do ERP."
            ),
            justify="center",
            font=("Segoe UI", 10),
        ).pack(anchor="center", pady=(0, 8))

        ttk.Label(
            self.external_empty_frame,
            text=(
                "O Banco Local logConf continua funcionando normalmente "
                "e não é alterado."
            ),
            justify="center",
            font=("Segoe UI", 9),
        ).pack(anchor="center")

        # Status real da conexão externa.
        self.external_live_status_var = tk.StringVar(
            value="● Conexão SQL: não verificada"
        )
        self.external_live_status_label = tk.Label(
            manager,
            textvariable=self.external_live_status_var,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.external_live_status_label.grid(
            row=11, column=0, columnspan=3, sticky="w",
            padx=10, pady=(10, 2)
        )

        connector_actions = ttk.Frame(manager)
        connector_actions.grid(
            row=12, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 8)
        )

        ttk.Button(
            connector_actions,
            text="Nova conexão",
            command=self._new_external_connection,
        ).pack(side="left")

        self.btn_external_edit = ttk.Button(
            connector_actions,
            text="Editar",
            command=self._edit_external_connection,
        )
        self.btn_external_edit.pack(side="left", padx=(8, 0))

        self.btn_external_delete = ttk.Button(
            connector_actions,
            text="Excluir",
            command=self._delete_external_connection,
        )
        self.btn_external_delete.pack(side="left", padx=(8, 0))

        self.btn_external_test = ttk.Button(
            connector_actions,
            text="Testar conexão",
            command=self._test_selected_external_connection,
        )
        self.btn_external_test.pack(side="left", padx=(18, 0))

        self.external_mapping_var = tk.StringVar(value="")
        ttk.Label(
            manager,
            textvariable=self.external_mapping_var,
            wraplength=760,
            justify="left",
        ).grid(row=13, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 6))

        self.external_hint_var = tk.StringVar(
            value=(
                "Nova conexão abre o assistente vazio. Editar abre a conexão atual "
                "com os dados preenchidos."
            )
        )
        ttk.Label(
            manager,
            textvariable=self.external_hint_var,
        ).grid(row=14, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))

        # ---- Ambiente de Testes
        self._build_test_environment_tab()

        # ---- Status / Logs
        self._build_status_tab()

        # ---- Sobre
        self._build_about_tab()

        # ---- Bottom
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(bottom, text="Salvar", command=self._save).pack(side="right")
        ttk.Button(bottom, text="Fechar", command=self._save_and_close).pack(side="right", padx=(0, 8))


    def _build_test_environment_tab(self):
        """Grades somente de leitura do banco est_ambTestes."""
        container = ttk.Frame(self.tab_test_environment)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            container,
            text=(
                "Consulta somente leitura do ambiente de testes. "
                "Nenhum INSERT, UPDATE ou DELETE é executado nesta tela."
            ),
        ).pack(anchor="w", pady=(0, 8))

        # Seleção do arquivo de carga do estoque de teste.
        file_box = ttk.LabelFrame(container, text="Arquivo de carga do estoque")
        file_box.pack(fill="x", pady=(0, 8))

        self.test_file_var = tk.StringVar(value="")

        ttk.Label(
            file_box,
            text="Arquivo TXT/CSV",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=8)

        ttk.Entry(
            file_box,
            textvariable=self.test_file_var,
            state="readonly",
            width=72,
        ).grid(row=0, column=1, sticky="w", padx=8, pady=8)

        ttk.Button(
            file_box,
            text="Escolher arquivo...",
            command=self._pick_test_environment_file,
        ).grid(row=0, column=2, sticky="w", padx=8, pady=8)

        ttk.Button(
            file_box,
            text="Importar Estoque",
            command=self._import_test_environment_stock,
        ).grid(row=0, column=3, sticky="w", padx=8, pady=8)

        self.test_file_status = tk.StringVar(
            value="Nenhum arquivo selecionado."
        )
        ttk.Label(
            file_box,
            textvariable=self.test_file_status,
        ).grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            padx=8,
            pady=(0, 8),
        )

        self.test_env_nb = ttk.Notebook(container)
        self.test_env_nb.pack(fill="both", expand=True)

        tab_stock = ttk.Frame(self.test_env_nb)
        tab_moves = ttk.Frame(self.test_env_nb)
        self.test_env_nb.add(tab_stock, text="Estoque Atual")
        self.test_env_nb.add(tab_moves, text="Movimentações")

        self._build_readonly_grid(
            tab_stock, "test_stock_tree", "test_stock_status",
            [
                ("codigo", "CodProd", 110),
                ("ean", "GTIN", 135), ("descricao", "Descrição", 250),
                ("local", "Local", 100), ("saldo", "Saldo", 90),
                ("atualizacao", "Atualização", 145),
                ("terminal", "Terminal", 110),
            ],
            self._refresh_test_stock,
        )

        self._build_readonly_grid(
            tab_moves, "test_moves_tree", "test_moves_status",
            [
                ("codigo", "CodProd", 90),
                ("gtin", "GTIN", 135),
                ("descricao", "Descrição", 280),
                ("qtd_antes", "Qtde Antes", 90),
                ("qtd_mov", "Qtde Movimentada", 115),
                ("qtd_depois", "Qtde Depois", 90),
                ("saldo_atualizado", "Saldo Atualizado", 110),
                ("datahora", "Data/Hora", 145),
                ("operacao", "Operação", 105),
                ("documento", "Documento", 110),
                ("terminal", "Terminal", 90),
                ("resultado", "Resultado", 90),
                ("detalhe", "Detalhe", 260),
            ],
            self._refresh_test_moves,
        )

        # Carrega automaticamente as grades ao abrir Ambiente de Testes.
        # O after() deixa a janela terminar de ser montada antes das consultas SQL.
        self.after(150, self._refresh_test_stock)
        self.after(250, self._refresh_test_moves)

    def _pick_test_environment_file(self):
        """Seleciona o TXT/CSV de carga. Nesta etapa, apenas guarda o caminho."""
        selected = filedialog.askopenfilename(
            parent=self,
            title="Selecionar arquivo de estoque de teste",
            filetypes=[
                ("Arquivos TXT e CSV", "*.txt *.csv"),
                ("Arquivo TXT", "*.txt"),
                ("Arquivo CSV", "*.csv"),
                ("Todos os arquivos", "*.*"),
            ],
        )

        if not selected:
            return

        self.test_file_var.set(selected)
        self.test_file_status.set(
            f"Arquivo selecionado: {os.path.basename(selected)}"
        )

    def _write_test_user_log(self, level, action, why, what_to_do="", details=None):
        """Registra evento amigável no mesmo usuario.log já usado pela aplicação."""
        from datetime import datetime

        log_dir = self.cfg.get(
            "logging", "log_dir", fallback=os.path.join(BASE_DIR, "logs")
        ).strip()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "usuario.log")

        lines = [
            f"{datetime.now():%d/%m/%Y %H:%M:%S} | {level} | {action}",
            f"Por que: {why}",
        ]
        if what_to_do:
            lines.append(f"O que fazer: {what_to_do}")
        if details:
            lines.append("Detalhes:")
            lines.extend(f"- {item}" for item in details)

        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")

    def _validate_test_stock_file(self, file_path):
        """Valida o arquivo inteiro antes de permitir qualquer INSERT."""
        expected = ["CodProd", "GTIN", "DescProd", "SaldoEstoque", "LocalEstoque"]
        errors = []
        valid_rows = []

        try:
            with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except UnicodeDecodeError:
            return [], [
                "Arquivo não está em UTF-8. Salve o TXT/CSV em UTF-8 e tente novamente."
            ]
        except Exception as e:
            return [], [f"Não foi possível ler o arquivo: {e}"]

        if not rows:
            return [], ["Arquivo vazio."]

        header = [str(v).strip() for v in rows[0]]
        if header != expected:
            errors.append(
                "Linha 1 - cabeçalho inválido. Esperado exatamente: "
                + ",".join(expected)
            )
            return [], errors

        # Consolidação por produto + GTIN + localização.
        # Mesmo produto no mesmo local soma o saldo.
        # Mesmo produto em locais diferentes permanece em posições separadas.
        grouped = {}

        # Mantém coerência entre Código e GTIN.
        cod_to_gtin = {}
        gtin_to_cod = {}

        for line_no, row in enumerate(rows[1:], start=2):
            if not row or all(not str(v).strip() for v in row):
                continue

            if len(row) != 5:
                errors.append(
                    f"Linha {line_no} - quantidade de campos inválida: "
                    f"esperado 5, encontrado {len(row)}."
                )
                continue

            codprod, gtin, desc, saldo_txt, local = [str(v).strip() for v in row]

            if not codprod and not gtin:
                errors.append(
                    f"Linha {line_no} - CodProd e GTIN estão vazios. "
                    "Informe pelo menos um dos dois campos."
                )
            if not desc:
                errors.append(f"Linha {line_no} - campo DescProd está vazio.")
            if not local:
                errors.append(f"Linha {line_no} - campo LocalEstoque está vazio.")

            try:
                saldo = float(saldo_txt.replace(",", "."))
                if saldo < 0:
                    errors.append(
                        f"Linha {line_no} - SaldoEstoque não pode ser negativo: {saldo_txt}."
                    )
            except Exception:
                saldo = None
                errors.append(
                    f'Linha {line_no} - SaldoEstoque inválido: "{saldo_txt}".'
                )

            if codprod and gtin:
                gtin_anterior = cod_to_gtin.get(codprod)
                if gtin_anterior and gtin_anterior != gtin:
                    errors.append(
                        f'Linha {line_no} - CodProd "{codprod}" aparece com GTIN diferente '
                        f'("{gtin_anterior}" e "{gtin}").'
                    )
                else:
                    cod_to_gtin[codprod] = gtin

                cod_anterior = gtin_to_cod.get(gtin)
                if cod_anterior and cod_anterior != codprod:
                    errors.append(
                        f'Linha {line_no} - GTIN "{gtin}" aparece com CodProd diferente '
                        f'("{cod_anterior}" e "{codprod}").'
                    )
                else:
                    gtin_to_cod[gtin] = codprod

            if (
                (codprod or gtin) and desc and local and saldo is not None
                and saldo >= 0
            ):
                key = (
                    codprod if codprod else "",
                    gtin if gtin else "",
                    local,
                )

                if key in grouped:
                    # Mesmo produto + GTIN + local: soma o saldo.
                    grouped[key]["saldo"] += saldo
                else:
                    grouped[key] = {
                        "codprod": codprod,
                        "gtin": gtin,
                        "desc": desc,
                        "local": local,
                        "saldo": saldo,
                    }

        if errors:
            return [], errors

        valid_rows = [
            (
                item["codprod"],
                item["gtin"],
                item["desc"],
                item["local"],
                item["saldo"],
            )
            for item in grouped.values()
        ]

        if not valid_rows:
            errors.append("O arquivo não possui registros de estoque para importar.")

        return valid_rows, errors

    def _import_test_environment_stock(self):
        """
        Importa somente após validar 100% do arquivo.
        Nesta etapa grava apenas dbo.ESTOQUE; não cria movimentações.
        """
        file_path = self.test_file_var.get().strip()

        if not file_path:
            messagebox.showwarning(
                "Importar Estoque",
                "Selecione primeiro o arquivo TXT/CSV de estoque.",
                parent=self,
            )
            return

        if not os.path.isfile(file_path):
            messagebox.showerror(
                "Importar Estoque",
                f"Arquivo não encontrado:\n{file_path}",
                parent=self,
            )
            return

        rows, errors = self._validate_test_stock_file(file_path)
        file_name = os.path.basename(file_path)

        if errors:
            self.test_file_status.set(
                f"Arquivo não importado: {len(errors)} erro(s) encontrado(s)."
            )
            self._write_test_user_log(
                "ERRO",
                f"Validação do arquivo de estoque: {file_name}",
                "Foram encontrados dados inválidos no arquivo. Nenhum registro foi importado.",
                "Corrija as linhas indicadas e tente novamente.",
                errors,
            )

            preview = "\n".join(errors[:15])
            if len(errors) > 15:
                preview += f"\n\n... e mais {len(errors) - 15} erro(s). Veja o Log do Usuário."

            messagebox.showerror(
                "Arquivo não importado",
                "Foram encontrados erros no arquivo.\n"
                "Nenhum registro foi importado.\n\n"
                f"{preview}\n\n"
                "Todos os detalhes também foram gravados no Log do Usuário.",
                parent=self,
            )
            return

        conn = None
        try:
            conn = pyodbc.connect(
                self._build_test_environment_conn_str().replace(
                    "ApplicationIntent=ReadOnly;", ""
                ),
                timeout=5,
                autocommit=False,
            )
            cur = conn.cursor()

            # Segurança: não misturamos uma nova carga com dados anteriores.
            cur.execute("SELECT COUNT(*) FROM dbo.ESTOQUE")
            existing = int(cur.fetchone()[0])

            if existing > 0:
                confirmar = messagebox.askyesno(
                    "Substituir estoque de testes?",
                    "A tabela de estoque de testes já possui "
                    f"{existing} registro(s).\n\n"
                    "Se continuar, TODO o estoque atual do ambiente de testes "
                    "será apagado e substituído pelo arquivo selecionado.\n\n"
                    "Deseja apagar o estoque atual e importar o novo arquivo?",
                    parent=self,
                )

                if not confirmar:
                    conn.rollback()
                    self.test_file_status.set(
                        "Importação cancelada. O estoque atual foi mantido."
                    )
                    self._write_test_user_log(
                        "ATENÇÃO",
                        f"Importação de estoque cancelada: {file_name}",
                        "O ambiente de testes já possuía registros e o usuário optou por mantê-los.",
                        "Nenhuma alteração foi realizada.",
                    )
                    return

                # Ambiente exclusivamente de testes:
                # após confirmação explícita, remove a carga anterior inteira
                # e reinicia também o histórico de movimentações.
                cur.execute("DELETE FROM dbo.movEstambTeste")
                cur.execute("DELETE FROM dbo.ESTOQUE")

                self._write_test_user_log(
                    "OK",
                    f"Substituição do estoque de testes: {file_name}",
                    f"O usuário confirmou a exclusão dos {existing} registro(s) anteriores.",
                    "O novo arquivo será carregado e o histórico de movimentações será reiniciado.",
                )

            sql = """
                INSERT INTO dbo.ESTOQUE
                    (COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL)
                VALUES (?, ?, ?, ?, ?)
            """
            cur.fast_executemany = True
            cur.executemany(sql, rows)

            # Registra a origem de cada posição de estoque como CARGA INICIAL.
            # Isso cria um extrato auditável sem alterar o saldo importado.
            sql_mov = """
                INSERT INTO dbo.movEstambTeste
                    (
                        NUM_DOCUMENTO,
                        COD_ITEM,
                        COD_BARRAS,
                        QTD_MOVIMENTADA,
                        SALDO_ANTERIOR,
                        SALDO_POSTERIOR,
                        IDENT_TERMINAL,
                        TIPO_OPERACAO,
                        RESULTADO,
                        DETALHE
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            movimentos = [
                (
                    "CARGA_INICIAL",
                    codprod,
                    gtin,
                    saldo,
                    0,
                    saldo,
                    None,
                    "SALDO INICIAL",
                    "SUCESSO",
                    f"Carga inicial do ambiente de testes | {desc} | Local: {local}",
                )
                for codprod, gtin, desc, local, saldo in rows
            ]

            cur.executemany(sql_mov, movimentos)
            conn.commit()

            self.test_file_status.set(
                f"Importação concluída: {len(rows)} produto(s)."
            )
            self._write_test_user_log(
                "OK",
                f"Importação de estoque de testes: {file_name}",
                (
                    f"{len(rows)} posição(ões) foram importadas para est_ambTestes.dbo.ESTOQUE "
                    f"e {len(rows)} lançamento(s) de SALDO INICIAL foram registrados."
                ),
            )

            self._refresh_test_stock()
            self._refresh_test_moves()

            messagebox.showinfo(
                "Importar Estoque",
                f"Importação concluída com sucesso.\n\n"
                f"Posições de estoque importadas: {len(rows)}\n"
                f"Lançamentos de SALDO INICIAL: {len(rows)}",
                parent=self,
            )

        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass

            detail = str(e)
            self.test_file_status.set("Falha na importação. Nenhum registro confirmado.")
            self._write_test_user_log(
                "ERRO",
                f"Importação de estoque de testes: {file_name}",
                "O SQL Server recusou ou interrompeu a importação. A transação foi cancelada.",
                "Verifique a conexão e o detalhe técnico informado.",
                [detail],
            )
            messagebox.showerror(
                "Falha na importação",
                "Nenhum registro foi confirmado no banco.\n\n"
                f"Detalhe: {detail}",
                parent=self,
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _build_readonly_grid(self, parent, tree_attr, status_attr, columns, refresh_command):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", padx=6, pady=(8, 4))
        status_var = tk.StringVar(value="Clique em Atualizar para consultar.")
        setattr(self, status_attr, status_var)

        ttk.Button(toolbar, text="↻ Atualizar", command=refresh_command).pack(side="left")
        ttk.Label(toolbar, textvariable=status_var).pack(side="left", padx=(12, 0))

        grid_frame = ttk.Frame(parent)
        grid_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        column_ids = [item[0] for item in columns]
        tree = ttk.Treeview(grid_frame, columns=column_ids, show="headings", selectmode="browse")
        setattr(self, tree_attr, tree)

        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=60, stretch=True, anchor="w")

        y_scroll = ttk.Scrollbar(grid_frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(grid_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        grid_frame.grid_rowconfigure(0, weight=1)
        grid_frame.grid_columnconfigure(0, weight=1)

    def _build_test_environment_conn_str(self):
        cfg = load_cfg()
        driver = cfg.get("sql", "driver", fallback="ODBC Driver 18 for SQL Server").strip()
        server = cfg.get("sql", "server", fallback="127.0.0.1").strip()
        trusted = as_bool(cfg.get("sql", "trusted_connection", fallback="no"))

        parts = [
            f"DRIVER={{{driver}}}", f"SERVER={server}",
            "DATABASE=est_ambTestes", "TrustServerCertificate=yes",
            "ApplicationIntent=ReadOnly",
        ]
        if trusted:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={cfg.get('sql', 'user', fallback='').strip()}")
            parts.append(f"PWD={cfg.get('sql', 'password', fallback='')}")
        return ";".join(parts) + ";"

    def _clear_test_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def _format_test_value(self, value):
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            try:
                return value.strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                pass
        return str(value)

    def _read_test_table(self, table_name):
        conn = pyodbc.connect(self._build_test_environment_conn_str(), timeout=5)
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = ?
                   ORDER BY ORDINAL_POSITION""",
                table_name,
            )
            columns = [row[0] for row in cur.fetchall()]
            if not columns:
                raise RuntimeError(f"Tabela dbo.{table_name} não encontrada em est_ambTestes.")
            cur.execute(f"SELECT * FROM dbo.[{table_name}]")
            return columns, cur.fetchall()
        finally:
            conn.close()

    def _column_value(self, row_map, aliases):
        normalized = {
            re.sub(r"[^a-z0-9]", "", str(key).lower()): value
            for key, value in row_map.items()
        }
        for alias in aliases:
            key = re.sub(r"[^a-z0-9]", "", alias.lower())
            if key in normalized:
                return normalized[key]
        return ""

    def _refresh_test_stock(self):
        tree, status = self.test_stock_tree, self.test_stock_status
        self._clear_test_tree(tree)
        status.set("Consultando est_ambTestes.dbo.ESTOQUE...")
        self.update_idletasks()
        try:
            columns, rows = self._read_test_table("ESTOQUE")
            for row in rows:
                m = dict(zip(columns, row))
                values = [
                    self._column_value(m, ["COD_ITEM", "Codigo", "CodProd", "CodigoProduto"]),
                    self._column_value(m, ["COD_BARRAS", "EAN", "GTIN", "EanProd"]),
                    self._column_value(m, ["DESCRICAO_ITEM", "Descricao", "DescProd", "DescricaoProduto"]),
                    self._column_value(m, ["LOCAL_ESTOQUE", "Local", "Localizacao", "Endereco"]),
                    self._column_value(m, ["SALDO_ATUAL", "Saldo", "Quantidade", "QtdEstoque", "Estoque"]),
                    self._column_value(m, ["DATA_ATUALIZACAO", "Atualizacao", "DataAtualizacao", "DataHora", "DtAtualizacao"]),
                    self._column_value(m, ["IDENT_TERMINAL", "Terminal", "ColetorID", "TerminalID"]),
                ]
                tree.insert("", "end", values=[self._format_test_value(v) for v in values])
            status.set("Banco vazio: nenhum registro encontrado." if not rows else f"{len(rows)} registro(s) carregado(s).")
        except Exception as e:
            status.set("Falha na consulta.")
            messagebox.showerror("Ambiente de Testes - Estoque Atual", f"Não foi possível consultar o estoque:\n{e}", parent=self)

    def _refresh_test_moves(self):
        tree, status = self.test_moves_tree, self.test_moves_status
        self._clear_test_tree(tree)
        status.set("Consultando est_ambTestes.dbo.movEstambTeste...")
        self.update_idletasks()
        try:
            columns, rows = self._read_test_table("movEstambTeste")
            for row in rows:
                m = dict(zip(columns, row))
                detalhe = self._column_value(
                    m, ["DETALHE", "Detalhe", "Mensagem", "Observacao", "Motivo"]
                )
                descricao = ""
                if detalhe:
                    partes = str(detalhe).split("|")
                    if len(partes) >= 2:
                        descricao = partes[1].strip()

                saldo_anterior = self._column_value(m, ["SALDO_ANTERIOR", "SaldoAntes", "SaldoAnterior"])
                qtd_movimentada = self._column_value(m, ["QTD_MOVIMENTADA", "Qtd", "Quantidade", "Qtde", "QtdMovimento"])
                saldo_posterior = self._column_value(m, ["SALDO_POSTERIOR", "SaldoDepois", "SaldoAtual", "NovoSaldo"])

                values = [
                    self._column_value(m, ["COD_ITEM", "Produto", "Codigo", "CodProd", "CodigoProduto"]),
                    self._column_value(m, ["COD_BARRAS", "EAN", "GTIN", "EanProd"]),
                    descricao,
                    saldo_anterior,
                    qtd_movimentada,
                    saldo_posterior,
                    saldo_posterior,
                    self._column_value(m, ["DATA_HORA", "DataHora", "DataMovimento", "Data", "DtMovimento"]),
                    self._column_value(m, ["TIPO_OPERACAO", "Operacao", "TipoOperacao", "Movimento"]),
                    self._column_value(m, ["NUM_DOCUMENTO", "Documento", "NumDoc", "NumNota", "NF"]),
                    self._column_value(m, ["IDENT_TERMINAL", "Terminal", "ColetorID", "TerminalID"]),
                    self._column_value(m, ["RESULTADO", "Resultado", "Status"]),
                    detalhe,
                ]
                tree.insert("", "end", values=[self._format_test_value(v) for v in values])
            status.set("Banco vazio: nenhum registro encontrado." if not rows else f"{len(rows)} registro(s) carregado(s).")
        except Exception as e:
            status.set("Falha na consulta.")
            messagebox.showerror("Ambiente de Testes - Movimentações", f"Não foi possível consultar as movimentações:\n{e}", parent=self)


    def _build_status_tab(self):
        top = ttk.LabelFrame(self.tab_status, text="Status do sistema")
        top.pack(fill="x", padx=10, pady=(10, 6))

        self.status_vars = {
            "importer": tk.StringVar(value="Verificando..."),
            "sql": tk.StringVar(value="Verificando..."),
            "pending": tk.StringVar(value="0"),
            "updated": tk.StringVar(value="-"),
            "result": tk.StringVar(value="-"),
        }

        labels = [
            ("Importador", "importer"),
            ("SQL Server", "sql"),
            ("Arquivos pendentes", "pending"),
            ("Última atualização", "updated"),
            ("Último resultado", "result"),
        ]

        for row, (label, key) in enumerate(labels):
            ttk.Label(top, text=f"{label}:").grid(
                row=row, column=0, sticky="w", padx=(10, 6), pady=4
            )
            ttk.Label(top, textvariable=self.status_vars[key]).grid(
                row=row, column=1, sticky="w", padx=(0, 10), pady=4
            )

        top.grid_columnconfigure(1, weight=1)

        info = ttk.LabelFrame(self.tab_status, text="Ambiente")
        info.pack(fill="x", padx=10, pady=6)

        self.status_env = tk.StringVar(value="")
        ttk.Label(
            info,
            textvariable=self.status_env,
            justify="left",
        ).pack(anchor="w", padx=10, pady=8)

        logs = ttk.LabelFrame(self.tab_status, text="Logs da aplicação")
        logs.pack(fill="both", expand=True, padx=10, pady=6)

        self.logs_nb = ttk.Notebook(logs)
        self.logs_nb.pack(fill="both", expand=True, padx=4, pady=4)

        self.tab_log_usuario = ttk.Frame(self.logs_nb)
        self.tab_log_tecnico = ttk.Frame(self.logs_nb)

        self.logs_nb.add(self.tab_log_usuario, text="Log do Usuário")
        self.logs_nb.add(self.tab_log_tecnico, text="Log Técnico")

        # ---- Log do usuário ----
        self.log_text = tk.Text(
            self.tab_log_usuario,
            wrap="none",
            height=14,
            state="disabled",
            font=("Consolas", 9),
        )
        user_y = ttk.Scrollbar(
            self.tab_log_usuario,
            orient="vertical",
            command=self.log_text.yview,
        )
        user_x = ttk.Scrollbar(
            self.tab_log_usuario,
            orient="horizontal",
            command=self.log_text.xview,
        )
        self.log_text.configure(
            yscrollcommand=user_y.set,
            xscrollcommand=user_x.set,
        )

        self.log_text.grid(row=0, column=0, sticky="nsew")
        user_y.grid(row=0, column=1, sticky="ns")
        user_x.grid(row=1, column=0, sticky="ew")
        self.tab_log_usuario.grid_rowconfigure(0, weight=1)
        self.tab_log_usuario.grid_columnconfigure(0, weight=1)

        # ---- Log técnico ----
        self.tech_log_text = tk.Text(
            self.tab_log_tecnico,
            wrap="none",
            height=14,
            state="disabled",
            font=("Consolas", 9),
        )
        tech_y = ttk.Scrollbar(
            self.tab_log_tecnico,
            orient="vertical",
            command=self.tech_log_text.yview,
        )
        tech_x = ttk.Scrollbar(
            self.tab_log_tecnico,
            orient="horizontal",
            command=self.tech_log_text.xview,
        )
        self.tech_log_text.configure(
            yscrollcommand=tech_y.set,
            xscrollcommand=tech_x.set,
        )

        self.tech_log_text.grid(row=0, column=0, sticky="nsew")
        tech_y.grid(row=0, column=1, sticky="ns")
        tech_x.grid(row=1, column=0, sticky="ew")
        self.tab_log_tecnico.grid_rowconfigure(0, weight=1)
        self.tab_log_tecnico.grid_columnconfigure(0, weight=1)

        actions = ttk.Frame(self.tab_status)
        actions.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(
            actions,
            text="↻ Atualizar",
            command=self._refresh_status_tab,
        ).pack(side="left")

    def _build_about_tab(self):
        container = ttk.Frame(self.tab_about, padding=28)
        container.pack(fill="both", expand=True)

        content = ttk.Frame(container)
        content.pack(anchor="nw", fill="x", padx=12, pady=10)

        # Logo menor no canto superior esquerdo.
        try:
            logo_path = resource_path(os.path.join("assets", "logo_2a.png"))
            image = Image.open(logo_path)
            image.thumbnail((210, 54), Image.LANCZOS)
            self._about_logo = ImageTk.PhotoImage(image)

            ttk.Label(
                content,
                image=self._about_logo,
            ).pack(anchor="w", pady=(0, 24))
        except Exception:
            ttk.Label(
                content,
                text="2A Tecnologia",
                font=("Segoe UI", 16),
            ).pack(anchor="w", pady=(0, 24))

        # Produto + versão na mesma linha, sem negrito e em tamanho discreto.
        title_row = ttk.Frame(content)
        title_row.pack(anchor="w", fill="x")

        ttk.Label(
            title_row,
            text="ImportFiles LogConf",
            font=("Segoe UI", 13),
        ).pack(side="left")

        ttk.Label(
            title_row,
            text="   |   ",
            font=("Segoe UI", 11),
        ).pack(side="left")

        ttk.Label(
            title_row,
            text=f"Versão {APP_VERSION} | Build {BUILD_DATE}",
            font=("Segoe UI", 11),
        ).pack(side="left")

        ttk.Separator(content, orient="horizontal").pack(
            fill="x", pady=(16, 20)
        )

        ttk.Label(
            content,
            text=(
                "Sistema para integração de dados de conferência para processos de\n"
                "recebimento, expedição e separação de mercadorias."
            ),
            justify="left",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 20))

        ttk.Separator(content, orient="horizontal").pack(
            fill="x", pady=(0, 20)
        )

        ttk.Label(
            content,
            text="Desenvolvido por 2A Tecnologia",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 14))

        contacts = ttk.Frame(content)
        contacts.pack(anchor="w", pady=(0, 18))

        self._about_contact_icons = []

        contact_rows = [
            ("whatsapp.png", "Telefone / WhatsApp:", "(11) 95246-9907"),
            ("email.png", "E-mail:", "faleconosco@2atecnologia.com.br"),
            ("site.png", "Site:", "2atec.com.br"),
        ]

        for row, (icon_name, label_text, value_text) in enumerate(contact_rows):
            try:
                icon_path = resource_path(os.path.join("assets", icon_name))
                icon_img = Image.open(icon_path)
                icon_img.thumbnail((22, 22), Image.LANCZOS)
                icon_photo = ImageTk.PhotoImage(icon_img)
                self._about_contact_icons.append(icon_photo)

                ttk.Label(
                    contacts,
                    image=icon_photo,
                ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=7)
            except Exception:
                ttk.Label(
                    contacts,
                    text="",
                    width=3,
                ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=7)

            ttk.Label(
                contacts,
                text=label_text,
                font=("Segoe UI", 10, "bold"),
            ).grid(row=row, column=1, sticky="w", padx=(0, 12), pady=7)

            ttk.Label(
                contacts,
                text=value_text,
                font=("Segoe UI", 10),
            ).grid(row=row, column=2, sticky="w", pady=7)

        ttk.Separator(content, orient="horizontal").pack(
            fill="x", pady=(0, 18)
        )

        ttk.Label(
            content,
            text="© 2026 2A Tecnologia\nTodos os direitos reservados.",
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

    def _on_main_tab_changed(self, event=None):
        """Maximiza somente a aba Ambiente de Testes e restaura nas demais."""
        try:
            current = self.nb.select()

            if current == str(self.tab_connector):
                # Consulta a conexão de verdade ao entrar na aba.
                self.after(100, self._refresh_external_connection_status_silent)

            if current == str(self.tab_test_environment):
                if not self._test_env_maximized:
                    self._normal_geometry = self.geometry()
                    try:
                        self.state("zoomed")
                    except Exception:
                        self.attributes("-zoomed", True)
                    self._test_env_maximized = True
            else:
                if self._test_env_maximized:
                    try:
                        self.state("normal")
                    except Exception:
                        try:
                            self.attributes("-zoomed", False)
                        except Exception:
                            pass

                    if self._normal_geometry:
                        self.geometry(self._normal_geometry)

                    self._test_env_maximized = False
        except Exception:
            pass

    def _select_initial_tab(self):
        initial = str(self.initial_tab).strip().lower()
        if initial == "status":
            self.nb.select(self.tab_status)
            self._refresh_status_tab()
        elif initial == "about":
            self.nb.select(self.tab_about)
            self.update_idletasks()
        else:
            self.nb.select(0)

    def _importer_rodando(self) -> bool:
        if os.name != "nt":
            return False

        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ImportFilesLogConfImporter.exe"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=3,
            )
            return "ImportFilesLogConfImporter.exe" in (result.stdout or "")
        except Exception:
            return False

    def _count_pending_files(self) -> int:
        try:
            input_dir = self.cfg.get(
                "watch",
                "input_dir",
                fallback=r"C:\MIS\entrada",
            ).strip()

            if not os.path.isdir(input_dir):
                return 0

            return sum(
                1
                for name in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, name))
            )
        except Exception:
            return 0

    def _get_log_path(self) -> str:
        log_dir = self.cfg.get(
            "logging",
            "log_dir",
            fallback=os.path.join(BASE_DIR, "logs"),
        ).strip()
        return os.path.join(log_dir, "usuario.log")

    def _read_recent_events(self, max_lines=160):
        log_path = self._get_log_path()

        if not os.path.isfile(log_path):
            return ["Nenhum evento para o usuário registrado ainda."]

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                linhas = [line.rstrip("\n") for line in f.readlines()]

            # usuario.log é gravado em blocos separados por linha em branco.
            # Mantemos o arquivo original intacto e apenas invertemos os blocos
            # para mostrar o evento mais recente no topo da interface.
            blocos = []
            bloco_atual = []

            for linha in linhas:
                if linha.strip():
                    bloco_atual.append(linha)
                elif bloco_atual:
                    blocos.append(bloco_atual)
                    bloco_atual = []

            if bloco_atual:
                blocos.append(bloco_atual)

            blocos.reverse()

            resultado = []
            for bloco in blocos:
                resultado.extend(bloco)
                resultado.append("")

                if len(resultado) >= max_lines:
                    break

            return resultado[:max_lines] or ["Nenhum evento para o usuário registrado ainda."]

        except Exception as e:
            return [f"Não foi possível ler o log do usuário: {e}"]

    def _read_technical_events(self, max_lines=220):
        log_dir = self.cfg.get(
            "logging",
            "log_dir",
            fallback=os.path.join(BASE_DIR, "logs"),
        ).strip()
        log_path = os.path.join(log_dir, "importador.log")

        if not os.path.isfile(log_path):
            return ["Nenhum evento técnico registrado ainda."]

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                linhas = [line.rstrip("\n") for line in f.readlines()]

            # Cada linha que começa com timestamp inicia um novo evento.
            # Linhas de traceback/continuação permanecem junto do evento anterior.
            inicio = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
            blocos = []
            atual = []

            for linha in linhas:
                if inicio.match(linha):
                    if atual:
                        blocos.append(atual)
                    atual = [linha]
                else:
                    if atual:
                        atual.append(linha)
                    elif linha.strip():
                        atual = [linha]

            if atual:
                blocos.append(atual)

            blocos.reverse()

            resultado = []
            for bloco in blocos:
                resultado.extend(bloco)
                resultado.append("")
                if len(resultado) >= max_lines:
                    break

            return resultado[:max_lines] or ["Nenhum evento técnico registrado ainda."]

        except Exception as e:
            return [f"Não foi possível ler o log técnico: {e}"]

    def _last_result_from_log(self) -> str:
        lines = self._read_recent_events(max_lines=80)
        for line in reversed(lines):
            if " | " in line:
                partes = line.split(" | ", 2)
                if len(partes) == 3 and partes[1] in ("OK", "ERRO", "ATENÇÃO", "INFO"):
                    return partes[2]
        return "-"

    def _refresh_status_tab(self):
        # Recarrega config para refletir qualquer alteração salva.
        self.cfg = load_cfg()
        runtime = read_runtime_status(BASE_DIR) or {}

        importer_ok = self._importer_rodando()
        estado = runtime.get("estado", "")

        self.status_vars["importer"].set(
            "AGUARDANDO NOVOS LANÇAMENTOS"
        )

        if estado == "SQL_PENDENTE":
            self.status_vars["sql"].set("INDISPONÍVEL")
        elif estado == "OK":
            self.status_vars["sql"].set("CONECTADO")
        else:
            self.status_vars["sql"].set("NÃO VERIFICADO")

        self.status_vars["pending"].set(str(self._count_pending_files()))
        self.status_vars["updated"].set(runtime.get("updated_at", "-") or "-")
        self.status_vars["result"].set(self._last_result_from_log())

        servidor = self.cfg.get("sql", "server", fallback="-")
        banco = self.cfg.get("sql", "database", fallback="-")
        formato = self.cfg.get("input", "format", fallback="-").upper()
        entrada = self.cfg.get("watch", "input_dir", fallback="-")

        self.status_env.set(
            f"Servidor SQL: {servidor}\n"
            f"Banco: {banco}\n"
            f"Formato: {formato}\n"
            f"Pasta monitorada: {entrada}"
        )

        events = self._read_recent_events()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(events))
        self.log_text.see("1.0")
        self.log_text.configure(state="disabled")

        technical_events = self._read_technical_events()
        self.tech_log_text.configure(state="normal")
        self.tech_log_text.delete("1.0", "end")
        self.tech_log_text.insert("1.0", "\n".join(technical_events))
        self.tech_log_text.see("1.0")
        self.tech_log_text.configure(state="disabled")

    def _status_auto_refresh(self):
        try:
            if hasattr(self, "nb") and hasattr(self, "tab_status"):
                if self.nb.select() == str(self.tab_status):
                    self._refresh_status_tab()
        finally:
            if self.winfo_exists():
                self.after(5000, self._status_auto_refresh)

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

        # Conexões externas (isoladas do Banco Local logConf)
        self._load_external_connections()

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

        # Arquivos de Saída
        self.vars["output.output_dir"].set(g("output", "output_dir", r"C:\MIS\saida"))

        # Compatibilidade com configurações antigas:
        # product_id=codigo/gtin/ambos e include_numdoc=yes/no.
        modo_antigo = g("output", "product_id", "ambos").strip().lower()
        incluir_numdoc_antigo = as_bool(g("output", "include_numdoc", "yes"))

        self.vars["output.export_numdoc"].set(
            as_bool(g("output", "export_numdoc", "yes" if incluir_numdoc_antigo else "no"))
        )
        self.vars["output.export_codigo"].set(
            as_bool(g("output", "export_codigo", "yes" if modo_antigo in ("codigo", "ambos") else "no"))
        )
        self.vars["output.export_gtin"].set(
            as_bool(g("output", "export_gtin", "yes" if modo_antigo in ("gtin", "ambos") else "no"))
        )
        self.vars["output.export_descricao"].set(
            as_bool(g("output", "export_descricao", "no"))
        )
        self.vars["output.export_qtdeesperada"].set(
            as_bool(g("output", "export_qtdeesperada", "no"))
        )
        self.vars["output.export_qtdelida"].set(
            as_bool(g("output", "export_qtdelida", "yes"))
        )
        self.vars["output.export_saldo"].set(
            as_bool(g("output", "export_saldo", "no"))
        )

        self.vars["output.individual_file"].set(as_bool(g("output", "individual_file", "yes")))
        self.vars["output.daily_file"].set(as_bool(g("output", "daily_file", "yes")))
        self.vars["output.delimiter"].set(g("output", "delimiter", ";"))

        file_name_labels = {
            "numdoc": "Só número do documento",
            "numdoc_data": "Número do documento + data",
            "numdoc_data_hora": "Número do documento + data + hora",
        }
        modo_nome = g("output", "file_name_mode", "numdoc_data_hora").strip().lower()
        self.vars["output.file_name_mode"].set(
            file_name_labels.get(modo_nome, file_name_labels["numdoc_data_hora"])
        )

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

        # Arquivos de Saída
        setv("output", "output_dir", self.vars["output.output_dir"].get().strip())
        setv("output", "export_numdoc", bool_to_ini(self.vars["output.export_numdoc"].get()))
        setv("output", "export_codigo", bool_to_ini(self.vars["output.export_codigo"].get()))
        setv("output", "export_gtin", bool_to_ini(self.vars["output.export_gtin"].get()))
        setv("output", "export_descricao", bool_to_ini(self.vars["output.export_descricao"].get()))
        setv("output", "export_qtdeesperada", bool_to_ini(self.vars["output.export_qtdeesperada"].get()))
        setv("output", "export_qtdelida", bool_to_ini(self.vars["output.export_qtdelida"].get()))
        setv("output", "export_saldo", bool_to_ini(self.vars["output.export_saldo"].get()))
        setv("output", "individual_file", bool_to_ini(self.vars["output.individual_file"].get()))
        setv("output", "daily_file", bool_to_ini(self.vars["output.daily_file"].get()))
        setv("output", "delimiter", self.vars["output.delimiter"].get() or ";")

        modos_nome = {
            "Só número do documento": "numdoc",
            "Número do documento + data": "numdoc_data",
            "Número do documento + data + hora": "numdoc_data_hora",
        }
        setv(
            "output",
            "file_name_mode",
            modos_nome.get(
                self.vars["output.file_name_mode"].get(),
                "numdoc_data_hora",
            ),
        )

    def _reload_external_connections_from_disk(self):
        """Recarrega somente as conexões externas salvas no config.ini."""
        cfg_disco = load_cfg()

        # Remove apenas as seções externas da cópia em memória.
        for section in list(self.cfg.sections()):
            if section.startswith("external_connection:"):
                self.cfg.remove_section(section)

        # Copia novamente do arquivo em disco.
        for section in cfg_disco.sections():
            if section.startswith("external_connection:"):
                self.cfg[section] = dict(cfg_disco[section])

        # Compatibilidade com a seção antiga [connector].
        if cfg_disco.has_section("connector"):
            if self.cfg.has_section("connector"):
                self.cfg.remove_section("connector")
            self.cfg["connector"] = dict(cfg_disco["connector"])

        self._load_external_connections()


    def _external_section_name(self, connection_id: str) -> str:
        return f"external_connection:{connection_id}"


    def _load_external_connections(self):
        """Carrega somente as conexões externas para o gerenciador."""
        if not hasattr(self, "current_external_vars"):
            return

        previous_current_external_id = getattr(self, "current_external_id", None)
        self.external_connections = {}

        # Compatibilidade: se já existia a seção [connector] da Etapa 1,
        # ela aparece como uma conexão externa sem alterar o Banco Local logConf.
        external_sections = [
            section for section in self.cfg.sections()
            if section.startswith("external_connection:")
        ]

        if not external_sections and self.cfg.has_section("connector"):
            legacy_has_data = any(
                self.cfg.get("connector", key, fallback="").strip()
                for key in ("server", "database", "user")
            )
            if legacy_has_data:
                connection_id = "legacy"
                self.external_connections[connection_id] = {
                    "id": connection_id,
                    "name": self.cfg.get("connector", "name", fallback="ERP / Conexão externa").strip() or "ERP / Conexão externa",
                    "type": self.cfg.get("connector", "type", fallback="Microsoft SQL Server").strip() or "Microsoft SQL Server",
                    "driver": self.cfg.get("connector", "driver", fallback="ODBC Driver 18 for SQL Server").strip(),
                    "server": self.cfg.get("connector", "server", fallback="").strip(),
                    "port": self.cfg.get("connector", "port", fallback="1433").strip(),
                    "database": self.cfg.get("connector", "database", fallback="").strip(),
                    "trusted_connection": as_bool(self.cfg.get("connector", "trusted_connection", fallback="no")),
                    "user": self.cfg.get("connector", "user", fallback="").strip(),
                    "password": self.cfg.get("connector", "password", fallback=""),
                    "schema": self.cfg.get("connector", "schema", fallback="dbo").strip() or "dbo",
                    "table": self.cfg.get("connector", "table", fallback="").strip(),
                    "field_codprod": self.cfg.get("connector", "field_codprod", fallback="").strip(),
                    "field_gtin": self.cfg.get("connector", "field_gtin", fallback="").strip(),
                    "field_saldo": self.cfg.get("connector", "field_saldo", fallback="").strip(),
                    "field_local": self.cfg.get("connector", "field_local", fallback="").strip(),
                    "field_terminal": self.cfg.get("connector", "field_terminal", fallback="").strip(),
                    "field_documento": self.cfg.get("connector", "field_documento", fallback="").strip(),
                    "status": "Não testado",
                }

        for section in external_sections:
            connection_id = section.split(":", 1)[1]
            self.external_connections[connection_id] = {
                "id": connection_id,
                "name": self.cfg.get(section, "name", fallback="Conexão externa").strip() or "Conexão externa",
                "type": self.cfg.get(section, "type", fallback="Microsoft SQL Server").strip() or "Microsoft SQL Server",
                "driver": self.cfg.get(section, "driver", fallback="ODBC Driver 18 for SQL Server").strip(),
                "server": self.cfg.get(section, "server", fallback="").strip(),
                "port": self.cfg.get(section, "port", fallback="1433").strip(),
                "database": self.cfg.get(section, "database", fallback="").strip(),
                "trusted_connection": as_bool(self.cfg.get(section, "trusted_connection", fallback="no")),
                "user": self.cfg.get(section, "user", fallback="").strip(),
                "password": self.cfg.get(section, "password", fallback=""),
                "schema": self.cfg.get(section, "schema", fallback="dbo").strip() or "dbo",
                "table": self.cfg.get(section, "table", fallback="").strip(),
                "field_codprod": self.cfg.get(section, "field_codprod", fallback="").strip(),
                "field_gtin": self.cfg.get(section, "field_gtin", fallback="").strip(),
                "field_saldo": self.cfg.get(section, "field_saldo", fallback="").strip(),
                "field_local": self.cfg.get(section, "field_local", fallback="").strip(),
                "field_terminal": self.cfg.get(section, "field_terminal", fallback="").strip(),
                "field_documento": self.cfg.get(section, "field_documento", fallback="").strip(),
                "status": "Não testado",
            }

        if (
            previous_current_external_id
            and previous_current_external_id in self.external_connections
        ):
            self.current_external_id = previous_current_external_id
        elif self.external_connections:
            self.current_external_id = next(iter(self.external_connections))
        else:
            self.current_external_id = None

        self._refresh_external_tree()


    def _refresh_external_tree(self):
        """Atualiza a exibição permanente da conexão externa atual."""
        if not hasattr(self, "current_external_vars"):
            return

        # Mantém a conexão atual se ela ainda existir; caso contrário,
        # usa a primeira conexão salva.
        if (
            not getattr(self, "current_external_id", None)
            or self.current_external_id not in self.external_connections
        ):
            self.current_external_id = (
                next(iter(self.external_connections), None)
                if self.external_connections
                else None
            )

        data = (
            self.external_connections.get(self.current_external_id, {})
            if self.current_external_id
            else {}
        )

        trusted = bool(data.get("trusted_connection", False))
        password = data.get("password", "")

        values = {
            "name": data.get("name", ""),
            "type": data.get("type", ""),
            "driver": data.get("driver", ""),
            "server": data.get("server", ""),
            "port": data.get("port", ""),
            "database": data.get("database", ""),
            "auth": (
                "Windows (Trusted Connection)"
                if trusted
                else ("SQL Server (usuário e senha)" if data else "")
            ),
            "user": "" if trusted else data.get("user", ""),
            "password": ("*" * len(password)) if password and not trusted else "",
            "status": data.get("status", "Salvo") if data else "Nenhuma conexão cadastrada",
        }

        for key, value in values.items():
            self.current_external_vars[key].set(value)

        has_connection = bool(data)
        button_state = "normal" if has_connection else "disabled"

        if hasattr(self, "btn_external_edit"):
            self.btn_external_edit.configure(state=button_state)
        if hasattr(self, "btn_external_delete"):
            self.btn_external_delete.configure(state=button_state)
        if hasattr(self, "btn_external_test"):
            self.btn_external_test.configure(state=button_state)

        # Com conexão: mostra os dados.
        # Sem conexão: esconde os campos vazios e mostra uma orientação clara.
        if hasattr(self, "external_detail_widgets"):
            for widget in self.external_detail_widgets:
                if has_connection:
                    widget.grid()
                else:
                    widget.grid_remove()

        if hasattr(self, "external_empty_frame"):
            if has_connection:
                self.external_empty_frame.grid_remove()
            else:
                self.external_empty_frame.grid()

        if hasattr(self, "external_mapping_var"):
            if has_connection:
                schema = data.get("schema", "dbo") or "dbo"
                table = data.get("table", "")
                cod = data.get("field_codprod", "") or "-"
                gtin = data.get("field_gtin", "") or "-"
                saldo = data.get("field_saldo", "") or "-"
                self.external_mapping_var.set(
                    f"Destino: {schema}.{table or '-'} | "
                    f"CodProd → {cod} | GTIN → {gtin} | Saldo → {saldo}"
                )
            else:
                self.external_mapping_var.set("")

        if hasattr(self, "external_live_status_var"):
            if not has_connection:
                self.external_live_status_var.set("● Conexão SQL: nenhuma conexão configurada")
            else:
                estado = str(data.get("status", "Não testado"))
                if estado == "Conectado":
                    self.external_live_status_var.set(
                        f"● Conectado ao SQL Server | "
                        f"{data.get('server', '-') or '-'} | "
                        f"{data.get('database', '-') or '-'}"
                    )
                elif estado == "Falha":
                    self.external_live_status_var.set(
                        f"● Desconectado | "
                        f"{data.get('server', '-') or '-'} | "
                        f"{data.get('database', '-') or '-'}"
                    )
                else:
                    self.external_live_status_var.set(
                        f"● Conexão SQL: não verificada | "
                        f"{data.get('server', '-') or '-'} | "
                        f"{data.get('database', '-') or '-'}"
                    )

        if hasattr(self, "external_hint_var"):
            if has_connection:
                self.external_hint_var.set(
                    "Nova conexão abre o assistente vazio. Editar abre a conexão atual "
                    "com os dados preenchidos."
                )
            else:
                self.external_hint_var.set(
                    "Nenhuma conexão configurada. Use “Nova conexão” para começar."
                )


    def _save_external_connections(self):
        """Persiste apenas as conexões externas em seções próprias."""
        for section in list(self.cfg.sections()):
            if section.startswith("external_connection:"):
                self.cfg.remove_section(section)

        for connection_id, data in self.external_connections.items():
            section = self._external_section_name(connection_id)
            self.cfg[section] = {
                "name": data.get("name", ""),
                "type": data.get("type", "Microsoft SQL Server"),
                "driver": data.get("driver", "ODBC Driver 18 for SQL Server"),
                "server": data.get("server", ""),
                "port": data.get("port", "1433"),
                "database": data.get("database", ""),
                "trusted_connection": bool_to_ini(bool(data.get("trusted_connection", False))),
                "user": data.get("user", ""),
                "password": data.get("password", ""),
                "schema": data.get("schema", "dbo"),
                "table": data.get("table", ""),
                "field_codprod": data.get("field_codprod", ""),
                "field_gtin": data.get("field_gtin", ""),
                "field_saldo": data.get("field_saldo", ""),
                "field_local": data.get("field_local", ""),
                "field_terminal": data.get("field_terminal", ""),
                "field_documento": data.get("field_documento", ""),
            }

        save_cfg(self.cfg)


    def _selected_external_id(self):
        return getattr(self, "current_external_id", None)


    def _new_external_connection(self):
        self._open_external_connection_dialog()




    def _edit_external_connection(self):
        connection_id = self._selected_external_id()
        if not connection_id:
            messagebox.showinfo(
                "Conexões Externas",
                "Nenhuma conexão atual está cadastrada para editar.",
            )
            return

        data = self.external_connections.get(connection_id)
        if not data:
            return

        self._open_external_connection_dialog(connection_id, data)


    def _delete_external_connection(self):
        """Exclui a conexão externa atual e deixa a tela em estado sem conexão."""
        connection_id = self._selected_external_id()
        if not connection_id:
            messagebox.showinfo(
                "Conexões Externas",
                "Nenhuma conexão externa está cadastrada.",
                parent=self,
            )
            return

        data = self.external_connections.get(connection_id, {})
        connection_name = data.get("name", "Conexão atual")

        if not messagebox.askyesno(
            "Excluir conexão",
            f'Deseja realmente excluir a conexão "{connection_name}"?',
            parent=self,
        ):
            return

        # Remove somente a conexão externa atual.
        self.external_connections.pop(connection_id, None)

        section = self._external_section_name(connection_id)
        if self.cfg.has_section(section):
            self.cfg.remove_section(section)

        # Remove também a configuração antiga [connector] para impedir
        # que uma conexão excluída reapareça ao reabrir a aplicação.
        if self.cfg.has_section("connector"):
            self.cfg.remove_section("connector")

        save_cfg(self.cfg)

        self.current_external_id = None
        self.external_connections = {}
        self._refresh_external_tree()
        self.update_idletasks()

        messagebox.showinfo(
            "Conexões Externas",
            "Conexão excluída com sucesso.",
            parent=self,
        )


    def _open_external_connection_dialog(self, connection_id=None, initial=None):
        initial = dict(initial or {})
        editing = connection_id is not None

        dlg = tk.Toplevel(self)
        dlg.title("Editar conexão externa" if editing else "Nova conexão externa")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        # Layout horizontal: mais largo e mais baixo para caber integralmente na tela.
        width = 1040
        height = 570
        self.update_idletasks()
        x = max(0, self.winfo_rootx() + (self.winfo_width() - width) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - height) // 2)
        dlg.geometry(f"{width}x{height}+{x}+{y}")

        content = ttk.Frame(dlg)
        content.pack(fill="both", expand=True, padx=12, pady=(12, 6))

        sql_frame = ttk.LabelFrame(content, text="Conexão SQL")
        sql_frame.pack(side="left", fill="both", expand=True, padx=(0, 6))

        map_frame = ttk.LabelFrame(content, text="Mapeamento da tabela de estoque do ERP")
        map_frame.pack(side="left", fill="both", expand=True, padx=(6, 0))

        vars_dlg = {
            "name": tk.StringVar(value=initial.get("name", "")),
            "type": tk.StringVar(value=initial.get("type", "Microsoft SQL Server")),
            "driver": tk.StringVar(value=initial.get("driver", "ODBC Driver 18 for SQL Server")),
            "server": tk.StringVar(value=initial.get("server", "")),
            "port": tk.StringVar(value=initial.get("port", "1433")),
            "database": tk.StringVar(value=initial.get("database", "")),
            "trusted": tk.BooleanVar(value=bool(initial.get("trusted_connection", False))),
            "user": tk.StringVar(value=initial.get("user", "")),
            "password": tk.StringVar(value=initial.get("password", "")),
            "schema": tk.StringVar(value=initial.get("schema", "dbo") or "dbo"),
            "table": tk.StringVar(value=initial.get("table", "")),
            "field_codprod": tk.StringVar(value=initial.get("field_codprod", "")),
            "field_gtin": tk.StringVar(value=initial.get("field_gtin", "")),
            "field_saldo": tk.StringVar(value=initial.get("field_saldo", "")),
            "field_local": tk.StringVar(value=initial.get("field_local", "")),
            "field_terminal": tk.StringVar(value=initial.get("field_terminal", "")),
            "field_documento": tk.StringVar(value=initial.get("field_documento", "")),
        }

        def add_entry(parent, row, label, key, show=None):
            ttk.Label(parent, text=label).grid(
                row=row, column=0, sticky="w", padx=8, pady=7
            )
            entry = ttk.Entry(
                parent, textvariable=vars_dlg[key], width=38, show=show
            )
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=7)
            return entry

        # Coluna esquerda: conexão.
        ent_name = add_entry(sql_frame, 0, "Nome da conexão", "name")

        ttk.Label(sql_frame, text="Tipo de banco").grid(
            row=1, column=0, sticky="w", padx=8, pady=7
        )
        cmb_type = ttk.Combobox(
            sql_frame,
            textvariable=vars_dlg["type"],
            values=[
                "Microsoft SQL Server",
                "PostgreSQL (em breve)",
                "MySQL / MariaDB (em breve)",
                "Oracle (em breve)",
                "SAP HANA (em breve)",
                "ODBC genérico (em breve)",
                "OLE DB (em breve)",
            ],
            state="readonly",
            width=35,
        )
        cmb_type.grid(row=1, column=1, sticky="ew", padx=8, pady=7)

        ent_driver = add_entry(sql_frame, 2, "Driver ODBC", "driver")
        ent_server = add_entry(sql_frame, 3, "Servidor", "server")
        ent_port = add_entry(sql_frame, 4, "Porta", "port")
        ent_database = add_entry(sql_frame, 5, "Banco", "database")

        chk_trusted = ttk.Checkbutton(
            sql_frame,
            text="Usar autenticação do Windows (Trusted Connection)",
            variable=vars_dlg["trusted"],
        )
        chk_trusted.grid(
            row=6, column=0, columnspan=2, sticky="w", padx=8, pady=9
        )

        ent_user = add_entry(sql_frame, 7, "Usuário", "user")
        ent_password = add_entry(sql_frame, 8, "Senha", "password", show="*")

        sql_frame.grid_columnconfigure(0, minsize=125)
        sql_frame.grid_columnconfigure(1, weight=1)

        # Coluna direita: nomes reais da tabela/campos do ERP.
        ttk.Label(
            map_frame,
            text=(
                "Informe exatamente os nomes existentes no banco do cliente. "
                "Nenhum UPDATE é executado nesta etapa."
            ),
            wraplength=430,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(9, 8))

        add_entry(map_frame, 1, "Schema", "schema")
        add_entry(map_frame, 2, "Tabela de estoque", "table")
        add_entry(map_frame, 3, "Campo CodProd", "field_codprod")
        add_entry(map_frame, 4, "Campo GTIN / EAN", "field_gtin")
        add_entry(map_frame, 5, "Campo Saldo", "field_saldo")
        add_entry(map_frame, 6, "Campo Localização", "field_local")
        add_entry(map_frame, 7, "Campo Terminal", "field_terminal")
        add_entry(map_frame, 8, "Campo Documento", "field_documento")

        ttk.Label(
            map_frame,
            text="Localização, Terminal e Documento são opcionais.",
            justify="left",
        ).grid(row=9, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 0))

        map_frame.grid_columnconfigure(0, minsize=145)
        map_frame.grid_columnconfigure(1, weight=1)

        # Rodapé fixo: nunca fica escondido.
        footer = ttk.Frame(dlg)
        footer.pack(side="bottom", fill="x", padx=12, pady=(4, 12))

        info_var = tk.StringVar(
            value="Nenhum dado será alterado. O teste executa somente uma consulta de identificação do banco."
        )
        ttk.Label(
            footer,
            textvariable=info_var,
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        buttons = ttk.Frame(footer)
        buttons.pack(side="right")

        def apply_auth_state():
            state = "disabled" if vars_dlg["trusted"].get() else "normal"
            ent_user.configure(state=state)
            ent_password.configure(state=state)

        chk_trusted.configure(command=apply_auth_state)
        apply_auth_state()

        buttons = ttk.Frame(dlg)
        buttons.pack(fill="x", padx=12, pady=(0, 12))

        def collect_data():
            name = vars_dlg["name"].get().strip()
            tipo = vars_dlg["type"].get().strip()
            driver = vars_dlg["driver"].get().strip()
            server = vars_dlg["server"].get().strip()
            port = vars_dlg["port"].get().strip()
            database = vars_dlg["database"].get().strip()
            trusted = vars_dlg["trusted"].get()
            user = vars_dlg["user"].get().strip()
            password = vars_dlg["password"].get()

            schema = vars_dlg["schema"].get().strip()
            table = vars_dlg["table"].get().strip()
            field_codprod = vars_dlg["field_codprod"].get().strip()
            field_gtin = vars_dlg["field_gtin"].get().strip()
            field_saldo = vars_dlg["field_saldo"].get().strip()
            field_local = vars_dlg["field_local"].get().strip()
            field_terminal = vars_dlg["field_terminal"].get().strip()
            field_documento = vars_dlg["field_documento"].get().strip()

            if not name:
                raise ValueError("Informe um nome para a conexão.")
            if tipo != "Microsoft SQL Server":
                raise ValueError(
                    "Nesta etapa, somente Microsoft SQL Server está disponível."
                )
            if not driver:
                raise ValueError("Informe o Driver ODBC.")
            if not server:
                raise ValueError("Informe o servidor SQL Server.")
            if port:
                if not port.isdigit() or not (1 <= int(port) <= 65535):
                    raise ValueError("Informe uma porta válida entre 1 e 65535.")
            if not database:
                raise ValueError("Informe o banco de dados.")
            if not trusted and not user:
                raise ValueError("Informe o usuário do SQL Server.")

            if not schema:
                raise ValueError("Informe o schema da tabela de estoque.")
            if not table:
                raise ValueError("Informe a tabela de estoque do ERP.")
            if not field_codprod and not field_gtin:
                raise ValueError("Informe pelo menos o Campo CodProd ou o Campo GTIN/EAN.")
            if not field_saldo:
                raise ValueError("Informe o campo de saldo do ERP.")

            return {
                "name": name,
                "type": tipo,
                "driver": driver,
                "server": server,
                "port": port,
                "database": database,
                "trusted_connection": trusted,
                "user": user,
                "password": password,
                "schema": schema,
                "table": table,
                "field_codprod": field_codprod,
                "field_gtin": field_gtin,
                "field_saldo": field_saldo,
                "field_local": field_local,
                "field_terminal": field_terminal,
                "field_documento": field_documento,
            }

        def test_dialog_connection():
            try:
                data = collect_data()
                banco_ok, servidor_ok = self._test_external_connection_data(data)
                info_var.set(
                    f"Conexão OK | Servidor: {servidor_ok} | Banco: {banco_ok} | Nenhum dado alterado."
                )
                messagebox.showinfo(
                    "Conexões Externas",
                    "Conexão realizada com sucesso.\n\n"
                    f"Servidor: {servidor_ok}\n"
                    f"Banco: {banco_ok}\n\n"
                    "Nenhum dado foi alterado.",
                    parent=dlg,
                )
            except Exception as e:
                messagebox.showerror(
                    "Conexões Externas",
                    f"Falha na conexão:\n{e}",
                    parent=dlg,
                )

        def save_dialog():
            try:
                data = collect_data()
            except Exception as e:
                messagebox.showerror(
                    "Conexões Externas",
                    str(e),
                    parent=dlg,
                )
                return

            cid = connection_id or uuid.uuid4().hex[:12]
            previous_status = initial.get("status", "Salvo")
            data["id"] = cid
            data["status"] = previous_status if previous_status in ("Conectado", "Falha") else "Salvo"
            self.external_connections[cid] = data
            self.current_external_id = cid
            self._save_external_connections()

            # Atualiza imediatamente a conexão atual exibida na aba.
            self._refresh_external_tree()
            self.update_idletasks()
            self.after(100, self._refresh_external_connection_status_silent)

            dlg.grab_release()
            dlg.destroy()
            self.nb.select(self.tab_connector)
            self.update_idletasks()

        ttk.Button(
            buttons,
            text="Testar conexão",
            command=test_dialog_connection,
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            buttons,
            text="Cancelar",
            command=dlg.destroy,
        ).pack(side="left", padx=(0, 8))

        ttk.Button(
            buttons,
            text="Salvar",
            command=save_dialog,
        ).pack(side="left")

        ent_name.focus_set()


    def _build_external_conn_str(self, data):
        driver = str(data.get("driver", "")).strip()
        server = str(data.get("server", "")).strip()
        database = str(data.get("database", "")).strip()
        port = str(data.get("port", "")).strip()
        trusted = bool(data.get("trusted_connection", False))

        server_target = f"{server},{port}" if port else server

        if trusted:
            return (
                f"DRIVER={{{driver}}};"
                f"SERVER={server_target};"
                f"DATABASE={database};"
                "Trusted_Connection=yes;"
                "TrustServerCertificate=yes;"
            )

        user = str(data.get("user", "")).strip()
        password = data.get("password", "")
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={server_target};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
            "TrustServerCertificate=yes;"
        )


    def _test_external_connection_data(self, data):
        if data.get("type") != "Microsoft SQL Server":
            raise ValueError(
                "Nesta etapa, somente Microsoft SQL Server está disponível."
            )

        conn_str = self._build_external_conn_str(data)
        conn = pyodbc.connect(conn_str, timeout=5)
        try:
            cur = conn.cursor()
            cur.execute("SELECT DB_NAME(), @@SERVERNAME")
            row = cur.fetchone()
        finally:
            conn.close()

        banco_ok = row[0] if row and row[0] else data.get("database", "")
        servidor_ok = row[1] if row and len(row) > 1 and row[1] else data.get("server", "")
        return banco_ok, servidor_ok


    def _refresh_external_connection_status_silent(self):
        """Testa a conexão atual sem abrir mensagens e atualiza somente o status visual."""
        connection_id = self._selected_external_id()
        if not connection_id:
            self._refresh_external_tree()
            return

        data = self.external_connections.get(connection_id)
        if not data:
            self._refresh_external_tree()
            return

        if hasattr(self, "external_live_status_var"):
            self.external_live_status_var.set(
                f"● Verificando conexão SQL... | "
                f"{data.get('server', '-') or '-'} | "
                f"{data.get('database', '-') or '-'}"
            )

        def worker():
            try:
                self._test_external_connection_data(data)
                ok = True
            except Exception:
                ok = False

            def finish():
                # A conexão pode ter sido excluída enquanto o teste rodava.
                if connection_id not in getattr(self, "external_connections", {}):
                    return
                self.external_connections[connection_id]["status"] = (
                    "Conectado" if ok else "Falha"
                )
                self._refresh_external_tree()

            try:
                self.after(0, finish)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()


    def _test_selected_external_connection(self):
        connection_id = self._selected_external_id()
        if not connection_id:
            messagebox.showinfo(
                "Conexões Externas",
                "Nenhuma conexão atual está cadastrada para testar.",
            )
            return

        data = self.external_connections.get(connection_id)
        if not data:
            return

        try:
            banco_ok, servidor_ok = self._test_external_connection_data(data)
            data["status"] = "Conectado"
            self._refresh_external_tree()

            messagebox.showinfo(
                "Conexões Externas",
                "Conexão realizada com sucesso.\n\n"
                f"Servidor: {servidor_ok}\n"
                f"Banco: {banco_ok}\n\n"
                "Nenhum dado foi alterado.",
            )
        except Exception as e:
            data["status"] = "Falha"
            self._refresh_external_tree()
            messagebox.showerror(
                "Conexões Externas",
                f"Falha na conexão:\n{e}",
            )


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

    def _save(self, show_message=True):
        try:
            self._write_from_form()

            # cria pastas (se não existirem)
            for sec, opt in (
                ("watch", "input_dir"),
                ("watch", "processed_dir"),
                ("watch", "error_dir"),
                ("watch", "duplicate_dir"),
                ("logging", "log_dir"),
                ("output", "output_dir"),
            ):
                p = self.cfg.get(sec, opt, fallback="").strip()
                if p:
                    os.makedirs(p, exist_ok=True)

            # Conexões externas são independentes e salvas em seções próprias.
            if hasattr(self, "external_connections"):
                for section in list(self.cfg.sections()):
                    if section.startswith("external_connection:"):
                        self.cfg.remove_section(section)

                for connection_id, data in self.external_connections.items():
                    section = self._external_section_name(connection_id)
                    self.cfg[section] = {
                        "name": data.get("name", ""),
                        "type": data.get("type", "Microsoft SQL Server"),
                        "driver": data.get("driver", "ODBC Driver 18 for SQL Server"),
                        "server": data.get("server", ""),
                        "port": data.get("port", "1433"),
                        "database": data.get("database", ""),
                        "trusted_connection": bool_to_ini(bool(data.get("trusted_connection", False))),
                        "user": data.get("user", ""),
                        "password": data.get("password", ""),
                        "schema": data.get("schema", "dbo"),
                        "table": data.get("table", ""),
                        "field_codprod": data.get("field_codprod", ""),
                        "field_gtin": data.get("field_gtin", ""),
                        "field_saldo": data.get("field_saldo", ""),
                        "field_local": data.get("field_local", ""),
                        "field_terminal": data.get("field_terminal", ""),
                        "field_documento": data.get("field_documento", ""),
                    }

            save_cfg(self.cfg)
            if show_message:
                messagebox.showinfo("Salvar", f"Salvo em: {os.path.abspath(CONFIG_PATH)}")
            return True
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return False

    def _save_and_close(self):
        """Salva o estado atual de todas as abas e fecha somente se salvar com sucesso."""
        if self._save(show_message=False):
            self.destroy()


if __name__ == "__main__":
    app = ConfigUI()
    app.mainloop()
    def __init__(self, initial_tab="config"):
        super().__init__()
        self.title("Gestor de Dados - 2A Tecnologia")

        # Ícone da janela. Salvar como assets/gestor_dados_icon.png
        try:
            icon_path = resource_path(os.path.join("assets", "gestor_dados_icon.png"))
            self._window_icon = tk.PhotoImage(file=icon_path)
            self.iconphoto(True, self._window_icon)
        except Exception:
            pass

        # Janela mais compacta e centralizada na tela.
        window_width = 900
        window_height = 540
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        pos_x = max(0, (screen_width - window_width) // 2)
        pos_y = max(0, (screen_height - window_height) // 2)
        self.geometry(f"{window_width}x{window_height}+{pos_x}+{pos_y}")
        self.minsize(900, 540)
        self.resizable(True, True)

        self._normal_geometry = self.geometry()
        self._test_env_maximized = False

        self.initial_tab = initial_tab

        self.cfg = load_cfg()

        self.vars = {}
        self.widgets = {}

        self._build()
        self._load_to_form()
        self._apply_states()
        self._select_initial_tab()

        # Qualquer forma de fechar a janela salva todas as configurações.
        self.protocol("WM_DELETE_WINDOW", self._save_and_close)

        # Atualiza a aba de Status/Logs periodicamente enquanto a janela estiver aberta.
        self.after(300, self._status_auto_refresh)

    def _build(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.nb.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        tab_sql = ttk.Frame(self.nb)
        tab_paths = ttk.Frame(self.nb)
        tab_input = ttk.Frame(self.nb)
        tab_app = ttk.Frame(self.nb)
        tab_output = ttk.Frame(self.nb)
        tab_connector = ttk.Frame(self.nb)
        self.tab_connector = tab_connector
        self.tab_test_environment = ttk.Frame(self.nb)
        self.tab_status = ttk.Frame(self.nb)

        self.nb.add(tab_sql, text="Banco Local logConf")
        self.nb.add(tab_paths, text="Pastas")
        self.nb.add(tab_input, text="Entrada (XML/TXT)")
        self.nb.add(tab_app, text="Aplicação")
        self.nb.add(tab_output, text="Arquivos de Saída")
        self.nb.add(tab_connector, text="Conexões Externas")
        self.nb.add(self.tab_test_environment, text="Ambiente de Testes")
        self.nb.add(self.tab_status, text="Status / Logs")

        self.tab_about = ttk.Frame(self.nb)
        self.nb.add(self.tab_about, text="Sobre")

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

        # ---- Arquivos de Saída
        fo = ttk.LabelFrame(tab_output, text="Configuração dos arquivos de saída")
        fo.pack(fill="x", padx=10, pady=10)

        self._dir(fo, "Pasta de saída", "output.output_dir", 0)

        campos = ttk.LabelFrame(fo, text="Campos a exportar")
        campos.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(8, 10))

        self.vars["output.export_numdoc"] = tk.BooleanVar()
        self.vars["output.export_codigo"] = tk.BooleanVar()
        self.vars["output.export_gtin"] = tk.BooleanVar()
        self.vars["output.export_descricao"] = tk.BooleanVar()
        self.vars["output.export_qtdeesperada"] = tk.BooleanVar()
        self.vars["output.export_qtdelida"] = tk.BooleanVar()
        self.vars["output.export_saldo"] = tk.BooleanVar()

        ttk.Checkbutton(
            campos,
            text="NumDoc",
            variable=self.vars["output.export_numdoc"],
        ).grid(row=0, column=0, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Código interno",
            variable=self.vars["output.export_codigo"],
        ).grid(row=0, column=1, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="GTIN / EAN",
            variable=self.vars["output.export_gtin"],
        ).grid(row=0, column=2, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Descrição",
            variable=self.vars["output.export_descricao"],
        ).grid(row=0, column=3, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Qtde Esperada",
            variable=self.vars["output.export_qtdeesperada"],
        ).grid(row=1, column=0, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Qtde Lida",
            variable=self.vars["output.export_qtdelida"],
        ).grid(row=1, column=1, sticky="w", padx=10, pady=6)

        ttk.Checkbutton(
            campos,
            text="Saldo",
            variable=self.vars["output.export_saldo"],
        ).grid(row=1, column=2, sticky="w", padx=10, pady=6)

        ttk.Label(
            fo,
            text=(
                "Ordem das colunas: NumDoc, Código interno, GTIN/EAN, "
                "Descrição, Qtde Esperada, Qtde Lida, Saldo."
            ),
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        self.vars["output.individual_file"] = tk.BooleanVar()
        ttk.Checkbutton(fo, text="Gerar arquivo individual por conferência",
                        variable=self.vars["output.individual_file"]).grid(
            row=3, column=0, columnspan=3, sticky="w", padx=8, pady=6)

        self.vars["output.daily_file"] = tk.BooleanVar()
        ttk.Checkbutton(fo, text="Gerar arquivo diário acumulado",
                        variable=self.vars["output.daily_file"]).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=8, pady=6)

        self.vars["output.delimiter"] = tk.StringVar()
        ttk.Label(fo, text="Separador").grid(
            row=5, column=0, sticky="w", padx=8, pady=6
        )
        ent_sep = ttk.Entry(
            fo,
            textvariable=self.vars["output.delimiter"],
            width=8,
        )
        ent_sep.grid(
            row=5, column=1, sticky="w", padx=8, pady=6
        )
        self.widgets["output.delimiter"] = ent_sep

        self.vars["output.file_name_mode"] = tk.StringVar()
        ttk.Label(fo, text="Nome do arquivo individual").grid(
            row=6, column=0, sticky="w", padx=8, pady=6
        )
        cmb_file_name = ttk.Combobox(
            fo,
            textvariable=self.vars["output.file_name_mode"],
            values=[
                "Só número do documento",
                "Número do documento + data",
                "Número do documento + data + hora",
            ],
            state="readonly",
            width=36,
        )
        cmb_file_name.grid(row=6, column=1, sticky="w", padx=8, pady=6)
        self.widgets["output.file_name_mode"] = cmb_file_name

        # ---- Conexões Externas - Etapa 2.4
        # Mostra permanentemente a conexão atual.
        # Nova conexão reinicia o assistente; Editar abre a conexão atual preenchida.
        manager = ttk.LabelFrame(tab_connector, text="Conexão Externa Atual")
        manager.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            manager,
            text=(
                "A conexão atualmente configurada é exibida abaixo. "
                "Nenhum dado do ERP é alterado nesta etapa."
            ),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 10))

        self.current_external_vars = {
            "name": tk.StringVar(),
            "type": tk.StringVar(),
            "driver": tk.StringVar(),
            "server": tk.StringVar(),
            "port": tk.StringVar(),
            "database": tk.StringVar(),
            "auth": tk.StringVar(),
            "user": tk.StringVar(),
            "password": tk.StringVar(),
            "status": tk.StringVar(),
        }

        labels = [
            ("Nome da conexão", "name", 42),
            ("Tipo de banco", "type", 34),
            ("Driver ODBC", "driver", 42),
            ("Servidor (IP ou HOST\\INSTÂNCIA)", "server", 42),
            ("Porta", "port", 12),
            ("Banco", "database", 36),
            ("Autenticação", "auth", 34),
            ("Usuário", "user", 30),
            ("Senha", "password", 30),
            ("Status", "status", 24),
        ]

        self.external_detail_widgets = []

        for row, (label, key, field_width) in enumerate(labels, start=1):
            lbl = ttk.Label(manager, text=label)
            lbl.grid(row=row, column=0, sticky="w", padx=10, pady=5)

            value_lbl = ttk.Label(
                manager,
                textvariable=self.current_external_vars[key],
                relief="sunken",
                anchor="w",
                width=field_width,
            )
            value_lbl.grid(row=row, column=1, sticky="w", padx=10, pady=5)

            self.external_detail_widgets.extend([lbl, value_lbl])

        # Estado visual quando não existe conexão configurada.
        self.external_empty_frame = ttk.Frame(manager)
        self.external_empty_frame.grid(
            row=1, column=0, columnspan=3, rowspan=10,
            sticky="nsew", padx=10, pady=(18, 12)
        )

        ttk.Label(
            self.external_empty_frame,
            text="Nenhuma conexão externa configurada",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="center", pady=(45, 10))

        ttk.Label(
            self.external_empty_frame,
            text=(
                "Clique em “Nova conexão” para iniciar o assistente e configurar "
                "o banco de dados do ERP."
            ),
            justify="center",
            font=("Segoe UI", 10),
        ).pack(anchor="center", pady=(0, 8))

        ttk.Label(
            self.external_empty_frame,
            text=(
                "O Banco Local logConf continua funcionando normalmente "
                "e não é alterado."
            ),
            justify="center",
            font=("Segoe UI", 9),
        ).pack(anchor="center")

        connector_actions = ttk.Frame(manager)
        connector_actions.grid(
            row=12, column=0, columnspan=3, sticky="w", padx=10, pady=(16, 8)
        )

        ttk.Button(
            connector_actions,
            text="Nova conexão",
            command=self._new_external_connection,
        ).pack(side="left")

        self.btn_external_edit = ttk.Button(
            connector_actions,
            text="Editar",
            command=self._edit_external_connection,
        )
        self.btn_external_edit.pack(side="left", padx=(8, 0))

        self.btn_external_delete = ttk.Button(
            connector_actions,
            text="Excluir",
            command=self._delete_external_connection,
        )
        self.btn_external_delete.pack(side="left", padx=(8, 0))

        self.btn_external_test = ttk.Button(
            connector_actions,
            text="Testar conexão",
            command=self._test_selected_external_connection,
        )
        self.btn_external_test.pack(side="left", padx=(18, 0))

        self.external_mapping_var = tk.StringVar(value="")
        ttk.Label(
            manager,
            textvariable=self.external_mapping_var,
            wraplength=760,
            justify="left",
        ).grid(row=13, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 6))

        self.external_hint_var = tk.StringVar(
            value=(
                "Nova conexão abre o assistente vazio. Editar abre a conexão atual "
                "com os dados preenchidos."
            )
        )
        ttk.Label(
            manager,
            textvariable=self.external_hint_var,
        ).grid(row=14, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))

        # ---- Ambiente de Testes
        self._build_test_environment_tab()

        # ---- Status / Logs
        self._build_status_tab()

        # ---- Sobre
        self._build_about_tab()

        # ---- Bottom
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(bottom, text="Salvar", command=self._save).pack(side="right")
        ttk.Button(bottom, text="Fechar", command=self._save_and_close).pack(side="right", padx=(0, 8))


    def _build_test_environment_tab(self):
        """Grades somente de leitura do banco est_ambTestes."""
        container = ttk.Frame(self.tab_test_environment)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            container,
            text=(
                "Consulta somente leitura do ambiente de testes. "
                "Nenhum INSERT, UPDATE ou DELETE é executado nesta tela."
            ),
        ).pack(anchor="w", pady=(0, 8))

        # Seleção do arquivo de carga do estoque de teste.
        file_box = ttk.LabelFrame(container, text="Arquivo de carga do estoque")
        file_box.pack(fill="x", pady=(0, 8))

        self.test_file_var = tk.StringVar(value="")

        ttk.Label(
            file_box,
            text="Arquivo TXT/CSV",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=8)

        ttk.Entry(
            file_box,
            textvariable=self.test_file_var,
            state="readonly",
            width=72,
        ).grid(row=0, column=1, sticky="w", padx=8, pady=8)

        ttk.Button(
            file_box,
            text="Escolher arquivo...",
            command=self._pick_test_environment_file,
        ).grid(row=0, column=2, sticky="w", padx=8, pady=8)

        ttk.Button(
            file_box,
            text="Importar Estoque",
            command=self._import_test_environment_stock,
        ).grid(row=0, column=3, sticky="w", padx=8, pady=8)

        self.test_file_status = tk.StringVar(
            value="Nenhum arquivo selecionado."
        )
        ttk.Label(
            file_box,
            textvariable=self.test_file_status,
        ).grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            padx=8,
            pady=(0, 8),
        )

        self.test_env_nb = ttk.Notebook(container)
        self.test_env_nb.pack(fill="both", expand=True)

        tab_stock = ttk.Frame(self.test_env_nb)
        tab_moves = ttk.Frame(self.test_env_nb)
        self.test_env_nb.add(tab_stock, text="Estoque Atual")
        self.test_env_nb.add(tab_moves, text="Movimentações")

        self._build_readonly_grid(
            tab_stock, "test_stock_tree", "test_stock_status",
            [
                ("codigo", "CodProd", 110),
                ("ean", "GTIN", 135), ("descricao", "Descrição", 250),
                ("local", "Local", 100), ("saldo", "Saldo", 90),
                ("atualizacao", "Atualização", 145),
                ("terminal", "Terminal", 110),
            ],
            self._refresh_test_stock,
        )

        self._build_readonly_grid(
            tab_moves, "test_moves_tree", "test_moves_status",
            [
                ("codigo", "CodProd", 90),
                ("gtin", "GTIN", 135),
                ("descricao", "Descrição", 280),
                ("qtd_antes", "Qtde Antes", 90),
                ("qtd_mov", "Qtde Movimentada", 115),
                ("qtd_depois", "Qtde Depois", 90),
                ("saldo_atualizado", "Saldo Atualizado", 110),
                ("datahora", "Data/Hora", 145),
                ("operacao", "Operação", 105),
                ("documento", "Documento", 110),
                ("terminal", "Terminal", 90),
                ("resultado", "Resultado", 90),
                ("detalhe", "Detalhe", 260),
            ],
            self._refresh_test_moves,
        )

        # Carrega automaticamente as grades ao abrir Ambiente de Testes.
        # O after() deixa a janela terminar de ser montada antes das consultas SQL.
        self.after(150, self._refresh_test_stock)
        self.after(250, self._refresh_test_moves)

    def _pick_test_environment_file(self):
        """Seleciona o TXT/CSV de carga. Nesta etapa, apenas guarda o caminho."""
        selected = filedialog.askopenfilename(
            parent=self,
            title="Selecionar arquivo de estoque de teste",
            filetypes=[
                ("Arquivos TXT e CSV", "*.txt *.csv"),
                ("Arquivo TXT", "*.txt"),
                ("Arquivo CSV", "*.csv"),
                ("Todos os arquivos", "*.*"),
            ],
        )

        if not selected:
            return

        self.test_file_var.set(selected)
        self.test_file_status.set(
            f"Arquivo selecionado: {os.path.basename(selected)}"
        )

    def _write_test_user_log(self, level, action, why, what_to_do="", details=None):
        """Registra evento amigável no mesmo usuario.log já usado pela aplicação."""
        from datetime import datetime

        log_dir = self.cfg.get(
            "logging", "log_dir", fallback=os.path.join(BASE_DIR, "logs")
        ).strip()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "usuario.log")

        lines = [
            f"{datetime.now():%d/%m/%Y %H:%M:%S} | {level} | {action}",
            f"Por que: {why}",
        ]
        if what_to_do:
            lines.append(f"O que fazer: {what_to_do}")
        if details:
            lines.append("Detalhes:")
            lines.extend(f"- {item}" for item in details)

        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n\n")

    def _validate_test_stock_file(self, file_path):
        """Valida o arquivo inteiro antes de permitir qualquer INSERT."""
        expected = ["CodProd", "GTIN", "DescProd", "SaldoEstoque", "LocalEstoque"]
        errors = []
        valid_rows = []

        try:
            with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except UnicodeDecodeError:
            return [], [
                "Arquivo não está em UTF-8. Salve o TXT/CSV em UTF-8 e tente novamente."
            ]
        except Exception as e:
            return [], [f"Não foi possível ler o arquivo: {e}"]

        if not rows:
            return [], ["Arquivo vazio."]

        header = [str(v).strip() for v in rows[0]]
        if header != expected:
            errors.append(
                "Linha 1 - cabeçalho inválido. Esperado exatamente: "
                + ",".join(expected)
            )
            return [], errors

        # Consolidação por produto + GTIN + localização.
        # Mesmo produto no mesmo local soma o saldo.
        # Mesmo produto em locais diferentes permanece em posições separadas.
        grouped = {}

        # Mantém coerência entre Código e GTIN.
        cod_to_gtin = {}
        gtin_to_cod = {}

        for line_no, row in enumerate(rows[1:], start=2):
            if not row or all(not str(v).strip() for v in row):
                continue

            if len(row) != 5:
                errors.append(
                    f"Linha {line_no} - quantidade de campos inválida: "
                    f"esperado 5, encontrado {len(row)}."
                )
                continue

            codprod, gtin, desc, saldo_txt, local = [str(v).strip() for v in row]

            if not codprod and not gtin:
                errors.append(
                    f"Linha {line_no} - CodProd e GTIN estão vazios. "
                    "Informe pelo menos um dos dois campos."
                )
            if not desc:
                errors.append(f"Linha {line_no} - campo DescProd está vazio.")
            if not local:
                errors.append(f"Linha {line_no} - campo LocalEstoque está vazio.")

            try:
                saldo = float(saldo_txt.replace(",", "."))
                if saldo < 0:
                    errors.append(
                        f"Linha {line_no} - SaldoEstoque não pode ser negativo: {saldo_txt}."
                    )
            except Exception:
                saldo = None
                errors.append(
                    f'Linha {line_no} - SaldoEstoque inválido: "{saldo_txt}".'
                )

            if codprod and gtin:
                gtin_anterior = cod_to_gtin.get(codprod)
                if gtin_anterior and gtin_anterior != gtin:
                    errors.append(
                        f'Linha {line_no} - CodProd "{codprod}" aparece com GTIN diferente '
                        f'("{gtin_anterior}" e "{gtin}").'
                    )
                else:
                    cod_to_gtin[codprod] = gtin

                cod_anterior = gtin_to_cod.get(gtin)
                if cod_anterior and cod_anterior != codprod:
                    errors.append(
                        f'Linha {line_no} - GTIN "{gtin}" aparece com CodProd diferente '
                        f'("{cod_anterior}" e "{codprod}").'
                    )
                else:
                    gtin_to_cod[gtin] = codprod

            if (
                (codprod or gtin) and desc and local and saldo is not None
                and saldo >= 0
            ):
                key = (
                    codprod if codprod else "",
                    gtin if gtin else "",
                    local,
                )

                if key in grouped:
                    # Mesmo produto + GTIN + local: soma o saldo.
                    grouped[key]["saldo"] += saldo
                else:
                    grouped[key] = {
                        "codprod": codprod,
                        "gtin": gtin,
                        "desc": desc,
                        "local": local,
                        "saldo": saldo,
                    }

        if errors:
            return [], errors

        valid_rows = [
            (
                item["codprod"],
                item["gtin"],
                item["desc"],
                item["local"],
                item["saldo"],
            )
            for item in grouped.values()
        ]

        if not valid_rows:
            errors.append("O arquivo não possui registros de estoque para importar.")

        return valid_rows, errors

    def _import_test_environment_stock(self):
        """
        Importa somente após validar 100% do arquivo.
        Nesta etapa grava apenas dbo.ESTOQUE; não cria movimentações.
        """
        file_path = self.test_file_var.get().strip()

        if not file_path:
            messagebox.showwarning(
                "Importar Estoque",
                "Selecione primeiro o arquivo TXT/CSV de estoque.",
                parent=self,
            )
            return

        if not os.path.isfile(file_path):
            messagebox.showerror(
                "Importar Estoque",
                f"Arquivo não encontrado:\n{file_path}",
                parent=self,
            )
            return

        rows, errors = self._validate_test_stock_file(file_path)
        file_name = os.path.basename(file_path)

        if errors:
            self.test_file_status.set(
                f"Arquivo não importado: {len(errors)} erro(s) encontrado(s)."
            )
            self._write_test_user_log(
                "ERRO",
                f"Validação do arquivo de estoque: {file_name}",
                "Foram encontrados dados inválidos no arquivo. Nenhum registro foi importado.",
                "Corrija as linhas indicadas e tente novamente.",
                errors,
            )

            preview = "\n".join(errors[:15])
            if len(errors) > 15:
                preview += f"\n\n... e mais {len(errors) - 15} erro(s). Veja o Log do Usuário."

            messagebox.showerror(
                "Arquivo não importado",
                "Foram encontrados erros no arquivo.\n"
                "Nenhum registro foi importado.\n\n"
                f"{preview}\n\n"
                "Todos os detalhes também foram gravados no Log do Usuário.",
                parent=self,
            )
            return

        conn = None
        try:
            conn = pyodbc.connect(
                self._build_test_environment_conn_str().replace(
                    "ApplicationIntent=ReadOnly;", ""
                ),
                timeout=5,
                autocommit=False,
            )
            cur = conn.cursor()

            # Segurança: não misturamos uma nova carga com dados anteriores.
            cur.execute("SELECT COUNT(*) FROM dbo.ESTOQUE")
            existing = int(cur.fetchone()[0])

            if existing > 0:
                confirmar = messagebox.askyesno(
                    "Substituir estoque de testes?",
                    "A tabela de estoque de testes já possui "
                    f"{existing} registro(s).\n\n"
                    "Se continuar, TODO o estoque atual do ambiente de testes "
                    "será apagado e substituído pelo arquivo selecionado.\n\n"
                    "Deseja apagar o estoque atual e importar o novo arquivo?",
                    parent=self,
                )

                if not confirmar:
                    conn.rollback()
                    self.test_file_status.set(
                        "Importação cancelada. O estoque atual foi mantido."
                    )
                    self._write_test_user_log(
                        "ATENÇÃO",
                        f"Importação de estoque cancelada: {file_name}",
                        "O ambiente de testes já possuía registros e o usuário optou por mantê-los.",
                        "Nenhuma alteração foi realizada.",
                    )
                    return

                # Ambiente exclusivamente de testes:
                # após confirmação explícita, remove a carga anterior inteira
                # e reinicia também o histórico de movimentações.
                cur.execute("DELETE FROM dbo.movEstambTeste")
                cur.execute("DELETE FROM dbo.ESTOQUE")

                self._write_test_user_log(
                    "OK",
                    f"Substituição do estoque de testes: {file_name}",
                    f"O usuário confirmou a exclusão dos {existing} registro(s) anteriores.",
                    "O novo arquivo será carregado e o histórico de movimentações será reiniciado.",
                )

            sql = """
                INSERT INTO dbo.ESTOQUE
                    (COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL)
                VALUES (?, ?, ?, ?, ?)
            """
            cur.fast_executemany = True
            cur.executemany(sql, rows)

            # Registra a origem de cada posição de estoque como CARGA INICIAL.
            # Isso cria um extrato auditável sem alterar o saldo importado.
            sql_mov = """
                INSERT INTO dbo.movEstambTeste
                    (
                        NUM_DOCUMENTO,
                        COD_ITEM,
                        COD_BARRAS,
                        QTD_MOVIMENTADA,
                        SALDO_ANTERIOR,
                        SALDO_POSTERIOR,
                        IDENT_TERMINAL,
                        TIPO_OPERACAO,
                        RESULTADO,
                        DETALHE
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            movimentos = [
                (
                    "CARGA_INICIAL",
                    codprod,
                    gtin,
                    saldo,
                    0,
                    saldo,
                    None,
                    "SALDO INICIAL",
                    "SUCESSO",
                    f"Carga inicial do ambiente de testes | {desc} | Local: {local}",
                )
                for codprod, gtin, desc, local, saldo in rows
            ]

            cur.executemany(sql_mov, movimentos)
            conn.commit()

            self.test_file_status.set(
                f"Importação concluída: {len(rows)} produto(s)."
            )
            self._write_test_user_log(
                "OK",
                f"Importação de estoque de testes: {file_name}",
                (
                    f"{len(rows)} posição(ões) foram importadas para est_ambTestes.dbo.ESTOQUE "
                    f"e {len(rows)} lançamento(s) de SALDO INICIAL foram registrados."
                ),
            )

            self._refresh_test_stock()
            self._refresh_test_moves()

            messagebox.showinfo(
                "Importar Estoque",
                f"Importação concluída com sucesso.\n\n"
                f"Posições de estoque importadas: {len(rows)}\n"
                f"Lançamentos de SALDO INICIAL: {len(rows)}",
                parent=self,
            )

        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass

            detail = str(e)
            self.test_file_status.set("Falha na importação. Nenhum registro confirmado.")
            self._write_test_user_log(
                "ERRO",
                f"Importação de estoque de testes: {file_name}",
                "O SQL Server recusou ou interrompeu a importação. A transação foi cancelada.",
                "Verifique a conexão e o detalhe técnico informado.",
                [detail],
            )
            messagebox.showerror(
                "Falha na importação",
                "Nenhum registro foi confirmado no banco.\n\n"
                f"Detalhe: {detail}",
                parent=self,
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _build_readonly_grid(self, parent, tree_attr, status_attr, columns, refresh_command):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", padx=6, pady=(8, 4))
        status_var = tk.StringVar(value="Clique em Atualizar para consultar.")
        setattr(self, status_attr, status_var)

        ttk.Button(toolbar, text="↻ Atualizar", command=refresh_command).pack(side="left")
        ttk.Label(toolbar, textvariable=status_var).pack(side="left", padx=(12, 0))

        grid_frame = ttk.Frame(parent)
        grid_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        column_ids = [item[0] for item in columns]
        tree = ttk.Treeview(grid_frame, columns=column_ids, show="headings", selectmode="browse")
        setattr(self, tree_attr, tree)

        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=60, stretch=True, anchor="w")

        y_scroll = ttk.Scrollbar(grid_frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(grid_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        grid_frame.grid_rowconfigure(0, weight=1)
        grid_frame.grid_columnconfigure(0, weight=1)

    def _build_test_environment_conn_str(self):
        cfg = load_cfg()
        driver = cfg.get("sql", "driver", fallback="ODBC Driver 18 for SQL Server").strip()
        server = cfg.get("sql", "server", fallback="127.0.0.1").strip()
        trusted = as_bool(cfg.get("sql", "trusted_connection", fallback="no"))

        parts = [
            f"DRIVER={{{driver}}}", f"SERVER={server}",
            "DATABASE=est_ambTestes", "TrustServerCertificate=yes",
            "ApplicationIntent=ReadOnly",
        ]
        if trusted:
            parts.append("Trusted_Connection=yes")
        else:
            parts.append(f"UID={cfg.get('sql', 'user', fallback='').strip()}")
            parts.append(f"PWD={cfg.get('sql', 'password', fallback='')}")
        return ";".join(parts) + ";"

    def _clear_test_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def _format_test_value(self, value):
        if value is None:
            return ""
        if hasattr(value, "strftime"):
            try:
                return value.strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                pass
        return str(value)

    def _read_test_table(self, table_name):
        conn = pyodbc.connect(self._build_test_environment_conn_str(), timeout=5)
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = ?
                   ORDER BY ORDINAL_POSITION""",
                table_name,
            )
            columns = [row[0] for row in cur.fetchall()]
            if not columns:
                raise RuntimeError(f"Tabela dbo.{table_name} não encontrada em est_ambTestes.")
            cur.execute(f"SELECT * FROM dbo.[{table_name}]")
            return columns, cur.fetchall()
        finally:
            conn.close()

    def _column_value(self, row_map, aliases):
        normalized = {
            re.sub(r"[^a-z0-9]", "", str(key).lower()): value
            for key, value in row_map.items()
        }
        for alias in aliases:
            key = re.sub(r"[^a-z0-9]", "", alias.lower())
            if key in normalized:
                return normalized[key]
        return ""

    def _refresh_test_stock(self):
        tree, status = self.test_stock_tree, self.test_stock_status
        self._clear_test_tree(tree)
        status.set("Consultando est_ambTestes.dbo.ESTOQUE...")
        self.update_idletasks()
        try:
            columns, rows = self._read_test_table("ESTOQUE")
            for row in rows:
                m = dict(zip(columns, row))
                values = [
                    self._column_value(m, ["COD_ITEM", "Codigo", "CodProd", "CodigoProduto"]),
                    self._column_value(m, ["COD_BARRAS", "EAN", "GTIN", "EanProd"]),
                    self._column_value(m, ["DESCRICAO_ITEM", "Descricao", "DescProd", "DescricaoProduto"]),
                    self._column_value(m, ["LOCAL_ESTOQUE", "Local", "Localizacao", "Endereco"]),
                    self._column_value(m, ["SALDO_ATUAL", "Saldo", "Quantidade", "QtdEstoque", "Estoque"]),
                    self._column_value(m, ["DATA_ATUALIZACAO", "Atualizacao", "DataAtualizacao", "DataHora", "DtAtualizacao"]),
                    self._column_value(m, ["IDENT_TERMINAL", "Terminal", "ColetorID", "TerminalID"]),
                ]
                tree.insert("", "end", values=[self._format_test_value(v) for v in values])
            status.set("Banco vazio: nenhum registro encontrado." if not rows else f"{len(rows)} registro(s) carregado(s).")
        except Exception as e:
            status.set("Falha na consulta.")
            messagebox.showerror("Ambiente de Testes - Estoque Atual", f"Não foi possível consultar o estoque:\n{e}", parent=self)

    def _refresh_test_moves(self):
        tree, status = self.test_moves_tree, self.test_moves_status
        self._clear_test_tree(tree)
        status.set("Consultando est_ambTestes.dbo.movEstambTeste...")
        self.update_idletasks()
        try:
            columns, rows = self._read_test_table("movEstambTeste")
            for row in rows:
                m = dict(zip(columns, row))
                detalhe = self._column_value(
                    m, ["DETALHE", "Detalhe", "Mensagem", "Observacao", "Motivo"]
                )
                descricao = ""
                if detalhe:
                    partes = str(detalhe).split("|")
                    if len(partes) >= 2:
                        descricao = partes[1].strip()

                saldo_anterior = self._column_value(m, ["SALDO_ANTERIOR", "SaldoAntes", "SaldoAnterior"])
                qtd_movimentada = self._column_value(m, ["QTD_MOVIMENTADA", "Qtd", "Quantidade", "Qtde", "QtdMovimento"])
                saldo_posterior = self._column_value(m, ["SALDO_POSTERIOR", "SaldoDepois", "SaldoAtual", "NovoSaldo"])

                values = [
                    self._column_value(m, ["COD_ITEM", "Produto", "Codigo", "CodProd", "CodigoProduto"]),
                    self._column_value(m, ["COD_BARRAS", "EAN", "GTIN", "EanProd"]),
                    descricao,
                    saldo_anterior,
                    qtd_movimentada,
                    saldo_posterior,
                    saldo_posterior,
                    self._column_value(m, ["DATA_HORA", "DataHora", "DataMovimento", "Data", "DtMovimento"]),
                    self._column_value(m, ["TIPO_OPERACAO", "Operacao", "TipoOperacao", "Movimento"]),
                    self._column_value(m, ["NUM_DOCUMENTO", "Documento", "NumDoc", "NumNota", "NF"]),
                    self._column_value(m, ["IDENT_TERMINAL", "Terminal", "ColetorID", "TerminalID"]),
                    self._column_value(m, ["RESULTADO", "Resultado", "Status"]),
                    detalhe,
                ]
                tree.insert("", "end", values=[self._format_test_value(v) for v in values])
            status.set("Banco vazio: nenhum registro encontrado." if not rows else f"{len(rows)} registro(s) carregado(s).")
        except Exception as e:
            status.set("Falha na consulta.")
            messagebox.showerror("Ambiente de Testes - Movimentações", f"Não foi possível consultar as movimentações:\n{e}", parent=self)


    def _build_status_tab(self):
        top = ttk.LabelFrame(self.tab_status, text="Status do sistema")
        top.pack(fill="x", padx=10, pady=(10, 6))

        self.status_vars = {
            "importer": tk.StringVar(value="Verificando..."),
            "sql": tk.StringVar(value="Verificando..."),
            "pending": tk.StringVar(value="0"),
            "updated": tk.StringVar(value="-"),
            "result": tk.StringVar(value="-"),
        }

        labels = [
            ("Importador", "importer"),
            ("SQL Server", "sql"),
            ("Arquivos pendentes", "pending"),
            ("Última atualização", "updated"),
            ("Último resultado", "result"),
        ]

        for row, (label, key) in enumerate(labels):
            ttk.Label(top, text=f"{label}:").grid(
                row=row, column=0, sticky="w", padx=(10, 6), pady=4
            )
            ttk.Label(top, textvariable=self.status_vars[key]).grid(
                row=row, column=1, sticky="w", padx=(0, 10), pady=4
            )

        top.grid_columnconfigure(1, weight=1)

        info = ttk.LabelFrame(self.tab_status, text="Ambiente")
        info.pack(fill="x", padx=10, pady=6)

        self.status_env = tk.StringVar(value="")
        ttk.Label(
            info,
            textvariable=self.status_env,
            justify="left",
        ).pack(anchor="w", padx=10, pady=8)

        logs = ttk.LabelFrame(self.tab_status, text="Logs da aplicação")
        logs.pack(fill="both", expand=True, padx=10, pady=6)

        self.logs_nb = ttk.Notebook(logs)
        self.logs_nb.pack(fill="both", expand=True, padx=4, pady=4)

        self.tab_log_usuario = ttk.Frame(self.logs_nb)
        self.tab_log_tecnico = ttk.Frame(self.logs_nb)

        self.logs_nb.add(self.tab_log_usuario, text="Log do Usuário")
        self.logs_nb.add(self.tab_log_tecnico, text="Log Técnico")

        # ---- Log do usuário ----
        self.log_text = tk.Text(
            self.tab_log_usuario,
            wrap="none",
            height=14,
            state="disabled",
            font=("Consolas", 9),
        )
        user_y = ttk.Scrollbar(
            self.tab_log_usuario,
            orient="vertical",
            command=self.log_text.yview,
        )
        user_x = ttk.Scrollbar(
            self.tab_log_usuario,
            orient="horizontal",
            command=self.log_text.xview,
        )
        self.log_text.configure(
            yscrollcommand=user_y.set,
            xscrollcommand=user_x.set,
        )

        self.log_text.grid(row=0, column=0, sticky="nsew")
        user_y.grid(row=0, column=1, sticky="ns")
        user_x.grid(row=1, column=0, sticky="ew")
        self.tab_log_usuario.grid_rowconfigure(0, weight=1)
        self.tab_log_usuario.grid_columnconfigure(0, weight=1)

        # ---- Log técnico ----
        self.tech_log_text = tk.Text(
            self.tab_log_tecnico,
            wrap="none",
            height=14,
            state="disabled",
            font=("Consolas", 9),
        )
        tech_y = ttk.Scrollbar(
            self.tab_log_tecnico,
            orient="vertical",
            command=self.tech_log_text.yview,
        )
        tech_x = ttk.Scrollbar(
            self.tab_log_tecnico,
            orient="horizontal",
            command=self.tech_log_text.xview,
        )
        self.tech_log_text.configure(
            yscrollcommand=tech_y.set,
            xscrollcommand=tech_x.set,
        )

        self.tech_log_text.grid(row=0, column=0, sticky="nsew")
        tech_y.grid(row=0, column=1, sticky="ns")
        tech_x.grid(row=1, column=0, sticky="ew")
        self.tab_log_tecnico.grid_rowconfigure(0, weight=1)
        self.tab_log_tecnico.grid_columnconfigure(0, weight=1)

        actions = ttk.Frame(self.tab_status)
        actions.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(
            actions,
            text="↻ Atualizar",
            command=self._refresh_status_tab,
        ).pack(side="left")

    def _build_about_tab(self):
        container = ttk.Frame(self.tab_about, padding=28)
        container.pack(fill="both", expand=True)

        content = ttk.Frame(container)
        content.pack(anchor="nw", fill="x", padx=12, pady=10)

        # Logo menor no canto superior esquerdo.
        try:
            logo_path = resource_path(os.path.join("assets", "logo_2a.png"))
            image = Image.open(logo_path)
            image.thumbnail((210, 54), Image.LANCZOS)
            self._about_logo = ImageTk.PhotoImage(image)

            ttk.Label(
                content,
                image=self._about_logo,
            ).pack(anchor="w", pady=(0, 24))
        except Exception:
            ttk.Label(
                content,
                text="2A Tecnologia",
                font=("Segoe UI", 16),
            ).pack(anchor="w", pady=(0, 24))

        # Produto + versão na mesma linha, sem negrito e em tamanho discreto.
        title_row = ttk.Frame(content)
        title_row.pack(anchor="w", fill="x")

        ttk.Label(
            title_row,
            text="ImportFiles LogConf",
            font=("Segoe UI", 13),
        ).pack(side="left")

        ttk.Label(
            title_row,
            text="   |   ",
            font=("Segoe UI", 11),
        ).pack(side="left")

        ttk.Label(
            title_row,
            text=f"Versão {APP_VERSION} | Build {BUILD_DATE}",
            font=("Segoe UI", 11),
        ).pack(side="left")

        ttk.Separator(content, orient="horizontal").pack(
            fill="x", pady=(16, 20)
        )

        ttk.Label(
            content,
            text=(
                "Sistema para integração de dados de conferência para processos de\n"
                "recebimento, expedição e separação de mercadorias."
            ),
            justify="left",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 20))

        ttk.Separator(content, orient="horizontal").pack(
            fill="x", pady=(0, 20)
        )

        ttk.Label(
            content,
            text="Desenvolvido por 2A Tecnologia",
            font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(0, 14))

        contacts = ttk.Frame(content)
        contacts.pack(anchor="w", pady=(0, 18))

        self._about_contact_icons = []

        contact_rows = [
            ("whatsapp.png", "Telefone / WhatsApp:", "(11) 95246-9907"),
            ("email.png", "E-mail:", "faleconosco@2atecnologia.com.br"),
            ("site.png", "Site:", "2atec.com.br"),
        ]

        for row, (icon_name, label_text, value_text) in enumerate(contact_rows):
            try:
                icon_path = resource_path(os.path.join("assets", icon_name))
                icon_img = Image.open(icon_path)
                icon_img.thumbnail((22, 22), Image.LANCZOS)
                icon_photo = ImageTk.PhotoImage(icon_img)
                self._about_contact_icons.append(icon_photo)

                ttk.Label(
                    contacts,
                    image=icon_photo,
                ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=7)
            except Exception:
                ttk.Label(
                    contacts,
                    text="",
                    width=3,
                ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=7)

            ttk.Label(
                contacts,
                text=label_text,
                font=("Segoe UI", 10, "bold"),
            ).grid(row=row, column=1, sticky="w", padx=(0, 12), pady=7)

            ttk.Label(
                contacts,
                text=value_text,
                font=("Segoe UI", 10),
            ).grid(row=row, column=2, sticky="w", pady=7)

        ttk.Separator(content, orient="horizontal").pack(
            fill="x", pady=(0, 18)
        )

        ttk.Label(
            content,
            text="© 2026 2A Tecnologia\nTodos os direitos reservados.",
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

    def _on_main_tab_changed(self, event=None):
        """Maximiza somente a aba Ambiente de Testes e restaura nas demais."""
        try:
            current = self.nb.select()

            if current == str(self.tab_test_environment):
                if not self._test_env_maximized:
                    self._normal_geometry = self.geometry()
                    try:
                        self.state("zoomed")
                    except Exception:
                        self.attributes("-zoomed", True)
                    self._test_env_maximized = True
            else:
                if self._test_env_maximized:
                    try:
                        self.state("normal")
                    except Exception:
                        try:
                            self.attributes("-zoomed", False)
                        except Exception:
                            pass

                    if self._normal_geometry:
                        self.geometry(self._normal_geometry)

                    self._test_env_maximized = False
        except Exception:
            pass

    def _select_initial_tab(self):
        initial = str(self.initial_tab).strip().lower()
        if initial == "status":
            self.nb.select(self.tab_status)
            self._refresh_status_tab()
        elif initial == "about":
            self.nb.select(self.tab_about)
            self.update_idletasks()
        else:
            self.nb.select(0)

    def _importer_rodando(self) -> bool:
        if os.name != "nt":
            return False

        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ImportFilesLogConfImporter.exe"],
                capture_output=True,
                text=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=3,
            )
            return "ImportFilesLogConfImporter.exe" in (result.stdout or "")
        except Exception:
            return False

    def _count_pending_files(self) -> int:
        try:
            input_dir = self.cfg.get(
                "watch",
                "input_dir",
                fallback=r"C:\MIS\entrada",
            ).strip()

            if not os.path.isdir(input_dir):
                return 0

            return sum(
                1
                for name in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, name))
            )
        except Exception:
            return 0

    def _get_log_path(self) -> str:
        log_dir = self.cfg.get(
            "logging",
            "log_dir",
            fallback=os.path.join(BASE_DIR, "logs"),
        ).strip()
        return os.path.join(log_dir, "usuario.log")

    def _read_recent_events(self, max_lines=160):
        log_path = self._get_log_path()

        if not os.path.isfile(log_path):
            return ["Nenhum evento para o usuário registrado ainda."]

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                linhas = [line.rstrip("\n") for line in f.readlines()]

            # usuario.log é gravado em blocos separados por linha em branco.
            # Mantemos o arquivo original intacto e apenas invertemos os blocos
            # para mostrar o evento mais recente no topo da interface.
            blocos = []
            bloco_atual = []

            for linha in linhas:
                if linha.strip():
                    bloco_atual.append(linha)
                elif bloco_atual:
                    blocos.append(bloco_atual)
                    bloco_atual = []

            if bloco_atual:
                blocos.append(bloco_atual)

            blocos.reverse()

            resultado = []
            for bloco in blocos:
                resultado.extend(bloco)
                resultado.append("")

                if len(resultado) >= max_lines:
                    break

            return resultado[:max_lines] or ["Nenhum evento para o usuário registrado ainda."]

        except Exception as e:
            return [f"Não foi possível ler o log do usuário: {e}"]

    def _read_technical_events(self, max_lines=220):
        log_dir = self.cfg.get(
            "logging",
            "log_dir",
            fallback=os.path.join(BASE_DIR, "logs"),
        ).strip()
        log_path = os.path.join(log_dir, "importador.log")

        if not os.path.isfile(log_path):
            return ["Nenhum evento técnico registrado ainda."]

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                linhas = [line.rstrip("\n") for line in f.readlines()]

            # Cada linha que começa com timestamp inicia um novo evento.
            # Linhas de traceback/continuação permanecem junto do evento anterior.
            inicio = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
            blocos = []
            atual = []

            for linha in linhas:
                if inicio.match(linha):
                    if atual:
                        blocos.append(atual)
                    atual = [linha]
                else:
                    if atual:
                        atual.append(linha)
                    elif linha.strip():
                        atual = [linha]

            if atual:
                blocos.append(atual)

            blocos.reverse()

            resultado = []
            for bloco in blocos:
                resultado.extend(bloco)
                resultado.append("")
                if len(resultado) >= max_lines:
                    break

            return resultado[:max_lines] or ["Nenhum evento técnico registrado ainda."]

        except Exception as e:
            return [f"Não foi possível ler o log técnico: {e}"]

    def _last_result_from_log(self) -> str:
        lines = self._read_recent_events(max_lines=80)
        for line in reversed(lines):
            if " | " in line:
                partes = line.split(" | ", 2)
                if len(partes) == 3 and partes[1] in ("OK", "ERRO", "ATENÇÃO", "INFO"):
                    return partes[2]
        return "-"

    def _refresh_status_tab(self):
        # Recarrega config para refletir qualquer alteração salva.
        self.cfg = load_cfg()
        runtime = read_runtime_status(BASE_DIR) or {}

        importer_ok = self._importer_rodando()
        estado = runtime.get("estado", "")

        self.status_vars["importer"].set(
            "AGUARDANDO NOVOS LANÇAMENTOS"
        )

        if estado == "SQL_PENDENTE":
            self.status_vars["sql"].set("INDISPONÍVEL")
        elif estado == "OK":
            self.status_vars["sql"].set("CONECTADO")
        else:
            self.status_vars["sql"].set("NÃO VERIFICADO")

        self.status_vars["pending"].set(str(self._count_pending_files()))
        self.status_vars["updated"].set(runtime.get("updated_at", "-") or "-")
        self.status_vars["result"].set(self._last_result_from_log())

        servidor = self.cfg.get("sql", "server", fallback="-")
        banco = self.cfg.get("sql", "database", fallback="-")
        formato = self.cfg.get("input", "format", fallback="-").upper()
        entrada = self.cfg.get("watch", "input_dir", fallback="-")

        self.status_env.set(
            f"Servidor SQL: {servidor}\n"
            f"Banco: {banco}\n"
            f"Formato: {formato}\n"
            f"Pasta monitorada: {entrada}"
        )

        events = self._read_recent_events()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(events))
        self.log_text.see("1.0")
        self.log_text.configure(state="disabled")

        technical_events = self._read_technical_events()
        self.tech_log_text.configure(state="normal")
        self.tech_log_text.delete("1.0", "end")
        self.tech_log_text.insert("1.0", "\n".join(technical_events))
        self.tech_log_text.see("1.0")
        self.tech_log_text.configure(state="disabled")

    def _status_auto_refresh(self):
        try:
            if hasattr(self, "nb") and hasattr(self, "tab_status"):
                if self.nb.select() == str(self.tab_status):
                    self._refresh_status_tab()
        finally:
            if self.winfo_exists():
                self.after(5000, self._status_auto_refresh)

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

        # Conexões externas (isoladas do Banco Local logConf)
        self._load_external_connections()

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

        # Arquivos de Saída
        self.vars["output.output_dir"].set(g("output", "output_dir", r"C:\MIS\saida"))

        # Compatibilidade com configurações antigas:
        # product_id=codigo/gtin/ambos e include_numdoc=yes/no.
        modo_antigo = g("output", "product_id", "ambos").strip().lower()
        incluir_numdoc_antigo = as_bool(g("output", "include_numdoc", "yes"))

        self.vars["output.export_numdoc"].set(
            as_bool(g("output", "export_numdoc", "yes" if incluir_numdoc_antigo else "no"))
        )
        self.vars["output.export_codigo"].set(
            as_bool(g("output", "export_codigo", "yes" if modo_antigo in ("codigo", "ambos") else "no"))
        )
        self.vars["output.export_gtin"].set(
            as_bool(g("output", "export_gtin", "yes" if modo_antigo in ("gtin", "ambos") else "no"))
        )
        self.vars["output.export_descricao"].set(
            as_bool(g("output", "export_descricao", "no"))
        )
        self.vars["output.export_qtdeesperada"].set(
            as_bool(g("output", "export_qtdeesperada", "no"))
        )
        self.vars["output.export_qtdelida"].set(
            as_bool(g("output", "export_qtdelida", "yes"))
        )
        self.vars["output.export_saldo"].set(
            as_bool(g("output", "export_saldo", "no"))
        )

        self.vars["output.individual_file"].set(as_bool(g("output", "individual_file", "yes")))
        self.vars["output.daily_file"].set(as_bool(g("output", "daily_file", "yes")))
        self.vars["output.delimiter"].set(g("output", "delimiter", ";"))

        file_name_labels = {
            "numdoc": "Só número do documento",
            "numdoc_data": "Número do documento + data",
            "numdoc_data_hora": "Número do documento + data + hora",
        }
        modo_nome = g("output", "file_name_mode", "numdoc_data_hora").strip().lower()
        self.vars["output.file_name_mode"].set(
            file_name_labels.get(modo_nome, file_name_labels["numdoc_data_hora"])
        )

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

        # Arquivos de Saída
        setv("output", "output_dir", self.vars["output.output_dir"].get().strip())
        setv("output", "export_numdoc", bool_to_ini(self.vars["output.export_numdoc"].get()))
        setv("output", "export_codigo", bool_to_ini(self.vars["output.export_codigo"].get()))
        setv("output", "export_gtin", bool_to_ini(self.vars["output.export_gtin"].get()))
        setv("output", "export_descricao", bool_to_ini(self.vars["output.export_descricao"].get()))
        setv("output", "export_qtdeesperada", bool_to_ini(self.vars["output.export_qtdeesperada"].get()))
        setv("output", "export_qtdelida", bool_to_ini(self.vars["output.export_qtdelida"].get()))
        setv("output", "export_saldo", bool_to_ini(self.vars["output.export_saldo"].get()))
        setv("output", "individual_file", bool_to_ini(self.vars["output.individual_file"].get()))
        setv("output", "daily_file", bool_to_ini(self.vars["output.daily_file"].get()))
        setv("output", "delimiter", self.vars["output.delimiter"].get() or ";")

        modos_nome = {
            "Só número do documento": "numdoc",
            "Número do documento + data": "numdoc_data",
            "Número do documento + data + hora": "numdoc_data_hora",
        }
        setv(
            "output",
            "file_name_mode",
            modos_nome.get(
                self.vars["output.file_name_mode"].get(),
                "numdoc_data_hora",
            ),
        )

    def _reload_external_connections_from_disk(self):
        """Recarrega somente as conexões externas salvas no config.ini."""
        cfg_disco = load_cfg()

        # Remove apenas as seções externas da cópia em memória.
        for section in list(self.cfg.sections()):
            if section.startswith("external_connection:"):
                self.cfg.remove_section(section)

        # Copia novamente do arquivo em disco.
        for section in cfg_disco.sections():
            if section.startswith("external_connection:"):
                self.cfg[section] = dict(cfg_disco[section])

        # Compatibilidade com a seção antiga [connector].
        if cfg_disco.has_section("connector"):
            if self.cfg.has_section("connector"):
                self.cfg.remove_section("connector")
            self.cfg["connector"] = dict(cfg_disco["connector"])

        self._load_external_connections()


    def _external_section_name(self, connection_id: str) -> str:
        return f"external_connection:{connection_id}"


    def _load_external_connections(self):
        """Carrega somente as conexões externas para o gerenciador."""
        if not hasattr(self, "current_external_vars"):
            return

        previous_current_external_id = getattr(self, "current_external_id", None)
        self.external_connections = {}

        # Compatibilidade: se já existia a seção [connector] da Etapa 1,
        # ela aparece como uma conexão externa sem alterar o Banco Local logConf.
        external_sections = [
            section for section in self.cfg.sections()
            if section.startswith("external_connection:")
        ]

        if not external_sections and self.cfg.has_section("connector"):
            legacy_has_data = any(
                self.cfg.get("connector", key, fallback="").strip()
                for key in ("server", "database", "user")
            )
            if legacy_has_data:
                connection_id = "legacy"
                self.external_connections[connection_id] = {
                    "id": connection_id,
                    "name": self.cfg.get("connector", "name", fallback="ERP / Conexão externa").strip() or "ERP / Conexão externa",
                    "type": self.cfg.get("connector", "type", fallback="Microsoft SQL Server").strip() or "Microsoft SQL Server",
                    "driver": self.cfg.get("connector", "driver", fallback="ODBC Driver 18 for SQL Server").strip(),
                    "server": self.cfg.get("connector", "server", fallback="").strip(),
                    "port": self.cfg.get("connector", "port", fallback="1433").strip(),
                    "database": self.cfg.get("connector", "database", fallback="").strip(),
                    "trusted_connection": as_bool(self.cfg.get("connector", "trusted_connection", fallback="no")),
                    "user": self.cfg.get("connector", "user", fallback="").strip(),
                    "password": self.cfg.get("connector", "password", fallback=""),
                    "schema": self.cfg.get("connector", "schema", fallback="dbo").strip() or "dbo",
                    "table": self.cfg.get("connector", "table", fallback="").strip(),
                    "field_codprod": self.cfg.get("connector", "field_codprod", fallback="").strip(),
                    "field_gtin": self.cfg.get("connector", "field_gtin", fallback="").strip(),
                    "field_saldo": self.cfg.get("connector", "field_saldo", fallback="").strip(),
                    "field_local": self.cfg.get("connector", "field_local", fallback="").strip(),
                    "field_terminal": self.cfg.get("connector", "field_terminal", fallback="").strip(),
                    "field_documento": self.cfg.get("connector", "field_documento", fallback="").strip(),
                    "status": "Não testado",
                }

        for section in external_sections:
            connection_id = section.split(":", 1)[1]
            self.external_connections[connection_id] = {
                "id": connection_id,
                "name": self.cfg.get(section, "name", fallback="Conexão externa").strip() or "Conexão externa",
                "type": self.cfg.get(section, "type", fallback="Microsoft SQL Server").strip() or "Microsoft SQL Server",
                "driver": self.cfg.get(section, "driver", fallback="ODBC Driver 18 for SQL Server").strip(),
                "server": self.cfg.get(section, "server", fallback="").strip(),
                "port": self.cfg.get(section, "port", fallback="1433").strip(),
                "database": self.cfg.get(section, "database", fallback="").strip(),
                "trusted_connection": as_bool(self.cfg.get(section, "trusted_connection", fallback="no")),
                "user": self.cfg.get(section, "user", fallback="").strip(),
                "password": self.cfg.get(section, "password", fallback=""),
                "schema": self.cfg.get(section, "schema", fallback="dbo").strip() or "dbo",
                "table": self.cfg.get(section, "table", fallback="").strip(),
                "field_codprod": self.cfg.get(section, "field_codprod", fallback="").strip(),
                "field_gtin": self.cfg.get(section, "field_gtin", fallback="").strip(),
                "field_saldo": self.cfg.get(section, "field_saldo", fallback="").strip(),
                "field_local": self.cfg.get(section, "field_local", fallback="").strip(),
                "field_terminal": self.cfg.get(section, "field_terminal", fallback="").strip(),
                "field_documento": self.cfg.get(section, "field_documento", fallback="").strip(),
                "status": "Não testado",
            }

        if (
            previous_current_external_id
            and previous_current_external_id in self.external_connections
        ):
            self.current_external_id = previous_current_external_id
        elif self.external_connections:
            self.current_external_id = next(iter(self.external_connections))
        else:
            self.current_external_id = None

        self._refresh_external_tree()


    def _refresh_external_tree(self):
        """Atualiza a exibição permanente da conexão externa atual."""
        if not hasattr(self, "current_external_vars"):
            return

        # Mantém a conexão atual se ela ainda existir; caso contrário,
        # usa a primeira conexão salva.
        if (
            not getattr(self, "current_external_id", None)
            or self.current_external_id not in self.external_connections
        ):
            self.current_external_id = (
                next(iter(self.external_connections), None)
                if self.external_connections
                else None
            )

        data = (
            self.external_connections.get(self.current_external_id, {})
            if self.current_external_id
            else {}
        )

        trusted = bool(data.get("trusted_connection", False))
        password = data.get("password", "")

        values = {
            "name": data.get("name", ""),
            "type": data.get("type", ""),
            "driver": data.get("driver", ""),
            "server": data.get("server", ""),
            "port": data.get("port", ""),
            "database": data.get("database", ""),
            "auth": (
                "Windows (Trusted Connection)"
                if trusted
                else ("SQL Server (usuário e senha)" if data else "")
            ),
            "user": "" if trusted else data.get("user", ""),
            "password": ("*" * len(password)) if password and not trusted else "",
            "status": data.get("status", "Salvo") if data else "Nenhuma conexão cadastrada",
        }

        for key, value in values.items():
            self.current_external_vars[key].set(value)

        has_connection = bool(data)
        button_state = "normal" if has_connection else "disabled"

        if hasattr(self, "btn_external_edit"):
            self.btn_external_edit.configure(state=button_state)
        if hasattr(self, "btn_external_delete"):
            self.btn_external_delete.configure(state=button_state)
        if hasattr(self, "btn_external_test"):
            self.btn_external_test.configure(state=button_state)

        # Com conexão: mostra os dados.
        # Sem conexão: esconde os campos vazios e mostra uma orientação clara.
        if hasattr(self, "external_detail_widgets"):
            for widget in self.external_detail_widgets:
                if has_connection:
                    widget.grid()
                else:
                    widget.grid_remove()

        if hasattr(self, "external_empty_frame"):
            if has_connection:
                self.external_empty_frame.grid_remove()
            else:
                self.external_empty_frame.grid()

        if hasattr(self, "external_mapping_var"):
            if has_connection:
                schema = data.get("schema", "dbo") or "dbo"
                table = data.get("table", "")
                cod = data.get("field_codprod", "") or "-"
                gtin = data.get("field_gtin", "") or "-"
                saldo = data.get("field_saldo", "") or "-"
                self.external_mapping_var.set(
                    f"Destino: {schema}.{table or '-'} | "
                    f"CodProd → {cod} | GTIN → {gtin} | Saldo → {saldo}"
                )
            else:
                self.external_mapping_var.set("")

        if hasattr(self, "external_hint_var"):
            if has_connection:
                self.external_hint_var.set(
                    "Nova conexão abre o assistente vazio. Editar abre a conexão atual "
                    "com os dados preenchidos."
                )
            else:
                self.external_hint_var.set(
                    "Nenhuma conexão configurada. Use “Nova conexão” para começar."
                )


    def _save_external_connections(self):
        """Persiste apenas as conexões externas em seções próprias."""
        for section in list(self.cfg.sections()):
            if section.startswith("external_connection:"):
                self.cfg.remove_section(section)

        for connection_id, data in self.external_connections.items():
            section = self._external_section_name(connection_id)
            self.cfg[section] = {
                "name": data.get("name", ""),
                "type": data.get("type", "Microsoft SQL Server"),
                "driver": data.get("driver", "ODBC Driver 18 for SQL Server"),
                "server": data.get("server", ""),
                "port": data.get("port", "1433"),
                "database": data.get("database", ""),
                "trusted_connection": bool_to_ini(bool(data.get("trusted_connection", False))),
                "user": data.get("user", ""),
                "password": data.get("password", ""),
                "schema": data.get("schema", "dbo"),
                "table": data.get("table", ""),
                "field_codprod": data.get("field_codprod", ""),
                "field_gtin": data.get("field_gtin", ""),
                "field_saldo": data.get("field_saldo", ""),
                "field_local": data.get("field_local", ""),
                "field_terminal": data.get("field_terminal", ""),
                "field_documento": data.get("field_documento", ""),
            }

        save_cfg(self.cfg)


    def _selected_external_id(self):
        return getattr(self, "current_external_id", None)


    def _new_external_connection(self):
        self._open_external_connection_dialog()




    def _edit_external_connection(self):
        connection_id = self._selected_external_id()
        if not connection_id:
            messagebox.showinfo(
                "Conexões Externas",
                "Nenhuma conexão atual está cadastrada para editar.",
            )
            return

        data = self.external_connections.get(connection_id)
        if not data:
            return

        self._open_external_connection_dialog(connection_id, data)


    def _delete_external_connection(self):
        """Exclui a conexão externa atual e deixa a tela em estado sem conexão."""
        connection_id = self._selected_external_id()
        if not connection_id:
            messagebox.showinfo(
                "Conexões Externas",
                "Nenhuma conexão externa está cadastrada.",
                parent=self,
            )
            return

        data = self.external_connections.get(connection_id, {})
        connection_name = data.get("name", "Conexão atual")

        if not messagebox.askyesno(
            "Excluir conexão",
            f'Deseja realmente excluir a conexão "{connection_name}"?',
            parent=self,
        ):
            return

        # Remove somente a conexão externa atual.
        self.external_connections.pop(connection_id, None)

        section = self._external_section_name(connection_id)
        if self.cfg.has_section(section):
            self.cfg.remove_section(section)

        # Remove também a configuração antiga [connector] para impedir
        # que uma conexão excluída reapareça ao reabrir a aplicação.
        if self.cfg.has_section("connector"):
            self.cfg.remove_section("connector")

        save_cfg(self.cfg)

        self.current_external_id = None
        self.external_connections = {}
        self._refresh_external_tree()
        self.update_idletasks()

        messagebox.showinfo(
            "Conexões Externas",
            "Conexão excluída com sucesso.",
            parent=self,
        )


    def _open_external_connection_dialog(self, connection_id=None, initial=None):
        initial = dict(initial or {})
        editing = connection_id is not None

        dlg = tk.Toplevel(self)
        dlg.title("Editar conexão externa" if editing else "Nova conexão externa")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        width = 660
        height = 610
        self.update_idletasks()
        x = max(0, self.winfo_rootx() + (self.winfo_width() - width) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - height) // 2)
        dlg.geometry(f"{width}x{height}+{x}+{y}")

        frame = ttk.LabelFrame(dlg, text="Dados da conexão")
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        vars_dlg = {
            "name": tk.StringVar(value=initial.get("name", "")),
            "type": tk.StringVar(value=initial.get("type", "Microsoft SQL Server")),
            "driver": tk.StringVar(value=initial.get("driver", "ODBC Driver 18 for SQL Server")),
            "server": tk.StringVar(value=initial.get("server", "")),
            "port": tk.StringVar(value=initial.get("port", "1433")),
            "database": tk.StringVar(value=initial.get("database", "")),
            "trusted": tk.BooleanVar(value=bool(initial.get("trusted_connection", False))),
            "user": tk.StringVar(value=initial.get("user", "")),
            "password": tk.StringVar(value=initial.get("password", "")),
            "schema": tk.StringVar(value=initial.get("schema", "dbo") or "dbo"),
            "table": tk.StringVar(value=initial.get("table", "")),
            "field_codprod": tk.StringVar(value=initial.get("field_codprod", "")),
            "field_gtin": tk.StringVar(value=initial.get("field_gtin", "")),
            "field_saldo": tk.StringVar(value=initial.get("field_saldo", "")),
            "field_local": tk.StringVar(value=initial.get("field_local", "")),
            "field_terminal": tk.StringVar(value=initial.get("field_terminal", "")),
            "field_documento": tk.StringVar(value=initial.get("field_documento", "")),
        }

        def add_label_entry(row, label, key, show=None):
            ttk.Label(frame, text=label).grid(
                row=row, column=0, sticky="w", padx=8, pady=6
            )
            entry = ttk.Entry(
                frame,
                textvariable=vars_dlg[key],
                width=58,
                show=show,
            )
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
            return entry

        ent_name = add_label_entry(0, "Nome da conexão", "name")

        ttk.Label(frame, text="Tipo de banco").grid(
            row=1, column=0, sticky="w", padx=8, pady=6
        )
        cmb_type = ttk.Combobox(
            frame,
            textvariable=vars_dlg["type"],
            values=[
                "Microsoft SQL Server",
                "PostgreSQL (em breve)",
                "MySQL / MariaDB (em breve)",
                "Oracle (em breve)",
                "SAP HANA (em breve)",
                "ODBC genérico (em breve)",
                "OLE DB (em breve)",
            ],
            state="readonly",
            width=55,
        )
        cmb_type.grid(row=1, column=1, sticky="ew", padx=8, pady=6)

        ent_driver = add_label_entry(2, "Driver ODBC", "driver")
        ent_server = add_label_entry(3, "Servidor (IP ou HOST\\INSTÂNCIA)", "server")
        ent_port = add_label_entry(4, "Porta", "port")
        ent_database = add_label_entry(5, "Banco", "database")

        chk_trusted = ttk.Checkbutton(
            frame,
            text="Usar autenticação do Windows (Trusted Connection)",
            variable=vars_dlg["trusted"],
        )
        chk_trusted.grid(
            row=6, column=0, columnspan=2, sticky="w", padx=8, pady=8
        )

        ent_user = add_label_entry(7, "Usuário", "user")
        ent_password = add_label_entry(8, "Senha", "password", show="*")

        ttk.Separator(frame, orient="horizontal").grid(
            row=9, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 6)
        )

        ttk.Label(
            frame,
            text="Mapeamento da tabela de estoque do ERP",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=10, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 3))

        ttk.Label(
            frame,
            text=(
                "Informe os nomes exatamente como existem no banco do cliente. "
                "Nesta etapa apenas salvamos o mapeamento; nenhum UPDATE será executado."
            ),
            wraplength=560,
            justify="left",
        ).grid(row=11, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        add_label_entry(12, "Schema", "schema")
        add_label_entry(13, "Tabela de estoque", "table")
        add_label_entry(14, "Campo CodProd", "field_codprod")
        add_label_entry(15, "Campo GTIN / EAN", "field_gtin")
        add_label_entry(16, "Campo Saldo", "field_saldo")
        add_label_entry(17, "Campo Localização (opcional)", "field_local")
        add_label_entry(18, "Campo Terminal (opcional)", "field_terminal")
        add_label_entry(19, "Campo Documento (opcional)", "field_documento")

        frame.grid_columnconfigure(0, minsize=190)
        frame.grid_columnconfigure(1, weight=0, minsize=390)

        def apply_auth_state():
            state = "disabled" if vars_dlg["trusted"].get() else "normal"
            ent_user.configure(state=state)
            ent_password.configure(state=state)

        chk_trusted.configure(command=apply_auth_state)
        apply_auth_state()

        info_var = tk.StringVar(
            value="Nenhum dado será alterado. O teste executa somente uma consulta de identificação do banco."
        )
        ttk.Label(
            frame,
            textvariable=info_var,
            wraplength=640,
            justify="left",
        ).grid(
            row=20, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4)
        )

        buttons = ttk.Frame(dlg)
        buttons.pack(fill="x", padx=12, pady=(0, 12))

        def collect_data():
            name = vars_dlg["name"].get().strip()
            tipo = vars_dlg["type"].get().strip()
            driver = vars_dlg["driver"].get().strip()
            server = vars_dlg["server"].get().strip()
            port = vars_dlg["port"].get().strip()
            database = vars_dlg["database"].get().strip()
            trusted = vars_dlg["trusted"].get()
            user = vars_dlg["user"].get().strip()
            password = vars_dlg["password"].get()

            schema = vars_dlg["schema"].get().strip()
            table = vars_dlg["table"].get().strip()
            field_codprod = vars_dlg["field_codprod"].get().strip()
            field_gtin = vars_dlg["field_gtin"].get().strip()
            field_saldo = vars_dlg["field_saldo"].get().strip()
            field_local = vars_dlg["field_local"].get().strip()
            field_terminal = vars_dlg["field_terminal"].get().strip()
            field_documento = vars_dlg["field_documento"].get().strip()

            if not name:
                raise ValueError("Informe um nome para a conexão.")
            if tipo != "Microsoft SQL Server":
                raise ValueError(
                    "Nesta etapa, somente Microsoft SQL Server está disponível."
                )
            if not driver:
                raise ValueError("Informe o Driver ODBC.")
            if not server:
                raise ValueError("Informe o servidor SQL Server.")
            if port:
                if not port.isdigit() or not (1 <= int(port) <= 65535):
                    raise ValueError("Informe uma porta válida entre 1 e 65535.")
            if not database:
                raise ValueError("Informe o banco de dados.")
            if not trusted and not user:
                raise ValueError("Informe o usuário do SQL Server.")

            if not schema:
                raise ValueError("Informe o schema da tabela de estoque.")
            if not table:
                raise ValueError("Informe a tabela de estoque do ERP.")
            if not field_codprod and not field_gtin:
                raise ValueError("Informe pelo menos o Campo CodProd ou o Campo GTIN/EAN.")
            if not field_saldo:
                raise ValueError("Informe o campo de saldo do ERP.")

            return {
                "name": name,
                "type": tipo,
                "driver": driver,
                "server": server,
                "port": port,
                "database": database,
                "trusted_connection": trusted,
                "user": user,
                "password": password,
                "schema": schema,
                "table": table,
                "field_codprod": field_codprod,
                "field_gtin": field_gtin,
                "field_saldo": field_saldo,
                "field_local": field_local,
                "field_terminal": field_terminal,
                "field_documento": field_documento,
            }

        def test_dialog_connection():
            try:
                data = collect_data()
                banco_ok, servidor_ok = self._test_external_connection_data(data)
                info_var.set(
                    f"Conexão OK | Servidor: {servidor_ok} | Banco: {banco_ok} | Nenhum dado alterado."
                )
                messagebox.showinfo(
                    "Conexões Externas",
                    "Conexão realizada com sucesso.\n\n"
                    f"Servidor: {servidor_ok}\n"
                    f"Banco: {banco_ok}\n\n"
                    "Nenhum dado foi alterado.",
                    parent=dlg,
                )
            except Exception as e:
                messagebox.showerror(
                    "Conexões Externas",
                    f"Falha na conexão:\n{e}",
                    parent=dlg,
                )

        def save_dialog():
            try:
                data = collect_data()
            except Exception as e:
                messagebox.showerror(
                    "Conexões Externas",
                    str(e),
                    parent=dlg,
                )
                return

            cid = connection_id or uuid.uuid4().hex[:12]
            previous_status = initial.get("status", "Salvo")
            data["id"] = cid
            data["status"] = previous_status if previous_status in ("Conectado", "Falha") else "Salvo"
            self.external_connections[cid] = data
            self.current_external_id = cid
            self._save_external_connections()

            # Atualiza imediatamente a conexão atual exibida na aba.
            self._refresh_external_tree()
            self.update_idletasks()

            dlg.grab_release()
            dlg.destroy()
            self.nb.select(self.tab_connector)
            self.update_idletasks()

        ttk.Button(
            buttons,
            text="Testar conexão",
            command=test_dialog_connection,
        ).pack(side="left")

        ttk.Button(
            buttons,
            text="Salvar",
            command=save_dialog,
        ).pack(side="right")

        ttk.Button(
            buttons,
            text="Cancelar",
            command=dlg.destroy,
        ).pack(side="right", padx=(0, 8))

        ent_name.focus_set()


    def _build_external_conn_str(self, data):
        driver = str(data.get("driver", "")).strip()
        server = str(data.get("server", "")).strip()
        database = str(data.get("database", "")).strip()
        port = str(data.get("port", "")).strip()
        trusted = bool(data.get("trusted_connection", False))

        server_target = f"{server},{port}" if port else server

        if trusted:
            return (
                f"DRIVER={{{driver}}};"
                f"SERVER={server_target};"
                f"DATABASE={database};"
                "Trusted_Connection=yes;"
                "TrustServerCertificate=yes;"
            )

        user = str(data.get("user", "")).strip()
        password = data.get("password", "")
        return (
            f"DRIVER={{{driver}}};"
            f"SERVER={server_target};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
            "TrustServerCertificate=yes;"
        )


    def _test_external_connection_data(self, data):
        if data.get("type") != "Microsoft SQL Server":
            raise ValueError(
                "Nesta etapa, somente Microsoft SQL Server está disponível."
            )

        conn_str = self._build_external_conn_str(data)
        conn = pyodbc.connect(conn_str, timeout=5)
        try:
            cur = conn.cursor()
            cur.execute("SELECT DB_NAME(), @@SERVERNAME")
            row = cur.fetchone()
        finally:
            conn.close()

        banco_ok = row[0] if row and row[0] else data.get("database", "")
        servidor_ok = row[1] if row and len(row) > 1 and row[1] else data.get("server", "")
        return banco_ok, servidor_ok


    def _test_selected_external_connection(self):
        connection_id = self._selected_external_id()
        if not connection_id:
            messagebox.showinfo(
                "Conexões Externas",
                "Nenhuma conexão atual está cadastrada para testar.",
            )
            return

        data = self.external_connections.get(connection_id)
        if not data:
            return

        try:
            banco_ok, servidor_ok = self._test_external_connection_data(data)
            data["status"] = "Conectado"
            self._refresh_external_tree()

            messagebox.showinfo(
                "Conexões Externas",
                "Conexão realizada com sucesso.\n\n"
                f"Servidor: {servidor_ok}\n"
                f"Banco: {banco_ok}\n\n"
                "Nenhum dado foi alterado.",
            )
        except Exception as e:
            data["status"] = "Falha"
            self._refresh_external_tree()
            messagebox.showerror(
                "Conexões Externas",
                f"Falha na conexão:\n{e}",
            )


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

    def _save(self, show_message=True):
        try:
            self._write_from_form()

            # cria pastas (se não existirem)
            for sec, opt in (
                ("watch", "input_dir"),
                ("watch", "processed_dir"),
                ("watch", "error_dir"),
                ("watch", "duplicate_dir"),
                ("logging", "log_dir"),
                ("output", "output_dir"),
            ):
                p = self.cfg.get(sec, opt, fallback="").strip()
                if p:
                    os.makedirs(p, exist_ok=True)

            # Conexões externas são independentes e salvas em seções próprias.
            if hasattr(self, "external_connections"):
                for section in list(self.cfg.sections()):
                    if section.startswith("external_connection:"):
                        self.cfg.remove_section(section)

                for connection_id, data in self.external_connections.items():
                    section = self._external_section_name(connection_id)
                    self.cfg[section] = {
                        "name": data.get("name", ""),
                        "type": data.get("type", "Microsoft SQL Server"),
                        "driver": data.get("driver", "ODBC Driver 18 for SQL Server"),
                        "server": data.get("server", ""),
                        "port": data.get("port", "1433"),
                        "database": data.get("database", ""),
                        "trusted_connection": bool_to_ini(bool(data.get("trusted_connection", False))),
                        "user": data.get("user", ""),
                        "password": data.get("password", ""),
                        "schema": data.get("schema", "dbo"),
                        "table": data.get("table", ""),
                        "field_codprod": data.get("field_codprod", ""),
                        "field_gtin": data.get("field_gtin", ""),
                        "field_saldo": data.get("field_saldo", ""),
                        "field_local": data.get("field_local", ""),
                        "field_terminal": data.get("field_terminal", ""),
                        "field_documento": data.get("field_documento", ""),
                    }

            save_cfg(self.cfg)
            if show_message:
                messagebox.showinfo("Salvar", f"Salvo em: {os.path.abspath(CONFIG_PATH)}")
            return True
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return False

    def _save_and_close(self):
        """Salva o estado atual de todas as abas e fecha somente se salvar com sucesso."""
        if self._save(show_message=False):
            self.destroy()


if __name__ == "__main__":
    app = ConfigUI()
    app.mainloop()
