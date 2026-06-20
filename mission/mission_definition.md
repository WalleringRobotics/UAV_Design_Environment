# Mission Definition — SE Bavaria Agricultural Survey

## Operational context

- **Theatre:** Southeast Bavaria, mixed agricultural terrain, field elevation ~500 m ASL.
- **Operator:** Wallering Robotics (single-pilot BVLOS-capable when permitted).
- **Mission cadence:** Repeat surveys of fields up to ~10 ha per sortie.

## Performance targets

| Parameter | Target | Notes |
|---|---|---|
| Hover endurance | ≥ 20 min | With nominal payload, 20 % battery reserve |
| Max wind | 8 m/s sustained | Gust margin via T/W = 2.0 |
| Operating temperature | −5 °C to +35 °C | Battery derating considered |
| AUW (design point) | 6.5 kg | Excludes margin contingency |
| AUW (max) | ~7.5 kg | Worst-case payload + reserve |

## Payload modes

- **Mapping (light):** Global shutter RGB + Orin Nano (always on).
- **Inspection (medium):** FLIR Boson+ thermal + global shutter RGB + Orin Nano.
- **Survey (heavy):** Livox Mid-360 LiDAR + MicaSense Altum-PT + Orin Nano.

Swap-bay logic: at most two non-default payloads simultaneously, gated by mass and
power budget (see `payload/06_payload_trades.ipynb`).

## Avionics baseline

- Flight controller: Pixhawk 6X (PX4)
- Companion compute: NVIDIA Orin Nano + carrier board
- GNSS: Holybro H-RTK F9P Helical
- RC link: ELRS
- Telemetry: TBD (LTE/SiK)

## Open requirements

- Confirm regulatory class (likely C2 / specific category).
- Decide LiPo vs Li-ion chemistry for endurance vs C-rate trade.
- Define payload data downlink (onboard SSD vs live stream).
