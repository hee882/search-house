import os
import subprocess

def run_git(args):
    subprocess.run(["git"] + args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 1. Reset soft to initial commit
run_git(["reset", "--soft", "e78f013"])
run_git(["reset", "HEAD"]) # Unstage everything

# 2. Commit Documents
run_git(["add", "PLAN.md", "README.md", "CLAUDE.md", "GEMINI.md", ".claude/", ".gitignore"])
run_git(["commit", "-m", "문서: 프로젝트 계획, 가이드라인 및 README 추가"])

# 3. Commit Infra (GitHub Actions)
run_git(["add", ".github/"])
run_git(["commit", "-m", "인프라: 실거래가 데이터 자동 수집 및 프론트엔드 배포 파이프라인 구축"])

# 4. Commit Backend
run_git(["add", "server/"])
run_git(["commit", "-m", "백엔드: FastAPI 기반 샐러리맨 워라밸 최적화 및 히든 코스트 알고리즘 구현\n\n- 국토교통부 실거래가 연동 API 구축\n- 통근 피로도 기반 '히든 라이프 코스트' 계산 엔진 적용\n- CORS 및 클라우드(Render) 배포 환경 최적화"])

# 5. Commit Frontend
run_git(["add", "client/"])
run_git(["commit", "-m", "프론트엔드: React 기반 프리미엄 지도 시각화 및 UI/UX 고도화\n\n- 샐러리맨 생존 모드 마케팅 카피 및 글래스모피즘 UI 적용\n- 지능형 2단계 줌 및 통근 경로(나/배우자) 동적 시각화\n- 한글 초성 기반 역 검색 드롭다운 및 지하철 호선 공식 색상 칩 적용\n- 네이버 부동산 단지 상세 페이지 다이렉트 연동\n- 사용자 경험을 해치지 않는 애드센스 2선 영역 배치"])

# 6. Check if anything is left and commit it
result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
if result.stdout.strip():
    run_git(["add", "."])
    run_git(["commit", "-m", "기타: 프로젝트 설정 및 의존성 업데이트"])

print("All commits rewritten successfully in Korean.")
