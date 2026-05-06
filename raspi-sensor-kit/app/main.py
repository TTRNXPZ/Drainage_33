# -*- coding: utf-8 -*-
"""Read UART + mud soft-UART sensors, POST payload to server. Run from this directory on the Pi."""

import asyncio
import os
import time

from api import SendAPI
from device_info import build_device_info
from sensors import cleanup, init_mud_soft_uart_sensor, init_uart_sensor, read_mud_distance_mm, read_a01nyub

# Height of tank/basin (cm). water_lv is computed as: TANK_HEIGHT - raw_water_lv
TANK_HEIGHT = 200.0

INTERVAL_SECONDS = float(os.environ.get("SENSOR_INTERVAL_SEC", "5"))


async def main():
    sender = SendAPI()

    while not init_uart_sensor():
        print("UART open failed, retry in 5s...")
        await asyncio.sleep(5)

    while not init_mud_soft_uart_sensor():
        print("Mud soft-UART / pigpiod not ready, retry in 5s (need: sudo pigpiod)...")
        await asyncio.sleep(5)

    print("--- start ---")
    last_mud_lv_cm = 0.0

    try:
        while True:
            # 1) Read raw water sensor value (distance -> raw level in cm)
            raw_water_mm = read_a01nyub()
            raw_water_lv = None
            if raw_water_mm is not None:
                try:
                    raw_water_lv = float(raw_water_mm) / 10.0
                except (TypeError, ValueError):
                    raw_water_lv = None

            # 2) Compute water level for API: water_lv = max(0, TANK_HEIGHT - raw_water_lv)
            if raw_water_lv is None:
                water_lv = 0.0
            else:
                water_lv = TANK_HEIGHT - float(raw_water_lv)
                if water_lv < 0:
                    water_lv = 0.0
                water_lv = round(water_lv, 1)

            # 3) Compute mud level for API: mud_lv = mud_lv_raw - water_lv
            mud_mm = read_mud_distance_mm()
            if mud_mm is not None:
                try:
                    last_mud_lv_cm = round(float(mud_mm) / 10.0, 1)
                except (TypeError, ValueError):
                    pass

            mud_lv_raw = float(last_mud_lv_cm)
            mud_lv = round(abs(mud_lv_raw - float(water_lv)), 1)

            payload = build_device_info(water_lv=water_lv, mud_lv=mud_lv)
            payload["timestamp"] = int(time.time())
            payload["measured_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

            print(
                time.strftime("%H:%M:%S"),
                "raw_water_mm=",
                raw_water_mm,
                "raw_water_lv_cm=",
                None if raw_water_lv is None else round(raw_water_lv, 1),
                "water_lv_cm=",
                water_lv,
                "mud_lv_cm_raw=",
                last_mud_lv_cm,
                "mud_lv_cm=",
                mud_lv,
            )

            send_status = "success"
            send_error = ""
            out = None
            try:
                out = await sender.send_api_request(payload)
            except Exception as e:
                send_status = "failed"
                send_error = str(e)

            if send_status == "success":
                print("send_status=success", "response=", out)
            else:
                print("send_status=failed", "error=", send_error)

            await asyncio.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        cleanup()


if __name__ == "__main__":
    asyncio.run(main())
