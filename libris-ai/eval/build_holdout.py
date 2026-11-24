"""Sinh eval/holdout.jsonl – bộ câu hỏi kiểm tra độc lập (hold-out).

Không dùng khi tinh chỉnh: chỉ để đo xem các cải tiến rút ra từ Golden Dataset (ánh xạ thuật ngữ, hư
từ, giảm điểm lĩnh vực chuyên biệt, tách câu nhiều ý...) có đúng với câu hỏi mới hay chỉ "học thuộc
đề". Đáp án đối chiếu nguyên văn trong kho như golden.jsonl. Định dạng giống golden.jsonl.
"""

from __future__ import annotations

import json
from pathlib import Path

from build_golden import BL19, HNGD, LD24, N168, TT, r

ITEMS = [
    # ---------------- Điều luật chưa có trong Golden Dataset
    ("lao_dong", "easy", "fact", "Mỗi tuần người lao động được nghỉ tối thiểu bao lâu?",
     "Mỗi tuần người lao động được nghỉ ít nhất 24 giờ liên tục.", [r(BL19, "Điều 111")], ["24 giờ"], {}),
    ("lao_dong", "medium", "colloquial", "Làm cho một công ty được 5 năm thì có được thêm ngày phép năm không?",
     "Có: cứ đủ 05 năm làm việc cho một người sử dụng lao động thì số ngày nghỉ hằng năm được tăng thêm tương ứng 01 ngày.",
     [r(BL19, "Điều 114")], ["01 ngày"], {}),
    ("lao_dong", "easy", "colloquial", "Nhân viên cưới vợ được nghỉ mấy ngày mà vẫn hưởng lương?",
     "Kết hôn: nghỉ 03 ngày hưởng nguyên lương.", [r(BL19, "Điều 115")], ["03 ngày"], {}),
    ("lao_dong", "easy", "fact", "Con của người lao động kết hôn thì người lao động được nghỉ mấy ngày?",
     "Con đẻ, con nuôi kết hôn: nghỉ 01 ngày hưởng nguyên lương.", [r(BL19, "Điều 115")], ["01 ngày"], {}),
    ("lao_dong", "medium", "colloquial", "Chị em đang mang bầu tháng thứ 8 có bị bắt làm ca đêm không?",
     "Không: người sử dụng lao động không được sử dụng lao động nữ mang thai từ tháng thứ 07 (hoặc tháng thứ 06 ở vùng cao, vùng sâu, vùng xa...) làm việc ban đêm, làm thêm giờ và đi công tác xa.",
     [r(BL19, "Điều 137", "Khoản 1")], ["tháng thứ 07"], {}),
    ("hon_nhan", "easy", "fact", "Kết hôn có bắt buộc phải đăng ký không?",
     "Có: việc kết hôn phải được đăng ký và do cơ quan nhà nước có thẩm quyền thực hiện; không đăng ký thì không có giá trị pháp lý.",
     [r(HNGD, "Điều 9")], ["đăng ký"], {}),
    ("hon_nhan", "medium", "fact", "Quan hệ hôn nhân chấm dứt từ thời điểm nào khi ly hôn?",
     "Quan hệ hôn nhân chấm dứt kể từ ngày bản án, quyết định ly hôn của Tòa án có hiệu lực pháp luật.",
     [r(HNGD, "Điều 57")], ["hiệu lực pháp luật"], {}),
    ("hon_nhan", "easy", "fact", "Ly hôn là gì theo Luật Hôn nhân và gia đình?",
     "Ly hôn là việc chấm dứt quan hệ vợ chồng theo bản án, quyết định có hiệu lực pháp luật của Tòa án.",
     [r(HNGD, "Điều 3", "Khoản 14")], ["Tòa án"], {}),
    ("dat_dai", "medium", "colloquial", "Đất có biến động (VD chuyển nhượng) thì phải đăng ký biến động trong bao lâu?",
     "Trong thời hạn 30 ngày kể từ ngày có biến động, người sử dụng đất phải đăng ký biến động tại cơ quan có thẩm quyền.",
     [r(LD24, "Điều 133", "Khoản 3")], ["30 ngày"], {}),
    ("giao_thong", "easy", "fact", "Xe gắn máy được chở tối đa mấy người?",
     "Chỉ được chở một người; được chở tối đa hai người khi chở người bệnh đi cấp cứu, áp giải người vi phạm pháp luật, trẻ em dưới 12 tuổi hoặc người già yếu, khuyết tật.",
     [r(TT, "Điều 33", "Khoản 1")], ["một người"], {}),
    ("giao_thong", "easy", "colloquial", "Đi xe đạp được chở mấy người?",
     "Chỉ được chở một người; chở thêm một trẻ em dưới 07 tuổi thì được chở tối đa hai người.",
     [r(TT, "Điều 31", "Khoản 1")], ["07 tuổi"], {}),
    ("giao_thong", "easy", "fact", "Bao nhiêu tuổi thì được cấp giấy phép lái xe hạng C?",
     "Người đủ 21 tuổi trở lên được cấp giấy phép lái xe hạng C, BE.", [r(TT, "Điều 59")], ["21 tuổi"], {}),
    # ---------------- Cách hỏi mới cho tình huống đã có (kiểm tra cải tiến có tổng quát không)
    ("giao_thong", "medium", "colloquial", "Vừa chạy xe máy vừa nhắn tin điện thoại thì bị phạt bao nhiêu?",
     "Dùng tay cầm và sử dụng điện thoại khi điều khiển xe mô tô, xe gắn máy: phạt tiền từ 800.000 đồng đến 1.000.000 đồng.",
     [r(N168, "Điều 7", "Khoản 4")], ["800.000", "1.000.000"], {}),
    ("giao_thong", "medium", "colloquial", "Lái ô tô mà vượt đèn đỏ thì mất bao nhiêu tiền phạt?",
     "Người điều khiển xe ô tô không chấp hành hiệu lệnh của đèn tín hiệu giao thông: phạt tiền từ 18.000.000 đồng đến 20.000.000 đồng.",
     [r(N168, "Điều 6", "Khoản 9")], ["18.000.000", "20.000.000"], {}),
    ("giao_thong", "medium", "colloquial", "Chạy xe gắn máy nhanh hơn tốc độ cho phép khoảng 12 km/h thì bị phạt bao nhiêu?",
     "Chạy quá tốc độ quy định từ 10 km/h đến 20 km/h: phạt tiền từ 800.000 đồng đến 1.000.000 đồng.",
     [r(N168, "Điều 7", "Khoản 4")], ["800.000", "1.000.000"], {}),
    ("giao_thong", "medium", "colloquial", "Say rượu chạy mô tô, đo ra vượt 0,4 miligam/lít khí thở thì phạt bao nhiêu?",
     "Nồng độ cồn vượt quá 0,4 miligam/1 lít khí thở khi điều khiển xe mô tô, xe gắn máy: phạt tiền từ 8.000.000 đồng đến 10.000.000 đồng.",
     [r(N168, "Điều 7", "Khoản 9")], ["8.000.000", "10.000.000"], {}),
    ("hon_nhan", "medium", "colloquial", "Bố mẹ bé 1 tuổi ly hôn thì ai được nuôi bé?",
     "Con dưới 36 tháng tuổi được giao cho mẹ trực tiếp nuôi, trừ khi mẹ không đủ điều kiện hoặc cha mẹ có thỏa thuận khác phù hợp với lợi ích của con.",
     [r(HNGD, "Điều 81")], ["36 tháng"], {}),
    ("lao_dong", "medium", "colloquial", "Công ty bắt nhân viên đặt cọc tiền khi ký hợp đồng có được không?",
     "Không: người sử dụng lao động không được yêu cầu người lao động thực hiện biện pháp bảo đảm bằng tiền hoặc tài sản khác cho việc thực hiện hợp đồng lao động.",
     [r(BL19, "Điều 17")], ["bảo đảm bằng tiền"], {}),
    # ---------------- Nhiều ý trong một câu
    ("lao_dong", "hard", "multi_hop", "Hợp đồng của tôi không xác định thời hạn. Muốn nghỉ việc thì báo trước bao lâu, và trợ cấp thôi việc tính thế nào?",
     "Báo trước ít nhất 45 ngày; trợ cấp thôi việc: mỗi năm làm việc được trợ cấp một nửa tháng tiền lương (làm việc thường xuyên từ đủ 12 tháng trở lên).",
     [r(BL19, "Điều 35"), r(BL19, "Điều 46")], ["45 ngày", "nửa tháng tiền lương"], {}),
    ("giao_thong", "hard", "multi_hop", "Đi xe máy vừa chở 3 người vừa không có gương chiếu hậu bên trái thì bị phạt những lỗi gì?",
     "Chở theo 02 người: phạt 400.000 – 600.000 đồng (Điều 7, Khoản 2); không có gương chiếu hậu bên trái: phạt 400.000 – 600.000 đồng (Điều 14, Khoản 1).",
     [r(N168, "Điều 7", "Khoản 2"), r(N168, "Điều 14", "Khoản 1")], ["400.000", "600.000"], {}),
]  # fmt: skip


def main() -> None:
    out = Path(__file__).with_name("holdout.jsonl")
    lines = []
    for i, (domain, level, kind, question, answer, refs, facts, opts) in enumerate(ITEMS, 1):
        lines.append(json.dumps({
            "id": f"HO-{i:03d}", "domain": domain, "difficulty": level, "type": kind,
            "question": question, "reference_answer": answer, "references": refs,
            "key_facts": facts, "forbidden": opts.get("forbidden", []),
            "expect_refusal": opts.get("expect_refusal", False),
        }, ensure_ascii=False))  # fmt: skip
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines)} câu -> {out}")


if __name__ == "__main__":
    main()
