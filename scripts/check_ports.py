"""检测 10.22.127.11 的常用端口"""
import socket

host = '10.22.127.11'
ports = [8001, 8000, 8080, 80, 443, 3000, 5000, 9000]

print(f"检测主机: {host}")
print("-" * 40)

for port in ports:
    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
        print(f"  {port}: OPEN")
    except socket.timeout:
        print(f"  {port}: TIMEOUT")
    except ConnectionRefusedError:
        print(f"  {port}: REFUSED")
    except Exception as e:
        print(f"  {port}: {type(e).__name__}")
