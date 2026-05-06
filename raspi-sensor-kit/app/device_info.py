import socket


def get_ip():
    """Prefer LAN IP over /etc/hosts 127.0.1.1."""
    lan = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        lan = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    if lan and not lan.startswith("127."):
        return lan
    try:
        h = socket.gethostbyname(socket.gethostname())
        if h and not h.startswith("127."):
            return h
    except OSError:
        pass
    return lan or "0.0.0.0"


def get_mac(interface=None):
    for iface in (interface, "eth0", "wlan0"):
        if not iface:
            continue
        try:
            with open(f"/sys/class/net/{iface}/address") as f:
                return f.read().strip()
        except OSError:
            continue
    return "N/A"


def get_hostname():
    return socket.gethostname()


def get_serial():
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.strip().split(": ")[1]
    except (OSError, IndexError):
        pass
    return "N/A"


def get_site_id():
    return "site-003-3"


def build_device_info(
    water_lv: float | None = None,
    mud_lv: float | None = None,
):
    """Distances in cm from respective ultrasonic sensors, or None if read failed."""
    return {
        "ip": get_ip(),
        "mac": get_mac(),
        "site_id": get_site_id(),
        "uuid": get_serial(),
        "name": get_hostname(),
        "sn": get_serial(),
        "index": "tontarn_sensor",
        "water_lv": water_lv,
        "mud_lv": mud_lv,
    }
