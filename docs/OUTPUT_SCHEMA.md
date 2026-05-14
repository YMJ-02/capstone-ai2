# 출력 스키마 — ai-pi-02 → MQTT

프로토콜: **MQTT 3.1.1** (Mosquitto, 기본 `127.0.0.1:1883`), 사용자명/비밀번호 인증, **QoS 1**, JSON UTF-8.

## 토픽

| 토픽 | retain | 트리거 | 용도 |
|---|---|---|---|
| `edgesafe/ai/fall` | No | 낙상 확정 1회 | 알림/대시보드/푸시 |
| `edgesafe/ai/status` | Yes | 시작/종료/10초마다 | 노드 상태 표시 |

## 공통 헤더 (모든 메시지)

```json
{
  "schema_version": "1.1",
  "event_type": "fall_detected | status",
  "occurred_at": "2026-04-28T16:52:42.000+09:00",
  "occurred_at_unix": 1777362762.058,
  "node_id": "ai-pi-02"
}
```

## fall_detected (edgesafe/ai/fall)

주요 필드:

- `event_id`: 중복 제거 키 — `fall-{node_id}-{timestamp}`
- `severity`: 항상 `"critical"`
- `location`: `{node_id, camera, label}`
- `confidence` (0.0–1.0), `confidence_pct` (0–100)
- `message`: `{title, body, short}` 알림용 텍스트
- `ai`: `{method, action, action_confidence}`
- `debug`: 진단 정보 (UI에 표시하지 않음)

## status (edgesafe/ai/status)

### online (시작)
```json
{ "status": "online" }
```

### normal (10초 heartbeat)
```json
{
  "status": "normal",
  "stats": { "uptime_sec": 50, "frames_received": 487, "fps": 9.74 }
}
```

### offline (종료/LWT)
```json
{ "status": "offline", "reason": "shutdown | lwt" }
```

대시보드 표시: online/normal=🟢, warning=🟡, offline=🔴.

## 출처

원본: `YMJ-02/edgesafe-ai-pi2/SCHEMA.md` v1.1
