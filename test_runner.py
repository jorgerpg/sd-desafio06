import subprocess
import re
import time
import pandas as pd
import matplotlib.pyplot as plt
import os

# ============================================================
# Configurações gerais
# ============================================================
NGINX_CONF = "nginx/nginx.conf"
MODES = ["round_robin", "least_conn", "ip_hash"]
RESULTS_DIR = "results"
AB_COMMAND = ["ab", "-n", "1000", "-c", "50", "http://localhost/"]

os.makedirs(RESULTS_DIR, exist_ok=True)

# ============================================================
# Funções auxiliares
# ============================================================

def set_nginx_mode(mode):
    """Altera o modo de balanceamento no nginx.conf."""
    with open(NGINX_CONF, "r") as f:
        conf = f.read()

    if mode == "round_robin":
        conf = re.sub(r"(least_conn;|ip_hash;)", "# \\1", conf)
    elif mode == "least_conn":
        conf = re.sub(r"upstream backend \{", "upstream backend {\n        least_conn;", conf)
        conf = conf.replace("ip_hash;", "# ip_hash;")
    elif mode == "ip_hash":
        conf = re.sub(r"upstream backend \{", "upstream backend {\n        ip_hash;", conf)
        conf = conf.replace("least_conn;", "# least_conn;")

    with open(NGINX_CONF, "w") as f:
        f.write(conf)

    # Reinicia o proxy
    subprocess.run(["docker", "exec", "sd-desafio06-proxy-1", "nginx", "-s", "reload"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f"[INFO] Nginx reiniciado com modo: {mode}")

def run_ab_test(mode):
    """Executa o ApacheBench e retorna tempo médio e throughput."""
    print(f"[TEST] Rodando modo {mode}...")
    result = subprocess.run(AB_COMMAND, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = result.stdout

    # Extrai dados do output
    requests_per_sec = re.search(r"Requests per second:\s+([\d\.]+)", output)
    time_per_req = re.search(r"Time per request:\s+([\d\.]+)", output)

    return {
        "mode": mode,
        "requests_per_sec": float(requests_per_sec.group(1)) if requests_per_sec else 0,
        "time_per_req": float(time_per_req.group(1)) if time_per_req else 0
    }

def get_server_distribution():
    """Analisa access.log para contar quantas requisições cada servidor atendeu."""
    logs = subprocess.run(["docker", "exec", "sd-desafio06-proxy-1", "cat", "/var/log/nginx/access.log"], stdout=subprocess.PIPE, text=True).stdout
    servers = re.findall(r"web\d+", logs)
    counts = {f"web{i}": servers.count(f"web{i}") for i in range(1, 4)}
    return counts

# ============================================================
# Execução dos testes
# ============================================================
all_results = []
for mode in MODES:
    set_nginx_mode(mode)
    time.sleep(2)  # Aguarda reload
    res = run_ab_test(mode)
    dist = get_server_distribution()
    res.update(dist)
    all_results.append(res)

# ============================================================
# Salvando resultados
# ============================================================
df = pd.DataFrame(all_results)
df.to_csv(os.path.join(RESULTS_DIR, "results.csv"), index=False)
print("\n[OK] Resultados salvos em results/results.csv")

# ============================================================
# Gráficos
# ============================================================
plt.figure(figsize=(10, 6))
plt.bar(df["mode"], df["requests_per_sec"])
plt.title("Desempenho - Requests por Segundo")
plt.ylabel("req/s")
plt.savefig(os.path.join(RESULTS_DIR, "requests_per_sec.png"))
plt.close()

plt.figure(figsize=(10, 6))
plt.bar(df["mode"], df["time_per_req"])
plt.title("Tempo Médio por Requisição (ms)")
plt.ylabel("ms")
plt.savefig(os.path.join(RESULTS_DIR, "time_per_request.png"))
plt.close()

# Distribuição de requisições por servidor
df_plot = df.melt(id_vars=["mode"], value_vars=["web1", "web2", "web3"],
                  var_name="server", value_name="requests")

plt.figure(figsize=(10, 6))
for server in ["web1", "web2", "web3"]:
    plt.plot(df_plot[df_plot["server"] == server]["mode"],
             df_plot[df_plot["server"] == server]["requests"],
             marker='o', label=server)
plt.title("Distribuição de Requisições por Servidor")
plt.ylabel("Quantidade de Requisições")
plt.legend()
plt.savefig(os.path.join(RESULTS_DIR, "server_distribution.png"))
plt.close()

print("[OK] Gráficos gerados em results/")
