# 아키텍처

```
[vision-pi (capstone-vision)]
   MediaPipe Pose → 33 landmarks
        │ ZMQ PUB tcp://<vision-pi>:5555  topic="pose"
        ▼
[ai-pi-02 (capstone-ai2)]
   ① ZMQ SUB (수신)               src/io/zmq_subscriber.py
   ② Feature Extractor            src/pipeline/features.py     (Phase 2)
   ③ Rule Gate (1차)              src/pipeline/rule_gate.py    (Phase 2)
   ④ 1D-CNN Validator (2차)       src/pipeline/cnn_validator.py(Phase 3)
   ⑤ Confidence Fusion            src/core/fall_detector.py    (Phase 3)
   ⑥ Event Builder + MQTT PUB     src/core/event_builder.py
                                  src/io/mqtt_publisher.py
        │ MQTT QoS=1
        ▼
   edgesafe/ai/fall    (낙상 이벤트, retain=False)
   edgesafe/ai/status  (heartbeat,   retain=True)
```

## 단계별 구현 상태

| Phase | 범위 | 상태 |
|---|---|---|
| 0 | Pi 셋업 (한글/git/Python/Mosquitto) | 사용자 진행 |
| 1 | config / io / event_builder / main / fake_vision / docs | ✅ |
| 2 | features, rule_gate, fall_detector, fall 발행 | ✅ |
| 3 | 1D-CNN 학습 + TFLite 추론 + confidence 융합 | ✅ |
| 4 | systemd 서비스화 (`deploy/`) | ✅ |
| 5 | 실기기 E2E 검증 (`tools/verify_e2e.py`, `docs/E2E_CHECKLIST.md`) | ✅ |

## 규칙 게이트 상태머신 (Phase 2)

```
                ① vel > THRESH  또는
                ② 이미 horizontal
NORMAL ─────────────────────────▶ DESCENDING
   ▲                                  │
   │ timeout(2.5s)                    │ horizontal=True
   │ 또는 직립 복귀                   │ (torso/vert/aspect 3중 2개)
   │                                  ▼
   │ ┌────────────────────────────── FALLEN
   │ │ exit: non-horizontal              │
   │ │       0.5초 지속                   │ ① stillness(0.8s, motion<0.10)
   │ │                                    │ ② 1.5초 시간 기반 확정
   │ └◀───────────────────────────────────│
   ◀──────────────────────────────────────┘
                                  ▼ FallTrigger(confirmed=True)
                                build_fall_payload → MQTT publish_fall
```

각 임계값은 `src/config.py:RuleConfig`에 모여있고 `.env`로 오버라이드 가능.

### horizontal 판정 (rule_gate)

3개 신호 중 **2개 이상 만족** 시 horizontal로 본다 (단일 신호 잡음 강건):

1. `torso_angle_deg > 55°` — 어깨→엉덩이 축이 수직축에서 55도 이상 기울어짐
2. `torso_vertical_extent < 0.12` — shoulder-hip y거리 (직립 ~0.25, 누움 ~0.05)
3. `bbox_aspect > 1.1` — 보이는 랜드마크의 폭/높이 비율

`hip_y` 절대값은 사용하지 않는다. 카메라 각도/거리에 따라 누워도 hip이 화면
위쪽으로 가는 경우가 있어 신뢰 못함 (Phase 2 후속 hotfix에서 제거).

## CNN Validator (Phase 3)

### 입력

WINDOW_LEN=30 프레임 × N_FEATURES=5 채널, 정규화된 float32:

| ch | feature | 정규화 |
|---|---|---|
| 0 | torso_angle_deg | `/180` |
| 1 | torso_vertical_extent | `/0.5` |
| 2 | bbox_aspect | `/3` |
| 3 | hip_center_y | `/1.5` |
| 4 | hip_velocity | `sigmoid` |

정규화 공식은 학습/추론 양쪽에서 동일하게 유지 (`ml/feature_window.normalize_row`,
`src/pipeline/cnn_validator._normalize_row`).

### 모델

`ml/model.py`. Conv1D(16,5) → Conv1D(32,3) → MaxPool → Conv1D(32,3) → GAP → Dense(1, sigmoid).
파라미터 약 4K, TFLite 16KB. Pi에서도 < 5ms 추론.

### 호출 시점

매 프레임 `observe(feats)` 로 window 갱신. **추론은 의심 시점에만** —
RuleGate가 suspected=True를 내거나 state ∈ {DESCENDING, FALLEN}일 때.
NORMAL 정상 상태에서는 비용 0.

### 융합

```
final_confidence = (1 - w) * rule_confidence + w * cnn_prob
                   default w = 0.4   (CNN_FUSION_WEIGHT)
```

CNN 비활성화 또는 window 미충분 시 rule_confidence 그대로. fall_detected 페이로드의
`ai.method` 가 `"rule+cnn"` 또는 `"rule_based"` 로 구분.

### Fail-safe

`.tflite` 파일이 없거나 TFLite 런타임 로드 실패 시 자동으로 enabled=False.
시스템은 규칙 게이트 단독으로 계속 동작한다. 학습이 안 되어 있어도 빌드가 깨지지 않음.

## 설계 원칙

- **모듈화**: `io/` 입출력, `pipeline/` 신호처리, `core/` 조립, `tools/` 개발용 보조
- **설정 집중화**: 모든 임계값을 `src/config.py` + `.env`
- **테스트 가능성**: `tools/fake_vision.py` 시나리오, pytest 단위 테스트 (`tests/`)
- **로깅 우선**: `print` 대신 `logging`, level은 `LOG_LEVEL`로 제어
- **타입 힌트**: 공개 API는 모두 타입 힌트
- **선택적 컴포넌트**: CNN처럼 실패해도 시스템이 동작할 수 있어야 함 (graceful degradation)
