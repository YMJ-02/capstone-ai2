#!/usr/bin/env bash
# systemd 서비스 설치 스크립트. 라즈베리파이에서 sudo로 실행.
#
# 사용:
#   bash deploy/install.sh           # 설치 + enable + start
#   bash deploy/install.sh --status  # 상태 확인
#   bash deploy/install.sh --logs    # 최근 로그
#   bash deploy/install.sh --remove  # 제거

set -euo pipefail

SERVICE_NAME="edgesafe-ai"
SERVICE_FILE="$(dirname "$(readlink -f "$0")")/edgesafe-ai.service"
SYSTEM_DIR="/etc/systemd/system"
TARGET="${SYSTEM_DIR}/${SERVICE_NAME}.service"

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "[install.sh] sudo 권한이 필요합니다. 다시 시도: sudo bash $0 $*"
    exit 1
  fi
}

cmd_install() {
  require_root
  if [[ ! -f "$SERVICE_FILE" ]]; then
    echo "[install.sh] 서비스 파일 누락: $SERVICE_FILE" >&2
    exit 1
  fi
  echo "[install.sh] 서비스 파일 복사: $SERVICE_FILE → $TARGET"
  cp "$SERVICE_FILE" "$TARGET"
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  sleep 1
  systemctl --no-pager --full status "$SERVICE_NAME" || true
  echo
  echo "[install.sh] 로그 보기: journalctl -u $SERVICE_NAME -f"
}

cmd_status() {
  systemctl --no-pager --full status "$SERVICE_NAME" || true
}

cmd_logs() {
  journalctl -u "$SERVICE_NAME" -n 100 --no-pager
}

cmd_remove() {
  require_root
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "$TARGET"
  systemctl daemon-reload
  echo "[install.sh] $SERVICE_NAME 제거 완료"
}

case "${1:-install}" in
  install|"") cmd_install ;;
  --status)   cmd_status ;;
  --logs)     cmd_logs ;;
  --remove)   cmd_remove ;;
  *)
    echo "사용법: $0 [install|--status|--logs|--remove]"
    exit 2
    ;;
esac
