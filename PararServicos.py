import subprocess
import time

def parar_aplicativos():
    # Lista com os 4 executáveis que você quer fechar
    apps_para_parar = [
        "ImportFilesLogConfTray.exe",
        "ImportFilesLogConfImporter.exe",
        "SefazDownloader.exe",
        "ImportFilesLogConfConfig.exe"
    ]

    print("="*55)
    print(" ENCERRANDO APLICATIVOS 2ATEC ".center(55, "="))
    print("="*55 + "\n")

    for app in apps_para_parar:
        print(f"Procurando {app}...")
        try:
            # Comando taskkill do Windows:
            # /F = Forçar parada
            # /IM = Nome do arquivo (Image Name)
            # /T = Mata processos filhos também
            resultado = subprocess.run(
                ["taskkill", "/F", "/IM", app, "/T"],
                capture_output=True,
                text=True
            )
            
            # Se retornar 0, significa que achou o processo e o matou
            if resultado.returncode == 0:
                print(f" -> [ OK ] {app} encerrado com sucesso!\n")
            else:
                # Se não retornar 0, geralmente é porque o app já estava fechado
                print(f" -> [INFO] {app} não estava rodando.\n")
                
        except Exception as e:
            print(f" -> [ERRO] Falha ao tentar encerrar {app}. Detalhe: {e}\n")
    
    print("="*55)
    print("Processo de encerramento concluído!")
    print("="*55)

if __name__ == "__main__":
    parar_aplicativos()
    # Pausa de 4 segundos para você conseguir ler a tela preta antes dela sumir
    time.sleep(4)