# parcel-desk

> 영어 원본: [README.md](../../README.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

소포 배송 견적 도구입니다. 견적은 청구 무게와 구역에 따른 기본 요금, 유류 할증, 선택 보험으로 이루어집니다.

## 사용법

```bash
python3 -m parcel quote --weight 1180 --zone B
python3 -m parcel quote --weight 2500 --zone A --declared 20000
```

- `quote --weight GRAMS --zone ZONE [--declared CENTS]`는 라벨과 견적을 센트 단위로 출력합니다.
- 무게는 500 g 단위로 올림해 청구합니다. 기본 요금은 청구 무게에 구역별 500 g당 요율을 곱한 값입니다.
- 유류 할증은 기본 요금의 8%입니다. 보험은 신고 가액의 1%이며 최소 50센트이고, 신고하지 않으면 0입니다.
- 명령이 실패하면 이유를 stderr에 출력하고 종료 코드 2로 끝납니다.

## 개발

```bash
python3 -m pytest -q
```

기여 규칙은 [AGENTS.md](../../AGENTS.md)에 있습니다. 이 문서의 한국어 번역본이 지금 보고 계신
[docs/ko/README.ko.md](README.ko.md)입니다.
