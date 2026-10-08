import subprocess, configparser, os, base64
from pathlib import Path

class License:

    def _unprotect_secret_windows(self, protected_b64):
        """Recupera um segredo protegido por DPAPI do Windows."""
        if not protected_b64:
            return ''
        import base64
        import ctypes
        from ctypes import wintypes
    
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]
        try:
            protected = base64.b64decode(protected_b64)
        except Exception:
            return ''
        protected_buffer = ctypes.create_string_buffer(protected, len(protected))
        in_blob = DATA_BLOB(len(protected), ctypes.cast(protected_buffer, ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
            return ''
        try:
            raw = ctypes.string_at(out_blob.pbData, out_blob.cbData)
            return raw.decode('utf-8')
        finally:
            ctypes.windll.kernel32.LocalFree(out_blob.pbData)

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
                result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command], capture_output=True, text=True, timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode != 0:
                    return ''
                return (result.stdout or '').strip()
            except Exception:
                return ''
        uuid_hw = _run_powershell('(Get-CimInstance Win32_ComputerSystemProduct).UUID')
        uuid_hw = uuid_hw.strip()
        invalid_uuid_values = {'', '00000000-0000-0000-0000-000000000000', 'FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF', 'TO BE FILLED BY O.E.M.', 'DEFAULT STRING', 'NONE', 'UNKNOWN'}
        if uuid_hw.upper() not in invalid_uuid_values:
            raw_parts.append('UUID=' + uuid_hw.upper())
        bios_serial = _run_powershell('(Get-CimInstance Win32_BIOS).SerialNumber').strip()
        invalid_serial_values = {'', 'TO BE FILLED BY O.E.M.', 'DEFAULT STRING', 'NONE', 'UNKNOWN', 'SYSTEM SERIAL NUMBER'}
        if bios_serial.upper() not in invalid_serial_values:
            raw_parts.append('BIOS=' + bios_serial.upper())
        board_serial = _run_powershell('(Get-CimInstance Win32_BaseBoard).SerialNumber').strip()
        if board_serial.upper() not in invalid_serial_values:
            raw_parts.append('BOARD=' + board_serial.upper())
        if raw_parts:
            raw = '|'.join(raw_parts)
        else:
            raw = ''
            try:
                import winreg
                access = winreg.KEY_READ
                try:
                    access |= winreg.KEY_WOW64_64KEY
                except Exception:
                    pass
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\Microsoft\\Cryptography', 0, access) as key:
                    raw = str(winreg.QueryValueEx(key, 'MachineGuid')[0]).strip()
            except Exception:
                pass
            if not raw:
                try:
                    import platform
                    raw = '|'.join([platform.node(), platform.machine(), platform.system()])
                except Exception:
                    raw = 'GESTOR-DADOS'
        import hashlib
        digest = hashlib.sha256(raw.encode('utf-8', errors='ignore')).hexdigest().upper()
        code = digest[:20]
        return '-'.join((code[i:i + 5] for i in range(0, 20, 5)))

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
            content = raw_bytes.decode('utf-16')
        except Exception:
            content = raw_bytes.decode('utf-16-le')
        content = content.lstrip('\ufeff')
        if len(content) < 32:
            raise RuntimeError('Arquivo .lic incompatível com o novo formato de licença.')
        iv_text = content[:16]
        cipher_text = content[16:]
        try:
            iv = bytes((ord(ch) for ch in iv_text))
            cipher = bytes((ord(ch) for ch in cipher_text))
        except Exception as exc:
            raise RuntimeError(f'Não foi possível interpretar o conteúdo binário da licença: {exc}')
        if len(iv) != 16:
            raise RuntimeError('IV inválido no arquivo .lic.')
        if not cipher or len(cipher) % 16 != 0:
            raise RuntimeError('Ciphertext inválido: o tamanho não é múltiplo de 16 bytes.')
        return (iv, cipher)

    def _decrypt_kalipso_license_windows(self, iv, cipher, support_code):
        """Decrypt AES-128-CBC diretamente em Python."""
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives import padding
        except ImportError as exc:
            raise RuntimeError("Biblioteca 'cryptography' não instalada. Execute: pip install cryptography") from exc
        license_key = b'2ATecLic2026Key!'
        if len(iv) != 16:
            raise RuntimeError(f'IV inválido: esperado 16 bytes, recebido {len(iv)}.')
        if not cipher or len(cipher) % 16 != 0:
            raise RuntimeError('Ciphertext inválido: o tamanho precisa ser múltiplo de 16 bytes.')
        try:
            decryptor = Cipher(algorithms.AES(license_key), modes.CBC(iv)).decryptor()
            padded_plain = decryptor.update(cipher) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            plain_bytes = unpadder.update(padded_plain) + unpadder.finalize()
            plain = plain_bytes.decode('utf-16-le')
            plain = plain.lstrip('\ufeff').rstrip('\x00').strip()
        except Exception as exc:
            raise RuntimeError(f'Falha ao descriptografar a licença: {exc}') from exc
        if plain == support_code:
            return (plain, 'AES-128-CBC')
        return (plain, f'SUPPORT_CODE_DIFERENTE | Esperado={support_code!r} | Obtido={plain!r} | Tamanhos={len(support_code)}/{len(plain)}')

    def check(self, folder):
        folder = Path(folder)
        code = self._get_support_code()
        state = configparser.ConfigParser(interpolation=None)
        state.read(folder / 'licenci.ini', encoding='utf-8')
        if state.get('licenca', 'status', fallback='') != 'Licenciada':
            raise RuntimeError('Importador sem licença ativa. Ative a licença no ImportFilesLogConf para liberar a atualização.')
        if state.get('licenca', 'support_code', fallback='') != code:
            raise RuntimeError('A licença pertence a outro PC.')
        name = state.get('licenca', 'license_file', fallback='')
        if not name or Path(name).name != name:
            raise RuntimeError('Arquivo de licença inválido.')
        iv, cipher = self._parse_kalipso_symmetric_license((folder / name).read_bytes())
        plain, _ = self._decrypt_kalipso_license_windows(iv, cipher, code)
        if plain != code:
            raise RuntimeError('Licença incompatível com este PC.')
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(folder / 'config.ini', encoding='utf-8-sig')
        # Consulta central somente de leitura; nunca altera a licença do importador.
        period = 'Licença local validada'
        section = 'licensing'
        server = cfg.get(section, 'sql_server', fallback='')
        user = cfg.get(section, 'sql_user', fallback='')
        password = self._unprotect_secret_windows(cfg.get(section, 'sql_password_dpapi', fallback='')) or cfg.get('sql', 'password', fallback='')
        if server and user and password:
            import pyodbc
            database = cfg.get(section, 'sql_license_database', fallback='demonstracao')
            table = cfg.get(section, 'sql_license_table', fallback='dbo.Demonstracao')
            if not all(p.replace('_','').isalnum() for p in table.split('.')):
                raise RuntimeError('Tabela de licença inválida.')
            driver = cfg.get(section, 'sql_driver', fallback='ODBC Driver 18 for SQL Server')
            port = cfg.get(section, 'sql_port', fallback='')
            if port and ',' not in server and chr(92) not in server:
                server += ',' + port
            try:
                conn = pyodbc.connect(f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};UID={user};PWD={password};TrustServerCertificate=yes;', timeout=8)
            except pyodbc.Error:
                return code, period + ' • Servidor central indisponível'
            try:
                row = conn.cursor().execute(f'SELECT TOP 1 DataIni, DataFim, Status FROM {table} WHERE Serial = ? ORDER BY DataFim DESC', code).fetchone()
                if row and str(row[2]).strip() in {'0', '2', '3'}:
                    raise RuntimeError('Licença expirada ou cancelada no servidor central.')
                if row:
                    period = f'{row[0]} a {row[1]}'
                support_db = cfg.get(section, 'sql_support_database', fallback='Suporte')
                support_table = cfg.get(section, 'sql_support_table', fallback='dbo.ExpSuporte')
                if not all(p.replace('_','').isalnum() for p in support_table.split('.')) or not support_db.replace('_','').isalnum():
                    raise RuntimeError('Banco/tabela de suporte inválido.')
                support = conn.cursor().execute(f'SELECT TOP 1 Status FROM [{support_db}].{support_table} WHERE Serial = ? ORDER BY DataFim DESC', code).fetchone()
                if support and str(support[0]).strip() == '3':
                    raise RuntimeError('Licença cancelada no servidor central.')
            finally:
                conn.close()
        return code, period


