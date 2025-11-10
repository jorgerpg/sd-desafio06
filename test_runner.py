import subprocess
import re
import time
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

# ============================================================
# Configurações gerais
# ============================================================
NGINX_CONF = "nginx/nginx.conf"
MODES = ["round_robin", "least_conn", "ip_hash"]
RESULTS_DIR = "results"
SCENARIOS = ["normal", "falha"]
BACKENDS = [f"web{i}" for i in range(1, 4)]
LOG_LINE_PATTERN = re.compile(
    r'"(?P<method>\S+) (?P<path>\S+) (?P<proto>[^"]+)" '
    r'(?P<status>\d{3}) .*? upstream=(?P<upstream>[\d\.]+:\d+) '
    r'backend_name=(?P<backend>[\w-]+) request_time=(?P<request_time>[\d\.]+)'
)

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
  """Extrai métricas por backend usando backend_name e request_time dos logs."""
  log_output = subprocess.run(
      ["docker", "exec", "sd-desafio06-proxy-1",
       "cat", "/var/log/nginx/access.log"],
      stdout=subprocess.PIPE, text=True
  ).stdout

  rows = []
  for line in log_output.strip().splitlines():
    match = LOG_LINE_PATTERN.search(line)
    if not match:
      continue
    rows.append({
        "backend_name": match.group("backend"),
        "status": int(match.group("status")),
        "request_time": float(match.group("request_time"))
    })

  if not rows:
    empty_stats = {}
    for backend in BACKENDS:
      empty_stats[f"{backend}_requests"] = 0
      empty_stats[f"{backend}_avg_time_ms"] = 0.0
    empty_stats["total_requests_logged"] = 0
    return empty_stats

  log_df = pd.DataFrame(rows)
  stats = {}
  for backend in BACKENDS:
    backend_df = log_df[log_df["backend_name"] == backend]
    stats[f"{backend}_requests"] = len(backend_df)
    stats[f"{backend}_avg_time_ms"] = (
        backend_df["request_time"].mean(
        ) * 1000 if not backend_df.empty else 0.0
    )
  stats["total_requests_logged"] = len(log_df)
  return stats


# ============================================================
# Execução dos testes
# ============================================================
results = []
test_matrix = [(1000, 10), (1000, 100)]

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
total_requests = df[[f"{b}_requests" for b in BACKENDS]].sum(axis=1)
total_requests = total_requests.replace(0, np.nan)
for backend in BACKENDS:
  df[f"{backend}_share"] = df[f"{backend}_requests"] / total_requests
df.fillna(0, inplace=True)

csv_path = os.path.join(RESULTS_DIR, "results_full.csv")
df.to_csv(csv_path, index=False)
print(f"\n✅ Resultados salvos em {csv_path}\n")

# Gráficos


def plot_metric(metric, ylabel, filename, title):
  rows = len(SCENARIOS)
  fig, axes = plt.subplots(rows, 1, figsize=(6, 4 * rows), sharey=True)

  if rows == 1:
    axes = [axes]

  c_values = sorted(df["c"].unique())
  x = np.arange(len(c_values))
  width = 0.7 / len(MODES) if MODES else 0.7

  for i, scenario in enumerate(SCENARIOS):
    ax = axes[i]
    subset = df[df["scenario"] == scenario]
    for idx, mode in enumerate(MODES):
      mode_subset = subset[subset["mode"] == mode]
      values = []
      for c_val in c_values:
        data = mode_subset[mode_subset["c"] == c_val][metric]
        values.append(data.mean() if not data.empty else 0)
      offsets = x - 0.35 + idx * width + width / 2
      ax.bar(offsets, values, width=width,
             label=mode if i == 0 else "")
    ax.set_title(f"Cenário: {scenario.capitalize()}")
    ax.set_xlabel("Concorrência (-c)")
    ax.set_xticks(x)
    ax.set_xticklabels([str(v) for v in c_values])
    ax.grid(True, axis="y", alpha=0.3)
    if i == 0:
      ax.set_ylabel(ylabel)

  handles, labels = axes[0].get_legend_handles_labels()
  fig.legend(handles, labels, loc="upper center", ncol=len(MODES))
  fig.suptitle(title)
  fig.tight_layout(rect=(0, 0, 1, 0.88))
  fig.savefig(os.path.join(RESULTS_DIR, filename))
  plt.close(fig)


plot_metric(
    metric="requests_per_sec",
    ylabel="req/s",
    filename="requests_per_sec_full.png",
    title="Requests por Segundo")

plot_metric(
    metric="time_per_req",
    ylabel="ms",
    filename="time_per_request_full.png",
    title="Tempo Médio por Requisição")

# Distribuição dos backends (stacked bar)
share_cols = [f"{backend}_share" for backend in BACKENDS]
agg = (df.groupby(["mode", "scenario"])[share_cols]
       .mean()
       .reset_index())
labels = [f"{row.mode}\n{row.scenario}" for row in agg.itertuples()]
bottom = np.zeros(len(agg))
plt.figure(figsize=(12, 6))
for backend in BACKENDS:
  plt.bar(labels, agg[f"{backend}_share"], bottom=bottom, label=backend)
  bottom += agg[f"{backend}_share"]
plt.title("Distribuição de Requisições por Backend (média)")
plt.ylabel("Proporção")
plt.ylim(0, 1)
plt.legend(title="Backend")
plt.grid(axis="y", alpha=0.2)
plt.savefig(os.path.join(RESULTS_DIR, "backend_distribution_full.png"))
plt.close()

print("✅ Gráficos atualizados em results/")
