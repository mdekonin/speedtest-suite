import socket
import time
import curses
import sys
import json

DEFAULT_SERVER = "192.168.1.160"
PORT = 5005
DEVICE_NAME = socket.gethostname()

def recv_exactly(sock, n):
    data = b''
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet: return None
        data += packet
    return data

def run_test(stdscr, server_ip):
    curses.start_color()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    
    def draw(row, title, msg, progress=0):
        stdscr.addstr(row, 4, f"[{title}]", curses.color_pair(1) | curses.A_BOLD)
        stdscr.addstr(row + 1, 6, f"{msg.ljust(50)}")
        if progress > 0:
            bar = "#" * int(progress / 6.25)
            stdscr.addstr(row + 2, 6, f"[{bar.ljust(16)}] {int(progress)}%")
        stdscr.refresh()

    stdscr.clear()
    stdscr.addstr(1, 2, f" PROTOCOL-DRIVEN SPEEDTEST ", curses.A_REVERSE)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        draw(3, "INIT", f"Connecting to {server_ip}...")
        sock.connect((server_ip, PORT))
        
        # 1. IDENTIFY
        sock.sendall(DEVICE_NAME.encode().ljust(64))

        # 2. GET MANIFEST
        manifest_raw = recv_exactly(sock, 256)
        manifest = json.loads(manifest_raw.decode().strip())
        UP_LEN, DOWN_LEN, BLOCK = manifest['up_len'], manifest['down_len'], manifest['block']

        # 3. PHASE 1: UPLOAD
        payload = b"X" * BLOCK
        start_t = time.time()
        for i in range(UP_LEN // BLOCK):
            sock.sendall(payload)
            if i % 200 == 0:
                draw(6, "UPLOAD", "Transferring...", (i * BLOCK / UP_LEN) * 100)
        up_speed = (UP_LEN * 8) / ((time.time() - start_t) * 1_000_000)
        draw(6, "UPLOAD", f"Complete: {up_speed:.2f} Mbps", 100)

        # 4. PHASE 2: LATENCY (RTT)
        draw(10, "QUALITY", "Pinging...")
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.settimeout(1.0)
        latencies = []
        for _ in range(100):
            t1 = time.perf_counter()
            udp.sendto(b"p", (server_ip, PORT + 1))
            try:
                udp.recvfrom(1024)
                latencies.append((time.perf_counter() - t1) * 1000)
            except: pass
            time.sleep(0.01)
        avg_lat = sum(latencies)/len(latencies) if latencies else 0
        jitter = sum(abs(latencies[i]-latencies[i-1]) for i in range(1, len(latencies)))/(len(latencies)-1) if len(latencies)>1 else 0
        draw(10, "QUALITY", f"Ping: {avg_lat:.2f}ms | Jitter: {jitter:.2f}ms")

        # 5. PHASE 3: DOWNLOAD
        draw(14, "DOWNLOAD", "Receiving...")
        start_t = time.time()
        received = 0
        while received < DOWN_LEN:
            data = sock.recv(min(BLOCK, DOWN_LEN - received))
            if not data: break
            received += len(data)
            if received % (BLOCK * 200) == 0:
                draw(14, "DOWNLOAD", "Receiving...", (received / DOWN_LEN) * 100)
        
        down_speed = (received * 8) / ((time.time() - start_t) * 1_000_000)
        draw(14, "DOWNLOAD", f"Complete: {down_speed:.2f} Mbps", 100)

        # 6. SEND RESULTS BACK TO SERVER
        final_stats = {"down_speed": down_speed, "latency": avg_lat, "jitter": jitter}
        sock.sendall(json.dumps(final_stats).ljust(256).encode())

        stdscr.addstr(18, 4, "TEST SUCCESSFUL. Press any key.", curses.color_pair(2) | curses.A_BOLD)
        stdscr.getch()

    except Exception as e:
        stdscr.addstr(20, 4, f"FATAL ERROR: {e}", curses.A_BOLD)
        stdscr.getch()
    finally:
        sock.close()

if __name__ == "__main__":
    curses.wrapper(run_test, sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERVER)
