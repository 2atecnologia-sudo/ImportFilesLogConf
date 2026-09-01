import os
import shutil
import configparser
import csv
import subprocess
import sys
import uuid
import threading
import time
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import pyodbc
from PIL import Image, ImageTk
from decimal import Decimal, InvalidOperation

from .runtime_status import read_runtime_status
import re

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

APP_VERSION = "1.0.2"
BUILD_DATE = "28/08/2026 20:30"

CONFIG_PATH = os.path.join(BASE_DIR, "config.ini")
EXAMPLE_PATH = os.path.join(BASE_DIR, "config.ini.example")
LICENCI_PATH = os.path.join(BASE_DIR, "licenci.ini")


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


def _acquire_config_single_instance():
    """
    Garante apenas uma janela do Config por sessão do Windows.
    Retorna o handle do mutex na primeira instância.
    Se já existir outra instância, informa o usuário e encerra a segunda.
    """
    if os.name != "nt":
        return None

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32

        # Local\\ evita problemas de permissão e é suficiente para impedir
        # duplicação da janela na sessão do usuário.
        mutex_name = "Local\\2ATecnologia_ImportFilesLogConf_Config"

        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(
            None,
            False,
            mutex_name,
        )

        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)

            user32.MessageBoxW(
                None,
                "A Configuração já está aberta.",
                "Gestor de Dados - 2A Tecnologia",
                0x00000040,  # MB_ICONINFORMATION
            )
            raise SystemExit(0)

        return handle

    except SystemExit:
        raise
    except Exception:
        # Se o Windows não permitir criar o mutex por alguma razão,
        # não bloqueia a abertura normal do Config.
        return None



class ConfigUI(tk.Tk):
    def __init__(self, initial_tab="config"):
        self._config_single_instance_mutex = _acquire_config_single_instance()
        super().__init__()
        self.title("Gestor de Dados - 2A Tecnologia")
        try:
            self.state("zoomed")
        except Exception:
            try:
                self.attributes("-zoomed", True)
            except Exception:
                pass

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

        # Monitor opcional da pasta de NF-e de entrada (somente Ambiente de Testes).
        self._nfe_watch_thread = None
        self._nfe_watch_stop = threading.Event()
        self._nfe_watch_enabled = False

        self._build()
        self._load_to_form()
        self._apply_states()
        self._select_initial_tab()
        self.after(150, self._apply_license_ui_mode)

        # Restaura automaticamente o monitor de NF-e caso ele tenha sido
        # deixado em PLAY na última execução.
        self.after(700, self._restore_nfe_watch_from_ini)

        # Qualquer forma de fechar a janela salva todas as configurações.
        self.protocol("WM_DELETE_WINDOW", self._save_and_close)

        # Atualiza a aba de Status/Logs periodicamente enquanto a janela estiver aberta.
        self.after(300, self._status_auto_refresh)

    def _build(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)
        self.nb.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        tab_sql = ttk.Frame(self.nb)
        self.tab_sql = tab_sql
        tab_paths = ttk.Frame(self.nb)
        self.tab_paths = tab_paths
        tab_input = ttk.Frame(self.nb)
        self.tab_input = tab_input
        tab_app = ttk.Frame(self.nb)
        self.tab_app = tab_app
        tab_output = ttk.Frame(self.nb)
        self.tab_output = tab_output
        tab_connector = ttk.Frame(self.nb)
        self.tab_connector = tab_connector
        self.tab_test_environment = ttk.Frame(self.nb)
        self.tab_status = ttk.Frame(self.nb)

        self.nb.add(tab_sql, text="Banco Local logConf")
        self.nb.add(tab_paths, text="Pastas")
        self.nb.add(tab_input, text="Entrada (XML/TXT)")
        self.nb.add(tab_app, text="Aplicação")
        self.nb.add(tab_output, text="Arquivos de Saída")
        self.nb.add(tab_connector, text="Fonte de Dados Externa")
        self.nb.add(self.tab_test_environment, text="Ambiente de Testes")
        self.nb.add(self.tab_status, text="Status / Logs")

        self.tab_licensing_admin = ttk.Frame(self.nb)
        self.nb.add(self.tab_licensing_admin, text="Licenciamento (Admin)")

        self.tab_help = ttk.Frame(self.nb)
        self.nb.add(self.tab_help, text="Ajuda")

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

        # ---- Licenciamento (Admin)
        self._build_licensing_admin_tab()

        # ---- Ajuda
        self._build_help_tab()

        # ---- Sobre
        self._build_about_tab()

        # ---- Ajuda contextual em cada aba
        self._add_context_help_buttons()

        # ---- Bottom
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(bottom, text="Salvar", command=self._save).pack(side="right")
        ttk.Button(bottom, text="Fechar", command=self._save_and_close).pack(side="right", padx=(0, 8))
        ttk.Button(bottom, text="? Ajuda", command=self._open_context_help).pack(side="left")


    def _build_test_environment_tab(self):
        """Grades somente de leitura do banco est_ambTestes."""
        container = ttk.Frame(self.tab_test_environment)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            container,
            text=(
                "Ambiente exclusivo para testes. "
                "As configurações de rede, SQL, pastas e conexões são preservadas."
            ),
        ).pack(anchor="w", pady=(0, 8))

        reset_box = ttk.LabelFrame(container, text="Preparação do Ambiente de Testes")
        reset_box.pack(fill="x", pady=(0, 8))

        ttk.Label(
            reset_box,
            text=(
                "Prepare o ambiente para novos testes. Você pode resetar os dados "
                "ou carregar novamente o banco de exemplo, sem alterar as configurações, "
                "conexões e pastas da aplicação."
            ),
            wraplength=600,
            justify="left",
        ).pack(side="left", padx=10, pady=9)

        ttk.Button(
            reset_box,
            text="Carregar Banco de Exemplo",
            command=self._load_example_stock,
        ).pack(side="right", padx=(6, 10), pady=9)

        ttk.Button(
            reset_box,
            text="Resetar Ambiente",
            command=self._reset_test_environment,
        ).pack(side="right", padx=6, pady=9)

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

        # Entrada de estoque por NF-e XML (camada isolada do fluxo de saída existente).
        xml_entry_box = ttk.LabelFrame(container, text="Entradas de Estoque por NF-e XML")
        xml_entry_box.pack(fill="x", pady=(0, 8))

        ttk.Label(
            xml_entry_box,
            text=(
                "Importa uma ou várias NF-e autorizadas e soma as quantidades ao estoque de teste. "
                "A identificação do produto aceita CodProd OU GTIN."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(8, 4))

        self.test_xml_status = tk.StringVar(value="Nenhum XML importado nesta sessão.")
        ttk.Button(
            xml_entry_box,
            text="Importar 1 ou vários XMLs...",
            command=self._import_nfe_xml_entries,
        ).grid(row=1, column=0, sticky="w", padx=8, pady=8)

        ttk.Label(
            xml_entry_box,
            textvariable=self.test_xml_status,
        ).grid(row=1, column=1, columnspan=3, sticky="w", padx=8, pady=8)

        # Pasta monitorada para NF-e de entrada.
        watch_box = ttk.LabelFrame(container, text="Pasta de NF-e de Entrada")
        watch_box.pack(fill="x", pady=(0, 8))

        self.test_nfe_watch_dir = tk.StringVar(
            value=self.cfg.get("test_environment", "nfe_input_dir", fallback="").strip()
        )
        self.test_nfe_watch_auto = tk.BooleanVar(
            value=as_bool(
                self.cfg.get(
                    "test_environment",
                    "nfe_auto_import",
                    fallback="no",
                )
            )
        )
        self.test_nfe_watch_status = tk.StringVar(value="⏹ Monitoramento parado.")

        ttk.Label(watch_box, text="Pasta").grid(
            row=0, column=0, sticky="w", padx=8, pady=8
        )

        ttk.Entry(
            watch_box,
            textvariable=self.test_nfe_watch_dir,
            width=48,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=8, pady=8)

        ttk.Button(
            watch_box,
            text="Escolher pasta...",
            command=self._pick_nfe_watch_folder,
        ).grid(row=0, column=2, sticky="w", padx=8, pady=8)

        ttk.Button(
            watch_box,
            text="Processar agora",
            command=self._process_nfe_watch_folder_now,
        ).grid(row=0, column=3, sticky="w", padx=8, pady=8)

        self.btn_nfe_watch_start = ttk.Button(
            watch_box,
            text="▶ Iniciar",
            command=self._start_nfe_watch,
        )
        self.btn_nfe_watch_start.grid(
            row=1, column=0, sticky="w", padx=(8, 4), pady=(0, 8)
        )

        self.btn_nfe_watch_stop = ttk.Button(
            watch_box,
            text="■ Parar",
            command=self._stop_nfe_watch,
            state="disabled",
        )
        self.btn_nfe_watch_stop.grid(
            row=1, column=1, sticky="w", padx=(4, 8), pady=(0, 8)
        )

        ttk.Label(
            watch_box,
            textvariable=self.test_nfe_watch_status,
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        watch_box.grid_columnconfigure(1, weight=1)

        self.test_env_nb = ttk.Notebook(container)
        self.test_env_nb.pack(fill="both", expand=True)

        tab_stock = ttk.Frame(self.test_env_nb)
        tab_moves = ttk.Frame(self.test_env_nb)
        self.test_env_nb.add(tab_stock, text="Estoque Atual")
        self.test_env_nb.add(tab_moves, text="Movimentações")

        stock_manual_actions = ttk.Frame(tab_stock)
        stock_manual_actions.pack(fill="x", padx=6, pady=(6, 0))

        ttk.Button(
            stock_manual_actions,
            text="Editar Saldo Manualmente...",
            command=self._edit_test_stock_balance,
        ).pack(side="left")

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
                ("cliente", "Cliente", 180),
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

            # O último estoque importado passa automaticamente a ser o
            # ESTOQUE PADRÃO da demonstração. Esta cópia não sofre baixas.
            cur.execute(
                """
                IF OBJECT_ID('dbo.ESTOQUE_BASE_DEMO', 'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.ESTOQUE_BASE_DEMO
                    (
                        COD_ITEM         VARCHAR(100)  NULL,
                        COD_BARRAS       VARCHAR(100)  NULL,
                        DESCRICAO_ITEM   VARCHAR(500)  NULL,
                        LOCAL_ESTOQUE    VARCHAR(100)  NULL,
                        SALDO_ATUAL      DECIMAL(18,3) NOT NULL
                    );
                END
                """
            )
            cur.execute("DELETE FROM dbo.ESTOQUE_BASE_DEMO")
            cur.execute(
                """
                INSERT INTO dbo.ESTOQUE_BASE_DEMO
                    (COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL)
                SELECT
                    COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL
                FROM dbo.ESTOQUE
                """
            )

            # Registra a origem de cada posição de estoque como CARGA INICIAL.
            # Isso cria um extrato auditável sem alterar o saldo importado.
            self._ensure_test_movement_description_column(cur)

            sql_mov = """
                INSERT INTO dbo.movEstambTeste
                    (
                        NUM_DOCUMENTO,
                        COD_ITEM,
                        COD_BARRAS,
                        DESCRICAO_ITEM,
                        QTD_MOVIMENTADA,
                        SALDO_ANTERIOR,
                        SALDO_POSTERIOR,
                        IDENT_TERMINAL,
                        TIPO_OPERACAO,
                        RESULTADO,
                        DETALHE
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            movimentos = [
                (
                    "CARGA_INICIAL",
                    codprod,
                    gtin,
                    desc,
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
                f"Lançamentos de SALDO INICIAL: {len(rows)}\n"
                f"Estoque Padrão da demonstração: SALVO",
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

    def _build_test_environment_write_conn_str(self):
        """Conexão de escrita SOMENTE para o banco fixo est_ambTestes."""
        return self._build_test_environment_conn_str().replace(
            "ApplicationIntent=ReadOnly;", ""
        )

    def _save_test_stock_as_default(self):
        """Salva o estoque fictício atual como modelo para futuros resets."""
        if self._importer_rodando():
            messagebox.showwarning(
                "Ambiente de Testes",
                "Pare o Importador antes de salvar o Estoque Padrão.",
                parent=self,
            )
            return

        if not messagebox.askyesno(
            "Salvar Estoque Padrão?",
            "O estoque ATUAL será guardado como modelo dos próximos resets.\n\n"
            "Rede, SQL e conexões NÃO serão alterados.\n\nContinuar?",
            parent=self,
        ):
            return

        conn = None
        try:
            conn = pyodbc.connect(
                self._build_test_environment_write_conn_str(),
                timeout=5,
                autocommit=False,
            )
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM dbo.ESTOQUE")
            total = int(cur.fetchone()[0])
            if total <= 0:
                raise RuntimeError("dbo.ESTOQUE está vazia.")

            cur.execute(
                """
                IF OBJECT_ID('dbo.ESTOQUE_BASE_DEMO', 'U') IS NULL
                BEGIN
                    CREATE TABLE dbo.ESTOQUE_BASE_DEMO
                    (
                        COD_ITEM VARCHAR(100) NULL,
                        COD_BARRAS VARCHAR(100) NULL,
                        DESCRICAO_ITEM VARCHAR(500) NULL,
                        LOCAL_ESTOQUE VARCHAR(100) NULL,
                        SALDO_ATUAL DECIMAL(18,3) NOT NULL
                    );
                END
                """
            )
            cur.execute("DELETE FROM dbo.ESTOQUE_BASE_DEMO")
            cur.execute(
                """
                INSERT INTO dbo.ESTOQUE_BASE_DEMO
                    (COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL)
                SELECT COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL
                FROM dbo.ESTOQUE
                """
            )
            conn.commit()

            self._write_test_user_log(
                "OK",
                "Estoque Padrão salvo",
                f"{total} posição(ões) preservadas como modelo de reset.",
                "Use Resetar Ambiente para voltar a este estado.",
            )
            messagebox.showinfo(
                "Estoque Padrão salvo",
                f"Estoque Padrão salvo com sucesso.\n\nPosições: {total}\n"
                "Configurações preservadas.",
                parent=self,
            )
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            messagebox.showerror(
                "Falha ao salvar Estoque Padrão",
                f"Nenhuma alteração confirmada.\n\n{e}",
                parent=self,
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _reset_test_environment(self):
        """Limpa os dados de teste, preservando todas as configurações."""
        if self._importer_rodando():
            messagebox.showwarning(
                "Resetar Ambiente",
                "Pare o Importador antes de executar o reset.",
                parent=self,
            )
            return

        if not messagebox.askyesno(
            "Resetar Ambiente de Testes?",
            "Serão eliminados:\n"
            "• estoque de teste;\n"
            "• movimentações;\n"
            "• logConf;\n"
            "• prodConf;\n"
            "• erros de conferência.\n\n"
            "Configurações SQL, rede, ERP, usuário, senha e pastas serão preservadas.\n\n"
            "Deseja continuar?",
            parent=self,
        ):
            return

        estoque_conn = None
        local_conn = None
        try:
            estoque_conn = pyodbc.connect(
                self._build_test_environment_write_conn_str(),
                timeout=5,
                autocommit=False,
            )
            ec = estoque_conn.cursor()
            ec.execute("DELETE FROM dbo.ESTOQUE")
            ec.execute(
                """
                IF OBJECT_ID('dbo.movEstambTeste', 'U') IS NOT NULL
                    DELETE FROM dbo.movEstambTeste
                """
            )
            ec.execute(
                """
                IF OBJECT_ID('dbo.EntradaNFeProcessada', 'U') IS NOT NULL
                    DELETE FROM dbo.EntradaNFeProcessada
                """
            )

            self.cfg = load_cfg()
            local_conn = pyodbc.connect(
                build_conn_str(self.cfg),
                timeout=5,
                autocommit=False,
            )
            lc = local_conn.cursor()

            limpas = []
            for tabela in ("LancamentoExternoStatus", "scanerroconf", "prodConf", "logConf"):
                lc.execute("SELECT OBJECT_ID(?, 'U')", (f"dbo.{tabela}",))
                if lc.fetchone()[0] is not None:
                    lc.execute(f"DELETE FROM dbo.[{tabela}]")
                    limpas.append(tabela)

            estoque_conn.commit()
            local_conn.commit()

            self._write_test_user_log(
                "OK",
                "RESET DO AMBIENTE DE TESTES",
                "Estoque, movimentações, conferências e erros foram eliminados.",
                "Importe um arquivo de estoque ou carregue o Banco de Exemplo para iniciar um novo teste.",
                [
                    "Configurações SQL/rede/ERP preservadas.",
                    "Tabelas locais limpas: " + (", ".join(limpas) if limpas else "nenhuma encontrada"),
                ],
            )

            self.test_file_status.set(
                "Estoque de teste vazio. Importe um arquivo ou carregue o Banco de Exemplo."
            )
            self._refresh_test_stock()
            self._refresh_test_moves()

            messagebox.showinfo(
                "Ambiente resetado",
                "RESET concluído com sucesso.\n\n"
                "O ambiente está vazio e pronto para um novo cenário.\n\n"
                "Importe um arquivo de estoque ou clique em 'Carregar Banco de Exemplo'.\n\n"
                "Configurações e conexões foram preservadas.",
                parent=self,
            )

            # A limpeza dos logs é opcional e independente do reset.
            if messagebox.askyesno(
                "Apagar Logs?",
                "O Ambiente de Testes foi resetado com sucesso.\n\n"
                "Deseja apagar também o Log do Usuário e o Log Técnico?",
                parent=self,
            ):
                self._clear_logs_after_test_reset()

        except Exception as e:
            if estoque_conn is not None:
                try:
                    estoque_conn.rollback()
                except Exception:
                    pass
            if local_conn is not None:
                try:
                    local_conn.rollback()
                except Exception:
                    pass

            self._write_test_user_log(
                "ERRO",
                "RESET DO AMBIENTE DE TESTES",
                "Reset não concluído.",
                "Nenhuma configuração foi alterada.",
                [str(e)],
            )
            messagebox.showerror(
                "Falha no RESET",
                "O reset não foi concluído. As transações abertas foram revertidas.\n\n"
                f"Detalhe: {e}",
                parent=self,
            )
        finally:
            for conn in (estoque_conn, local_conn):
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def _load_example_stock(self):
        """Carrega o estoque DEMO salvo em ESTOQUE_BASE_DEMO."""
        if self._importer_rodando():
            messagebox.showwarning(
                "Banco de Exemplo",
                "Pare o Importador antes de carregar o Banco de Exemplo.",
                parent=self,
            )
            return

        conn = None
        try:
            conn = pyodbc.connect(
                self._build_test_environment_write_conn_str(),
                timeout=5,
                autocommit=False,
            )
            cur = conn.cursor()

            cur.execute("SELECT OBJECT_ID('dbo.ESTOQUE_BASE_DEMO', 'U')")
            if cur.fetchone()[0] is None:
                raise RuntimeError("Banco de Exemplo ainda não está disponível.")

            cur.execute("SELECT COUNT(*) FROM dbo.ESTOQUE_BASE_DEMO")
            total = int(cur.fetchone()[0])
            if total <= 0:
                raise RuntimeError("Banco de Exemplo está vazio.")

            cur.execute("DELETE FROM dbo.ESTOQUE")
            cur.execute(
                """
                INSERT INTO dbo.ESTOQUE
                    (COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL)
                SELECT
                    COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL
                FROM dbo.ESTOQUE_BASE_DEMO
                """
            )
            conn.commit()

            self._write_test_user_log(
                "OK",
                "BANCO DE EXEMPLO CARREGADO",
                f"{total} posição(ões) de estoque carregadas.",
                "Ambiente pronto para demonstração.",
            )
            self.test_file_status.set(
                f"Banco de Exemplo carregado: {total} posição(ões)."
            )
            self._refresh_test_stock()

            messagebox.showinfo(
                "Banco de Exemplo",
                f"Banco de Exemplo carregado com sucesso.\n\n"
                f"Posições de estoque: {total}\n\n"
                "Ambiente pronto para testes.",
                parent=self,
            )
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self._write_test_user_log(
                "ERRO",
                "BANCO DE EXEMPLO",
                "Não foi possível carregar o Banco de Exemplo.",
                "Verifique o detalhe técnico.",
                [str(e)],
            )
            messagebox.showerror(
                "Banco de Exemplo",
                f"Não foi possível carregar o Banco de Exemplo.\n\n{e}",
                parent=self,
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


    def _ensure_nfe_entry_control_table(self, cur):
        """Cria somente a tabela de controle de NF-e já processada, se ainda não existir."""
        cur.execute(
            """
            IF OBJECT_ID('dbo.EntradaNFeProcessada', 'U') IS NULL
            BEGIN
                CREATE TABLE dbo.EntradaNFeProcessada
                (
                    ChaveNFe       VARCHAR(44)   NOT NULL PRIMARY KEY,
                    NumNF          VARCHAR(50)   NULL,
                    Emitente       VARCHAR(300)  NULL,
                    DataEmissao    DATETIME2(0)  NULL,
                    Arquivo        VARCHAR(500)  NULL,
                    ItensLancados  INT           NOT NULL DEFAULT (0),
                    ProcessadoEm   DATETIME2(0)  NOT NULL DEFAULT (SYSDATETIME())
                );
            END
            """
        )

    def _read_nfe_xml_for_stock_entry(self, file_path):
        """Lê NF-e 4.00 autorizada e devolve cabeçalho + itens para entrada de estoque."""
        ns = {"nfe": "http://www.portalfiscal.inf.br/nfe"}
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except Exception as e:
            raise RuntimeError(f"XML inválido: {e}") from e

        inf_nfe = root.find(".//nfe:infNFe", ns)
        if inf_nfe is None:
            raise RuntimeError("Estrutura infNFe não encontrada.")

        chave = str(inf_nfe.attrib.get("Id", "")).strip()
        if chave.startswith("NFe"):
            chave = chave[3:]

        if len(chave) != 44 or not chave.isdigit():
            ch_tag = root.find(".//nfe:protNFe/nfe:infProt/nfe:chNFe", ns)
            chave = str(ch_tag.text or "").strip() if ch_tag is not None else ""

        if len(chave) != 44 or not chave.isdigit():
            raise RuntimeError("Chave de acesso da NF-e não encontrada ou inválida.")

        cstat = root.find(".//nfe:protNFe/nfe:infProt/nfe:cStat", ns)
        cstat_value = str(cstat.text or "").strip() if cstat is not None else ""
        if cstat_value != "100":
            raise RuntimeError(
                f"NF-e não autorizada para uso. cStat={cstat_value or 'não informado'}."
            )

        n_nf = root.find(".//nfe:ide/nfe:nNF", ns)
        dh_emi = root.find(".//nfe:ide/nfe:dhEmi", ns)
        emit = root.find(".//nfe:emit/nfe:xNome", ns)

        num_nf = str(n_nf.text or "").strip() if n_nf is not None else ""
        data_emissao = str(dh_emi.text or "").strip() if dh_emi is not None else ""
        emitente = str(emit.text or "").strip() if emit is not None else ""

        items = []
        for det in inf_nfe.findall("nfe:det", ns):
            prod = det.find("nfe:prod", ns)
            if prod is None:
                continue

            def _txt(tag):
                node = prod.find(f"nfe:{tag}", ns)
                return str(node.text or "").strip() if node is not None else ""

            codprod = _txt("cProd")
            gtin_trib = _txt("cEANTrib")
            gtin_com = _txt("cEAN")
            gtin = gtin_trib if gtin_trib and gtin_trib.upper() != "SEM GTIN" else gtin_com
            if gtin and gtin.upper() == "SEM GTIN":
                gtin = ""

            desc = _txt("xProd")
            qtd_txt = _txt("qTrib") or _txt("qCom")
            try:
                qtd = Decimal(str(qtd_txt).replace(",", "."))
            except Exception:
                raise RuntimeError(
                    f"Quantidade inválida no item {det.attrib.get('nItem', '?')}: {qtd_txt!r}"
                )

            if qtd <= 0:
                raise RuntimeError(
                    f"Quantidade não positiva no item {det.attrib.get('nItem', '?')}."
                )

            if not codprod and not gtin:
                raise RuntimeError(
                    f"Item {det.attrib.get('nItem', '?')} sem cProd e sem GTIN."
                )

            items.append(
                {
                    "item": str(det.attrib.get("nItem", "")).strip(),
                    "codprod": codprod,
                    "gtin": gtin,
                    "desc": desc,
                    "qtd": qtd,
                }
            )

        if not items:
            raise RuntimeError("NF-e sem itens de produto.")

        return {
            "chave": chave,
            "num_nf": num_nf,
            "emitente": emitente,
            "data_emissao": data_emissao,
            "items": items,
            "arquivo": os.path.basename(file_path),
        }

    def _find_stock_row_for_nfe_item(self, cur, codprod, gtin):
        """
        Localiza por CodProd OU GTIN.
        Se ambos encontrarem a mesma posição, usa normalmente.
        Se só um encontrar, usa normalmente.
        Se encontrarem posições diferentes, bloqueia por ambiguidade.
        """
        matches = []

        if codprod:
            cur.execute(
                """
                SELECT COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL
                FROM dbo.ESTOQUE
                WHERE LTRIM(RTRIM(COD_ITEM)) = ?
                """,
                (codprod,),
            )
            matches.extend(cur.fetchall())

        if gtin:
            cur.execute(
                """
                SELECT COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL
                FROM dbo.ESTOQUE
                WHERE LTRIM(RTRIM(COD_BARRAS)) = ?
                """,
                (gtin,),
            )
            matches.extend(cur.fetchall())

        unique = {}
        for row in matches:
            key = (
                str(row[0] or "").strip(),
                str(row[1] or "").strip(),
                str(row[3] or "").strip(),
            )
            unique[key] = row

        rows = list(unique.values())

        if not rows:
            return None

        if len(rows) > 1:
            raise RuntimeError(
                "CodProd/GTIN localizaram mais de uma posição de estoque. "
                "A entrada foi bloqueada para evitar lançamento incorreto."
            )

        return rows[0]

    def _process_single_nfe_stock_entry(self, cur, nfe):
        """Processa uma única NF-e dentro da transação já aberta."""
        self._ensure_nfe_entry_control_table(cur)

        cur.execute(
            "SELECT COUNT(*) FROM dbo.EntradaNFeProcessada WHERE ChaveNFe = ?",
            (nfe["chave"],),
        )
        if int(cur.fetchone()[0]) > 0:
            return {
                "status": "DUPLICADA",
                "num_nf": nfe["num_nf"],
                "arquivo": nfe["arquivo"],
                "itens": 0,
                "detalhe": (
                    f"NF-e {nfe['num_nf'] or '-'} já importada anteriormente. "
                    "Nenhuma nova entrada de estoque foi realizada."
                ),
            }

        prepared = []
        for item in nfe["items"]:
            row = self._find_stock_row_for_nfe_item(
                cur,
                item["codprod"],
                item["gtin"],
            )

            if row is None:
                # Produto novo no ERP de simulação:
                # cadastra automaticamente usando os dados disponíveis na NF-e.
                cod_item = str(item["codprod"] or "").strip()
                cod_barras = str(item["gtin"] or "").strip()
                descricao = str(item["desc"] or "").strip()
                local = "SEM_LOCAL"
                saldo_anterior = Decimal("0")
                saldo_posterior = item["qtd"]
                novo_produto = True
            else:
                cod_item = str(row[0] or "").strip()
                cod_barras = str(row[1] or "").strip()
                descricao = str(row[2] or item["desc"] or "").strip()
                local = str(row[3] or "").strip()
                saldo_anterior = Decimal(str(row[4] or 0))
                saldo_posterior = saldo_anterior + item["qtd"]
                novo_produto = False

            prepared.append(
                (
                    item,
                    cod_item,
                    cod_barras,
                    descricao,
                    local,
                    saldo_anterior,
                    saldo_posterior,
                    novo_produto,
                )
            )

        # Só grava depois que TODOS os itens foram validados.
        for (
            item,
            cod_item,
            cod_barras,
            descricao,
            local,
            saldo_anterior,
            saldo_posterior,
            novo_produto,
        ) in prepared:
            if novo_produto:
                cur.execute(
                    """
                    INSERT INTO dbo.ESTOQUE
                        (COD_ITEM, COD_BARRAS, DESCRICAO_ITEM, LOCAL_ESTOQUE, SALDO_ATUAL)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        cod_item or None,
                        cod_barras or None,
                        descricao,
                        local,
                        saldo_posterior,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE dbo.ESTOQUE
                    SET SALDO_ATUAL = ?
                    WHERE LTRIM(RTRIM(COD_ITEM)) = ?
                      AND LTRIM(RTRIM(COD_BARRAS)) = ?
                      AND LTRIM(RTRIM(LOCAL_ESTOQUE)) = ?
                    """,
                    (
                        saldo_posterior,
                        cod_item,
                        cod_barras,
                        local,
                    ),
                )

            self._ensure_test_movement_description_column(cur)

            cur.execute(
                """
                INSERT INTO dbo.movEstambTeste
                (
                    NUM_DOCUMENTO,
                    COD_ITEM,
                    COD_BARRAS,
                    DESCRICAO_ITEM,
                    QTD_MOVIMENTADA,
                    SALDO_ANTERIOR,
                    SALDO_POSTERIOR,
                    IDENT_TERMINAL,
                    TIPO_OPERACAO,
                    RESULTADO,
                    DETALHE
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nfe["num_nf"] or nfe["chave"],
                    cod_item or item["codprod"],
                    cod_barras or item["gtin"],
                    descricao,
                    item["qtd"],
                    saldo_anterior,
                    saldo_posterior,
                    None,
                    "ENTRADA_NFE",
                    "SUCESSO",
                    (
                        f"Entrada por NF-e | Emitente: {nfe['emitente']} | "
                        f"XML cProd={item['codprod'] or '-'} | "
                        f"XML GTIN={item['gtin'] or '-'} | "
                        f"{descricao} | Local: {local} | "
                        f"{'Produto cadastrado automaticamente' if novo_produto else 'Produto existente atualizado'}"
                    ),
                ),
            )

        cur.execute(
            """
            INSERT INTO dbo.EntradaNFeProcessada
                (ChaveNFe, NumNF, Emitente, DataEmissao, Arquivo, ItensLancados)
            VALUES (?, ?, ?, TRY_CONVERT(DATETIME2(0), ?), ?, ?)
            """,
            (
                nfe["chave"],
                nfe["num_nf"],
                nfe["emitente"],
                nfe["data_emissao"],
                nfe["arquivo"],
                len(prepared),
            ),
        )

        return {
            "status": "OK",
            "num_nf": nfe["num_nf"],
            "arquivo": nfe["arquivo"],
            "itens": len(prepared),
            "detalhe": f"{len(prepared)} item(ns) lançados.",
        }

    def _import_nfe_xml_entries(self):
        """Seleciona 1 ou vários XMLs e lança entradas no estoque de testes."""
        files = filedialog.askopenfilenames(
            parent=self,
            title="Selecionar NF-e XML para entrada de estoque",
            filetypes=[
                ("Arquivos XML", "*.xml"),
                ("Todos os arquivos", "*.*"),
            ],
        )

        if not files:
            return

        conn = None
        results = []
        try:
            conn = pyodbc.connect(
                self._build_test_environment_write_conn_str(),
                timeout=5,
                autocommit=False,
            )
            cur = conn.cursor()

            for file_path in files:
                try:
                    nfe = self._read_nfe_xml_for_stock_entry(file_path)
                    result = self._process_single_nfe_stock_entry(cur, nfe)
                    if result["status"] == "OK":
                        conn.commit()
                    else:
                        conn.rollback()
                    results.append(result)
                except Exception as e:
                    conn.rollback()
                    results.append(
                        {
                            "status": "ERRO",
                            "num_nf": "",
                            "arquivo": os.path.basename(file_path),
                            "itens": 0,
                            "detalhe": str(e),
                        }
                    )

            ok = sum(1 for r in results if r["status"] == "OK")
            dup = sum(1 for r in results if r["status"] == "DUPLICADA")
            err = sum(1 for r in results if r["status"] == "ERRO")
            itens = sum(int(r.get("itens") or 0) for r in results if r["status"] == "OK")

            self.test_xml_status.set(
                f"XMLs processados: {len(results)} | OK: {ok} | Duplicados: {dup} | "
                f"Erros: {err} | Itens lançados: {itens}"
            )

            detalhes = []
            for r in results:
                detalhes.append(
                    f"{r['status']} | NF={r.get('num_nf') or '-'} | "
                    f"{r['arquivo']} | {r['detalhe']}"
                )

            if dup > 0 and ok == 0 and err == 0:
                log_level = "ATENÇÃO"
                log_reason = (
                    f"{dup} NF-e já importada anteriormente. "
                    "Nenhuma nova entrada de estoque foi realizada."
                )
                log_action = (
                    "Nenhuma ação necessária. A proteção contra duplicidade impediu "
                    "um novo lançamento da mesma NF-e."
                )
            else:
                log_level = "OK" if err == 0 else "ATENÇÃO"
                log_reason = (
                    f"{ok} XML(s) lançado(s), {dup} NF-e já importada(s) ignorada(s), "
                    f"{err} com erro."
                )
                log_action = "Consulte os detalhes abaixo quando houver erro."

            self._write_test_user_log(
                log_level,
                "IMPORTAÇÃO DE NF-e DE ENTRADA",
                log_reason,
                log_action,
                detalhes,
            )

            self._refresh_test_stock()
            self._refresh_test_moves()

            messagebox.showinfo(
                "Entrada de Estoque por NF-e",
                (
                    f"Arquivos selecionados: {len(results)}\n"
                    f"Importados: {ok}\n"
                    f"NF-e já importadas (ignoradas): {dup}\n"
                    f"Com erro: {err}\n"
                    f"Itens lançados: {itens}\n\n"
                    "Cada NF-e é transacionada separadamente: se um item da nota falhar, "
                    "nenhum item daquela NF-e é confirmado."
                ),
                parent=self,
            )

        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self.test_xml_status.set("Falha ao iniciar importação de NF-e.")
            messagebox.showerror(
                "Entrada de Estoque por NF-e",
                f"Não foi possível processar os XMLs.\n\nDetalhe: {e}",
                parent=self,
            )
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


    def _edit_test_stock_balance(self):
        """
        Ajuste manual SOMENTE do saldo de uma posição do estoque de testes.

        Não interfere no looper nem na lógica de saída.
        Registra o ajuste em dbo.movEstambTeste para manter auditoria.
        """
        tree = getattr(self, "test_stock_tree", None)
        if tree is None:
            return

        selected = tree.selection()
        if not selected:
            messagebox.showwarning(
                "Editar Saldo",
                "Selecione primeiro um produto na grade Estoque Atual.",
                parent=self,
            )
            return

        values = tree.item(selected[0], "values")
        if not values or len(values) < 5:
            messagebox.showerror(
                "Editar Saldo",
                "Não foi possível identificar os dados do produto selecionado.",
                parent=self,
            )
            return

        codprod = str(values[0] or "").strip()
        gtin = str(values[1] or "").strip()
        descricao = str(values[2] or "").strip()
        local = str(values[3] or "").strip()
        saldo_atual_txt = str(values[4] or "0").strip()

        try:
            saldo_atual = Decimal(saldo_atual_txt.replace(",", "."))
        except Exception:
            messagebox.showerror(
                "Editar Saldo",
                f"Saldo atual inválido: {saldo_atual_txt}",
                parent=self,
            )
            return

        novo_txt = simpledialog.askstring(
            "Editar Saldo",
            (
                f"Produto: {codprod or '-'}\n"
                f"GTIN: {gtin or '-'}\n"
                f"Descrição: {descricao or '-'}\n"
                f"Local: {local or '-'}\n"
                f"Saldo atual: {saldo_atual}\n\n"
                "Informe o NOVO saldo:"
            ),
            parent=self,
            initialvalue=str(saldo_atual),
        )

        if novo_txt is None:
            return

        try:
            novo_saldo = Decimal(str(novo_txt).strip().replace(",", "."))
        except Exception:
            messagebox.showerror(
                "Editar Saldo",
                "Informe um valor numérico válido.",
                parent=self,
            )
            return

        if novo_saldo < 0:
            messagebox.showerror(
                "Editar Saldo",
                "O saldo não pode ser negativo.",
                parent=self,
            )
            return

        if novo_saldo == saldo_atual:
            messagebox.showinfo(
                "Editar Saldo",
                "O novo saldo é igual ao saldo atual. Nenhuma alteração foi realizada.",
                parent=self,
            )
            return

        if not messagebox.askyesno(
            "Confirmar Ajuste de Saldo",
            (
                f"Produto: {codprod or '-'}\n"
                f"GTIN: {gtin or '-'}\n"
                f"Local: {local or '-'}\n\n"
                f"Saldo atual: {saldo_atual}\n"
                f"Novo saldo: {novo_saldo}\n\n"
                "Confirmar o ajuste manual?"
            ),
            parent=self,
        ):
            return

        conn = None
        try:
            conn = pyodbc.connect(
                self._build_test_environment_write_conn_str(),
                timeout=5,
                autocommit=False,
            )
            cur = conn.cursor()

            cur.execute(
                """
                SELECT COUNT(*)
                FROM dbo.ESTOQUE
                WHERE LTRIM(RTRIM(ISNULL(COD_ITEM, ''))) = ?
                  AND LTRIM(RTRIM(ISNULL(COD_BARRAS, ''))) = ?
                  AND LTRIM(RTRIM(ISNULL(LOCAL_ESTOQUE, ''))) = ?
                """,
                (codprod, gtin, local),
            )
            total = int(cur.fetchone()[0])

            if total != 1:
                raise RuntimeError(
                    f"Esperada exatamente 1 posição de estoque para o item selecionado; encontrado(s): {total}."
                )

            cur.execute(
                """
                UPDATE dbo.ESTOQUE
                SET SALDO_ATUAL = ?
                WHERE LTRIM(RTRIM(ISNULL(COD_ITEM, ''))) = ?
                  AND LTRIM(RTRIM(ISNULL(COD_BARRAS, ''))) = ?
                  AND LTRIM(RTRIM(ISNULL(LOCAL_ESTOQUE, ''))) = ?
                """,
                (novo_saldo, codprod, gtin, local),
            )

            diferenca = novo_saldo - saldo_atual

            self._ensure_test_movement_description_column(cur)

            cur.execute(
                """
                INSERT INTO dbo.movEstambTeste
                (
                    NUM_DOCUMENTO,
                    COD_ITEM,
                    COD_BARRAS,
                    DESCRICAO_ITEM,
                    QTD_MOVIMENTADA,
                    SALDO_ANTERIOR,
                    SALDO_POSTERIOR,
                    IDENT_TERMINAL,
                    TIPO_OPERACAO,
                    RESULTADO,
                    DETALHE
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "AJUSTE_MANUAL",
                    codprod or None,
                    gtin or None,
                    descricao,
                    diferenca,
                    saldo_atual,
                    novo_saldo,
                    None,
                    "AJUSTE_MANUAL",
                    "SUCESSO",
                    (
                        f"Ajuste manual de saldo | {descricao} | Local: {local or '-'} | "
                        f"Saldo anterior={saldo_atual} | Novo saldo={novo_saldo}"
                    ),
                ),
            )

            conn.commit()

            self._write_test_user_log(
                "OK",
                "AJUSTE MANUAL DE SALDO",
                (
                    f"Saldo alterado de {saldo_atual} para {novo_saldo} "
                    f"no produto {codprod or gtin or '-'}."
                ),
                "A movimentação foi registrada no histórico do Ambiente de Testes.",
                [
                    f"CodProd: {codprod or '-'}",
                    f"GTIN: {gtin or '-'}",
                    f"Local: {local or '-'}",
                    f"Variação: {diferenca}",
                ],
            )

            self._refresh_test_stock()
            self._refresh_test_moves()

            messagebox.showinfo(
                "Editar Saldo",
                (
                    "Saldo atualizado com sucesso.\n\n"
                    f"Saldo anterior: {saldo_atual}\n"
                    f"Novo saldo: {novo_saldo}"
                ),
                parent=self,
            )

        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass

            messagebox.showerror(
                "Editar Saldo",
                f"Nenhuma alteração foi confirmada.\n\nDetalhe: {e}",
                parent=self,
            )

        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


    def _save_nfe_watch_settings(self):
        """Persiste somente as opções da pasta de NF-e de entrada."""
        cfg = load_cfg()
        if not cfg.has_section("test_environment"):
            cfg.add_section("test_environment")
        cfg.set(
            "test_environment",
            "nfe_input_dir",
            self.test_nfe_watch_dir.get().strip(),
        )
        cfg.set(
            "test_environment",
            "nfe_auto_import",
            bool_to_ini(bool(self.test_nfe_watch_auto.get())),
        )
        save_cfg(cfg)
        self.cfg = cfg

    def _pick_nfe_watch_folder(self):
        selected = filedialog.askdirectory(
            parent=self,
            title="Selecionar pasta de NF-e de entrada",
        )
        if not selected:
            return
        self.test_nfe_watch_dir.set(selected)
        self._save_nfe_watch_settings()
        self.test_nfe_watch_status.set(
            f"Pasta configurada: {selected}"
        )
        self._write_test_user_log(
            "OK",
            "PASTA DE NF-e CONFIGURADA",
            f"Pasta de entrada definida para: {selected}",
            "Use 'Processar agora' para uma varredura manual ou '▶ Iniciar' para monitoramento automático.",
        )

    def _nfe_watch_destination_dirs(self):
        base = self.test_nfe_watch_dir.get().strip()
        return {
            "processados": os.path.join(base, "processados"),
            "duplicados": os.path.join(base, "duplicados"),
            "erros": os.path.join(base, "erros"),
        }

    def _move_nfe_watch_file(self, source_path, bucket):
        dirs = self._nfe_watch_destination_dirs()
        dest_dir = dirs[bucket]
        os.makedirs(dest_dir, exist_ok=True)

        base_name = os.path.basename(source_path)
        dest_path = os.path.join(dest_dir, base_name)

        if os.path.exists(dest_path):
            stem, ext = os.path.splitext(base_name)
            dest_path = os.path.join(
                dest_dir,
                f"{stem}_{int(time.time())}{ext}",
            )

        shutil.move(source_path, dest_path)
        return dest_path

    def _process_nfe_watch_folder(self, show_message=False):
        """
        Processa todos os XMLs encontrados na pasta configurada.

        Reutiliza exatamente a mesma rotina já validada de entrada por NF-e.
        Cada XML é transacionado separadamente.
        """
        folder = self.test_nfe_watch_dir.get().strip()
        if not folder:
            if show_message:
                messagebox.showwarning(
                    "Pasta de NF-e",
                    "Selecione primeiro a pasta de NF-e de entrada.",
                    parent=self,
                )
            return {
                "total": 0,
                "ok": 0,
                "duplicadas": 0,
                "erros": 0,
                "itens": 0,
            }

        if not os.path.isdir(folder):
            if show_message:
                messagebox.showerror(
                    "Pasta de NF-e",
                    f"Pasta não encontrada:\n{folder}",
                    parent=self,
                )
            return {
                "total": 0,
                "ok": 0,
                "duplicadas": 0,
                "erros": 0,
                "itens": 0,
            }

        files = sorted(
            [
                os.path.join(folder, name)
                for name in os.listdir(folder)
                if name.lower().endswith(".xml")
                and os.path.isfile(os.path.join(folder, name))
            ]
        )

        if not files:
            self.test_nfe_watch_status.set("Nenhum XML encontrado na pasta.")
            if show_message:
                messagebox.showinfo(
                    "Pasta de NF-e",
                    "Nenhum arquivo XML encontrado na pasta configurada.",
                    parent=self,
                )
            return {
                "total": 0,
                "ok": 0,
                "duplicadas": 0,
                "erros": 0,
                "itens": 0,
            }

        conn = None
        results = []
        try:
            conn = pyodbc.connect(
                self._build_test_environment_write_conn_str(),
                timeout=5,
                autocommit=False,
            )
            cur = conn.cursor()

            for file_path in files:
                result = None
                try:
                    nfe = self._read_nfe_xml_for_stock_entry(file_path)
                    result = self._process_single_nfe_stock_entry(cur, nfe)

                    if result["status"] == "OK":
                        conn.commit()
                        moved_to = self._move_nfe_watch_file(
                            file_path,
                            "processados",
                        )
                        result["movido_para"] = moved_to
                    elif result["status"] == "DUPLICADA":
                        conn.rollback()
                        moved_to = self._move_nfe_watch_file(
                            file_path,
                            "duplicados",
                        )
                        result["movido_para"] = moved_to
                    else:
                        conn.rollback()

                except Exception as e:
                    conn.rollback()
                    moved_to = self._move_nfe_watch_file(
                        file_path,
                        "erros",
                    )
                    result = {
                        "status": "ERRO",
                        "num_nf": "",
                        "arquivo": os.path.basename(file_path),
                        "itens": 0,
                        "detalhe": str(e),
                        "movido_para": moved_to,
                    }

                results.append(result)

            ok = sum(1 for r in results if r["status"] == "OK")
            dup = sum(1 for r in results if r["status"] == "DUPLICADA")
            err = sum(1 for r in results if r["status"] == "ERRO")
            itens = sum(
                int(r.get("itens") or 0)
                for r in results
                if r["status"] == "OK"
            )

            if ok > 0 and dup == 0 and err == 0:
                status_text = (
                    f"Importação concluída: {ok} NF-e | "
                    f"Itens lançados: {itens}"
                )
                log_level = "OK"
                log_reason = (
                    f"{ok} NF-e importada(s) com sucesso. "
                    f"{itens} item(ns) lançado(s) no estoque."
                )
                log_action = (
                    "Nenhuma ação necessária. XML(s) movido(s) para a pasta processados."
                )
            elif ok == 0 and dup > 0 and err == 0:
                status_text = (
                    f"NF-e já importada: {dup} | "
                    "Nenhuma nova entrada realizada"
                )
                log_level = "ATENÇÃO"
                log_reason = (
                    f"{dup} NF-e já havia(m) sido importada(s) anteriormente. "
                    "Nenhuma nova entrada de estoque e nenhuma nova movimentação foram criadas."
                )
                log_action = (
                    "Nenhuma ação necessária. A proteção contra duplicidade funcionou "
                    "e o(s) XML(s) foi(ram) movido(s) para a pasta duplicados."
                )
            else:
                status_text = (
                    f"Varredura concluída | Importadas: {ok} | "
                    f"Já importadas: {dup} | Erros: {err} | Itens: {itens}"
                )
                log_level = "ATENÇÃO" if err > 0 or dup > 0 else "OK"
                log_reason = (
                    f"Importadas: {ok} | Já importadas: {dup} | "
                    f"Erros: {err} | Itens lançados: {itens}."
                )
                log_action = (
                    "Consulte os detalhes abaixo. Arquivos foram separados em "
                    "processados, duplicados e erros conforme o resultado."
                )

            self.test_nfe_watch_status.set(status_text)

            detalhes = []
            for r in results:
                if r["status"] == "OK":
                    resultado_amigavel = "IMPORTADA"
                elif r["status"] == "DUPLICADA":
                    resultado_amigavel = "JÁ IMPORTADA - NENHUMA ALTERAÇÃO"
                else:
                    resultado_amigavel = "ERRO"

                detalhes.append(
                    f"{resultado_amigavel} | NF={r.get('num_nf') or '-'} | "
                    f"{r['arquivo']} | {r['detalhe']} | "
                    f"Destino={r.get('movido_para', '-')}"
                )

            self._write_test_user_log(
                log_level,
                "PROCESSAMENTO DA PASTA DE NF-e",
                log_reason,
                log_action,
                detalhes,
            )

            self.after(0, self._refresh_test_stock)
            self.after(0, self._refresh_test_moves)

            if show_message:
                messagebox.showinfo(
                    "Pasta de NF-e",
                    (
                        f"Arquivos encontrados: {len(results)}\n"
                        f"NF-e importadas: {ok}\n"
                        f"NF-e já importadas: {dup}\n"
                        f"Com erro: {err}\n"
                        f"Itens lançados: {itens}\n\n"
                        + (
                            "Nenhuma alteração foi realizada no estoque."
                            if ok == 0 and dup > 0 and err == 0
                            else ""
                        )
                    ),
                    parent=self,
                )

            return {
                "total": len(results),
                "ok": ok,
                "duplicadas": dup,
                "erros": err,
                "itens": itens,
            }

        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self.test_nfe_watch_status.set(
                f"Falha no processamento da pasta: {e}"
            )
            if show_message:
                messagebox.showerror(
                    "Pasta de NF-e",
                    f"Falha ao processar a pasta.\n\nDetalhe: {e}",
                    parent=self,
                )
            return {
                "total": 0,
                "ok": 0,
                "duplicadas": 0,
                "erros": 1,
                "itens": 0,
            }
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _process_nfe_watch_folder_now(self):
        self._save_nfe_watch_settings()
        folder = self.test_nfe_watch_dir.get().strip()
        self._write_test_user_log(
            "OK",
            "VARREDURA MANUAL DE NF-e",
            f"Usuário solicitou processamento imediato da pasta: {folder or '(não configurada)'}",
            "Os XMLs encontrados serão processados usando a mesma regra validada de entrada de estoque.",
        )
        self._process_nfe_watch_folder(show_message=True)

    def _nfe_watch_loop(self):
        while not self._nfe_watch_stop.is_set():
            try:
                if self._nfe_watch_enabled:
                    self._process_nfe_watch_folder(show_message=False)
            except Exception:
                pass

            # Verificação da pasta a cada 30 segundos.
            # O Event permite encerrar rapidamente ao clicar em Parar.
            self._nfe_watch_stop.wait(30)

    def _restore_nfe_watch_from_ini(self):
        """
        Restaura o estado PLAY salvo no config.ini.

        Se nfe_auto_import=yes e a pasta ainda existir, o monitor volta
        automaticamente sem exigir novo clique do usuário.
        """
        if not bool(self.test_nfe_watch_auto.get()):
            return

        folder = self.test_nfe_watch_dir.get().strip()
        if not folder or not os.path.isdir(folder):
            self.test_nfe_watch_auto.set(False)
            self._nfe_watch_enabled = False
            self._save_nfe_watch_settings()
            self.btn_nfe_watch_start.configure(state="normal")
            self.btn_nfe_watch_stop.configure(state="disabled")
            self.test_nfe_watch_status.set(
                "■ Monitoramento não restaurado — pasta configurada não está disponível."
            )
            self._write_test_user_log(
                "ATENÇÃO",
                "MONITOR DE NF-e NÃO RESTAURADO",
                "O monitor estava salvo como ativo, mas a pasta configurada não foi encontrada.",
                "Selecione novamente uma pasta válida e clique em ▶ Iniciar.",
                [f"Pasta configurada: {folder or '-'}"],
            )
            return

        self._nfe_watch_enabled = True
        self._nfe_watch_stop.clear()

        if (
            self._nfe_watch_thread is None
            or not self._nfe_watch_thread.is_alive()
        ):
            self._nfe_watch_thread = threading.Thread(
                target=self._nfe_watch_loop,
                name="NFeInputWatch",
                daemon=True,
            )
            self._nfe_watch_thread.start()

        self.btn_nfe_watch_start.configure(state="disabled")
        self.btn_nfe_watch_stop.configure(state="normal")
        self.test_nfe_watch_status.set(
            f"▶ MONITORANDO — restaurado automaticamente | Varredura: 30 s | {folder}"
        )

        self._write_test_user_log(
            "OK",
            "MONITOR DE NF-e RESTAURADO",
            "A aplicação foi aberta e restaurou automaticamente o monitor que estava em PLAY.",
            "A pasta continuará sendo verificada a cada 30 segundos.",
            [f"Pasta monitorada: {folder}"],
        )

        # Primeira varredura logo após restaurar.
        self.after(100, self._process_nfe_watch_folder_now_silent)

    def _start_nfe_watch(self):
        folder = self.test_nfe_watch_dir.get().strip()

        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(
                "Monitor de NF-e",
                "Selecione uma pasta válida antes de iniciar o monitoramento.",
                parent=self,
            )
            return

        self._nfe_watch_enabled = True
        self.test_nfe_watch_auto.set(True)
        self._nfe_watch_stop.clear()
        self._save_nfe_watch_settings()

        if (
            self._nfe_watch_thread is None
            or not self._nfe_watch_thread.is_alive()
        ):
            self._nfe_watch_thread = threading.Thread(
                target=self._nfe_watch_loop,
                name="NFeInputWatch",
                daemon=True,
            )
            self._nfe_watch_thread.start()

        self.btn_nfe_watch_start.configure(state="disabled")
        self.btn_nfe_watch_stop.configure(state="normal")
        self.test_nfe_watch_status.set(
            f"▶ MONITORANDO — aguardando XMLs em: {folder} | Varredura: 30 s"
        )

        self._write_test_user_log(
            "OK",
            "MONITOR DE NF-e INICIADO",
            f"Monitoramento automático iniciado na pasta: {folder}",
            "A aplicação fará uma primeira varredura agora e depois repetirá a cada 30 segundos.",
        )

        # Faz uma primeira varredura imediatamente ao clicar em Play.
        self.after(100, self._process_nfe_watch_folder_now_silent)

    def _process_nfe_watch_folder_now_silent(self):
        if self._nfe_watch_enabled:
            self._process_nfe_watch_folder(show_message=False)

    def _stop_nfe_watch(self):
        self._nfe_watch_enabled = False
        self.test_nfe_watch_auto.set(False)
        self._nfe_watch_stop.set()
        self._save_nfe_watch_settings()

        self.btn_nfe_watch_start.configure(state="normal")
        self.btn_nfe_watch_stop.configure(state="disabled")
        self.test_nfe_watch_status.set("■ Monitoramento parado.")

        self._write_test_user_log(
            "OK",
            "MONITOR DE NF-e PARADO",
            "Monitoramento automático da pasta de NF-e foi interrompido pelo usuário.",
            "Use '▶ Iniciar' para voltar a monitorar a pasta.",
        )

    def _toggle_nfe_watch(self):
        """Compatibilidade interna: direciona para os novos botões Play/Stop."""
        if self._nfe_watch_enabled:
            self._stop_nfe_watch()
        else:
            self._start_nfe_watch()


    def _ensure_test_movement_description_column(self, cur):
        """
        Valida somente a existência de DESCRICAO_ITEM em dbo.movEstambTeste.

        IMPORTANTE:
        - não cria coluna;
        - não altera estrutura do banco;
        - não executa UPDATE de movimentos antigos;
        - evita exigir permissão ALTER TABLE do usuário da aplicação.
        """
        cur.execute(
            "SELECT COL_LENGTH('dbo.movEstambTeste', 'DESCRICAO_ITEM')"
        )
        if cur.fetchone()[0] is None:
            raise RuntimeError(
                "A coluna dbo.movEstambTeste.DESCRICAO_ITEM não existe. "
                "Crie a coluna uma única vez com um usuário administrador do SQL Server."
            )


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

            # Exibe primeiro os itens mais recentemente incluídos/atualizados.
            # Não altera nenhum dado do estoque; muda somente a ordem visual da grade.
            normalized_columns = {
                re.sub(r"[^a-z0-9]", "", str(name).lower()): idx
                for idx, name in enumerate(columns)
            }
            data_idx = next(
                (
                    normalized_columns[k]
                    for k in (
                        "dataatualizacao",
                        "atualizacao",
                        "datahora",
                        "dtatualizacao",
                    )
                    if k in normalized_columns
                ),
                None,
            )
            if data_idx is not None:
                rows = sorted(
                    rows,
                    key=lambda r: (
                        r[data_idx] is not None,
                        r[data_idx] if r[data_idx] is not None else "",
                    ),
                    reverse=True,
                )

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

            # Após atualizar, mantém a grade posicionada no topo.
            tree.yview_moveto(0)

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
            # A estrutura da tabela é administrada no SQL Server.
            # Aqui apenas lemos os dados; nenhuma alteração estrutural é tentada.
            columns, rows = self._read_test_table("movEstambTeste")

            # Nome do cliente vem do banco local logConf, relacionando
            # Documento da movimentação com NumNF da conferência.
            clientes_por_documento = {}
            conn_local = None
            try:
                self.cfg = load_cfg()
                conn_local = pyodbc.connect(
                    build_conn_str(self.cfg),
                    timeout=5,
                )
                cur_local = conn_local.cursor()
                cur_local.execute(
                    """
                    SELECT NumNF, NomeCli
                    FROM dbo.logConf
                    """
                )
                for num_nf, nome_cli in cur_local.fetchall():
                    chave = str(num_nf or "").strip()
                    if chave and chave not in clientes_por_documento:
                        clientes_por_documento[chave] = str(nome_cli or "").strip()
            finally:
                if conn_local is not None:
                    conn_local.close()

            # Exibe primeiro as movimentações mais recentes.
            # Prioriza DATA_HORA e usa o ID como desempate quando existir.
            normalized_columns = {
                re.sub(r"[^a-z0-9]", "", str(name).lower()): idx
                for idx, name in enumerate(columns)
            }
            data_idx = next((normalized_columns[k] for k in (
                "datahora", "datamovimento", "dtmovimento", "data"
            ) if k in normalized_columns), None)
            id_idx = next((normalized_columns[k] for k in (
                "idmovimento", "idmov", "id"
            ) if k in normalized_columns), None)

            if data_idx is not None:
                rows = sorted(
                    rows,
                    key=lambda r: (
                        r[data_idx] is not None,
                        r[data_idx],
                        r[id_idx] if id_idx is not None and r[id_idx] is not None else 0,
                    ),
                    reverse=True,
                )
            elif id_idx is not None:
                rows = sorted(
                    rows,
                    key=lambda r: (r[id_idx] is not None, r[id_idx] or 0),
                    reverse=True,
                )

            for row in rows:
                m = dict(zip(columns, row))
                detalhe = self._column_value(
                    m, ["DETALHE", "Detalhe", "Mensagem", "Observacao", "Motivo"]
                )
                descricao = self._column_value(
                    m,
                    ["DESCRICAO_ITEM", "Descricao", "DescProd", "DescricaoProduto"],
                )
                if not descricao and detalhe:
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
                    clientes_por_documento.get(
                        str(self._column_value(
                            m, ["NUM_DOCUMENTO", "Documento", "NumDoc", "NumNota", "NF"]
                        ) or "").strip(),
                        "",
                    ),
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


    def _clear_logs_after_test_reset(self):
        """Limpa somente os logs quando o usuário optar por isso após o reset."""
        log_dir = self.cfg.get(
            "logging", "log_dir", fallback=r"C:\MIS\logs"
        ).strip() or r"C:\MIS\logs"

        cleared = 0
        errors = []

        try:
            os.makedirs(log_dir, exist_ok=True)
            for name in os.listdir(log_dir):
                path = os.path.join(log_dir, name)
                if os.path.isfile(path) and name.lower().endswith(".log"):
                    try:
                        with open(path, "w", encoding="utf-8"):
                            pass
                        cleared += 1
                    except Exception as exc:
                        errors.append(f"{name}: {exc}")
        except Exception as exc:
            errors.append(f"Pasta de logs: {exc}")

        # Nova primeira entrada após apagar o histórico.
        try:
            self._write_test_user_log(
                "OK",
                "AMBIENTE DE TESTES RESETADO E LOGS LIMPOS",
                "O usuário optou por apagar os logs após resetar o Ambiente de Testes.",
                "Configurações, conexões e pastas foram preservadas.",
                [f"Arquivos de log limpos: {cleared}"],
            )
        except Exception as exc:
            errors.append(f"Registro da limpeza: {exc}")

        try:
            self._refresh_status_tab()
        except Exception:
            pass

        if errors:
            messagebox.showwarning(
                "Limpeza de Logs",
                "O reset foi concluído, mas a limpeza dos logs foi parcial.\\n\\n"
                + "\\n".join(errors[:8]),
                parent=self,
            )

    def _add_context_help_buttons(self):
        """Adiciona um botão ? discreto no canto superior direito de cada aba."""
        tab_topics = [
            (self.tab_sql, "Banco Local logConf"),
            (self.tab_paths, "Pastas"),
            (self.tab_input, "Entrada (XML/TXT)"),
            (self.tab_app, "Aplicação"),
            (self.tab_output, "Arquivos de Saída"),
            (self.tab_connector, "Fonte de Dados Externa"),
            (self.tab_test_environment, "Ambiente de Testes"),
            (self.tab_status, "Status / Logs"),
            (self.tab_licensing_admin, "Licenciamento (Admin)"),
        ]

        for tab, topic in tab_topics:
            btn = ttk.Button(
                tab,
                text="?",
                width=3,
                command=lambda t=topic: self._open_help_topic(t),
            )
            # Posicionamento independente para não mexer no layout já validado.
            btn.place(relx=1.0, x=-12, y=8, anchor="ne")
            btn.lift()


    def _protect_secret_windows(self, value):
        """Protege um segredo com DPAPI do Windows e retorna Base64."""
        if not value:
            return ""

        import base64
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        raw = value.encode("utf-8")
        raw_buffer = ctypes.create_string_buffer(raw, len(raw))
        in_blob = DATA_BLOB(
            len(raw),
            ctypes.cast(raw_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        out_blob = DATA_BLOB()

        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "2A Tecnologia - Gestor de Dados",
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            raise ctypes.WinError()

        try:
            protected = ctypes.string_at(
                out_blob.pbData,
                out_blob.cbData,
            )
            return base64.b64encode(protected).decode("ascii")
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    def _unprotect_secret_windows(self, protected_b64):
        """Recupera um segredo protegido por DPAPI do Windows."""
        if not protected_b64:
            return ""

        import base64
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        try:
            protected = base64.b64decode(protected_b64)
        except Exception:
            return ""

        protected_buffer = ctypes.create_string_buffer(
            protected,
            len(protected),
        )
        in_blob = DATA_BLOB(
            len(protected),
            ctypes.cast(
                protected_buffer,
                ctypes.POINTER(ctypes.c_byte),
            ),
        )
        out_blob = DATA_BLOB()

        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            return ""

        try:
            raw = ctypes.string_at(
                out_blob.pbData,
                out_blob.cbData,
            )
            return raw.decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    def _build_licensing_admin_tab(self):
        """Área protegida para parâmetros do servidor de licenciamento."""

        # A aba cresceu e pode ultrapassar a altura útil em algumas resoluções.
        # Por isso, somente esta aba usa rolagem vertical, sem alterar as demais.
        scroll_host = ttk.Frame(self.tab_licensing_admin)
        scroll_host.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            scroll_host,
            highlightthickness=0,
            borderwidth=0,
        )
        vscroll = ttk.Scrollbar(
            scroll_host,
            orient="vertical",
            command=canvas.yview,
        )
        canvas.configure(yscrollcommand=vscroll.set)

        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        outer = ttk.Frame(canvas)
        canvas_window = canvas.create_window(
            (0, 0),
            window=outer,
            anchor="nw",
        )

        def _lic_admin_update_scrollregion(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _lic_admin_fit_width(event):
            canvas.itemconfigure(
                canvas_window,
                width=event.width,
            )

        outer.bind(
            "<Configure>",
            _lic_admin_update_scrollregion,
        )
        canvas.bind(
            "<Configure>",
            _lic_admin_fit_width,
        )

        # Mouse wheel funciona somente quando o cursor está nesta aba.
        def _lic_admin_mousewheel(event):
            canvas.yview_scroll(
                int(-1 * (event.delta / 120)),
                "units",
            )

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _lic_admin_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True, padx=12, pady=12)

        self.lic_admin_unlocked = False
        self.lic_admin_body = ttk.Frame(content)

        self.lic_admin_lock = ttk.LabelFrame(
            content,
            text="Área protegida",
        )
        self.lic_admin_lock.pack(fill="x", pady=(0, 10))

        ttk.Label(
            self.lic_admin_lock,
            text=(
                "Esta área contém configurações administrativas do licenciamento. "
                "O acesso exige a senha administrativa."
            ),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=10, pady=(10, 8))

        ttk.Button(
            self.lic_admin_lock,
            text="Desbloquear Configuração",
            command=self._unlock_licensing_admin,
        ).pack(anchor="w", padx=10, pady=(0, 10))

        # Variáveis dos parâmetros NÃO sensíveis.
        self.lic_ftp_host = tk.StringVar(
            value=self.cfg.get("licensing", "ftp_host", fallback="ftp.2atec.com.br").strip()
        )
        self.lic_ftp_port = tk.StringVar(
            value=self.cfg.get("licensing", "ftp_port", fallback="21").strip()
        )
        self.lic_ftp_user = tk.StringVar(
            value=self.cfg.get("licensing", "ftp_user", fallback="u300658511").strip()
        )
        self.lic_ftp_base_path = tk.StringVar(
            value=self.cfg.get("licensing", "ftp_base_path", fallback="/public_html/activate").strip()
        )

        # Migração da configuração administrativa.
        # A partir da versão 3, o SQL de licenciamento usa a instância
        # WIN-4LDPKMOC3M6\SQLEXPRESS e porta vazia.
        lic_cfg_version = int(
            self.cfg.get(
                "licensing",
                "config_version",
                fallback="1",
            )
            or "1"
        )

        if lic_cfg_version < 3:
            default_sql_server = r"WIN-4LDPKMOC3M6\SQLEXPRESS"
            default_sql_port = ""
            default_sql_database = "Suporte"
            default_sql_user = "logconf"
        else:
            default_sql_server = self.cfg.get(
                "licensing",
                "sql_server",
                fallback=r"WIN-4LDPKMOC3M6\SQLEXPRESS",
            ).strip()
            default_sql_port = self.cfg.get(
                "licensing",
                "sql_port",
                fallback="",
            ).strip()
            default_sql_database = self.cfg.get(
                "licensing",
                "sql_database",
                fallback="Suporte",
            ).strip()
            default_sql_user = self.cfg.get(
                "licensing",
                "sql_user",
                fallback="logconf",
            ).strip()

        self.lic_sql_driver = tk.StringVar(
            value=self.cfg.get(
                "licensing",
                "sql_driver",
                fallback="ODBC Driver 17 for SQL Server",
            ).strip()
        )

        self.lic_sql_server = tk.StringVar(
            value=default_sql_server
        )
        self.lic_sql_port = tk.StringVar(
            value=default_sql_port
        )
        self.lic_sql_license_database = tk.StringVar(
            value=self.cfg.get("licensing", "sql_license_database", fallback="demonstracao").strip()
        )
        self.lic_sql_support_database = tk.StringVar(
            value=self.cfg.get("licensing", "sql_support_database", fallback="Suporte").strip()
        )
        self.lic_sql_user = tk.StringVar(
            value=default_sql_user
        )
        self.lic_sql_license_table = tk.StringVar(
            value=self.cfg.get(
                "licensing",
                "sql_license_table",
                fallback="dbo.Demonstracao",
            ).strip()
        )
        self.lic_sql_support_table = tk.StringVar(
            value=self.cfg.get(
                "licensing",
                "sql_support_table",
                fallback="dbo.ExpSuporte",
            ).strip()
        )

        # Senhas persistidas com DPAPI: nunca em texto aberto no config.ini.
        self.lic_ftp_password = tk.StringVar(
            value=self._unprotect_secret_windows(
                self.cfg.get(
                    "licensing",
                    "ftp_password_dpapi",
                    fallback="",
                )
            )
        )
        saved_sql_secret = self._unprotect_secret_windows(
            self.cfg.get(
                "licensing",
                "sql_password_dpapi",
                fallback="",
            )
        )
        if not saved_sql_secret:
            # Migração segura: reutiliza apenas em memória a senha já existente
            # na seção [sql]. Ao clicar Salvar Configuração, ela passa a ficar
            # protegida por DPAPI na seção [licensing].
            saved_sql_secret = self.cfg.get(
                "sql",
                "password",
                fallback="",
            )

        self.lic_sql_password = tk.StringVar(
            value=saved_sql_secret
        )
        self.lic_ftp_test_status = tk.StringVar(
            value=self.cfg.get(
                "licensing",
                "ftp_last_status",
                fallback="Não testado",
            )
        )
        self.lic_sql_test_status = tk.StringVar(
            value=self.cfg.get(
                "licensing",
                "sql_last_status",
                fallback="Não testado",
            )
        )

        ftp = ttk.LabelFrame(self.lic_admin_body, text="Servidor FTP de Licenciamento")
        ftp.pack(fill="x", pady=(0, 10))
        ftp.columnconfigure(1, weight=1)

        self._lic_admin_field(ftp, "Servidor", self.lic_ftp_host, 0)
        self._lic_admin_field(ftp, "Porta", self.lic_ftp_port, 1, width=12)
        self._lic_admin_field(ftp, "Usuário", self.lic_ftp_user, 2)
        self._lic_admin_field(ftp, "Senha", self.lic_ftp_password, 3, show="*")
        self._lic_admin_field(ftp, "Pasta base", self.lic_ftp_base_path, 4)
        ftp_actions = ttk.Frame(ftp)
        ftp_actions.grid(row=5, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 10))
        ttk.Button(
            ftp_actions,
            text="Testar FTP",
            command=self._test_licensing_ftp,
        ).pack(side="left")
        ttk.Label(
            ftp_actions,
            textvariable=self.lic_ftp_test_status,
        ).pack(side="left", padx=(10, 0))

        sql = ttk.LabelFrame(
            self.lic_admin_body,
            text="SQL Server - Licenciamento e Suporte",
        )
        sql.pack(fill="x", pady=(0, 10))
        sql.columnconfigure(1, weight=1)

        ttk.Label(sql, text="Driver ODBC").grid(
            row=0, column=0, sticky="w", padx=10, pady=5
        )
        installed_sql_drivers = [
            d for d in pyodbc.drivers()
            if "SQL Server" in d
        ]
        self.lic_sql_driver_combo = ttk.Combobox(
            sql,
            textvariable=self.lic_sql_driver,
            values=installed_sql_drivers,
            width=45,
            state="readonly",
        )
        self.lic_sql_driver_combo.grid(
            row=0, column=1, sticky="w", padx=(0, 10), pady=5
        )

        self._lic_admin_field(sql, "Servidor", self.lic_sql_server, 1)
        self._lic_admin_field(sql, "Porta", self.lic_sql_port, 2, width=12)
        self._lic_admin_field(sql, "Usuário", self.lic_sql_user, 3)
        self._lic_admin_field(sql, "Senha", self.lic_sql_password, 4, show="*")

        self._lic_admin_field(
            sql,
            "Banco da Licença",
            self.lic_sql_license_database,
            5,
        )
        self._lic_admin_field(
            sql,
            "Tabela de Licença",
            self.lic_sql_license_table,
            6,
        )

        self._lic_admin_field(
            sql,
            "Banco do Suporte",
            self.lic_sql_support_database,
            7,
        )
        self._lic_admin_field(
            sql,
            "Tabela de Suporte",
            self.lic_sql_support_table,
            8,
        )

        sql_actions = ttk.Frame(sql)
        sql_actions.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="w",
            padx=10,
            pady=(8, 10),
        )
        ttk.Button(
            sql_actions,
            text="Testar SQL",
            command=self._test_licensing_sql,
        ).pack(side="left")
        ttk.Label(
            sql_actions,
            textvariable=self.lic_sql_test_status,
        ).pack(side="left", padx=(10, 0))

        note = ttk.LabelFrame(self.lic_admin_body, text="Segurança")
        note.pack(fill="x", pady=(0, 10))
        ttk.Label(
            note,
            text=(
                "Servidor, porta, usuário, caminhos, banco e tabelas são salvos na configuração. "
                "As senhas são protegidas pelo Windows (DPAPI) e nunca ficam em texto aberto. "
                "O caminho da licença usa: pasta base / 9 primeiros caracteres / licence12.lic."
            ),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", padx=10, pady=10)

        actions = ttk.Frame(self.lic_admin_body)
        actions.pack(fill="x")
        ttk.Button(
            actions,
            text="Salvar Configuração",
            command=self._save_licensing_admin_settings,
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Bloquear",
            command=self._lock_licensing_admin,
        ).pack(side="left", padx=(8, 0))

    def _lic_admin_field(self, parent, label, variable, row, width=48, show=None):
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=10, pady=5
        )
        ttk.Entry(
            parent,
            textvariable=variable,
            width=width,
            show=show,
        ).grid(
            row=row, column=1, sticky="w", padx=(0, 10), pady=5
        )

    def _admin_password_hash(self, password, salt_hex):
        import hashlib
        salt = bytes.fromhex(salt_hex)
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            200000,
        ).hex()

    def _unlock_licensing_admin(self):
        """
        No primeiro acesso, permite criar a senha administrativa.
        Depois, somente essa senha desbloqueia a área.
        A senha não é salva; apenas salt + hash ficam no config.ini.
        """
        import os as _os
        from tkinter import simpledialog

        cfg = load_cfg()
        if not cfg.has_section("licensing_admin"):
            cfg.add_section("licensing_admin")

        salt_hex = cfg.get("licensing_admin", "salt", fallback="").strip()
        saved_hash = cfg.get("licensing_admin", "password_hash", fallback="").strip()

        if not salt_hex or not saved_hash:
            p1 = simpledialog.askstring(
                "Criar Senha Administrativa",
                "Primeiro acesso.\n\nCrie a senha exclusiva da área de licenciamento:",
                show="*",
                parent=self,
            )
            if not p1:
                return
            p2 = simpledialog.askstring(
                "Confirmar Senha",
                "Digite novamente a senha administrativa:",
                show="*",
                parent=self,
            )
            if p1 != p2:
                messagebox.showerror(
                    "Senha Administrativa",
                    "As senhas não conferem.",
                    parent=self,
                )
                return

            salt_hex = _os.urandom(16).hex()
            saved_hash = self._admin_password_hash(p1, salt_hex)
            cfg.set("licensing_admin", "salt", salt_hex)
            cfg.set("licensing_admin", "password_hash", saved_hash)
            save_cfg(cfg)
            self.cfg = cfg
        else:
            password = simpledialog.askstring(
                "Licenciamento (Admin)",
                "Digite a senha administrativa:",
                show="*",
                parent=self,
            )
            if password is None:
                return

            informed = self._admin_password_hash(password, salt_hex)
            import hmac
            if not hmac.compare_digest(informed, saved_hash):
                messagebox.showerror(
                    "Acesso negado",
                    "Senha administrativa inválida.",
                    parent=self,
                )
                return

        self.lic_admin_unlocked = True
        self.lic_admin_lock.pack_forget()
        self.lic_admin_body.pack(fill="both", expand=True)

    def _lock_licensing_admin(self):
        self.lic_admin_unlocked = False
        self.lic_admin_body.pack_forget()
        self.lic_admin_lock.pack(fill="x", pady=(0, 10))


    def _save_licensing_last_status(self, key, value):
        """Persiste o último resultado conhecido de FTP/SQL da área Admin."""
        try:
            cfg = load_cfg()
            if not cfg.has_section("licensing"):
                cfg.add_section("licensing")
            cfg.set("licensing", key, value)
            save_cfg(cfg)
            self.cfg = cfg
        except Exception:
            pass

    def _test_licensing_ftp(self):
        """Testa somente conexão e acesso à pasta-base do FTP."""
        host = self.lic_ftp_host.get().strip()
        user = self.lic_ftp_user.get().strip()
        password = self.lic_ftp_password.get()
        base_path = self.lic_ftp_base_path.get().strip() or "/"
        try:
            port = int(self.lic_ftp_port.get().strip() or "21")
        except Exception:
            messagebox.showerror(
                "Testar FTP",
                "Porta FTP inválida.",
                parent=self,
            )
            return

        if not host or not user or not password:
            messagebox.showwarning(
                "Testar FTP",
                "Informe servidor, usuário e senha antes de testar.",
                parent=self,
            )
            return

        self.lic_ftp_test_status.set("Testando...")
        self.update_idletasks()

        ftp = None
        try:
            from ftplib import FTP

            ftp = FTP()
            ftp.connect(host=host, port=port, timeout=10)
            ftp.login(user=user, passwd=password)
            ftp.set_pasv(True)

            if base_path:
                ftp.cwd(base_path)

            current_dir = ftp.pwd()
            self.lic_ftp_test_status.set("Conectado")
            self._save_licensing_last_status("ftp_last_status", "Conectado")
            messagebox.showinfo(
                "Testar FTP",
                "Conexão FTP realizada com sucesso.\n\n"
                f"Pasta acessada: {current_dir}",
                parent=self,
            )
        except Exception as exc:
            self.lic_ftp_test_status.set("Falha")
            self._save_licensing_last_status("ftp_last_status", "Falha")
            messagebox.showerror(
                "Testar FTP",
                "Não foi possível conectar/acessar o FTP.\n\n"
                f"Detalhe: {exc}",
                parent=self,
            )
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    try:
                        ftp.close()
                    except Exception:
                        pass

    def _test_licensing_sql(self):
        """Testa o SQL central nos bancos de licença e suporte."""
        driver = self.lic_sql_driver.get().strip()
        server = self.lic_sql_server.get().strip()
        port = self.lic_sql_port.get().strip()
        user = self.lic_sql_user.get().strip()
        password = self.lic_sql_password.get()

        license_database = (
            self.lic_sql_license_database.get().strip()
            or "demonstracao"
        )
        support_database = (
            self.lic_sql_support_database.get().strip()
            or "Suporte"
        )

        license_table = (
            self.lic_sql_license_table.get().strip()
            or "dbo.Demonstracao"
        )
        support_table = (
            self.lic_sql_support_table.get().strip()
            or "dbo.ExpSuporte"
        )

        if not driver or not server or not user or not password:
            messagebox.showwarning(
                "Testar SQL",
                "Informe Driver ODBC, servidor, usuário e senha antes de testar.",
                parent=self,
            )
            return

        self.lic_sql_test_status.set("Testando...")
        self.update_idletasks()

        installed = pyodbc.drivers()
        if driver not in installed:
            self.lic_sql_test_status.set("Falha")
            self._save_licensing_last_status("sql_last_status", "Falha")
            messagebox.showerror(
                "Testar SQL",
                f"Driver ODBC não instalado nesta máquina:\n{driver}",
                parent=self,
            )
            return

        server_value = server
        if (
            port
            and "," not in server_value
            and "\\" not in server_value
        ):
            server_value = f"{server_value},{port}"

        def safe_table_name(value):
            cleaned = (
                value.replace("[", "")
                .replace("]", "")
                .strip()
            )
            if "." not in cleaned:
                cleaned = "dbo." + cleaned

            parts = cleaned.split(".")
            if (
                len(parts) != 2
                or not all(
                    part.replace("_", "").isalnum()
                    for part in parts
                )
            ):
                raise RuntimeError(
                    f"Nome de tabela inválido: {value}"
                )
            return cleaned

        safe_license = safe_table_name(license_table)
        safe_support = safe_table_name(support_table)

        def test_database(database, table):
            conn = None
            try:
                conn_str = (
                    f"DRIVER={{{driver}}};"
                    f"SERVER={server_value};"
                    f"DATABASE={database};"
                    f"UID={user};"
                    f"PWD={password};"
                    "TrustServerCertificate=yes;"
                )

                conn = pyodbc.connect(
                    conn_str,
                    timeout=8,
                )

                cur = conn.cursor()
                cur.execute(
                    f"SELECT TOP 1 * FROM {table}"
                )
                cur.fetchone()
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

        try:
            # Valida primeiro o banco/tabela da licença.
            test_database(
                license_database,
                safe_license,
            )

            # Depois valida o banco/tabela do suporte.
            test_database(
                support_database,
                safe_support,
            )

            self.lic_sql_test_status.set("Conectado")
            self._save_licensing_last_status("sql_last_status", "Conectado")
            messagebox.showinfo(
                "Testar SQL",
                "Conexão SQL realizada com sucesso.\n\n"
                f"Licença: {license_database}.{safe_license}\n"
                f"Suporte: {support_database}.{safe_support}",
                parent=self,
            )

        except Exception as exc:
            self.lic_sql_test_status.set("Falha")
            self._save_licensing_last_status("sql_last_status", "Falha")
            messagebox.showerror(
                "Testar SQL",
                "Não foi possível conectar ou consultar o SQL de licenciamento.\n\n"
                f"Detalhe: {exc}",
                parent=self,
            )

    def _save_licensing_admin_settings(self):
        if not self.lic_admin_unlocked:
            return

        cfg = load_cfg()
        if not cfg.has_section("licensing"):
            cfg.add_section("licensing")

        values = {
            "config_version": "3",
            "ftp_host": self.lic_ftp_host.get().strip(),
            "ftp_port": self.lic_ftp_port.get().strip() or "21",
            "ftp_user": self.lic_ftp_user.get().strip(),
            "ftp_base_path": (
                self.lic_ftp_base_path.get().strip()
                or "/public_html/activate"
            ),
            "sql_driver": self.lic_sql_driver.get().strip(),
            "sql_server": self.lic_sql_server.get().strip(),
            "sql_port": self.lic_sql_port.get().strip(),
            "sql_license_database": (
                self.lic_sql_license_database.get().strip()
                or "demonstracao"
            ),
            "sql_support_database": (
                self.lic_sql_support_database.get().strip()
                or "Suporte"
            ),
            "sql_user": self.lic_sql_user.get().strip(),
            "sql_license_table": (
                self.lic_sql_license_table.get().strip()
                or "dbo.Demonstracao"
            ),
            "sql_support_table": (
                self.lic_sql_support_table.get().strip()
                or "dbo.ExpSuporte"
            ),
        }

        for key, value in values.items():
            cfg.set("licensing", key, value)

        cfg.set(
            "licensing",
            "ftp_password_dpapi",
            self._protect_secret_windows(
                self.lic_ftp_password.get()
            ),
        )
        cfg.set(
            "licensing",
            "sql_password_dpapi",
            self._protect_secret_windows(
                self.lic_sql_password.get()
            ),
        )

        # Remove qualquer chave antiga/insegura.
        for old_key in (
            "ftp_password",
            "sql_password",
            "sql_trusted_connection",
            "sql_database",
            "sql_table",
            "license_filename",
        ):
            if cfg.has_option("licensing", old_key):
                cfg.remove_option("licensing", old_key)

        save_cfg(cfg)
        self.cfg = cfg

        messagebox.showinfo(
            "Licenciamento (Admin)",
            "Configuração salva com sucesso.\n\n"
            "FTP e SQL serão restaurados exatamente como foram salvos na próxima abertura.\n"
            "As senhas foram protegidas pelo Windows.",
            parent=self,
        )


    def _build_help_tab(self):
        """Ajuda local e objetiva sobre cada área do Gestor de Dados."""
        container = ttk.Frame(self.tab_help)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Label(
            container,
            text="Ajuda do Gestor de Dados",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", pady=(0, 4))

        ttk.Label(
            container,
            text=(
                "Selecione uma área à esquerda para ver uma explicação rápida "
                "sobre sua finalidade e os principais recursos."
            ),
        ).pack(anchor="w", pady=(0, 10))

        body = ttk.Frame(container)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=(0, 10))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        self.help_topics = {
            "Banco Local logConf": (
                "BANCO LOCAL logConf\n\n"
                "Configura a conexão com o banco SQL utilizado pelo sistema principal.\n\n"
                "• Driver ODBC: driver instalado no Windows para acesso ao SQL Server.\n"
                "• Servidor: endereço, nome da máquina ou instância do SQL Server.\n"
                "• Banco: banco local utilizado pelo sistema.\n"
                "• Autenticação: pode utilizar usuário/senha SQL ou autenticação do Windows.\n"
                "• Testar conexão: confirma se os parâmetros informados permitem acesso ao banco.\n\n"
                "Alterações nesta área afetam somente a conexão com o banco local."
            ),
            "Pastas": (
                "PASTAS\n\n"
                "Define os diretórios utilizados pelo importador para receber e organizar arquivos.\n\n"
                "• Entrada: pasta monitorada pelo importador.\n"
                "• Processados: arquivos concluídos com sucesso.\n"
                "• Erros: arquivos que não puderam ser processados.\n"
                "• Duplicados: arquivos reconhecidos como repetidos.\n"
                "• Pasta de logs: local onde ficam os registros da aplicação.\n\n"
                "Evite alterar essas pastas durante uma operação em andamento."
            ),
            "Entrada (XML/TXT)": (
                "ENTRADA (XML/TXT)\n\n"
                "Define o formato dos arquivos recebidos pelo fluxo principal.\n\n"
                "• Formato XML/TXT: escolha conforme o tipo de arquivo utilizado.\n"
                "• Delimitador: separador usado em arquivos TXT.\n"
                "• Encoding: codificação do arquivo.\n"
                "• Primeira linha é cabeçalho: indica se o TXT possui nomes de colunas.\n\n"
                "Essas opções pertencem ao fluxo principal de importação."
            ),
            "Aplicação": (
                "APLICAÇÃO\n\n"
                "Contém parâmetros gerais de funcionamento do importador.\n\n"
                "• Status inicial: estado atribuído ao registro quando aplicável.\n"
                "• Agrupar itens iguais: soma itens repetidos antes da gravação, quando ativado.\n\n"
                "Altere somente quando souber qual comportamento deseja aplicar ao fluxo principal."
            ),
            "Arquivos de Saída": (
                "ARQUIVOS DE SAÍDA\n\n"
                "Controla os arquivos gerados pelo sistema após as conferências.\n\n"
                "• Pasta de saída: local onde os arquivos serão gravados.\n"
                "• Campos a exportar: define quais informações serão incluídas.\n"
                "• Arquivo individual: gera um arquivo por conferência.\n"
                "• Arquivo diário: mantém um arquivo acumulado do dia.\n"
                "• Separador e nome do arquivo: ajustam o formato final.\n\n"
                "Essas opções não alteram os dados já gravados no banco."
            ),
            "Fonte de Dados Externa": (
                "FONTE DE DADOS EXTERNA\n\n"
                "Configura o banco do ERP externo usado para simular e realizar lançamentos de estoque.\n\n"
                "• Nova conexão: inicia o assistente para cadastrar uma fonte externa.\n"
                "• Editar: altera os dados da conexão atual.\n"
                "• Excluir: remove a configuração externa.\n"
                "• Testar conexão: verifica o acesso ao banco informado.\n\n"
                "O controle de execução dessa integração é independente do importador principal."
            ),
            "Ambiente de Testes": (
                "AMBIENTE DE TESTES\n\n"
                "Área isolada para validar entradas e movimentações de estoque sem utilizar o estoque real do ERP.\n\n"
                "• Resetar Ambiente: limpa os dados de teste e prepara um novo cenário. Após o reset, pergunta se deseja apagar também os logs.\n"
                "• Carregar Banco de Exemplo: restaura o estoque de exemplo.\n"
                "• Importar Estoque: carrega um TXT/CSV de estoque.\n"
                "• Importar 1 ou vários XMLs: realiza entradas de estoque por NF-e.\n"
                "• Pasta de NF-e de Entrada: define uma pasta para importação automática.\n"
                "• ▶ Iniciar: inicia o monitoramento da pasta a cada 30 segundos.\n"
                "• ■ Parar: interrompe somente o monitor de NF-e.\n"
                "• Processar agora: executa uma varredura imediata da pasta.\n"
                "• Estoque Atual: mostra a posição atual dos produtos.\n"
                "• Editar Saldo Manualmente: permite ajustar o saldo de um produto de teste.\n"
                "• Movimentações: mostra o histórico de entradas e ajustes.\n\n"
                "NF-e já importada não é lançada novamente. Produto existente recebe acréscimo no saldo; "
                "produto novo é cadastrado automaticamente."
            ),
            "Licenciamento (Admin)": (
                "LICENCIAMENTO (ADMIN)\n\n"
                "Área protegida para configurar o servidor FTP onde ficam os arquivos .lic "
                "e o SQL Server utilizado para controle central de licença e suporte.\n\n"
                "No primeiro acesso é criada uma senha administrativa exclusiva. "
                "Nas próximas vezes, essa senha será exigida para desbloquear a área.\n\n"
                "As senhas de FTP e SQL não são gravadas em texto aberto no config.ini.\n\n"
                "Use Testar FTP para validar o acesso ao servidor e à pasta-base. "
                "Use Testar SQL para validar o banco da licença (demonstracao/dbo.Demonstracao) e o banco do suporte (Suporte/dbo.ExpSuporte)."
            ),
            "Status / Logs": (
                "STATUS / LOGS\n\n"
                "Mostra o estado atual da aplicação e os registros gerados durante a operação.\n\n"
                "• Importador: indica se o processo principal está ativo.\n"
                "• SQL Server: mostra o estado da conexão.\n"
                "• Arquivos pendentes: quantidade de arquivos aguardando processamento.\n"
                "• Último resultado: última ação relevante registrada.\n"
                "• Log do Usuário: mensagens mais claras e orientadas à operação.\n"
                "• Log Técnico: detalhes utilizados para diagnóstico.\n\n"
                "Em caso de falha, consulte primeiro o Log do Usuário."
            ),
        }

        self.help_list = tk.Listbox(
            left,
            width=28,
            height=16,
            exportselection=False,
        )
        self.help_list.pack(fill="y", expand=False)

        for topic in self.help_topics:
            self.help_list.insert("end", topic)

        self.help_list.bind("<<ListboxSelect>>", self._on_help_topic_selected)

        text_frame = ttk.Frame(right)
        text_frame.pack(fill="both", expand=True)

        self.help_text = tk.Text(
            text_frame,
            wrap="word",
            state="disabled",
            relief="sunken",
            borderwidth=1,
            font=("Segoe UI", 10),
        )
        help_scroll = ttk.Scrollbar(
            text_frame,
            orient="vertical",
            command=self.help_text.yview,
        )
        self.help_text.configure(yscrollcommand=help_scroll.set)

        self.help_text.pack(side="left", fill="both", expand=True)
        help_scroll.pack(side="right", fill="y")

        # Abre a ajuda já no primeiro tópico.
        self.help_list.selection_set(0)
        self.help_list.activate(0)
        self._show_help_topic("Banco Local logConf")

    def _show_help_topic(self, topic):
        content = self.help_topics.get(topic, "")
        self.help_text.configure(state="normal")
        self.help_text.delete("1.0", "end")
        self.help_text.insert("1.0", content)
        self.help_text.configure(state="disabled")
        self.help_text.see("1.0")

    def _on_help_topic_selected(self, event=None):
        selection = self.help_list.curselection()
        if not selection:
            return
        topic = self.help_list.get(selection[0])
        self._show_help_topic(topic)

    def _open_help_topic(self, topic):
        """Abre a aba Ajuda já posicionada no assunto solicitado."""
        self.nb.select(self.tab_help)

        try:
            topics = list(self.help_topics.keys())
            idx = topics.index(topic)
        except Exception:
            idx = 0

        self.help_list.selection_clear(0, "end")
        self.help_list.selection_set(idx)
        self.help_list.activate(idx)
        self.help_list.see(idx)
        self._show_help_topic(topics[idx])

    def _open_context_help(self):
        """Abre a ajuda correspondente à aba atual."""
        current = self.nb.select()

        mapping = {
            str(self.tab_sql): "Banco Local logConf",
            str(self.tab_paths): "Pastas",
            str(self.tab_input): "Entrada (XML/TXT)",
            str(self.tab_app): "Aplicação",
            str(self.tab_output): "Arquivos de Saída",
            str(self.tab_connector): "Fonte de Dados Externa",
            str(self.tab_test_environment): "Ambiente de Testes",
            str(self.tab_status): "Status / Logs",
            str(self.tab_licensing_admin): "Licenciamento (Admin)",
        }

        # Demais abas são identificadas pelo texto da própria guia.
        topic = mapping.get(current)
        if topic is None:
            try:
                topic = self.nb.tab(current, "text")
            except Exception:
                topic = "Banco Local logConf"

        if topic not in self.help_topics:
            topic = "Banco Local logConf"

        self._open_help_topic(topic)

    def _write_local_license_state(self, status, support_code="", license_file=""):
        """Grava o estado local da licença em licenci.ini."""
        cfg = configparser.ConfigParser()
        cfg["licenca"] = {
            "status": status,
            "support_code": support_code,
            "license_file": license_file,
        }
        with open(LICENCI_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)

    def _read_local_license_state(self):
        """Lê licenci.ini e devolve o estado local da licença."""
        if not os.path.exists(LICENCI_PATH):
            return {
                "status": "Não ativada",
                "support_code": "",
                "license_file": "",
            }

        cfg = configparser.ConfigParser()
        try:
            cfg.read(LICENCI_PATH, encoding="utf-8")
            return {
                "status": cfg.get("licenca", "status", fallback="Não ativada").strip(),
                "support_code": cfg.get("licenca", "support_code", fallback="").strip(),
                "license_file": cfg.get("licenca", "license_file", fallback="").strip(),
            }
        except Exception:
            return {
                "status": "Não ativada",
                "support_code": "",
                "license_file": "",
            }

    def _restore_local_license_status(self):
        """
        Restaura o status visual da licença ao abrir o Config.
        O INI só vale para o mesmo Support Code e exige o .lic local.
        """
        state = self._read_local_license_state()
        current_support = self.support_code_var.get().strip()

        if (
            state.get("status") == "Licenciada"
            and state.get("support_code") == current_support
        ):
            license_name = state.get("license_file", "")
            local_license = (
                os.path.join(BASE_DIR, license_name)
                if license_name
                else ""
            )

            if local_license and os.path.isfile(local_license):
                self.license_status_var.set("Licenciada")
                try:
                    self._apply_license_ui_mode()
                except Exception:
                    pass
                return

        self.license_status_var.set("Não ativada")
        try:
            self._apply_license_ui_mode()
        except Exception:
            pass

    def _licensing_sql_connection(self, database):
        """Abre conexão no SQL central de licenciamento usando a configuração Admin."""
        driver = self.lic_sql_driver.get().strip()
        server = self.lic_sql_server.get().strip()
        port = self.lic_sql_port.get().strip()
        user = self.lic_sql_user.get().strip()
        password = self.lic_sql_password.get()

        if not driver or not server or not user or not password:
            raise RuntimeError("Configuração SQL de licenciamento incompleta.")

        server_value = server
        if port and "," not in server_value and "\\" not in server_value:
            server_value = f"{server_value},{port}"

        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server_value};"
            f"DATABASE={database};"
            f"UID={user};"
            f"PWD={password};"
            "TrustServerCertificate=yes;"
        )
        return pyodbc.connect(conn_str, timeout=8)

    def _safe_licensing_table(self, value, fallback):
        value = (value or fallback).replace("[", "").replace("]", "").strip()
        if "." not in value:
            value = "dbo." + value
        parts = value.split(".")
        if len(parts) != 2 or not all(
            part.replace("_", "").isalnum() for part in parts
        ):
            raise RuntimeError(f"Nome de tabela inválido: {value}")
        return value

    def _format_license_date(self, value):
        if value is None:
            return "-"
        try:
            if hasattr(value, "strftime"):
                return value.strftime("%d/%m/%Y")
        except Exception:
            pass

        raw = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                from datetime import datetime
                return datetime.strptime(raw[:10], fmt).strftime("%d/%m/%Y")
            except Exception:
                pass
        return raw

    def _delete_license_local_and_ftp(self):
        """
        Remove licence12.lic local e remoto.
        Também tenta remover a pasta dos 9 primeiros caracteres se ficar vazia.
        """
        from ftplib import FTP
        import posixpath

        support_code = self.support_code_var.get().strip()
        prefix = support_code[:9]

        # Local
        local_path = os.path.join(BASE_DIR, "licence12.lic")
        try:
            if os.path.isfile(local_path):
                os.remove(local_path)
        except Exception:
            pass

        # FTP
        ftp = None
        try:
            host = self.lic_ftp_host.get().strip()
            user = self.lic_ftp_user.get().strip()
            password = self.lic_ftp_password.get()
            port = int(self.lic_ftp_port.get().strip() or "21")
            base_path = (
                self.lic_ftp_base_path.get().strip()
                or "/public_html/activate"
            )

            if host and user and password:
                ftp = FTP()
                ftp.connect(host=host, port=port, timeout=12)
                ftp.login(user=user, passwd=password)
                ftp.set_pasv(True)

                remote_dir = posixpath.join(
                    base_path.rstrip("/"),
                    prefix,
                )
                ftp.cwd(remote_dir)

                try:
                    ftp.delete("licence12.lic")
                except Exception:
                    pass

                # Volta à pasta base e tenta remover a pasta do prefixo
                # somente se estiver vazia.
                try:
                    ftp.cwd(base_path.rstrip("/"))
                    ftp.rmd(prefix)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    try:
                        ftp.close()
                    except Exception:
                        pass

    def _revoke_current_license(self, display_status="Licença expirada"):
        """Invalida a licença local, remove o .lic e volta a exibir o botão Ativar."""
        support_code = self.support_code_var.get().strip()

        self._delete_license_local_and_ftp()
        self._write_local_license_state(
            display_status,
            support_code=support_code,
        )

        self.license_status_var.set(display_status)
        try:
            self.btn_activate_license.pack(side="left")
        except Exception:
            pass

        self._apply_license_ui_mode()

    def _refresh_license_support_status(self, silent=True):
        """
        Consulta os dois bancos centrais pelo Support Code/Serial.

        Demonstração:
          1 = período válido
          0/2 = período encerrado -> revoga a licença.

        Suporte:
          1 = suporte válido (verde)
          0/2 = suporte expirado (vermelho, sem revogar)
          3 = licença substituída/cancelada -> revoga a licença.
        """
        support_code = self.support_code_var.get().strip()
        if not support_code:
            return False

        license_db = (
            self.lic_sql_license_database.get().strip()
            or "demonstracao"
        )
        support_db = (
            self.lic_sql_support_database.get().strip()
            or "Suporte"
        )
        license_table = self._safe_licensing_table(
            self.lic_sql_license_table.get().strip(),
            "dbo.Demonstracao",
        )
        support_table = self._safe_licensing_table(
            self.lic_sql_support_table.get().strip(),
            "dbo.ExpSuporte",
        )

        license_row = None
        support_row = None

        # ----- Período de teste / locação
        conn = None
        try:
            conn = self._licensing_sql_connection(license_db)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT TOP 1 DataIni, DataFim, Status
                FROM {license_table}
                WHERE Serial = ?
                ORDER BY DataFim DESC
                """,
                support_code,
            )
            license_row = cur.fetchone()
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        # ----- Suporte
        conn = None
        try:
            conn = self._licensing_sql_connection(support_db)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT TOP 1 DataIni, DataFim, Status
                FROM {support_table}
                WHERE Serial = ?
                ORDER BY DataFim DESC
                """,
                support_code,
            )
            support_row = cur.fetchone()
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        # ----- Aplica licença / período
        if license_row:
            data_ini, data_fim, raw_status = license_row
            status = str(raw_status).strip()

            self.license_period_var.set(
                f"{self._format_license_date(data_ini)} a "
                f"{self._format_license_date(data_fim)}"
            )

            try:
                self.license_period_label.configure(
                    foreground=("green" if status == "1" else "red")
                )
            except Exception:
                pass

            if status == "1":
                # Só força Licenciada se o .lic local já foi validado.
                state = self._read_local_license_state()
                if (
                    state.get("status") == "Licenciada"
                    and state.get("support_code") == support_code
                    and state.get("license_file")
                    and os.path.isfile(
                        os.path.join(BASE_DIR, state.get("license_file"))
                    )
                ):
                    self.license_status_var.set("Licenciada")
                    try:
                        self.btn_activate_license.pack_forget()
                    except Exception:
                        pass
            elif status in {"0", "2"}:
                self._revoke_current_license("Licença expirada")

        # ----- Aplica suporte
        if support_row:
            sup_ini, sup_fim, raw_sup_status = support_row
            sup_status = str(raw_sup_status).strip()
            period = (
                f"{self._format_license_date(sup_ini)} a "
                f"{self._format_license_date(sup_fim)}"
            )
            self.support_period_var.set(period)

            if sup_status == "1":
                self.support_status_var.set("Suporte válido")
                color = "green"
            elif sup_status in {"0", "2"}:
                self.support_status_var.set("Suporte expirado")
                color = "red"
            elif sup_status == "3":
                self.support_status_var.set("Licença cancelada")
                color = "red"
                self._revoke_current_license("Não ativada")
            else:
                self.support_status_var.set(f"Status de suporte: {sup_status}")
                color = "black"

            try:
                self.support_status_label.configure(foreground=color)
                self.support_period_label.configure(foreground=color)
            except Exception:
                pass
        else:
            self.support_status_var.set("Não informado")
            self.support_period_var.set("Não informado")

        return True

    def _refresh_license_support_status_safe(self):
        try:
            self._refresh_license_support_status(silent=True)
        except Exception:
            # Nesta etapa, falha de internet/SQL não derruba a licença local.
            pass

    def _is_locally_licensed(self):
        """Valida o estado local mínimo: licenci.ini + Support Code + arquivo .lic local."""
        try:
            state = self._read_local_license_state()
            current_support = self.support_code_var.get().strip()

            if (
                state.get("status") != "Licenciada"
                or state.get("support_code") != current_support
            ):
                return False

            license_name = state.get("license_file", "").strip()
            if not license_name:
                return False

            return os.path.isfile(os.path.join(BASE_DIR, license_name))
        except Exception:
            return False

    def _apply_license_ui_mode(self):
        """
        Sem licença válida:
          - libera somente Sobre e Licenciamento (Admin)
          - desabilita todas as outras abas
          - exibe aviso de licenciamento

        Com licença válida:
          - libera todas as abas
          - oculta botão Ativar
          - remove aviso
        """
        try:
            licensed = (
                self.license_status_var.get().strip() == "Licenciada"
                and self._is_locally_licensed()
            )

            allowed = {
                str(self.tab_about),
                str(self.tab_licensing_admin),
            }

            for tab_id in self.nb.tabs():
                if licensed:
                    self.nb.tab(tab_id, state="normal")
                else:
                    self.nb.tab(
                        tab_id,
                        state=("normal" if tab_id in allowed else "disabled"),
                    )

            if licensed:
                try:
                    self.btn_activate_license.pack_forget()
                except Exception:
                    pass
                try:
                    self.license_required_var.set("")
                except Exception:
                    pass
            else:
                try:
                    self.btn_activate_license.pack(side="left")
                except Exception:
                    pass
                try:
                    self.license_required_var.set(
                        "Aplicação não licenciada. "
                        "Ative a licença para liberar os recursos."
                    )
                except Exception:
                    pass

                current = self.nb.select()
                if current not in allowed:
                    self.nb.select(self.tab_about)

        except Exception:
            pass

    def _build_about_tab(self):
        """Tela Sobre com a estrutura inicial do futuro licenciamento."""
        container = ttk.Frame(self.tab_about)
        container.pack(fill="both", expand=True, padx=18, pady=18)

        ttk.Label(
            container,
            text="Gestor de Dados - 2A Tecnologia",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            container,
            text="Importador e gerenciador de dados",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 16))

        info = ttk.LabelFrame(container, text="Informações da Aplicação")
        info.pack(fill="x", pady=(0, 12))

        ttk.Label(info, text="Versão:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4)
        )
        ttk.Label(info, text=APP_VERSION).grid(
            row=0, column=1, sticky="w", padx=10, pady=(10, 4)
        )

        ttk.Label(info, text="Build:").grid(
            row=1, column=0, sticky="w", padx=10, pady=4
        )
        ttk.Label(info, text=BUILD_DATE).grid(
            row=1, column=1, sticky="w", padx=10, pady=4
        )

        ttk.Label(info, text="Fornecedor:").grid(
            row=2, column=0, sticky="w", padx=10, pady=(4, 10)
        )
        ttk.Label(info, text="2A Tecnologia").grid(
            row=2, column=1, sticky="w", padx=10, pady=(4, 10)
        )

        license_box = ttk.LabelFrame(container, text="Licenciamento e Suporte")
        license_box.pack(fill="x", pady=(0, 12))
        license_box.columnconfigure(1, weight=1)

        ttk.Label(license_box, text="Código de Suporte:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 5)
        )

        self.support_code_var = tk.StringVar(value=self._get_support_code())
        support_entry = ttk.Entry(
            license_box,
            textvariable=self.support_code_var,
            state="readonly",
            width=28,
        )
        support_entry.grid(
            row=0, column=1, sticky="ew", padx=(0, 5), pady=(10, 5)
        )

        # Facilita o envio do Código de Suporte: botão de prancheta e
        # menu de contexto com o botão direito.
        ttk.Button(
            license_box,
            text="Copiar",
            width=7,
            command=self._copy_support_code,
        ).grid(row=0, column=2, sticky="w", padx=(0, 10), pady=(10, 5))

        self.support_code_menu = tk.Menu(self, tearoff=0)
        self.support_code_menu.add_command(
            label="Copiar Código de Suporte",
            command=self._copy_support_code,
        )
        support_entry.bind("<Button-3>", self._show_support_code_menu)

        ttk.Label(license_box, text="Status da Licença:").grid(
            row=1, column=0, sticky="w", padx=10, pady=5
        )
        self.license_status_var = tk.StringVar(value="Não ativada")
        self._restore_local_license_status()
        ttk.Label(
            license_box,
            textvariable=self.license_status_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=1, column=1, sticky="w", padx=(0, 10), pady=5)

        ttk.Label(license_box, text="Período válido:").grid(
            row=2, column=0, sticky="w", padx=10, pady=5
        )
        self.license_period_var = tk.StringVar(value="Não informado")
        self.license_period_label = tk.Label(
            license_box,
            textvariable=self.license_period_var,
            anchor="w",
        )
        self.license_period_label.grid(
            row=2, column=1, sticky="w", padx=(0, 10), pady=5
        )

        ttk.Label(license_box, text="Status do Suporte:").grid(
            row=3, column=0, sticky="w", padx=10, pady=5
        )
        self.support_status_var = tk.StringVar(value="Não informado")
        self.support_status_label = tk.Label(
            license_box,
            textvariable=self.support_status_var,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        self.support_status_label.grid(
            row=3, column=1, sticky="w", padx=(0, 10), pady=5
        )

        ttk.Label(license_box, text="Período do Suporte:").grid(
            row=4, column=0, sticky="w", padx=10, pady=5
        )
        self.support_period_var = tk.StringVar(value="Não informado")
        self.support_period_label = tk.Label(
            license_box,
            textvariable=self.support_period_var,
            anchor="w",
        )
        self.support_period_label.grid(
            row=4, column=1, sticky="w", padx=(0, 10), pady=5
        )

        buttons = ttk.Frame(license_box)
        buttons.grid(
            row=5, column=0, columnspan=2, sticky="w",
            padx=10, pady=(8, 12)
        )

        self.btn_activate_license = ttk.Button(
            buttons,
            text="Ativar Licença",
            command=self._activate_license_test,
        )
        self.btn_activate_license.pack(side="left")

        if self.license_status_var.get().strip() == "Licenciada":
            self.btn_activate_license.pack_forget()

        ttk.Label(
            license_box,
            text=(
                "A licença é vinculada ao Código de Suporte deste PC."
            ),
            wraplength=700,
        ).grid(
            row=6, column=0, columnspan=2,
            sticky="w", padx=10, pady=(0, 10)
        )

        ttk.Label(
            container,
            text="© 2026 2A Tecnologia. Todos os direitos reservados.",
        ).pack(anchor="w", pady=(8, 0))

        self.after(100, self._apply_license_ui_mode)

        # Atualiza período de licença e suporte após a construção da tela.
        self.after(250, self._refresh_license_support_status_safe)

    def _get_support_code(self):
        """
        Gera um Código de Suporte estável por máquina física.

        Prioridade:
        1. UUID do equipamento via Win32_ComputerSystemProduct.UUID
        2. Serial da BIOS
        3. Serial da placa-mãe
        4. MachineGuid do Windows apenas como último fallback

        Assim, uma simples reinicialização ou formatação do Windows não deve
        alterar o Código de Suporte quando o hardware principal permanece igual.
        """
        raw_parts = []

        def _run_powershell(command):
            try:
                result = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        command,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode != 0:
                    return ""
                return (result.stdout or "").strip()
            except Exception:
                return ""

        # 1) UUID físico do equipamento (firmware / placa-mãe)
        uuid_hw = _run_powershell(
            "(Get-CimInstance Win32_ComputerSystemProduct).UUID"
        )
        uuid_hw = uuid_hw.strip()

        invalid_uuid_values = {
            "",
            "00000000-0000-0000-0000-000000000000",
            "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
            "TO BE FILLED BY O.E.M.",
            "DEFAULT STRING",
            "NONE",
            "UNKNOWN",
        }

        if uuid_hw.upper() not in invalid_uuid_values:
            raw_parts.append("UUID=" + uuid_hw.upper())

        # 2) Serial da BIOS
        bios_serial = _run_powershell(
            "(Get-CimInstance Win32_BIOS).SerialNumber"
        ).strip()

        invalid_serial_values = {
            "",
            "TO BE FILLED BY O.E.M.",
            "DEFAULT STRING",
            "NONE",
            "UNKNOWN",
            "SYSTEM SERIAL NUMBER",
        }

        if bios_serial.upper() not in invalid_serial_values:
            raw_parts.append("BIOS=" + bios_serial.upper())

        # 3) Serial da placa-mãe
        board_serial = _run_powershell(
            "(Get-CimInstance Win32_BaseBoard).SerialNumber"
        ).strip()

        if board_serial.upper() not in invalid_serial_values:
            raw_parts.append("BOARD=" + board_serial.upper())

        # Se o UUID físico existe, ele é a principal âncora do código.
        # BIOS/BaseBoard entram junto para reduzir colisões em fabricantes ruins.
        if raw_parts:
            raw = "|".join(raw_parts)
        else:
            # 4) Último fallback: MachineGuid do Windows.
            # Esse valor pode mudar após formatação/reinstalação.
            raw = ""
            try:
                import winreg
                access = winreg.KEY_READ
                try:
                    access |= winreg.KEY_WOW64_64KEY
                except Exception:
                    pass

                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                    0,
                    access,
                ) as key:
                    raw = str(
                        winreg.QueryValueEx(key, "MachineGuid")[0]
                    ).strip()
            except Exception:
                pass

            if not raw:
                try:
                    import platform
                    raw = "|".join(
                        [
                            platform.node(),
                            platform.machine(),
                            platform.system(),
                        ]
                    )
                except Exception:
                    raw = "GESTOR-DADOS"

        import hashlib
        digest = hashlib.sha256(
            raw.encode("utf-8", errors="ignore")
        ).hexdigest().upper()

        # Código curto e fácil de informar.
        code = digest[:20]
        return "-".join(
            code[i:i + 5]
            for i in range(0, 20, 5)
        )

    def _copy_support_code(self):
        code = self.support_code_var.get().strip()
        if not code:
            return
        self.clipboard_clear()
        self.clipboard_append(code)
        self.update_idletasks()

    def _show_support_code_menu(self, event):
        try:
            self.support_code_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.support_code_menu.grab_release()


    def _parse_kalipso_symmetric_license(self, raw_bytes):
        """
        Formato definitivo gerado pelo Kalipso Encrypt Symmetric:
        - Data Type: Text UTF-16 LE
        - Result Encoding: None (Binary)
        - AES CBC PKCS5 Padding
        - 128 bit key
        - IV Provided
        - Append Result to IV = Yes

        O arquivo é gravado como UTF-16 LE. Os 16 primeiros caracteres
        representam o IV anexado; os caracteres seguintes representam,
        byte a byte, o ciphertext AES.
        """
        try:
            content = raw_bytes.decode("utf-16")
        except Exception:
            content = raw_bytes.decode("utf-16-le")

        content = content.lstrip("\ufeff")

        if len(content) < 32:
            raise RuntimeError(
                "Arquivo .lic incompatível com o novo formato de licença."
            )

        iv_text = content[:16]
        cipher_text = content[16:]

        try:
            iv = bytes(ord(ch) for ch in iv_text)
            cipher = bytes(ord(ch) for ch in cipher_text)
        except Exception as exc:
            raise RuntimeError(
                f"Não foi possível interpretar o conteúdo binário da licença: {exc}"
            )

        if len(iv) != 16:
            raise RuntimeError("IV inválido no arquivo .lic.")

        if not cipher or len(cipher) % 16 != 0:
            raise RuntimeError(
                "Ciphertext inválido: o tamanho não é múltiplo de 16 bytes."
            )

        return iv, cipher


    def _decrypt_kalipso_license_windows(self, iv, cipher, support_code):
        """Decrypt AES-128-CBC diretamente em Python."""
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives import padding
        except ImportError as exc:
            raise RuntimeError(
                "Biblioteca 'cryptography' não instalada. Execute: pip install cryptography"
            ) from exc

        license_key = b"2ATecLic2026Key!"

        if len(iv) != 16:
            raise RuntimeError(f"IV inválido: esperado 16 bytes, recebido {len(iv)}.")

        if not cipher or len(cipher) % 16 != 0:
            raise RuntimeError(
                "Ciphertext inválido: o tamanho precisa ser múltiplo de 16 bytes."
            )

        try:
            decryptor = Cipher(
                algorithms.AES(license_key),
                modes.CBC(iv),
            ).decryptor()

            padded_plain = decryptor.update(cipher) + decryptor.finalize()

            unpadder = padding.PKCS7(128).unpadder()
            plain_bytes = unpadder.update(padded_plain) + unpadder.finalize()

            plain = plain_bytes.decode("utf-16-le")
            plain = plain.lstrip("\ufeff").rstrip("\x00").strip()

        except Exception as exc:
            raise RuntimeError(
                f"Falha ao descriptografar a licença: {exc}"
            ) from exc

        if plain == support_code:
            return plain, "AES-128-CBC"

        return plain, (
            "SUPPORT_CODE_DIFERENTE | "
            f"Esperado={support_code!r} | "
            f"Obtido={plain!r} | "
            f"Tamanhos={len(support_code)}/{len(plain)}"
        )


    def _activate_license_test(self):
        from ftplib import FTP
        import os
        import posixpath

        support_code = self.support_code_var.get().strip()

        if not support_code:
            messagebox.showerror(
                "Ativar Licença",
                "Código de Suporte não disponível.",
                parent=self,
            )
            return

        prefix = support_code[:9]
        host = self.lic_ftp_host.get().strip()
        user = self.lic_ftp_user.get().strip()
        password = self.lic_ftp_password.get()
        base_path = self.lic_ftp_base_path.get().strip() or "/public_html/activate"

        try:
            port = int(self.lic_ftp_port.get().strip() or "21")
        except Exception:
            messagebox.showerror(
                "Ativar Licença",
                "Porta FTP inválida.",
                parent=self,
            )
            return

        if not host or not user or not password:
            messagebox.showwarning(
                "Ativar Licença",
                "Credenciais FTP incompletas. Confira Licenciamento (Admin).",
                parent=self,
            )
            return

        ftp = None

        try:
            self.license_status_var.set("Verificando licença...")
            self.update_idletasks()

            ftp = FTP()
            ftp.connect(host=host, port=port, timeout=12)
            ftp.login(user=user, passwd=password)
            ftp.set_pasv(True)

            remote_dir = posixpath.join(
                base_path.rstrip("/"),
                prefix,
            )
            ftp.cwd(remote_dir)

            remote_files = [
                os.path.basename(name)
                for name in ftp.nlst()
            ]

            # O servidor já teve as duas grafias em testes:
            # License12.lic e Licence12.lic.
            # Usa sempre o nome REAL devolvido pelo FTP, preservando maiúsculas/minúsculas.
            accepted_names = {
                "license12.lic",
                "licence12.lic",
            }

            exact_name = next(
                (
                    name
                    for name in remote_files
                    if name.lower() in accepted_names
                ),
                None,
            )

            if exact_name:
                lic_names = [exact_name]
            else:
                lic_names = []

            if not lic_names:
                self.license_status_var.set("Não ativada")
                try:
                    self.btn_activate_license.pack(side="left")
                except Exception:
                    pass

                self._write_local_license_state(
                    "Não ativada",
                    support_code=support_code,
                )
                self._apply_license_ui_mode()
                messagebox.showwarning(
                    "Ativar Licença",
                    "Licença não encontrada para este terminal.",
                    parent=self,
                )
                return

            last_detail = ""

            for remote_name in lic_names:
                chunks = []
                ftp.retrbinary(f"RETR {remote_name}", chunks.append)
                raw_file = b"".join(chunks)

                local_path = os.path.join(BASE_DIR, remote_name)
                with open(local_path, "wb") as f:
                    f.write(raw_file)

                try:
                    iv, cipher = self._parse_kalipso_symmetric_license(
                        raw_file
                    )
                    plain, method = self._decrypt_kalipso_license_windows(
                        iv,
                        cipher,
                        support_code,
                    )

                    if plain == support_code:
                        self.license_status_var.set("Licenciada")
                        try:
                            self.btn_activate_license.pack_forget()
                        except Exception:
                            pass

                        self._write_local_license_state(
                            "Licenciada",
                            support_code=support_code,
                            license_file=remote_name,
                        )

                        # Já traz período de teste/locação e suporte nesta ativação.
                        self._refresh_license_support_status_safe()

                        # Se o SQL central revogou a licença, não mostra sucesso.
                        if self.license_status_var.get().strip() != "Licenciada":
                            self._apply_license_ui_mode()
                            messagebox.showwarning(
                                "Ativar Licença",
                                "A licença foi localizada, porém o período não está válido.",
                                parent=self,
                            )
                            return

                        self._apply_license_ui_mode()

                        messagebox.showinfo(
                            "Ativar Licença",
                            "Licença ativada com sucesso neste PC.",
                            parent=self,
                        )
                        return

                    last_detail = method or "Decrypt não retornou o Código de Suporte."

                except Exception as exc:
                    last_detail = str(exc)

            self.license_status_var.set("Licença inválida")
            try:
                self.btn_activate_license.pack(side="left")
            except Exception:
                pass

            self._write_local_license_state(
                "Licença inválida",
                support_code=support_code,
            )
            self._apply_license_ui_mode()
            messagebox.showwarning(
                "Ativar Licença",
                "O arquivo .lic foi encontrado e baixado, mas o conteúdo "
                "descriptografado não corresponde ao Código de Suporte desta máquina.\n\n"
                f"Detalhe: {last_detail}",
                parent=self,
            )

        except Exception as exc:
            self.license_status_var.set("Não ativada")

            detail = str(exc).lower()

            # FTP 550 é o retorno normal quando a pasta da máquina
            # ou o arquivo de licença ainda não existe.
            if (
                "550" in detail
                or "no such file" in detail
                or "no such directory" in detail
                or "not found" in detail
            ):
                try:
                    self.btn_activate_license.pack(side="left")
                except Exception:
                    pass

                self._write_local_license_state(
                    "Não ativada",
                    support_code=support_code,
                )

                messagebox.showwarning(
                    "Ativar Licença",
                    "Licença não encontrada para este terminal.",
                    parent=self,
                )
            else:
                messagebox.showerror(
                    "Ativar Licença",
                    "Não foi possível concluir a ativação.\n\n"
                    f"Detalhe: {exc}",
                    parent=self,
                )
        finally:
            if ftp is not None:
                try:
                    ftp.quit()
                except Exception:
                    try:
                        ftp.close()
                    except Exception:
                        pass


    def _on_main_tab_changed(self, event=None):
        """Mantém o Config maximizado em todas as abas."""
        try:
            current = self.nb.select()

            if current == str(self.tab_connector):
                self.after(
                    100,
                    self._refresh_external_connection_status_silent,
                )

            try:
                if self.state() != "zoomed":
                    self.state("zoomed")
            except Exception:
                try:
                    self.attributes("-zoomed", True)
                except Exception:
                    pass

            self._test_env_maximized = True

        except Exception:
            pass


    def _select_initial_tab(self):
        initial = str(self.initial_tab).strip().lower()
        if initial == "status":
            self.nb.select(self.tab_status)
            self._refresh_status_tab()
        elif initial == "help":
            self.nb.select(self.tab_help)
            self.update_idletasks()
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
        # Importante: primeiro persiste se o monitor estava em PLAY ou STOP.
        # Só depois encerra a thread desta execução.
        try:
            self._save_nfe_watch_settings()
        except Exception:
            pass

        self._nfe_watch_enabled = False
        self._nfe_watch_stop.set()

        if self._save(show_message=False):
            self.destroy()


if __name__ == "__main__":
    app = ConfigUI()
    app.mainloop()
