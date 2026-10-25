import sys

from patch_tools import write

repo = sys.argv[1]

DOC = """# Stock reservation

## Problem and goals

Stock is taken from the warehouses when an order is placed (`OrderService.create_order` calls
`StockLedger.allocate`). A shopper who is still in checkout holds nothing, so the last units can be sold to someone
else while the first shopper is paying. We want to hold stock for an unconfirmed order for N minutes.

Goals:

- A reservation holds units of one SKU across the warehouses, drawn in the same priority order as an order.
- An unconfirmed reservation expires after N minutes (default 15, configurable) and its units become available again.
- Confirming a reservation creates the order from exactly the units that were held.
- Two requests for the same SKU never hand out more units than exist.

## Non-goals

- Payment handling, carts, or customer accounts.
- Reservations that outlive a day, or recurring holds.
- Moving the JSON file to a database. The design must work with the current single-file storage.

## Design

### Data

`Database` gets a `reservations` map. A `Reservation` holds `id`, `sku`, `quantity`, `allocations` (the same
`Allocation` records orders use), `created_at`, `expires_at`, and `status` (`held`, `confirmed`, `released`,
`expired`). Held units are subtracted from the warehouse levels immediately, exactly like an order allocation, so
`StockLedger.total` and the reports keep meaning "units that can still be sold".

### Operations

- `ReservationService.reserve(sku, quantity, ttl)` calls `StockLedger.allocate` with the reference
  `reservation-<id>:hold`, which records the per-warehouse split, and stores the reservation.
- `ReservationService.confirm(reservation_id)` checks that the reservation is `held` and not past `expires_at`
  (using the injected clock), then moves its allocations onto a new order line without touching stock again.
- `ReservationService.release(reservation_id)` calls `StockLedger.release` for the stored allocations and marks the
  reservation `released`.
- Expiry is lazy plus a sweep: every `reserve` and `confirm` first calls `expire_due()`, which releases all held
  reservations whose `expires_at` is not after `clock()`. `inventory reservation sweep` runs the same function from cron.

### Concurrency

The data file is read and replaced as a whole, so the unit of safety is the file. `JsonStore.save` becomes
read-modify-write under an exclusive `fcntl.flock` on a lock file next to the data file: each CLI command loads,
changes, and saves while holding the lock. Two simultaneous `reserve` calls for the last unit are therefore
serialized; the second sees the reduced stock and fails with `InsufficientStock`. Because allocation runs in
warehouse priority order inside that critical section, two warehouses cannot be double-drawn.

### Interaction with cancellation

`cancel_order` keeps releasing the per-line allocations. A confirmed reservation hands its allocations to the order
line, so cancelling the order returns the units to the same warehouses as before. Cancelling a reservation that is
still held calls `release`. An expired reservation is already released, so confirming it raises `ReservationExpired`
and the shopper must reserve again.

## Alternatives considered

1. Hold counters in a separate table and subtract them when reading availability. Rejected: every reader
   (`total`, reports, `allocate`) must remember to subtract holds, and a forgotten call oversells.
2. Background thread that expires holds. Rejected: the service is a CLI over a file and has no long-running process.
3. Optimistic version number on the file instead of a lock. Considered: it avoids lock files but needs retry logic in
   every command; revisit if the storage moves to a database.

## Risks and open questions

- `fcntl.flock` is not available on Windows; the lock helper needs a fallback if Windows is supported.
- Lazy expiry means a reservation can show as `held` after its time until the next command runs; reports must call
  `expire_due()` first.
- Open: should a reservation allow several SKUs at once? The first version holds one SKU per reservation.
- Open: the default N and whether it is per customer.

## Test plan

- Reserve then let the injected clock pass `expires_at`; the next `reserve` sees the units again.
- Two reservations for the last unit: the second fails with `InsufficientStock`, and the audit log nets to zero.
- Reserve across two warehouses, confirm, cancel the order: each warehouse returns to its starting level.
- Confirm after expiry raises `ReservationExpired` and leaves stock unchanged.
- A lock test starts two processes that reserve the same SKU and checks that total reserved never exceeds stock.
"""

MIRROR = """# 재고 예약

> 영어 원본: [docs/design/stock-reservation.md](../../../../docs/design/stock-reservation.md). 이 문서는 번역본이며 원본보다 우선하지 않습니다.

## 문제와 목표

주문을 넣을 때 창고에서 재고를 차감합니다(`OrderService.create_order`가 `StockLedger.allocate`를 부릅니다). 결제 중인
고객은 아무것도 잡아 두지 못하므로, 첫 고객이 결제하는 동안 마지막 수량이 다른 사람에게 팔릴 수 있습니다. 확정되지 않은
주문을 위해 재고를 N분 동안 잡아 두려고 합니다.

목표:

- 예약은 한 SKU의 수량을 주문과 같은 우선순위로 여러 창고에서 잡습니다.
- 확정되지 않은 예약은 N분(기본 15분, 설정 가능) 뒤 만료되고 수량이 다시 판매 가능해집니다.
- 예약을 확정하면 잡아 둔 수량 그대로 주문이 만들어집니다.
- 같은 SKU에 대한 두 요청이 실제 재고보다 많이 내주는 일은 없습니다.

## 비목표

- 결제 처리, 장바구니, 고객 계정.
- 하루를 넘기는 예약이나 반복 예약.
- JSON 파일을 데이터베이스로 바꾸는 일. 현재의 단일 파일 저장소에서 동작해야 합니다.

## 설계

영어 원본의 데이터, 연산, 동시성, 취소와의 상호작용 절을 따릅니다. 핵심은 예약이 주문과 같은 `Allocation` 기록으로 재고를
즉시 차감하고, 만료는 `reserve`와 `confirm` 호출 때 게으르게 처리하며(`expire_due()`), 파일 전체를 읽고 쓰는 구간을
`flock`으로 직렬화한다는 점입니다.

## 검토한 대안

1. 별도 테이블에 예약 수량을 두고 조회 때마다 뺍니다. 모든 읽기 경로가 빼는 것을 기억해야 해서 과다 판매 위험이 있어
   채택하지 않았습니다.
2. 만료를 처리하는 백그라운드 스레드. 상주 프로세스가 없는 CLI라서 채택하지 않았습니다.
3. 잠금 대신 파일 버전 번호를 쓰는 낙관적 방식. 모든 명령에 재시도 로직이 필요해 저장소를 DB로 옮길 때 다시 검토합니다.

## 위험과 열린 질문

- `fcntl.flock`은 Windows에 없으므로 Windows를 지원하려면 대체 수단이 필요합니다.
- 게으른 만료 때문에 다음 명령이 실행되기 전까지 만료된 예약이 `held`로 보일 수 있습니다.
- 열린 질문: 한 예약에 여러 SKU를 허용할지, 기본 N을 고객별로 둘지.

## 테스트 계획

- 예약 후 주입한 시계를 만료 시각 뒤로 보내면 다음 `reserve`가 그 수량을 다시 봅니다.
- 마지막 한 개에 대한 두 예약 중 두 번째는 `InsufficientStock`으로 실패하고 감사 로그 합계가 0입니다.
- 두 창고에 걸쳐 예약하고 확정한 뒤 주문을 취소하면 각 창고가 처음 수량으로 돌아갑니다.
- 만료 뒤 확정하면 `ReservationExpired`가 나고 재고는 그대로입니다.
- 두 프로세스가 같은 SKU를 예약해도 예약 합계가 재고를 넘지 않는지 확인하는 잠금 테스트.
"""

write(repo, "docs/design/stock-reservation.md", DOC)
write(repo, "docs/ko/docs/design/stock-reservation.ko.md", MIRROR)
