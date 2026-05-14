# capstone-ai2 (EdgeSafe AI Node, Pi #2)

vision-pi(`capstone-vision`)가 ZMQ로 보내는 **MediaPipe 자세 좌표 33개**를 받아,
**규칙 기반 1차 게이트 + 1D-CNN 2차 검증**으로 낙상을 판정하고
**MQTT**로 알림 이벤트를 발행하는 라즈베리파이용 서비스.

기존 `edgesafe-ai-pi2`의 스파게티 구조를 정리하고 모듈 단위로 재작성한 버전.

## 현재 진행 상태

- [x] Phase 1 — 입출력 골격 (ZMQ 수신 / MQTT status 발행)
- [x] Phase 2 — 특징 추출 + 규칙 기반 낙상 게이트 + fall 이벤트 발행
- [x] Phase 3 — 1D-CNN 학습 + TFLite 통합 (rule confidence와 가중 융합)
- [x] Phase 4 — systemd 서비스화
- [x] Phase 5 — 실기기 E2E 검증 도구 (`tools/verify_e2e.py`, `docs/E2E_CHECKLIST.md`)

세부는 `docs/ARCHITECTURE.md` 참조.

## 디렉터리

```
capstone-ai2/
├── src/
│   ├── config.py              # 설정 (env 오버라이드)
│   ├── io/
│   │   ├── zmq_subscriber.py  # vision-pi 수신
│   │   └── mqtt_publisher.py  # 알림/status 발행
│   ├── pipeline/
│   │   ├── features.py        # 자세 → 특징 벡터
│   │   ├── rule_gate.py       # 규칙 기반 1차 게이트 (상태머신)
│   │   └── cnn_validator.py   # 1D-CNN 2차 검증 (TFLite 추론, 선택적)
│   ├── core/
│   │   ├── event_builder.py   # MQTT 봉투 빌더
│   │   └── fall_detector.py   # 파이프라인 조립 + rule/cnn 융합 + payload
│   └── main.py                # 엔트리 포인트
├── tools/
│   ├── fake_vision.py         # vision-pi 모킹 (random/stable/fall)
│   └── verify_e2e.py          # Phase 5 E2E sanity check (import/MQTT/ZMQ)
├── tests/                     # pytest 단위 테스트
├── ml/                        # Phase 3 학습 (data_synth, model, train)
├── models/                    # 학습 산출물 (.keras, .tflite, report)
├── deploy/                    # Phase 4 systemd 서비스 + install.sh
├── docs/                      # 스키마, 아키텍처, E2E 체크리스트
├── requirements.txt           # Pi 런타임 의존성
├── requirements-train.txt     # 학습 전용 (개발 머신)
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

### 3) 연결 검증 (vision-pi 없이) — Phase 1

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

### 4) 낙상 시나리오 검증 — Phase 2

**기본 시나리오(`random`)는 일부러 낙상을 안 발생시킨다** — 좌표가 매 프레임 균등 난수라
bbox 종횡비가 ~1.0으로 누운 자세 조건을 못 만족시키기 때문. 낙상을 보려면
명시적으로 `--scenario fall`을 사용한다:

```bash
python tools/fake_vision.py --scenario fall --fps 10
```

이 시나리오는 **30초 주기로** 직립→급강하→누움→일어남→직립을 반복하므로,
main을 언제 켜도 다음 사이클부터 감지된다.

기대 동작 (시작 후 약 5~6초경, 이후 30초마다 반복):
- fake_vision 로그: `[fake_vision] t=  5.0s phase=falling` → `t=  5.4s phase=lying`
- 메인 로그: `rule_gate: NORMAL → DESCENDING` → `rule_gate: DESCENDING → FALLEN`
  → `FALL CONFIRMED conf=0.XX`
- B 터미널: `edgesafe/ai/fall` 토픽으로 fall_detected 메시지 1회 발행 (cooldown 5초)

### 5) 단위 테스트

```bash
pip install pytest
python -m pytest tests/ -v
```

### 6) 1D-CNN 학습 — Phase 3 (개발 머신에서)

학습은 라즈베리파이가 아닌 개발 머신에서 수행하고, 산출된 `.tflite` 만 Pi로 복사한다.

```bash
# 개발 머신
pip install -r requirements-train.txt
python -m ml.train
# 산출물: models/fall_validator.{keras,tflite}, training_report.txt

# Pi로 .tflite 복사
scp models/fall_validator.tflite ai@<pi-ip>:~/projects/capstone-ai2/models/
```

런타임 동작:
- Pi에 `models/fall_validator.tflite` 가 있으면 CNN validator 자동 활성화
- 없으면 자동 비활성화 (규칙 게이트 단독으로 동작) — 시스템은 항상 fail-safe
- 활성화 시 `fall_detected.ai.method = "rule+cnn"`, fusion confidence = `0.6*rule + 0.4*cnn`

학습 데이터는 `ml/data_synth.py` 의 시뮬레이션. 실 데이터셋 라벨링이 가능해지면
같은 입력 스펙(WINDOW_LEN=30, N_FEATURES=5)으로 fine-tuning 권장.

### 7) systemd 서비스화 — Phase 4

```bash
sudo bash deploy/install.sh           # 설치 + enable + start
sudo bash deploy/install.sh --status  # 상태 확인
sudo bash deploy/install.sh --logs    # 최근 100줄 로그
sudo bash deploy/install.sh --remove  # 제거
```

서비스 파일은 `deploy/edgesafe-ai.service`. `User=ai`, `WorkingDirectory=/home/ai/projects/capstone-ai2`,
`Restart=on-failure`로 설정. 사용자/경로가 다르면 파일을 직접 수정.

부팅 자동 시작 + 비정상 종료 시 5초 후 자동 재시작.

### 8) E2E 검증 — Phase 5

체크리스트 전체: `docs/E2E_CHECKLIST.md`

빠른 sanity check:
```bash
python tools/verify_e2e.py --check all
# 또는 개별: --check imports | mqtt | zmq
```

### 9) 실 vision-pi 연결

`.env`의 `ZMQ_ENDPOINT`만 실제 vision-pi IP로 바꾸고 `python -m src.main`.
vision-pi 쪽에서 `hostname -I` 또는 `ip addr` 로 IP 확인.

## 스키마

- 입력 (ZMQ): `docs/INPUT_SCHEMA.md`
- 출력 (MQTT): `docs/OUTPUT_SCHEMA.md`
