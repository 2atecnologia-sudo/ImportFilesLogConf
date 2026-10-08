"""Usuários locais da retaguarda; senhas armazenadas por hash com salt."""
import hashlib
import hmac
import json
import os
from pathlib import Path


def password_record(password):
    if not password:raise ValueError('Informe uma senha.')
    salt=os.urandom(16).hex()
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),300000).hex()
    return {'salt':salt,'hash':digest}


class Users:
    def __init__(self,base):
        self.path=Path(base)/'usuarios.json'
        if not self.path.exists():self.save({'admin':{'role':'admin',**password_record('config')}})
    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8'))
    def save(self,users):
        temporary=self.path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(users,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,self.path)
    def authenticate(self,username,password):
        username=username.strip().lower();record=self.read().get(username)
        if not record:return None
        digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(record['salt']),300000).hex()
        return record['role'] if hmac.compare_digest(digest,record['hash']) else None
    def add(self,actor,username,password,role):
        users=self.read()
        if users.get(actor,{}).get('role')!='admin':raise ValueError('Apenas administradores podem cadastrar usuários.')
        username=username.strip().lower()
        if not username:raise ValueError('Informe o usuário.')
        if username in users:raise ValueError('Usuário já cadastrado.')
        if role not in ('admin','user'):raise ValueError('Perfil inválido.')
        users[username]={'role':role,**password_record(password)};self.save(users)
    def change_password(self,actor,username,password):
        users=self.read()
        if actor!=username and users.get(actor,{}).get('role')!='admin':raise ValueError('Você só pode alterar sua própria senha.')
        if username not in users:raise ValueError('Usuário não encontrado.')
        users[username].update(password_record(password));self.save(users)
