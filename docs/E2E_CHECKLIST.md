# Phase 5 — 실기기 E2E 검증 체크리스트

본 노드(ai-pi-02)가 vision-pi와 dashboard/notifier 사이에서 정확히 동작하는지
하나의 시나리오 모음으로 검증한다. 각 항목은 라즈베리파이에서 직접 수행.

## 0. 사전 조건

- [ ] Pi #2 부팅, 네트워크 연결
- [ ] vision-pi(Pi #1) 동작 중, `tcp://<vision-pi-ip>:5555` 에서 ZMQ PUB
- [ ] Mosquitto broker 동작 중 (`sudo systemctl status mosquitto`)
- [ ] `.env` 의 `ZMQ_ENDPOINT` 가 vision-pi 실제 IP로 설정
- [ ] `python -m ml.train` 한 번 실행해서 `models/fall_validator.tflite` 존재 (또는 git LFS/repo 동봉)

## 1. 의존성/모듈 임포트 sanity

```bash
cd ~/projects/capstone-ai2
source .venv/bin/activate
python tools/verify_e2e.py --check imports
```
- [ ] `ALL CHECKS PASSED` 출력

## 2. 단위 테스트

```bash
python -m pytest tests/ -v
```
- [ ] 모든 테스트 통과

## 3. MQTT 연결성

```bash
python tools/verify_e2e.py --check mqtt
```
- [ ] `MQTT connect OK`
- [ ] `subscribe self-publish round-trip OK`

## 4. ZMQ 수신

vision-pi 동작 중 상태에서:
```bash
python tools/verify_e2e.py --check zmq --timeout 5
```
- [ ] 5초 이내에 최소 1프레임 수신 (`got 1 pose frame`)
- [ ] landmarks 33개, frame_id/timestamp 정상

(vision-pi 없으면 fake_vision 사용:
```bash
python tools/fake_vision.py --bind tcp://0.0.0.0:5555 --fps 10 &
ZMQ_ENDPOINT=tcp://127.0.0.1:5555 python tools/verify_e2e.py --check zmq --timeout 5
```)

## 5. 낙상 시나리오 (모킹)

터미널 A:
```bash
python tools/fake_vision.py --bind tcp://0.0.0.0:5555 --fps 10 --scenario fall
```
터미널 B:
```bash
mosquitto_sub -t 'edgesafe/ai/#' -v
```
터미널 C:
```bash
ZMQ_ENDPOINT=tcp://127.0.0.1:5555 python -m src.main
```

기대 동작 (30초 주기):
- [ ] 터미널 C: `rule_gate: NORMAL → DESCENDING → FALLEN`
- [ ] 터미널 C: `FALL CONFIRMED conf=0.X frame_id=N`
- [ ] 터미널 B: `edgesafe/ai/fall` 메시지 1회
- [ ] 페이로드의 `confidence` 0.5 이상, `confidence_pct` 일치
- [ ] `ai.method` 가 `"rule+cnn"` (CNN 활성화 시) 또는 `"rule_based"`
- [ ] cooldown(5초) 내 추가 발행 없음

## 6. 실 사용자 낙상

vision-pi와 실제 카메라 연결 상태에서 직접 시연:
- [ ] 직립 → 의도적 낙상 → 누움 1.5초 이상
- [ ] `edgesafe/ai/fall` 토픽 발행 확인
- [ ] confidence_pct 가 합리적 (≥ 50)
- [ ] 직립 복귀 후 5초 cooldown 지나면 재감지 가능

## 7. systemd 서비스화

```bash
sudo bash deploy/install.sh
sudo bash deploy/install.sh --status
sudo bash deploy/install.sh --logs
```
- [ ] `Active: active (running)`
- [ ] journal 로그에 `MQTT connected` / `ZMQ SUB connected` 등장
- [ ] `sudo reboot` 후 자동 시작 확인 (`systemctl is-active edgesafe-ai` = `active`)
- [ ] 강제 종료 시 자동 재시작 (`sudo kill -9 <PID>` 후 5초 대기)

## 8. LWT / 종료 메시지

```bash
sudo systemctl stop edgesafe-ai
mosquitto_sub -t edgesafe/ai/status -C 1
```
- [ ] `status: offline` 메시지 수신 (정상 종료 또는 LWT)

## 9. 부하/안정성 (선택)

5분 이상 연속 실행:
- [ ] CPU 사용률 < 30% (htop)
- [ ] 메모리 안정 (증가 없음)
- [ ] status heartbeat 10초마다 누락 없이 발행
- [ ] frame drop이 있어도 서비스 안 죽음

## 결과 기록

- 검증자: ________
- 일시: ________
- 펌웨어/커밋: `git rev-parse HEAD` ________
- 비고: ________
