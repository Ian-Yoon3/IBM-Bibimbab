# Baseline V1 데이터 사전

`data/`는 UTF-8 CSV, 쉼표 구분, 첫 줄 헤더입니다. 날짜는 `YYYY-MM-DD` 형식의 달력일입니다. `int`는 정수, `ID`는 문자열 식별자, `FK`는 참조 키입니다. `scenarios.disruption_id`만 빈 값을 허용합니다. 금액은 가상 USD입니다. BOM에 없는 조합의 소요량은 0입니다.

## products.csv (3행)

기본 키 `product_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `product_id` | ID | 완제품 키 |
| `product_name` | text | 완제품명 |
| `production_days` | int | 자재 투입부터 완료까지 달력일 |

## components.csv (5행)

기본 키 `component_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `component_id` | ID | 부품 키 |
| `component_name` | text | 부품명 |
| `uom` | enum | 수량 단위 EA |

## bom.csv (12행)

기본 키 `product_id + component_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `product_id` | FK products | 완제품 |
| `component_id` | FK components | 투입 부품 |
| `qty_per_unit` | int | 완제품 1 EA당 부품 EA |

## suppliers.csv (4행)

기본 키 `supplier_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `supplier_id` | ID | 공급업체 키 |
| `supplier_name` | text | 가상 공급업체명 |

## warehouses.csv (3행)

기본 키 `warehouse_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `warehouse_id` | ID | 창고 키 |
| `warehouse_name` | text | 창고명 |
| `role` | enum | PRODUCTION 또는 BUFFER |

## inventory.csv (15행)

기본 키 `warehouse_id + component_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `warehouse_id` | FK warehouses | 보유 창고 |
| `component_id` | FK components | 부품 |
| `on_hand_qty` | int | 기준일 기초 실물재고 EA |
| `reserved_qty` | int | 외부 작업에 이미 배정된 수량 EA |
| `protected_qty` | int | 별도로 보호하는 안전재고 EA |

## orders.csv (12행)

기본 키 `order_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `order_id` | ID | 고객 주문 키 |
| `customer_id` | ID | 가상 고객 코드 |
| `product_id` | FK products | 주문 완제품 |
| `qty` | int | 완제품 주문량 EA |
| `due_date` | date | 고객 납기 |
| `priority_rank` | int | 같은 납기에서 작은 값 우선 |
| `warehouse_id` | FK warehouses | 자재 투입 창고 |

## supplier_offers.csv (6행)

기본 키 `offer_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `offer_id` | ID | 공급 조건 키 |
| `supplier_id` | FK suppliers | 제안 공급업체 |
| `component_id` | FK components | 공급 부품 |
| `lead_days` | int | 발주부터 도착까지 달력일 |
| `unit_cost_usd` | int | 개당 구매 단가 USD |
| `fixed_fee_usd` | int | 건당 고정비 USD |
| `min_qty` | int | 최소 발주량 EA |
| `multiple_qty` | int | 발주 배수 EA |
| `max_qty` | int | 대안별 최대 구매량 EA |

## purchase_orders.csv (1행)

기본 키 `po_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `po_id` | ID | 확정 PO 행 키 |
| `offer_id` | FK supplier_offers | 계약 공급 조건 |
| `warehouse_id` | FK warehouses | 입고 창고 |
| `order_date` | date | 기존 발주일 |
| `qty` | int | 미입고 확정 수량 EA |
| `planned_receipt_date` | date | 기존 예정 입고일 |

## disruptions.csv (1행)

기본 키 `disruption_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `disruption_id` | ID | 중단 이벤트 키 |
| `po_id` | FK purchase_orders | 영향받은 PO |
| `reported_date` | date | 중단 인지일 |
| `revised_receipt_date` | date | 수정 입고일 |
| `reason` | text | 가상 원인 |

## transfer_lanes.csv (2행)

기본 키 `lane_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `lane_id` | ID | 이전 경로 키 |
| `from_warehouse_id` | FK warehouses | 출발 창고 |
| `to_warehouse_id` | FK warehouses | 도착 창고 |
| `lead_days` | int | 출발부터 입고까지 달력일 |
| `max_qty` | int | 대안별 경로 운송 한도 EA |
| `unit_cost_usd` | int | 개당 이전비 USD |
| `fixed_fee_usd` | int | 출고 건당 비용 USD |

## scenarios.csv (5행)

기본 키 `scenario_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `scenario_id` | ID | 대안 키 |
| `disruption_id` | nullable FK disruptions | 적용 중단 ID. 빈 값이면 정상 |
| `label` | text | 비교 대안명 |

## recovery_purchases.csv (2행)

기본 키 `scenario_id + offer_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `scenario_id` | FK scenarios | 독립 평가 대안 |
| `offer_id` | FK supplier_offers | 대체 공급 조건 |
| `warehouse_id` | FK warehouses | 입고 창고 |
| `action_date` | date | 신규 발주 가정일 |
| `qty` | int | 신규 구매 EA |

## recovery_transfers.csv (4행)

기본 키 `scenario_id + lane_id + component_id`.

| 필드 | 형식 | 정의 |
|---|---|---|
| `scenario_id` | FK scenarios | 독립 평가 대안 |
| `lane_id` | FK transfer_lanes | 창고 이전 경로 |
| `component_id` | FK components | 이전 부품 |
| `action_date` | date | 출고 가정일 |
| `qty` | int | 이전 EA |
