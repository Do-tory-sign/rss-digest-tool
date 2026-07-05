"""스케줄러로 실행될 때 콘솔 출력을 파일로도 남기는 헬퍼.

Task Scheduler는 콘솔 출력을 어디에도 저장 안 하기 때문에, 실패해도 사후에
원인을 알 방법이 없었다 (2026-06-24 인스타 업로드 실패 원인 추적 불가 사고).
이걸 호출해두면 output/오늘날짜/{label}.log에 그날 실행 기록이 남는다.
"""
import sys
from datetime import datetime
import config


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def reconfigure(self, *args, **kwargs):
        """다른 모듈(v2_main.py 등)이 import 시점에 sys.stdout.reconfigure()를 호출해도
        _Tee로 바꿔치기된 stdout/stderr에는 그 메서드가 없어 AttributeError가 났다
        (2026-06-24 인스타 카드 v2 합성 매번 실패 사고). 실제 스트림에 위임만 해주면 됨."""
        for s in self.streams:
            try:
                s.reconfigure(*args, **kwargs)
            except Exception:
                pass

    def __getattr__(self, name):
        for s in self.streams:
            if hasattr(s, name):
                return getattr(s, name)
        raise AttributeError(name)


def enable(label: str):
    """오늘자 output 폴더에 {label}.log로 stdout/stderr 동시 기록 시작. 로그 파일 경로 반환."""
    today = datetime.now().strftime("%Y%m%d")
    log_dir = config.OUTPUT_DIR / today
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{label}.log"
    f = open(log_path, "a", encoding="utf-8")
    f.write(f"\n===== {datetime.now().isoformat()} =====\n")
    sys.stdout = _Tee(sys.stdout, f)
    sys.stderr = _Tee(sys.stderr, f)
    return log_path
