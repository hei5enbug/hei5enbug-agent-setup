-- demo.orders: 주문 한 건이 한 행이다.
CREATE TABLE demo.orders (
    id          bigint PRIMARY KEY,
    status      text        NOT NULL,
    placed_at   timestamptz NOT NULL,
    legacy_code text,          -- 2025년부터 모든 행이 비어 있다
    old_status  text           -- status 로 옮겨 담은 옛 값이다
);
