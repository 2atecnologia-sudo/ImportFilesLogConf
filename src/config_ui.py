import os
import shutil
import configparser
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pyodbc
from PIL import Image, ImageTk

from .runtime_status import read_runtime_status

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

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
        self.title("ImportFiles LogConf")

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

        self.initial_tab = initial_tab

        self.cfg = load_cfg()

        self.vars = {}
        self.widgets = {}

        self._build()
        self._load_to_form()
        self._apply_states()
        self._select_initial_tab()

        # Atualiza a aba de Status/Logs periodicamente enquanto a janela estiver aberta.
        self.after(300, self._status_auto_refresh)

    def _build(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=10)

        tab_sql = ttk.Frame(self.nb)
        tab_paths = ttk.Frame(self.nb)
        tab_input = ttk.Frame(self.nb)
        tab_app = ttk.Frame(self.nb)
        tab_output = ttk.Frame(self.nb)
        self.tab_status = ttk.Frame(self.nb)

        self.nb.add(tab_sql, text="SQL Server")
        self.nb.add(tab_paths, text="Pastas")
        self.nb.add(tab_input, text="Entrada (XML/TXT)")
        self.nb.add(tab_app, text="Aplicação")
        self.nb.add(tab_output, text="Arquivos de Saída")
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

        # ---- Status / Logs
        self._build_status_tab()

        # ---- Sobre
        self._build_about_tab()

        # ---- Bottom
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(bottom, text="Salvar", command=self._save).pack(side="right")
        ttk.Button(bottom, text="Fechar", command=self.destroy).pack(side="right", padx=(0, 8))


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

        logs = ttk.LabelFrame(self.tab_status, text="Eventos recentes")
        logs.pack(fill="both", expand=True, padx=10, pady=6)

        self.log_text = tk.Text(
            logs,
            wrap="none",
            height=16,
            state="disabled",
            font=("Consolas", 9),
        )
        yscroll = ttk.Scrollbar(logs, orient="vertical", command=self.log_text.yview)
        xscroll = ttk.Scrollbar(logs, orient="horizontal", command=self.log_text.xview)
        self.log_text.configure(
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )

        self.log_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        logs.grid_rowconfigure(0, weight=1)
        logs.grid_columnconfigure(0, weight=1)

        actions = ttk.Frame(self.tab_status)
        actions.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(
            actions,
            text="Atualizar",
            command=self._refresh_status_tab,
        ).pack(side="left")

        ttk.Button(
            actions,
            text="Abrir pasta de logs",
            command=self._open_log_dir,
        ).pack(side="left", padx=(8, 0))

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
            text="Versão 1.0.0",
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

    def _select_initial_tab(self):
        if str(self.initial_tab).lower() == "status":
            self.nb.select(self.tab_status)
            self._refresh_status_tab()
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
        return os.path.join(log_dir, "importador.log")

    def _read_recent_events(self, max_lines=120):
        log_path = self._get_log_path()

        if not os.path.isfile(log_path):
            return ["Nenhum log encontrado ainda."]

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            interesting = []
            keywords = (
                "[ARQUIVO]",
                "[SYNC PENDENTE]",
                "[SYNC PAR DETECTADO]",
                "[SYNC][LOGCONF]",
                "[SYNC][PRODCONF]",
                "[SYNC VALIDACAO CONCLUIDA]",
                "[SIMULACAO][LOGCONF]",
                "[SIMULACAO][PRODCONF]",
                "[PREFLIGHT OK]",
                "[SYNC GRAVACAO OK]",
                "[SYNC ARQUIVOS PROCESSADOS]",
                "[SYNC][SQL PENDENTE]",
                "[SYNC ABORTADA]",
                "[REPROCESSAMENTO AUTOMATICO]",
                "Iniciando importador",
            )

            for line in lines:
                if any(k in line for k in keywords):
                    interesting.append(line.rstrip())

            return interesting[-max_lines:] or ["Nenhum evento relevante encontrado."]
        except Exception as e:
            return [f"Erro ao ler log: {e}"]

    def _last_result_from_log(self) -> str:
        lines = self._read_recent_events(max_lines=80)

        for line in reversed(lines):
            if "[SYNC GRAVACAO OK]" in line:
                return "Processamento concluído com COMMIT OK"
            if "[SYNC][SQL PENDENTE]" in line:
                return "SQL indisponível - arquivos preservados"
            if "[SYNC ABORTADA]" in line:
                return "Sincronização abortada - verificar log"
        return "-"

    def _refresh_status_tab(self):
        # Recarrega config para refletir qualquer alteração salva.
        self.cfg = load_cfg()
        runtime = read_runtime_status(BASE_DIR) or {}

        importer_ok = self._importer_rodando()
        estado = runtime.get("estado", "")

        self.status_vars["importer"].set(
            "RODANDO" if importer_ok else "PARADO"
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
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _status_auto_refresh(self):
        try:
            if hasattr(self, "nb") and hasattr(self, "tab_status"):
                if self.nb.select() == str(self.tab_status):
                    self._refresh_status_tab()
        finally:
            if self.winfo_exists():
                self.after(5000, self._status_auto_refresh)

    def _open_log_dir(self):
        log_dir = self.cfg.get(
            "logging",
            "log_dir",
            fallback=os.path.join(BASE_DIR, "logs"),
        ).strip()
        os.makedirs(log_dir, exist_ok=True)

        if os.name == "nt":
            os.startfile(log_dir)

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
                ("output", "output_dir"),
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