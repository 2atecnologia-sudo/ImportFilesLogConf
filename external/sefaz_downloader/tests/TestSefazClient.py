from src.services.SefazClient import SefazClient

cliente = SefazClient()

cliente.conectar()

nsu = cliente.consultarUltimoNSU()

print()

print("Último NSU:", nsu)

cliente.desconectar()