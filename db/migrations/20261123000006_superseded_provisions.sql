-- migrate:up

-- Điều/Khoản của một văn bản bị văn bản khác bãi bỏ hoặc thay nội dung (Task 3.2).
-- Văn bản bị sửa đổi một phần vẫn có trạng thái AMENDED, nhưng các Điều/Khoản ở đây không còn hiệu
-- lực kể từ effective_date. VD: NĐ 168/2024 bãi bỏ Điều 5-11, 16-22... của NĐ 100/2019 (phần đường
-- bộ), trong khi phần đường sắt của NĐ 100/2019 vẫn còn hiệu lực.
CREATE TABLE superseded_provisions (
  target_number  text NOT NULL,   -- văn bản bị tác động
  article        text NOT NULL,   -- "Điều 6"
  clause         text NOT NULL DEFAULT '',  -- "Khoản 2"; '' = cả Điều
  kind           text NOT NULL CHECK (kind IN ('repealed', 'amended')),
  source_number  text NOT NULL,   -- văn bản bãi bỏ / sửa đổi
  effective_date date,            -- kể từ ngày này Điều/Khoản không còn hiệu lực
  evidence       text NOT NULL,
  PRIMARY KEY (target_number, article, clause, source_number)
);

-- migrate:down
DROP TABLE IF EXISTS superseded_provisions;
