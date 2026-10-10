"""Photogrammetry flight geometry: GSD, footprint, trigger rate, blur, coverage.

The survey requirement is what links the payload to the airframe: overlap,
exposure and frame rate bound the ground speed, and ground speed x swath x
endurance is the commercial number — hectares per flight.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Camera:
    pixels_across: int          # across-track (sensor long side across the flight line)
    pixels_along: int
    pixel_um: float
    focal_mm: float
    max_fps: float

    @classmethod
    def from_dict(cls, d: dict) -> "Camera":
        return cls(int(d["pixels_across"]), int(d["pixels_along"]), float(d["pixel_um"]),
                   float(d["focal_mm"]), float(d["max_fps"]))

    def gsd_m(self, agl_m: float) -> float:
        return self.pixel_um * 1e-6 * agl_m / (self.focal_mm * 1e-3)

    def swath_m(self, agl_m: float) -> float:
        return self.gsd_m(agl_m) * self.pixels_across

    def footprint_along_m(self, agl_m: float) -> float:
        return self.gsd_m(agl_m) * self.pixels_along


def trigger_rate_hz(cam: Camera, agl_m: float, ground_speed_m_s: float, forward_overlap: float) -> float:
    """Frames per second needed for a forward overlap at a ground speed."""
    base = cam.footprint_along_m(agl_m) * (1.0 - forward_overlap)
    return ground_speed_m_s / base


def max_ground_speed_m_s(cam: Camera, agl_m: float, forward_overlap: float, fps_margin: float = 0.8) -> float:
    """Ground speed at which the camera hits `fps_margin` of its max frame rate."""
    base = cam.footprint_along_m(agl_m) * (1.0 - forward_overlap)
    return base * cam.max_fps * fps_margin


def blur_px(cam: Camera, agl_m: float, ground_speed_m_s: float, exposure_s: float) -> float:
    """Forward-motion blur in pixels."""
    return ground_speed_m_s * exposure_s / cam.gsd_m(agl_m)


def max_speed_for_blur(cam: Camera, agl_m: float, exposure_s: float, blur_limit_px: float) -> float:
    return blur_limit_px * cam.gsd_m(agl_m) / exposure_s


def coverage_ha(
    cam: Camera,
    agl_m: float,
    ground_speed_m_s: float,
    side_overlap: float,
    survey_time_s: float,
    turn_efficiency: float = 0.80,
) -> float:
    """Area mapped in `survey_time_s`; `turn_efficiency` = fraction of time on line."""
    line_spacing = cam.swath_m(agl_m) * (1.0 - side_overlap)
    return ground_speed_m_s * survey_time_s * turn_efficiency * line_spacing / 1e4
