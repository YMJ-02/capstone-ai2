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
   ⑤ Event Builder + MQTT PUB     src/core/event_builder.py
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
| 2 | features, rule_gate, fall_detector, fall 발행 | ✅ 본 커밋 |
| 3 | 1D-CNN 학습 + TFLite 통합 | 다음 |
| 4 | systemd 서비스화 | 다음 |
| 5 | 실기기 E2E 검증 | 다음 |

## 규칙 게이트 상태머신 (Phase 2)

```
        hip_velocity > THRESH
NORMAL ─────────────────────────▶ DESCENDING
   ▲                                  │
   │ timeout(1.5s)                    │ torso>55° AND hip_y>0.65
   │                                  │ AND bbox_aspect>1.3
   │                                  ▼
   │                                FALLEN
   │   확정 후 cooldown(5s)            │ stillness(0.8s, motion<0.05)
   ◀──────────────────────────────────┘
                                  ▼ FallTrigger(confirmed=True)
                                build_fall_payload → MQTT publish_fall
```

각 임계값은 `src/config.py:RuleConfig`에 모여있고 `.env`로 오버라이드 가능.
Phase 3에서 DESCENDING 진입 또는 FALLEN 직전에 CNN validator를 호출해
confidence를 융합할 계획.

## 설계 원칙

- **모듈화**: `io/` 입출력, `pipeline/` 신호처리, `core/` 조립, `tools/` 개발용 보조
- **설정 집중화**: 모든 임계값을 `src/config.py` + `.env`
- **테스트 가능성**: `tools/fake_vision.py` 시나리오, pytest 단위 테스트 (`tests/`)
- **로깅 우선**: `print` 대신 `logging`, level은 `LOG_LEVEL`로 제어
- **타입 힌트**: 공개 API는 모두 타입 힌트
