from flask import Flask, jsonify, request, after_this_request
import os
import time

app = Flask(__name__)

# Nome do servidor vem de variável de ambiente
SERVER_NAME = os.getenv("SERVER_NAME", "undefined")


@app.after_request
def add_header(response):
  response.headers['X-Backend-Name'] = SERVER_NAME
  return response


@app.route('/')
def index():
  response = {
      "server": SERVER_NAME,
      "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
      "latency": round(time.time() % 1, 3),
      "client_ip": request.remote_addr
  }
  return jsonify(response)


if __name__ == '__main__':
  app.run(host='0.0.0.0', port=5000)
