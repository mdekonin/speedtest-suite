import socket
import time
import csv
import os
import json

BIND_IP = "0.0.0.0"
PORT = 5005
# Protocol Configuration
BLOCK_SIZE = 16384 # 16KB
UPLOAD_EXPECTED = 6400 * BLOCK_SIZE   # ~100MB
DOWNLOAD_EXPECTED = 6400 * BLOCK_SIZE # ~100MB
CSV_FILE = "network_stats.csv"

def recv_exactly(sock, n):
    """Robustly receive exactly n bytes or return None if connection closes."""
    data = b''
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet: return None
        data += packet
    return data

def log_to_csv(data):
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Device", "Upload_Mbps", "Download_Mbps", "Latency_ms", "Jitter_ms"])
        writer.writerow(data)

def run_server():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((BIND_IP, PORT))
    server_sock.listen(5)
    
    print(f"[*] Server Listening on {PORT} (Protocol v2.0)")

    while True:
        conn, addr = server_sock.accept()
        try:
            # 1. IDENTIFY
            device_name = conn.recv(1024).decode().strip()
            
            # 2. SEND MANIFEST (Protocol Setup)
            manifest = {
                "up_len": UPLOAD_EXPECTED,
                "down_len": DOWNLOAD_EXPECTED,
                "block": BLOCK_SIZE
            }
            manifest_str = json.dumps(manifest).ljust(256) # Fixed size header
            conn.sendall(manifest_str.encode())

            # 3. PHASE 1: UPLOAD (Receive)
            start_t = time.time()
            recv_exactly(conn, UPLOAD_EXPECTED)
            up_dur = time.time() - start_t
            up_speed = (UPLOAD_EXPECTED * 8) / (up_dur * 1_000_000)

            # 4. PHASE 2: LATENCY (UDP Reflector)
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sock.bind((BIND_IP, PORT + 1))
            udp_sock.settimeout(2.0)
            for _ in range(100):
                try:
                    data, c_addr = udp_sock.recvfrom(1024)
                    udp_sock.sendto(data, c_addr)
                except: break
            udp_sock.close()

            # 5. PHASE 3: DOWNLOAD (Send)
            payload = b"X" * BLOCK_SIZE
            start_t = time.time()
            for _ in range(DOWNLOAD_EXPECTED // BLOCK_SIZE):
                conn.sendall(payload)
            
            # 6. FINAL SYNC: Receive Client Results
            results_raw = recv_exactly(conn, 256)
            results = json.loads(results_raw.decode().strip())
            
            # LOGGING
            log_to_csv([
                time.ctime(), device_name, 
                round(up_speed, 2), round(results['down_speed'], 2),
                round(results['latency'], 2), round(results['jitter'], 2)
            ])
            
            print(f"[{device_name}] UP: {up_speed:.2f} | DOWN: {results['down_speed']:.2f} | PING: {results['latency']:.2f}ms")

        except Exception as e:
            print(f"[!] Test Error: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    run_server()
