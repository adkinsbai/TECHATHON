"""Loop Xiaoyi TTS into local SenseVoice ASR without chat writes or speaker playback."""
import argparse
import io
import json
import time
import wave

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    with httpx.Client(base_url=args.url, trust_env=False, timeout=90) as client:
        before = client.get('/api/status').json()
        started = time.monotonic()
        tts = client.post('/api/body/tts', json={'text': '你好，这是本地语音测试。'})
        tts.raise_for_status()
        tts_seconds = time.monotonic() - started
        with wave.open(io.BytesIO(tts.content), 'rb') as wav:
            audio = {'rate': wav.getframerate(), 'channels': wav.getnchannels(),
                     'width': wav.getsampwidth(), 'frames': wav.getnframes()}
        started = time.monotonic()
        asr = client.post('/api/body/asr', files={'file': ('local-test.wav', tts.content, 'audio/wav')})
        asr.raise_for_status()
        asr_seconds = time.monotonic() - started
        heard = asr.json().get('text', '')
        after = client.get('/api/status').json()
        assert heard and '本地' in heard, 'The local loopback did not recognize the test phrase'
        print(json.dumps({'xiaoyi_tts': True, 'local_asr': True, 'recognized_test_phrase': heard,
                          'tts_seconds': round(tts_seconds, 2), 'asr_seconds': round(asr_seconds, 2),
                          'audio': audio, 'chat_write_performed': False,
                          'message_count_before': before['message_count'],
                          'message_count_after': after['message_count']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
