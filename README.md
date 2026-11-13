# CathPlot

CATHENA 해석 결과 등 시간 이력 데이터(Time-history data)를 불러와 곡선을 구성하고, 그래프를 생성·비교·저장·출력하기 위한 Windows 데스크톱 GUI 프로그램입니다.

## 주요 기능

- **데이터 읽기 및 파싱**: CATHENA DAT 파일의 OUTPUT 정의, 신호 이름, 배율 및 DATA 영역을 읽습니다. 시간 열과 신호별 데이터 열을 처리하며, 주석 및 빈 줄을 구분합니다.
- **그래프 구성**: 데이터 신호를 곡선으로 구성하고 선 색상·선 종류·마커 등 표시 스타일을 설정할 수 있습니다.
- **그래프 생성**: 외부 그래프 엔진인 gnuplot을 이용해 그래프를 생성합니다.
- **복수 작업 처리**: Batch Set/Queue 방식으로 여러 그래프 작업을 관리하고, 제한된 병렬 실행으로 처리 시간을 줄입니다.
- **애니메이션 및 미리보기**: 그래프 애니메이션과 출력 전 미리보기 등 GUI 기능을 제공합니다.
- **결과 저장 및 출력**: PDF, PNG/JPG, SVG, EMF 등 그래픽 형식의 변환·저장 기능과 인쇄 기능을 지원합니다. 실제 지원 형식과 옵션은 설치 버전 및 gnuplot 환경에 따라 달라질 수 있습니다.
- **Windows 실행 파일 배포**: PyInstaller 설정(CathPlot.spec)을 사용해 실행 파일 배포 폴더를 구성하며, 사용자 설명서·변경 이력·발표자료를 함께 배포하도록 설정되어 있습니다.

## 구성 파일

| 파일 | 설명 |
|---|---|
| `cathplot_gui.py` | Tkinter 기반 메인 GUI 및 사용자 작업 흐름 |
| `data_parser.py` | CATHENA DAT 데이터와 메타데이터 파싱, 데이터 변환 공통 함수 |
| `gnu_generator.py` | gnuplot 스크립트 생성, 그래프 렌더링 및 출력 형식 변환 |
| `requirements.txt` | Python 외부 패키지 목록 |
| `CathPlot.spec` | PyInstaller 패키징 설정 |

## 개발 및 실행 환경

- OS: Windows (인쇄 및 일부 GUI 연동 기능은 Windows API 사용)
- Python: Python 3 환경
- GUI: Tkinter
- Plot engine: gnuplot (별도 설치 및 실행 경로 설정 필요)
- 주요 Python 패키지:
  - `pywin32`: Windows 인쇄 및 GUI 연동
  - `Pillow`: 이미지 처리, PNG 해상도 및 폰트 관련 처리
  - `PyMuPDF`: PDF 렌더링 및 PDF 기반 이미지/SVG 변환

## 설치 및 실행

1. Python 3와 gnuplot을 설치합니다.
2. 저장소를 내려받거나 복제합니다.
3. 필요한 Python 패키지를 설치합니다.

   ```bash
   pip install -r requirements.txt
   ```

4. gnuplot 실행 파일을 사용할 수 있도록 시스템 PATH 또는 프로그램 설정을 확인합니다.
5. 프로그램을 실행합니다.

   ```bash
   python cathplot_gui.py
   ```

> 실제 배포·운영 환경의 상세 설치 절차, gnuplot 경로 설정 및 화면별 사용법은 저장소에 포함된 사용자 설명서를 우선 참조하십시오.

## 문서

- [사용 설명서 (V1.0)](CathPlot_사용설명서(V1.0).docx)
- [변경 이력 (V1.0)](CathPlot_변경이력(V1.0).docx)
- [CathPlot 발표자료](CathPlot_발표.pptx)

## 참고 사항

- DAT 파일의 신호 정의와 DATA 열은 서로 대응하며, DATA의 첫 번째 열은 시간(Time)입니다.
- gnuplot은 Python 패키지와 별도로 설치해야 하는 외부 프로그램입니다.
- 일부 이미지·인쇄·변환 기능은 Windows 환경 및 선택적 패키지 설치 여부에 영향을 받습니다.
- 본 README는 저장소의 소스 코드, 의존성 및 포함 문서의 파일 구성을 바탕으로 작성한 개요입니다. 세부 사용법과 최신 변경 사항은 사용자 설명서 및 변경 이력을 확인하십시오.
