# capstone-app 통합 가이드

본 문서는 **capstone-app**(Flutter, `YMJ-02/capstone-app` 레포)이 본 노드
(capstone-ai2 = ai-pi-02)와 통신하기 위해 알아야 할 모든 정보입니다.

## 1. 엔드포인트 요약

| 채널 | URL | 정의 | 상태 |
|---|---|---|---|
| WebSocket (낙상 stream) | `ws://<ai-pi-02-ip>:8765` | `APP_WS_PORT` | ✅ 구현 |
| HTTP 헬스 | `http://<ai-pi-02-ip>:8080/health` | `APP_HTTP_PORT` | ✅ 구현 |
| MJPEG 라이브 스트림 | `http://.../stream` | — | ❌ 본 노드 범위 밖 (vision-pi 또는 별도) |
| 영상 클립 서빙 | `http://.../recordings/...` | — | ❌ 본 노드 범위 밖 |

**호스트 IP**: ai-pi-02의 LAN IP. Pi에서 `hostname -I` 로 확인.
`AppConfig.host` 를 이 IP로 변경하거나 빌드 시 `--dart-define=API_HOST=192.168.x.x` 로 주입.

**바인딩**: 본 서비스는 기본 `0.0.0.0` 으로 바인딩하므로 같은 LAN의 어느 디바이스든
접속 가능. 외부 노출이 필요하면 `.env` 의 `APP_WS_HOST`, `APP_HTTP_HOST` 를 `127.0.0.1` 로
좁힐 수 있음.

## 2. WebSocket 페이로드 스펙

본 노드가 매 frame `ws://<ai-pi-02-ip>:8765` 에 broadcast하는 JSON:

```json
{
  "timestamp": 1735000000,
  "fall_prob": 0.8,
  "status": "FALL",
  "pose_data": [
    {"x": 0.5123, "y": 0.4456, "z": 0.0021, "visibility": 0.95},
    {"x": 0.5102, "y": 0.4301, "z": 0.0019, "visibility": 0.92},
    "... 33개 (MediaPipe Pose 표준 인덱스 0~32) ..."
  ],
  "video_clip_url": null
}
```

### 필드

| 필드 | 타입 | 범위/형식 | 설명 |
|---|---|---|---|
| `timestamp` | int | Unix epoch(seconds) | frame 발생 시각. `frame.timestamp` 의 int 캐스트 |
| `fall_prob` | float | [0.0, 1.0] | 매 frame 낙상 확률. 자세한 산정은 §3 |
| `status` | string | `"NORMAL"`/`"WARNING"`/`"FALL"` | 현재 상태 (fall_prob와 일치하도록 산정됨) |
| `pose_data` | array(33) | — | MediaPipe 33-landmark. 누락된 id는 visibility=0.0으로 패딩 |
| `video_clip_url` | null | — | 본 노드에서는 항상 `null` (영상 미지원) |

### `pose_data[i]` 구조

| 키 | 타입 | 범위 |
|---|---|---|
| `x` | float | 0.0~1.0 (정규화 가로) |
| `y` | float | 0.0~1.0 (정규화 세로, 0=상) |
| `z` | float | ~-1~+1 (엉덩이 중점 기준 깊이) |
| `visibility` | float | 0.0~1.0 (가시성/신뢰도) |

> 앱 측 핸드오프 문서의 `v` 필드를 그대로 받지 않고 **`visibility` 로 키를 변경**해 송신함.
> 앱이 이미 `visibility` 키로 파싱하고 있어 호환됨 (`main.dart:54-68`).

## 3. fall_prob 산정 방식

매 frame 본 노드의 `rule_gate.state` 에 따라:

| 내부 state | status | fall_prob (기본) | 비고 |
|---|---|---|---|
| NORMAL | `"NORMAL"` | 0.0 | 직립/평상 |
| DESCENDING | `"WARNING"` | 0.5 | 낙상 의심 |
| FALLEN (not confirmed) | `"FALL"` | 0.8 | 누운 자세 감지 |
| FALLEN (confirmed) | `"FALL"` | **fused_confidence** | rule + CNN 융합값 |

값은 `.env` 의 `APP_WARNING_PROB`, `APP_FALL_PROB` 로 조정 가능.

confirmed 시점 1프레임의 fall_prob는 실제 fused confidence(보통 0.7~0.95)로
override되어 더 강한 알림 트리거가 됨.

## 4. 임계값 일치

`main.dart`의 `FallData.fromJson` 이 `fall_prob >= 0.7` 을 FALL로, `>= 0.4` 를 WARNING으로
**재계산**합니다. 본 노드의 출력 임계값과 맞춰져 있어 호환됩니다 (FALL=0.8, WARNING=0.5).

권장 사항(앱 측): 핸드오프 문서 §3.4 의 제안대로 **앱이 status 문자열을 그대로 신뢰**하도록
변경하면 임계값 미스매치 우려가 없어집니다.

## 5. HTTP 헬스 체크

```http
GET /health
→ 200 OK
{"status": "ok", "ws_clients": 2}
```

- `ws_clients`: 현재 WebSocket 연결 수
- 다른 path는 404. 영상 관련 path(`/recordings/...`, `/stream`)는 본 노드 미지원.

앱은 시작 시 한 번 호출해 서버 가용성 확인하는 용도로 사용.

## 6. 발행 주기 & 연결 동작

- **frame 송신 주기**: vision-pi가 보내는 frame rate를 그대로 따름 (대개 3~10 fps).
- **client 0개**: WS broadcast는 즉시 종료 (서버 비용 0). main loop 블로킹 없음.
- **client N개**: 모두에게 동일 페이로드 송신. multi-device 보호자 대응 가능.
- **연결 끊김**: 자동 정리. client 재연결 시 즉시 stream 재개.
- **back-pressure**: 송신 큐 최대 32 frame, 가득 차면 가장 오래된 frame drop.
  (slow client가 다른 client 지연시키지 않음)

## 7. 앱 측 권장 처리

```dart
// 의사 코드
final ws = WebSocketChannel.connect(Uri.parse('ws://192.168.0.X:8765'));
ws.stream.listen((raw) {
  final data = FallData.fromJson(jsonDecode(raw));
  // status 신뢰 사용 권장
  if (data.status == 'FALL') showAlert(data);
  updatePoseOverlay(data.poseData);
});
```

- **재연결**: WS 끊기면 exponential backoff (1s→2s→4s, max 30s) 로 재연결 권장.
- **헬스 미회신**: `/health` 가 응답 없으면 "AI 서버 연결 실패" UI.
- **fall 알람 중복 방지**: state가 FALL→NORMAL 천이될 때만 다이얼로그 1회 (현재 앱 동작 유지).

## 8. 개발 환경에서 본 노드 없이 모킹

조원이 Pi 없이 앱 개발할 수 있게 mock publisher 제공 예정 (`tools/mock_app_publisher.py`).
즉시 사용 가능한 임시 명령:

```bash
# 30초 동안 매 frame 페이로드 송신하는 임시 mock (websocat 등으로 수동 송신 가능)
# Pi의 fall 시연 영상 녹화본을 그대로 재생하는 방식은 vision-pi 자료가 있어야 함.
```

## 9. systemd 서비스 동작

`deploy/edgesafe-ai.service` 로 등록되어 부팅 시 자동 시작. 앱이 Pi에 붙으려면
Pi 부팅 후 30~60초 뒤부터 가능 (Mosquitto + vision-pi 연결 대기).

```bash
systemctl is-active edgesafe-ai           # active
sudo journalctl -u edgesafe-ai -f         # 실시간 로그
sudo bash deploy/install.sh --logs        # 최근 로그 100줄
```

## 10. 향후 확장 (조원과 합의 필요)

- **MJPEG 라이브 스트림**: capstone-vision(vision-pi) 또는 별도 ESP32-CAM 모듈이 책임
- **영상 클립 저장**: vision-pi가 ±20초 ring buffer 운영, ai-pi-02의 fall 이벤트로 flush
- **본 노드의 MQTT 채널 활용**: 보호자 다중 디바이스 + 클라우드 브리지 시 MQTT가 유리
  - 토픽 `edgesafe/ai/fall`, `edgesafe/ai/status` 는 이미 운영 중
  - 자세한 schema는 `docs/OUTPUT_SCHEMA.md` 참조
