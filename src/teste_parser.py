from parser_txt import parse_txt_documents

d = parse_txt_documents(
    r"data\entrada\exemplo.txt",
    delimiter=",",
    encoding="utf-8",
    has_header=True,
    group_items=False
)

print("Documentos:", len(d))
print("Chaves:", list(d.keys()))
print("Itens no 100:", len(d["100"]["Itens"]))
print("Primeiro item:", d["100"]["Itens"][0])