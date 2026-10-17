"""录音 WAV 与 24kHz 双声道播放数据。"""
import array
import io
import sys
import wave

RATE = 24000
CHUNK_BYTES = 4096
MAX_CAPTURE_BYTES = 15 * RATE * 2


def wav_bytes(pcm):
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm[:len(pcm) & ~1])
    return out.getvalue()


def decode_audio(data):
    import miniaudio
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('语音文件过大')
    sound = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16,
                            nchannels=2, sample_rate=RATE)
    samples = sound.samples
    if len(samples) > RATE * 2 * 90:
        raise ValueError('语音超过 90 秒')
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


def scale_pcm(pcm, volume=10):
    if not isinstance(volume, int) or not 0 <= volume <= 100:
        raise ValueError('音量须为 0..100')
    samples = array.array('h')
    samples.frombytes(pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    samples = array.array('h', (int(value * volume / 100) for value in samples))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


def chunks(pcm):
    for offset in range(0, len(pcm), CHUNK_BYTES):
        yield pcm[offset:offset + CHUNK_BYTES].ljust(CHUNK_BYTES, b'\0')
