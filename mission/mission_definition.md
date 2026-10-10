# Mission Definition — SE Bavaria Agricultural Survey

Shared by every platform. Structured site parameters are in
`mission/mission_params.yaml`; each platform's targets are in
`platforms/<platform>/design_point.yaml`.

## Operational context

- **Theatre:** Southeast Bavaria, mixed agricultural terrain, field elevation ~500 m ASL.
- **Operator:** Wallering Robotics (single-pilot BVLOS-capable when permitted).
- **Mission cadence:** Repeat surveys of fields up to ~10 ha per sortie.
- **Max wind:** 8 m/s sustained.
- **Operating temperature:** −5 °C to +35 °C (battery derating considered).

## Multirotor performance targets

| Parameter | Target | Notes |
|---|---|---|
| Hover endurance | ≥ 20 min | With nominal payload, 20 % battery reserve |
| Gust margin | T/W = 2.0 | Against 8 m/s sustained wind |
| AUW (design point) | 6.5 kg | Excludes margin contingency |
| AUW (max) | ~7.5 kg | Worst-case payload + reserve |

### Payload modes

- **Mapping (light):** Global shutter RGB + Orin Nano (always on).
- **Inspection (medium):** FLIR Boson+ thermal + global shutter RGB + Orin Nano.
- **Survey (heavy):** Livox Mid-360 LiDAR + MicaSense Altum-PT + Orin Nano.

Swap-bay logic: at most two non-default payloads simultaneously, gated by mass and
power budget (see `platforms/multirotor/06_payload_trades.ipynb`).

## Flying-wing performance targets

| Parameter | Target | Notes |
|---|---|---|
| Endurance | ≥ 45 min | Climb to 120 m + cruise, 20 % battery reserve untouched |
| AUW (design point) | 0.9 kg | Excludes margin contingency |
| Stall speed | ≤ 13 m/s | Landing and low-speed handling |
| Launch | Hand launch at 15 m/s | Launch at ≥ 1.2 Vs |
| Climb | 3 m/s at 14 m/s | Sets motor/ESC rating |
| Turn | 45° bank sustained at 16 m/s | |
| Static margin | 6 % MAC | Intermediate pilot setting |

Payloads are drawn from the same manifest; the multirotor's always-on compute
stack is excluded on this airframe.

## Avionics baseline (multirotor)

- Flight controller: Pixhawk 6X (PX4)
- Companion compute: NVIDIA Orin Nano + carrier board
- GNSS: Holybro H-RTK F9P Helical
- RC link: ELRS
- Telemetry: TBD (LTE/SiK)

## Open requirements

- Confirm regulatory class (likely C2 / specific category) for each platform.
- Decide LiPo vs Li-ion chemistry for endurance vs C-rate trade.
- Define payload data downlink (onboard SSD vs live stream).
- Flying wing: choose the reflexed airfoil and replace the placeholder polar
  (CD0, e, CLmax) with an XFLR5/AVL result; weigh real components.
