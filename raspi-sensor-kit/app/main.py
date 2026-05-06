# -*- coding: utf-8 -*-
"""Read UART + mud soft-UART sensors, POST payload to server. Run from this directory on the Pi."""
import asyncio
import os
import time

from api import SendAPI
from device_info import build_device_info
from sensors import cleanup, init_mud_soft_uart_sensor, init_uart_sensor, read_mud_distance_mm, read_a01nyub

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
            distance_mm = read_a01nyub()
            water_lv = (
                round(float(distance_mm) / 10.0, 1)
                if distance_mm is not None
                else None
            )

            mud_mm = read_mud_distance_mm()
            if mud_mm is not None:
                last_mud_lv_cm = round(float(mud_mm) / 10.0, 1)
            mud_lv = last_mud_lv_cm

            payload = build_device_info(water_lv=water_lv, mud_lv=mud_lv)
            payload["timestamp"] = int(time.time())
            payload["measured_at"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime()
            )
            print(
                time.strftime("%H:%M:%S"),
                "distance_mm=",
                distance_mm,
                "water_lv_cm=",
                water_lv,
                "mud_lv_cm=",
                mud_lv,
            )
            out = await sender.send_api_request(payload)
            print("response", out)
            await asyncio.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        cleanup()


if __name__ == "__main__":
    asyncio.run(main())
