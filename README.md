# capstone-ai2 (EdgeSafe AI Node, Pi #2)

vision-pi(`capstone-vision`)가 ZMQ로 보내는 **MediaPipe 자세 좌표 33개**를 받아,
**규칙 기반 1차 게이트 + 1D-CNN 2차 검증**으로 낙상을 판정하고
**MQTT**로 알림 이벤트를 발행하는 라즈베리파이용 서비스.

기존 `edgesafe-ai-pi2`의 스파게티 구조를 정리하고 모듈 단위로 재작성한 버전.

## 현재 진행 상태

- [x] Phase 1 — 입출력 골격 (ZMQ 수신 / MQTT status 발행)
- [ ] Phase 2 — 특징 추출 + 규칙 기반 낙상 게이트
- [ ] Phase 3 — 1D-CNN 학습 + TFLite 통합
- [ ] Phase 4 — systemd 서비스화
- [ ] Phase 5 — 실기기 E2E 검증

세부는 `docs/ARCHITECTURE.md` 참조.

## 디렉터리

```
capstone-ai2/
├── src/
│   ├── config.py              # 설정 (env 오버라이드)
│   ├── io/
│   │   ├── zmq_subscriber.py  # vision-pi 수신
│   │   └── mqtt_publisher.py  # 알림/status 발행
│   ├── core/event_builder.py  # MQTT 봉투 빌더
│   └── main.py                # 엔트리 포인트
├── tools/fake_vision.py       # vision-pi 모킹 ZMQ PUB
├── docs/                      # 스키마/아키텍처
├── ml/                        # (Phase 3) 학습 스크립트
├── deploy/                    # (Phase 4) systemd
├── requirements.txt
└── .env.example
```

## 실행 (라즈베리파이)

### 1) 의존성

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-dev \
                    build-essential libzmq3-dev \
                    mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto

cd ~/projects/capstone-ai2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 환경변수

```bash
cp .env.example .env
# .env 편집: ZMQ_ENDPOINT를 실제 vision-pi IP로 교체
```

### 3) 연결 검증 (vision-pi 없이)

터미널 A — fake vision-pi:
```bash
source .venv/bin/activate
python tools/fake_vision.py --bind tcp://0.0.0.0:5555 --fps 10
```

터미널 B — MQTT 출력 구독:
```bash
mosquitto_sub -t 'edgesafe/ai/#' -v
```

터미널 C — 메인 서비스:
```bash
source .venv/bin/activate
ZMQ_ENDPOINT=tcp://127.0.0.1:5555 python -m src.main
```

기대 동작:
- 메인 로그에 `MQTT connected` → `ZMQ SUB connected` → `received 50 frames, ...`
- B 터미널에 `edgesafe/ai/status` 메시지가 시작 시 1회, 이후 10초마다 보임

### 4) 실 vision-pi 연결

`.env`의 `ZMQ_ENDPOINT`만 실제 IP로 바꾸고 `python -m src.main`.

## 스키마

- 입력 (ZMQ): `docs/INPUT_SCHEMA.md`
- 출력 (MQTT): `docs/OUTPUT_SCHEMA.md`
