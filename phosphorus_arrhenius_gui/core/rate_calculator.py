from __future__ import annotations


def calculate_interval_rate(t1: float, t2: float, p1: float, p2: float) -> tuple[float, float, float, float]:
    duration = t2 - t1
    loss = p1 - p2
    if duration <= 0:
        raise ValueError("duration <= 0")
    if loss <= 0:
        raise ValueError("loss <= 0")
    rate_min = loss / duration
    return duration, loss, rate_min, rate_min * 60


def calculate_cumulative_loss(initial_p: float, remaining_p: float) -> float:
    loss = initial_p - remaining_p
    if loss < 0:
        raise ValueError("cumulative loss < 0")
    return loss
