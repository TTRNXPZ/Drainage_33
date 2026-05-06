# -*- coding: utf-8 -*-
"""UART + pigpio soft-serial sensors.

Hardware UART (``/dev/serial0``) is often **root:root 600** when the kernel
uses that port as serial console (**console=serial0,115200** in
``/boot/firmware/cmdline.txt``). Fix: remove that stanza (keep ``console=tty1``),
``sudo systemctl mask serial-getty@ttyS0``, ensure user is in **dialout**,
reboot. Symptom: ``Permission denied`` despite ``groups`` listing dialout.
"""
import errno
import os
import time

import pigpio
import serial

BAUD_RATE = 9600
HEADER = 0xFF
DISTANCE_MIN = 0
DISTANCE_MAX = 7500

# Software UART mud sensor (GPIO BCM numbers): TX 23, RX 24
MUD_TX_GPIO = 23
MUD_RX_GPIO = 24
MUD_TRIGGER_BYTE = 0x55
MUD_BAUD = int(os.environ.get("MUD_UART_BAUD", "9600"))
MUD_READ_DEADLINE_S = float(os.environ.get("MUD_READ_DEADLINE_SEC", "0.2"))

_FALLBACK_DEVS = ("/dev/serial0", "/dev/ttyS0", "/dev/ttyAMA0")

ser = None
mud_pi = None


def _candidate_ports() -> list[str]:
    env = os.environ.get("RASPI_UART_PORT", "").strip()
    out: list[str] = []
    if env:
        out.append(env)
    for p in _FALLBACK_DEVS:
        if p not in out:
            out.append(p)
    resolved: list[str] = []
    for p in out:
        if p == env or os.path.exists(p):
            resolved.append(p)
    return resolved if resolved else [env or "/dev/serial0"]


def init_uart_sensor():
    global ser
    last_err = None
    for port in _candidate_ports():
        try:
            ser = serial.Serial(
                port=port,
                baudrate=BAUD_RATE,
                timeout=0.05,
                write_timeout=0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            print(f"UART opened: {port} @ {BAUD_RATE}")
            return True
        except (serial.SerialException, OSError, ValueError) as e:
            last_err = e
            print(f"  (skip {port}: {e})")
    print(f"ERROR: Cannot open UART (tried {_candidate_ports()!r}) -> {last_err}")
    errn = getattr(last_err, "errno", None)
    if errn in (errno.EACCES, errno.EPERM) or errn == 13:
        print(
            "HINT: UART permission denied — serial console on ttyS0/serial0 is a "
            "common cause; see module docstring at top of sensors.py."
        )
    return False


def read_a01nyub():
    if ser is None or not ser.is_open:
        return None

    try:
        ser.reset_input_buffer()
        time.sleep(0.08)

        while True:
            byte = ser.read(1)
            if len(byte) == 0:
                return None
            if byte[0] == HEADER:
                break

        remaining = ser.read(3)
        if len(remaining) < 3:
            return None

        data_h = remaining[0]
        data_l = remaining[1]
        checksum = remaining[2]

        calc_sum = (HEADER + data_h + data_l) & 0xFF
        if calc_sum != checksum:
            return None

        distance_mm = data_h * 256 + data_l

        if distance_mm < DISTANCE_MIN or distance_mm > DISTANCE_MAX:
            return None

        return distance_mm

    except serial.SerialException:
        return None
    except Exception as e:
        print(f"Unexpected error in read_a01nyub: {e}")
        return None


def _mud_parse_frame(buf: bytearray):
    n = len(buf)
    if n < 4:
        return None, None
    for i in range(n - 3):
        if buf[i] != HEADER:
            continue
        high = buf[i + 1]
        low = buf[i + 2]
        csum = buf[i + 3]
        if ((HEADER + high + low) & 0xFF) == csum:
            return (high << 8) | low, i
    return None, None


def _mud_send_trigger(pi: pigpio.pi, baud: int) -> None:
    pi.wave_clear()
    pi.wave_add_serial(MUD_TX_GPIO, baud, [MUD_TRIGGER_BYTE])
    wid = pi.wave_create()
    if wid < 0:
        raise RuntimeError("wave_create failed: {}".format(wid))
    pi.wave_send_once(wid)
    while pi.wave_tx_busy():
        time.sleep(0.00005)
    pi.wave_delete(wid)


def _mud_measure_once(pi: pigpio.pi, baud: int, deadline_s: float = MUD_READ_DEADLINE_S):
    try:
        pi.bb_serial_read_close(MUD_RX_GPIO)
    except Exception:
        pass
    time.sleep(0.002)
    st = pi.bb_serial_read_open(MUD_RX_GPIO, baud, 8)
    if st != 0:
        raise RuntimeError("bb_serial_read_open failed: {}".format(st))

    buf = bytearray()
    _mud_send_trigger(pi, baud)

    t_end = time.time() + deadline_s
    while time.time() < t_end:
        count, data = pi.bb_serial_read(MUD_RX_GPIO)
        if count and count > 0:
            buf.extend(memoryview(data)[:count])
            dist, _ = _mud_parse_frame(buf)
            if dist is not None:
                if dist < DISTANCE_MIN or dist > DISTANCE_MAX:
                    return None
                return dist
        elif count is not None and count < 0:
            print(f"bb_serial_read error: {count}")
            return None
        time.sleep(0.002)
    return None


def init_mud_soft_uart_sensor():
    """pigpio bit-bang UART on GPIO23/24; requires pigpiod."""
    global mud_pi
    mud_pi = pigpio.pi()
    if not mud_pi.connected:
        print("pigpio: cannot connect to pigpiod. Start daemon with: sudo pigpiod")
        mud_pi = None
        return False
    mud_pi.set_mode(MUD_TX_GPIO, pigpio.OUTPUT)
    mud_pi.set_pull_up_down(MUD_RX_GPIO, pigpio.PUD_UP)
    try:
        mud_pi.bb_serial_read_close(MUD_RX_GPIO)
    except Exception:
        pass
    print(
        f"Mud soft-UART ready: TX=GPIO{MUD_TX_GPIO} RX=GPIO{MUD_RX_GPIO} @ {MUD_BAUD} baud"
    )
    return True


def read_mud_distance_mm():
    """One shot read from mud sensor (mm), or None on failure."""
    global mud_pi
    if mud_pi is None or not mud_pi.connected:
        return None
    try:
        return _mud_measure_once(mud_pi, MUD_BAUD, MUD_READ_DEADLINE_S)
    except Exception as e:
        print(f"read_mud_distance_mm error: {e}")
        return None


def cleanup():
    global ser, mud_pi
    if ser and ser.is_open:
        ser.close()
        print("UART closed")
    if mud_pi is not None:
        try:
            mud_pi.bb_serial_read_close(MUD_RX_GPIO)
        except Exception:
            pass
        try:
            mud_pi.stop()
        except Exception:
            pass
        mud_pi = None
        print("pigpio mud sensor closed")
