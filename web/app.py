from flask import Flask, jsonify, request
import socket, time

app = Flask(__name__)

@app.route('/')
def index():
    response = {
        "server": socket.gethostname(),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "latency": round(time.time() % 1, 3),
        "client_ip": request.remote_addr
    }
    return jsonify(response)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
