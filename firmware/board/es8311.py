"""Minimal ES8311 codec driver for MicroPython (ESP32-S3 + ES8311/NS4150B module).

Write-only: register *reads* from this module are unreliable (they NACK), so the
driver only writes explicit values instead of doing read-modify-write.

Wiring (module <-> ESP32-S3-N16R8):
    SDA=GPIO5  SCL=GPIO4  MCLK=GPIO6
    SCLK(BCLK)=GPIO14  LRCK(WS)=GPIO12
    DIN (MCU -> module) = GPIO11    DOUT (module -> MCU) = GPIO13
Register sequence ported from esp_codec_dev device/es8311/es8311.c
(slave mode, MCLK=6.144MHz, 24kHz, 16bit, analog mic, DAC+ADC).
"""

import time

from machine import Pin, I2C

ADDR = 0x18

# reset/standby sequence (es8311_suspend in esp_codec_dev) -> known register state
_WAKE = (
    (0x32, 0x00), (0x17, 0x00), (0x0E, 0xFF), (0x12, 0x02), (0x14, 0x00),
    (0x0D, 0xFA), (0x15, 0x00), (0x02, 0x10), (0x00, 0x00), (0x00, 0x1F),
    (0x01, 0x30), (0x01, 0x00), (0x45, 0x00), (0x0D, 0xFC), (0x02, 0x00),
)

# es8311_open() with: slave mode, use_mclk, no inverted clocks, analog mic
_OPEN = (
    (0x44, 0x08),  # enhance I2C noise immunity
    (0x44, 0x08),  # second write (chip sometimes misses the first)
    (0x01, 0x30),
    (0x02, 0x00),
    (0x03, 0x10),
    (0x16, 0x24),
    (0x04, 0x10),
    (0x05, 0x00),
    (0x0B, 0x00),
    (0x0C, 0x00),
    (0x10, 0x1F),
    (0x11, 0x7F),
    (0x00, 0x80),  # CSM power on, slave
    (0x13, 0x10),
    (0x1B, 0x0A),
    (0x1C, 0x6A),
    (0x44, 0x58),  # internal reference (ADCL + DACR)
)

# 16 bit / I2S / 24 kHz, clock taken from BCLK (use_mclk = False)
_FS_24K_BCLK = (
    (0x09, 0x0C),
    (0x0A, 0x0C),
    (0x06, 0x00),
    (0x02, 0x18),   # pre_div = 1, pre_multi = x8  (clock from BCLK)
    (0x05, 0x00),   # adc_div = 1, dac_div = 1
    (0x03, 0x10),   # adc osr
    (0x04, 0x10),   # dac osr
    (0x07, 0x00),   # lrck_h
    (0x08, 0xFF),   # lrck_l
    (0x06, 0x03),   # bclk_div = 4  -> BCLK = MCLK/8
)

# same but with an external 6.144 MHz MCLK on the MCLK pin
_FS_24K_MCLK = (
    (0x09, 0x0C),
    (0x0A, 0x0C),
    (0x06, 0x00),
    (0x02, 0x00),   # pre_div = 1, pre_multi = x1
    (0x05, 0x00),
    (0x03, 0x10),
    (0x04, 0x10),
    (0x07, 0x00),
    (0x08, 0xFF),
    (0x06, 0x03),
)

# 16 kHz with an external 4.096 MHz MCLK (exactly reproducible with PWM)
_FS_16K_MCLK = (
    (0x09, 0x0C),
    (0x0A, 0x0C),
    (0x06, 0x00),
    (0x02, 0x00),   # pre_div = 1, pre_multi = x1
    (0x05, 0x00),
    (0x03, 0x10),   # adc osr
    (0x04, 0x20),   # dac osr (1/2 of the 24k value)
    (0x07, 0x00),
    (0x08, 0xFF),
    (0x06, 0x03),   # bclk_div = 4  -> BCLK = MCLK/8 = 512 kHz
)

# 32 kHz with an external 8.192 MHz MCLK (also exactly reproducible with PWM)
_FS_32K_MCLK = (
    (0x09, 0x0C),
    (0x0A, 0x0C),
    (0x06, 0x00),
    (0x02, 0x00),   # pre_div = 1, pre_multi = x1
    (0x05, 0x00),
    (0x03, 0x10),   # adc osr
    (0x04, 0x10),   # dac osr
    (0x07, 0x00),
    (0x08, 0xFF),
    (0x06, 0x03),   # bclk_div = 4  -> BCLK = MCLK/8 = 1.024 MHz
)

# es8311_start(): enable DAC + ADC
_START_BCLK = (
    (0x00, 0x80),
    (0x01, 0xBF),   # use_mclk = 0
    (0x09, 0x0C),
    (0x0A, 0x0C),
    (0x17, 0xBF),
    (0x0E, 0x02),
    (0x12, 0x00),
    (0x14, 0x1A),
    (0x0D, 0x01),
    (0x15, 0x40),
    (0x37, 0x08),
    (0x45, 0x00),
    (0x31, 0x00),   # DAC not muted
)

_START_MCLK = (
    (0x00, 0x80),
    (0x01, 0x3F),   # use_mclk = 1
    (0x09, 0x0C),
    (0x0A, 0x0C),
    (0x17, 0xBF),
    (0x0E, 0x02),
    (0x12, 0x00),
    (0x14, 0x1A),
    (0x0D, 0x01),
    (0x15, 0x40),
    (0x37, 0x08),
    (0x45, 0x00),
    (0x31, 0x00),   # DAC not muted
)


class ES8311:
    def __init__(self, i2c=None, addr=ADDR):
        self.addr = addr
        self.i2c = i2c or I2C(0, scl=Pin(4), sda=Pin(5), freq=100000)

    def w(self, reg, val, tries=6):
        data = bytes((reg & 0xFF, val & 0xFF))
        last = None
        for _ in range(tries):
            try:
                self.i2c.writeto(self.addr, data)
                return True
            except OSError as exc:      # ES8311 occasionally NACKs a transaction
                last = exc
                time.sleep_ms(2)
        raise last

    def r(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0]

    def init(self, sample_rate=24000, use_mclk=False):
        if sample_rate not in (16000, 24000, 32000):
            raise ValueError("only 16000/24000/32000 Hz supported")
        self.use_mclk = use_mclk
        self.sample_rate = sample_rate
        if sample_rate == 16000:
            fs_seq = _FS_16K_MCLK
        elif sample_rate == 32000:
            fs_seq = _FS_32K_MCLK
        else:
            fs_seq = _FS_24K_MCLK if use_mclk else _FS_24K_BCLK
        seqs = (_WAKE, _OPEN, fs_seq)
        for seq in seqs:
            for reg, val in seq:
                self.w(reg, val)
        self.w(0x01, 0x3F if use_mclk else 0xBF)
        self.volume(-6)
        return True

    def start(self):
        for reg, val in (_START_MCLK if getattr(self, "use_mclk", False) else _START_BCLK):
            self.w(reg, val)
        return True

    def mute(self, on=True):
        self.w(0x31, 0x60 if on else 0x00)

    def volume(self, db=0.0):
        """DAC volume register 0x32: 0x00 = -95.5 dB, 0xFF = +32.0 dB (linear)."""
        lo, hi = -95.5, 32.0
        reg = int(round((db - lo) * 255.0 / (hi - lo)))
        if reg < 0:
            reg = 0
        if reg > 255:
            reg = 255
        self.w(0x32, reg)

    def mic_gain(self, db=24):
        table = (0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38)
        idx = 0 if db < 6 else min(7, 1 + (int(db) - 6) // 6)
        self.w(0x16, table[idx])
