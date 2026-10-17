"""静置校准、迟滞及消抖；压力只表示接触。"""
from statistics import median


class Pressure:
    def __init__(self, calibration_samples=10, debounce=.12,
                 press_delta=180, release_delta=80):
        self.calibration_samples = calibration_samples
        self.debounce = debounce
        self.press_delta = press_delta
        self.release_delta = release_delta
        self.reset()

    def reset(self):
        self.baseline = None
        self.pressed = False
        self.samples = []
        self.candidate = None
        self.since = 0
        self.strength = 0.0

    def update(self, raw, at):
        raw = float(raw)
        if self.baseline is None:
            self.samples.append(raw)
            if len(self.samples) >= self.calibration_samples:
                self.baseline = median(self.samples)
                self.samples.clear()
            return None
        # 当前 FSR 模块空载约 4095；按压时 ADC 下降。
        delta = self.baseline - raw
        self.strength = max(0.0, min(1.0, delta / max(1, self.baseline)))
        target = delta >= (self.release_delta if self.pressed else self.press_delta)
        if target == self.pressed:
            self.candidate = None
            return None
        if self.candidate != target:
            self.candidate, self.since = target, at
        elif at - self.since >= self.debounce:
            self.pressed, self.candidate = target, None
            return 'press' if target else 'release'
        return None
