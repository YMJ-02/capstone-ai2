# 입력 스키마 — vision-pi (capstone-vision) → ai-pi-02

전송 계층: **ZeroMQ PUB/SUB**, 토픽 prefix 방식.

- vision-pi: `tcp://0.0.0.0:5555` 바인딩, topic `pose`
- ai-pi-02 (본 노드): SUB → `tcp://<vision-pi>:5555` 연결

메시지는 `"<topic> <json>"` 단일 문자열로 발행된다.

## JSON 페이로드

```json
{
  "node_id": "vision-pi-01",
  "frame_id": 142,
  "timestamp": 1735689012.345,
  "image_size": [640, 480],
  "landmarks": [
    {"id": 0,  "x": 0.5023, "y": 0.3145, "z": -0.0712, "v": 0.9821},
    {"id": 1,  "x": 0.5102, "y": 0.3001, "z": -0.0689, "v": 0.9756},
    "...",
    {"id": 32, "x": 0.6055, "y": 0.8211, "z":  0.0034, "v": 0.8732}
  ]
}
```

## 필드

| 필드 | 타입 | 단위/범위 | 설명 |
|---|---|---|---|
| `node_id` | string | – | vision 노드 식별자 |
| `frame_id` | int | 0→∞ | 단조증가, 드롭 감지용 |
| `timestamp` | float | Unix epoch sec | vision-pi의 `time.time()` |
| `image_size` | [int,int] | px [W,H] | 정규화 좌표 → 픽셀 환산 시 사용 |
| `landmarks` | array(33) | – | 33개 MediaPipe Pose 랜드마크 |

## 랜드마크

| 키 | 범위 | 의미 |
|---|---|---|
| `id` | 0–32 | 인덱스 |
| `x` | 0.0–1.0 | 정규화 가로 (0=좌, 1=우) |
| `y` | 0.0–1.0 | 정규화 세로 (0=상, 1=하) |
| `z` | ~−1~+1 | 엉덩이 중점 기준 깊이 (음=카메라쪽) |
| `v` | 0.0–1.0 | 가시성/신뢰도 |

## 주요 인덱스 (낙상 관련)

- 0: 코
- 11/12: 어깨 (L/R)
- 13/14: 팔꿈치
- 15/16: 손목
- 23/24: 엉덩이
- 25/26: 무릎
- 27/28: 발목
- 29–32: 발

전체 매핑은 MediaPipe Pose Landmark Model 공식 문서 참조.

## 픽셀 환산

```
px_x = x * image_size[0]
px_y = y * image_size[1]
```

## 출처

원본: `YMJ-02/capstone-vision/docs/INTERFACE.md`
