# Phosphorus Sublimation Arrhenius Analyzer

적린 승화 실험 데이터를 읽어 조건별 질량 소모속도, Arrhenius fitting, 온도/시간 예측, 장시간 constant-rate schedule을 계산하는 Python 데스크톱 GUI입니다.

## 설치 및 실행

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

또는:

```bat
run_app.bat
```

## 테스트

```bat
pytest -v
```

## 사용한 Excel 범위

- `수식` 시트: Excel 90행 header, 91-106행 데이터, A:J 열만 사용
- `전체 기록` 시트: Excel 1행 header, 지정 행만 사용
  - 2-6, 8, 23, 28-31, 41-43, 50, 64
- 다른 시트와 다른 행은 분석하지 않습니다.

## 압력 normalization

- raw `0.15 Torr`는 canonical `0.15 Torr / Ar 20 sccm`
- raw `0.029 Torr`와 `0.02 Torr`는 canonical `0.02 Torr / Ar 0 sccm`
- 원본 압력값과 canonical 압력값은 모두 export에 남깁니다.

## 온도 보정

- `"365(MFC)=374"`는 사용자 지정 보정으로 `373.5℃`로 변환합니다.
- 다음 연속 `"365(MFC)"`도 조건이 맞으면 `373.5℃`를 상속합니다.
- `374℃` 그룹은 만들지 않고 `373.5℃` 그룹으로 fitting합니다.

## 질량 소모 계산

- `수식` 시트: `p1 - p2`, `T2 - T1`로 interval 소모속도 계산
- `전체 기록` 시트: 각 행을 0분부터 측정시간까지의 독립 누적 실험으로 보고 `초기 P - 잔여 P`를 계산
- 전체 기록의 잔류량끼리 직접 빼지 않고, 누적 소모량 차이로 interval을 생성합니다.
- 기존 퍼센트 소모율 열은 fitting에 사용하지 않습니다.
- 수분 보정과 200 mg 고정 분모 보정은 적용하지 않습니다.

## Interval 병합 및 중복 처리

- 기본 fitting에서는 30-40분과 40-60분 short interval을 30-60분으로 병합합니다.
- 원래 short interval과 merged interval을 동시에 fitting하지 않습니다.
- 두 시트에 동일 실험이 있으면 `수식` 시트 데이터를 우선합니다.

## Arrhenius 식

```text
q(T) = A * exp(-Ea / (R * T))
```

- q: P 질량 소모속도, mg/min
- Ea: apparent activation energy, J/mol
- R = 8.314462618 J/(mol*K)
- T: K

`0.15 Torr / Ar 20 sccm`과 `0.02 Torr / Ar 0 sccm`은 독립적으로 fitting합니다.

## Prediction 탭

condition, 초기 P 질량, 온도, 공정시간, surface-area scaling factor를 입력하면 예상 소모량과 잔류량을 계산합니다.

중요: 초기 P 총량만으로 소모속도가 자동 확대되지 않습니다. 이 모델의 rate는 실험 source geometry에서 측정된 질량 소모속도입니다.

## Constant Rate Schedule 탭

목표 평균 소모속도와 최소 순간 소모속도를 만족하는 장시간 온도 schedule을 계산합니다.

기본값:

- Target average rate: 120 mg/hour
- Minimum instantaneous rate: 80 mg/hour
- Temperature increment: 5℃
- Minimum stage duration: 0.5 hour
- Maximum stage count: 8

## 모델 한계

- 측정 온도 범위 밖 예측은 extrapolation입니다.
- 0.02 Torr 모델은 raw 0.029/0.02를 사용자 규칙으로 통합한 모델입니다.
- surface-area factor는 실험 geometry 차이를 보정하기 위한 계수이며, 자동 추정하지 않습니다.
- startup interval에는 초기 안정화, 수분 탈착, 표면 효과가 포함될 수 있습니다.
