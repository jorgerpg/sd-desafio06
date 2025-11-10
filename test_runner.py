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
AB_BASE = ["ab", "-n", "1000", "-c", "50", "http://localhost/"]
SCENARIOS = ["normal", "falha"]

os.makedirs(RESULTS_DIR, exist_ok=True)

# ============================================================
# Funções auxiliares
# ============================================================


def clear_nginx_log():
  """Zera o access.log antes de cada rodada."""
  subprocess.run(
      ["docker", "exec", "sd-desafio06-proxy-1",
       "sh", "-c", "echo '' > /var/log/nginx/access.log"]
  )


def set_nginx_mode(mode):
  """Ativa o algoritmo desejado no nginx.conf e recarrega o proxy."""
  with open(NGINX_CONF, "r") as f:
    conf = f.read()

  conf = re.sub(r"(least_conn;|ip_hash;)", "# \\1", conf)
  if mode == "least_conn":
    conf = conf.replace(
        "upstream backend {", "upstream backend {\n        least_conn;")
  elif mode == "ip_hash":
    conf = conf.replace(
        "upstream backend {", "upstream backend {\n        ip_hash;")

  with open(NGINX_CONF, "w") as f:
    f.write(conf)

  subprocess.run(
      ["docker", "exec", "sd-desafio06-proxy-1", "nginx", "-s", "reload"],
      stdout=subprocess.PIPE, stderr=subprocess.PIPE
  )
  print(f"[INFO] 🔄 Nginx reiniciado em modo: {mode}")


def run_ab_test(n, c):
  """Executa ApacheBench e retorna métricas."""
  cmd = ["ab", "-n", str(n), "-c", str(c), "http://localhost/"]
  result = subprocess.run(cmd, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)
  output = result.stdout

  rps = re.search(r"Requests per second:\s+([\d\.]+)", output)
  tpr = re.search(r"Time per request:\s+([\d\.]+)", output)

  return (
      float(rps.group(1)) if rps else 0,
      float(tpr.group(1)) if tpr else 0
  )


def get_server_distribution():
  """Conta requisições por backend com base no IP dos containers."""
  container_ips = {}
  for i in range(1, 4):
    name = f"sd-desafio06-web{i}-1"
    ip = subprocess.run(
        ["docker", "inspect", "-f",
         "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", name],
        stdout=subprocess.PIPE, text=True
    ).stdout.strip()
    container_ips[ip] = f"web{i}"

  logs = subprocess.run(
      ["docker", "exec", "sd-desafio06-proxy-1",
       "cat", "/var/log/nginx/access.log"],
      stdout=subprocess.PIPE, text=True
  ).stdout

  counts = {f"web{i}": 0 for i in range(1, 4)}
  for ip, label in container_ips.items():
    counts[label] = logs.count(ip)

  return counts


# ============================================================
# Execução dos testes
# ============================================================
results = []
test_matrix = [(500, 10), (1000, 50)]

for mode in MODES:
  set_nginx_mode(mode)
  time.sleep(2)

  for n, c in test_matrix:
    for scenario in SCENARIOS:
      clear_nginx_log()

      if scenario == "falha":
        print("[SIM] 💥 Pausando web1 para simular falha...")
        subprocess.run(["docker", "pause", "sd-desafio06-web1-1"])
        time.sleep(1)

      print(f"[RUN] {mode} - {scenario} - n={n}, c={c}")
      rps, tpr = run_ab_test(n, c)
      dist = get_server_distribution()
      dist.update({
          "mode": mode, "n": n, "c": c,
          "requests_per_sec": rps,
          "time_per_req": tpr,
          "scenario": scenario
      })
      results.append(dist)

      if scenario == "falha":
        subprocess.run(["docker", "unpause", "sd-desafio06-web1-1"])
        time.sleep(2)

# ============================================================
# Salvando resultados e gráficos
# ============================================================
df = pd.DataFrame(results)
csv_path = os.path.join(RESULTS_DIR, "results_full.csv")
df.to_csv(csv_path, index=False)
print(f"\n✅ Resultados salvos em {csv_path}\n")

# Gráficos
plt.figure(figsize=(10, 6))
for mode in MODES:
  subset = df[(df["mode"] == mode) & (df["scenario"] == "normal")]
  plt.plot(subset["c"], subset["requests_per_sec"], marker='o', label=mode)
plt.title("Requests por Segundo (Cenário Normal)")
plt.xlabel("Concorrência (-c)")
plt.ylabel("req/s")
plt.legend()
plt.grid(True)
plt.savefig(os.path.join(RESULTS_DIR, "requests_per_sec_full.png"))
plt.close()

plt.figure(figsize=(10, 6))
for mode in MODES:
  subset = df[(df["mode"] == mode) & (df["scenario"] == "normal")]
  plt.plot(subset["c"], subset["time_per_req"], marker='o', label=mode)
plt.title("Tempo Médio por Requisição (ms)")
plt.xlabel("Concorrência (-c)")
plt.ylabel("ms")
plt.legend()
plt.grid(True)
plt.savefig(os.path.join(RESULTS_DIR, "time_per_request_full.png"))
plt.close()

print("✅ Gráficos atualizados em results/")
