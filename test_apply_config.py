#!/usr/bin/env python3
"""
test_apply_config.py - Cambiar config Y aplicarla (stop/start sense o reboot).
Ejecutar: venv\\Scripts\\python.exe test_apply_config.py
"""
import time
import hid

VID, PID = 0x0E6A, 0x0317

def build_cmd(cmd_byte, data=b""):
    msg_len = 1 + len(data)
    return bytes([0x02, msg_len, cmd_byte]) + data

def send_recv(dev, frame, timeout_ms=2000):
    report_id = len(frame)
    report = bytes([report_id]) + frame.ljust(63, b'\x00')
    dev.write(list(report))
    resp = dev.read(64, timeout_ms=timeout_ms)
    if not resp:
        return None
    raw = bytes(resp)
    for i in range(min(4, len(raw))):
        if raw[i] == 0x02:
            msg_len = raw[i + 1]
            return raw[i:i + 2 + msg_len]
    return raw

def main():
    interfaces = [d for d in hid.enumerate()
                  if d["vendor_id"] == VID and d["product_id"] == PID]
    consumer = next((d for d in interfaces if d.get("usage_page") == 0x000C), None)
    if not consumer:
        print("Lector no encontrado")
        return

    dev = hid.device()
    dev.open_path(consumer["path"])

    print("=" * 50)
    print("Test: Cambiar a 8H SIN Enter y aplicar")
    print("=" * 50)

    # 1. Setear 8H + Normal + SIN ENTER (0x00)
    print("\n[1] SetParam: 8H, Normal, Sin Enter (add=0x00)...")
    frame = build_cmd(0x03, bytes([0x03, 0x05, 0x01, 0x00]))
    r = send_recv(dev, frame)
    print(f"    Echo: {r.hex(' ').upper() if r else 'ERROR'}")

    # 2. Stop Sense
    print("\n[2] Stop Sense...")
    frame = build_cmd(0x02, bytes([0x11]))
    r = send_recv(dev, frame)
    print(f"    Resp: {r.hex(' ').upper() if r else 'ERROR'}")

    # 3. Start Sense
    print("\n[3] Start Sense...")
    time.sleep(0.3)
    frame = build_cmd(0x02, bytes([0x12]))
    r = send_recv(dev, frame)
    print(f"    Resp: {r.hex(' ').upper() if r else 'ERROR'}")

    # 4. Verificar
    print("\n[4] Verificar config...")
    time.sleep(0.3)
    frame = build_cmd(0x03, bytes([0x03]))
    r = send_recv(dev, frame)
    if r and len(r) >= 8:
        add = r[7]
        print(f"    Config: {r.hex(' ').upper()}")
        print(f"    add=0x{add:02X} → {'SIN Enter' if add == 0 else 'CON Enter'}")

    print("\n>>> Ahora pasa una pulsera para ver si hace Enter o no.")
    print(">>> (Abre un Notepad y acerca la pulsera al lector)")
    print("\n>>> Si SIGUE haciendo Enter, pulsa Ctrl+C y probaremos reboot.")

    try:
        input("\n>>> Pulsa Enter aqui para probar con REBOOT en su lugar...")
    except KeyboardInterrupt:
        dev.close()
        return

    # 5. Alternativa: Reboot
    print("\n[5] Enviando Reboot al lector...")
    frame = build_cmd(0x0F, bytes([0x01]))
    r = send_recv(dev, frame)
    print(f"    Resp: {r.hex(' ').upper() if r else 'Sin respuesta (normal durante reboot)'}")

    print("\n>>> El lector se reiniciara. Espera 3 segundos...")
    print(">>> Luego prueba con una pulsera en Notepad.")

    dev.close()

if __name__ == "__main__":
    main()
