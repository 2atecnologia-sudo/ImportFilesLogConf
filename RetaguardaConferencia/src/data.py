import configparser
from contextlib import closing

def connection(folder):
    import pyodbc
    from pathlib import Path
    cfg=configparser.ConfigParser(interpolation=None)
    cfg.read(Path(folder)/'config.ini',encoding='utf-8-sig')
    s=cfg['sql']
    server=s.get('server','')
    port=s.get('port','')
    if port and ',' not in server and '\\' not in server: server+=','+port
    def quote(value): return '{'+str(value).replace('}','}}')+'}'
    text=f"DRIVER={quote(s.get('driver','ODBC Driver 18 for SQL Server'))};SERVER={quote(server)};DATABASE={quote(s.get('database',''))};TrustServerCertificate=yes;"
    if s.get('trusted_connection','no').lower() in ('yes','true','1'):
        text+='Trusted_Connection=yes;'
    else: text+=f"UID={quote(s.get('user',''))};PWD={quote(s.get('password',''))};"
    conn=pyodbc.connect(text,timeout=8)
    conn.timeout=30
    return conn

def rows(conn,table):
    cur=conn.cursor()
    cur.execute('SELECT * FROM dbo.'+table)
    cols=[c[0].lower() for c in cur.description]
    return [dict(zip(cols,r)) for r in cur.fetchall()]

def load(folder):
    with closing(connection(folder)) as conn:
        heads=rows(conn,'logConf')
        items=rows(conn,'prodConf')
        cur=conn.cursor()
        exists=cur.execute("SELECT OBJECT_ID('dbo.scanocorconf', 'U')").fetchone()[0]
        occurrences=rows(conn,'scanocorconf') if exists else []
        return heads,items,occurrences

def norm(value):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD',str(value or '').upper().strip()) if unicodedata.category(c)!='Mn')

def number(value):
    try: return float(value or 0)
    except (TypeError,ValueError): return 0

def document(value):
    from decimal import Decimal, InvalidOperation
    try: return str(int(Decimal(str(value))))
    except (InvalidOperation,ValueError,TypeError): return str(value or '').strip()

def related(header,items):
    doc=document(header.get('numnf'))
    process=norm(header.get('processo'))
    return [i for i in items if document(i.get('numdoc'))==doc and (norm(i.get('processo'))==process or not norm(i.get('processo')))]

def format_time(value):
    """Formata valores SQL TIME e HHMMSS legados sem alterar o banco."""
    from datetime import datetime,time
    from decimal import Decimal
    if value is None or str(value).strip()=='':return ''
    if isinstance(value,(datetime,time)):return value.strftime('%H:%M:%S')
    text=str(value).strip()
    if ':' in text:
        parts=text.split(':')
        try:
            hour=int(parts[0]);minute=int(parts[1]);second=int(float(parts[2])) if len(parts)==3 else 0
            return time(hour,minute,second).strftime('%H:%M:%S')
        except (ValueError,IndexError):return text
    try:
        raw=Decimal(text)
        if raw!=raw.to_integral_value() or raw<0:return text
        digits=str(int(raw)).zfill(6)
        if len(digits)!=6:return text
        return time(int(digits[:2]),int(digits[2:4]),int(digits[4:])).strftime('%H:%M:%S')
    except (ValueError,ArithmeticError):return text

def order_items(items):
    """Itens lidos primeiro; leitura mais recente antes, quando registrada."""
    from datetime import datetime
    def stamp(item):
        value=item.get('dataehora')
        if isinstance(value,datetime):return value.replace(tzinfo=None)
        text=str(value or '').strip()
        try:return datetime.fromisoformat(text).replace(tzinfo=None)
        except ValueError:pass
        for fmt in ('%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M','%Y%m%d%H%M%S'):
            try:return datetime.strptime(text,fmt)
            except ValueError:pass
        return datetime.min
    return sorted(items,key=lambda i:(number(i.get('qtdelido'))>0,stamp(i) if number(i.get('qtdelido'))>0 else datetime.min),reverse=True)

def item_totals(items):
    expected=sum(number(i.get('qtdedoc')) for i in items)
    read=sum(number(i.get('qtdelido')) for i in items)
    missing=sum(max(number(i.get('qtdedoc'))-number(i.get('qtdelido')),0) for i in items)
    return f'{len(items)} itens • Total esperado: {expected:g} • Total lido: {read:g} • Qtde restante: {missing:g}'
