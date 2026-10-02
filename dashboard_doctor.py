"""
Run from the JARVIS folder, with JARVIS already running:   python dashboard_doctor.py

Finds out why the phone's Remote Control page will not open and says what to do.
It only READS things (network adapters, firewall rules, a test connection to your
own PC) - it changes nothing.
"""
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PORT = 8000
OK, BAD, WARN = "[ OK ]", "[FAIL]", "[WARN]"


def say(tag, msg):
    print(f"{tag} {msg}")


def main():
    problems = 0
    try:
        from dashboard import server as ds
    except Exception as e:
        say(BAD, f"Cannot load dashboard/server.py: {e}")
        say(" -- ", "Install its packages:  pip install fastapi \"uvicorn[standard]\" cryptography python-multipart")
        return

    # 1. Which address would the phone be told to use? -------------------------
    print("\n1) Network adapters on this PC")
    ranked = ds._lan_candidates()
    chosen = ds._local_ip()
    if not ranked:
        say(WARN, "No adapters found (is psutil installed?)  pip install psutil")
    for score, ip, name in ranked:
        mark = "<-- JARVIS gives the phone this one" if ip == chosen else ""
        kind = "virtual/VPN" if ds._VIRTUAL_NIC.search(name) else "real"
        print(f"      {ip:16s} {name:34s} ({kind}) {mark}")
    if ds._configured_ip():
        say(OK, f'"dashboard_ip" is set manually to {chosen}')
    vpn_up = [n for _, _, n in ranked if ds._VIRTUAL_NIC.search(n)]
    if vpn_up:
        say(WARN, "VPN/virtual adapters are active: " + ", ".join(sorted(set(vpn_up))))
        say(" -- ", "A VPN is fine, but the phone must use the Wi-Fi/Ethernet address above, not a VPN one.")
    if chosen.startswith("127.") or chosen.startswith("192.0.2."):
        problems += 1
        say(BAD, "No usable LAN address. Connect this PC to the same Wi-Fi/router as the phone.")

    # 2. Is the dashboard running, and is it HTTP or HTTPS? ---------------------
    print(f"\n2) Is the dashboard listening on port {PORT}?")
    proto = None
    try:
        raw = socket.create_connection(("127.0.0.1", PORT), timeout=3)
        raw.close()
    except OSError:
        problems += 1
        say(BAD, f"Nothing is listening on port {PORT}. Start JARVIS first (and check the console for '[Dashboard] Disabled').")
        say(" -- ", 'If it says a module is missing:  pip install fastapi "uvicorn[standard]" cryptography python-multipart')
        raw = None
    if raw is not None:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection(("127.0.0.1", PORT), timeout=3) as s:
                with ctx.wrap_socket(s, server_hostname="localhost"):
                    proto = "https"
        except ssl.SSLError:
            proto = "http"
        except OSError:
            proto = None
        if proto:
            say(OK, f"The dashboard is serving {proto.upper()} on port {PORT}.")
            say(" -- ", f"So the phone URL must start with  {proto}://  - typing the other one just spins forever.")

    # 3. Can this PC reach itself through its LAN address? ---------------------
    print("\n3) Reaching the dashboard through the LAN address")
    if proto:
        t0 = time.time()
        try:
            socket.create_connection((chosen, PORT), timeout=4).close()
            say(OK, f"{chosen}:{PORT} answered in {time.time() - t0:.2f}s.")
        except OSError as e:
            problems += 1
            say(BAD, f"{chosen}:{PORT} did not answer ({e}).")

    # 4. Windows firewall and network profile ----------------------------------
    if sys.platform == "win32":
        print("\n4) Windows firewall")
        for port in (PORT, PORT + 1):
            try:
                r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule",
                                    f"name=JARVIS Dashboard Port {port}"],
                                   capture_output=True, text=True, timeout=8)
                found = r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                found = False
            if found:
                say(OK, f"Firewall rule for port {port} exists.")
            else:
                problems += 1
                say(BAD, f"No firewall rule for port {port}. Phones are blocked until it exists.")
                say(" -- ", "Open Command Prompt AS ADMINISTRATOR and run:")
                print(f'        netsh advfirewall firewall add rule name="JARVIS Dashboard Port {port}" '
                      f"protocol=TCP dir=in localport={port} action=allow profile=any")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Get-NetConnectionProfile | ForEach-Object { $_.Name + '|' + $_.NetworkCategory }"],
                               capture_output=True, text=True, timeout=10)
            for line in r.stdout.strip().splitlines():
                name, _, cat = line.partition("|")
                if cat.strip().lower() == "public":
                    say(WARN, f"Network '{name.strip()}' is set to PUBLIC. Windows hides the PC from other devices on Public networks.")
                    say(" -- ", "Settings > Network & internet > Wi-Fi > (your network) > Network profile type: Private.")
                else:
                    say(OK, f"Network '{name.strip()}' is {cat.strip()}.")
        except Exception:
            pass

    # 5. Certificate ------------------------------------------------------------
    print("\n5) HTTPS certificate")
    crt = ROOT / "config" / "certs" / "jarvis.crt"
    if proto == "https":
        if crt.exists():
            try:
                from cryptography import x509
                cert = x509.load_pem_x509_certificate(crt.read_bytes())
                san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                ips = [str(i) for i in san.get_values_for_type(x509.IPAddress)]
                if chosen in ips:
                    say(OK, f"The certificate was made for {chosen}.")
                else:
                    say(WARN, f"The certificate was made for {', '.join(ips) or 'other addresses'}, not {chosen}.")
                    say(" -- ", "The phone will show a bigger warning. To regenerate: delete the config/certs folder and restart JARVIS.")
            except Exception:
                pass
        say(" -- ", "The phone shows 'Your connection is not private'. That is expected (the certificate is made on your own PC).")
        say(" -- ", "Tap Advanced > Proceed. Open the link in CHROME or Safari - the browser inside WhatsApp/Messenger/Telegram cannot proceed and just shows a blank page.")
    else:
        say(" -- ", "Serving plain HTTP, so there is no certificate warning (but the phone microphone needs HTTPS).")

    # Verdict -------------------------------------------------------------------
    print("\n" + "=" * 60)
    if proto and chosen and not chosen.startswith(("127.", "192.0.2.")):
        print(f"On the phone (same Wi-Fi as this PC, mobile data OFF), open Chrome and type:\n\n      {proto}://{chosen}:{PORT}\n")
        print(f"If that spins forever: try  {proto}://{chosen}:{PORT + 1}  - and if neither loads, the router is isolating")
        print("devices ('AP/client isolation' or a Guest network). Use the main Wi-Fi, or turn that setting off.")
    if problems:
        print(f"\n{problems} problem(s) found above - fix those first.")


if __name__ == "__main__":
    main()
