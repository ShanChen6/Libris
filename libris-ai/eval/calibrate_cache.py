"""Chọn ngưỡng cho Semantic Cache (Task 5.3) bằng dữ liệu.

    uv run python eval/calibrate_cache.py

- Cặp KHÁC đáp án: mọi cặp câu hỏi khác nhau trong Golden Dataset (VD "xe máy vượt đèn đỏ" và
  "ô tô vượt đèn đỏ"). Ngưỡng phải cao hơn cặp giống nhau nhất ở nhóm này, nếu không cache trả
  nhầm câu trả lời của câu khác.
- Cặp CÙNG đáp án: câu hỏi và cách hỏi lại (PARAPHRASES) – tỷ lệ vượt ngưỡng là tỷ lệ trúng cache.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from golden import load_golden  # noqa: E402

from app.pipeline.embedding import get_embedder  # noqa: E402

# (câu trong Golden Dataset, cách hỏi lại cùng ý)
PARAPHRASES = [
    ("Không đội mũ bảo hiểm khi đi xe máy bị phạt bao nhiêu tiền?",
     "Đi xe máy không đội mũ bảo hiểm thì bị phạt bao nhiêu?"),
    ("Không đội mũ bảo hiểm khi đi xe máy bị phạt bao nhiêu tiền?",
     "không đội mũ bảo hiểm khi đi xe máy bị phạt bao nhiêu tiền"),
    ("Xe máy vượt đèn đỏ bị phạt bao nhiêu tiền?", "Vượt đèn đỏ bằng xe máy phạt bao nhiêu tiền?"),
    ("Xe máy vượt đèn đỏ bị phạt bao nhiêu tiền?", "xe máy vượt đèn đỏ bị phạt bao nhiêu"),
    ("Nam nữ bao nhiêu tuổi thì được kết hôn?", "Bao nhiêu tuổi thì được kết hôn?"),
    ("Nam nữ bao nhiêu tuổi thì được kết hôn?", "Độ tuổi kết hôn của nam và nữ là bao nhiêu?"),
    ("Lao động nữ được nghỉ thai sản bao lâu?", "Nghỉ thai sản được bao nhiêu tháng?"),
    ("Thời gian thử việc tối đa đối với công việc cần trình độ cao đẳng là bao lâu?",
     "Thời gian thử việc tối đa với công việc yêu cầu trình độ cao đẳng là bao lâu?"),
    ("Tết Âm lịch người lao động được nghỉ mấy ngày hưởng nguyên lương?",
     "Nghỉ Tết Âm lịch được mấy ngày?"),
    ("Giấy phép lái xe có tổng cộng bao nhiêu điểm?", "Bằng lái xe có bao nhiêu điểm?"),
    ("Thời hạn sử dụng đất nông nghiệp của cá nhân là bao lâu?",
     "Đất nông nghiệp của cá nhân được sử dụng trong thời hạn bao lâu?"),
    ("Làm thêm giờ vào ngày thường được trả lương ít nhất bao nhiêu?",
     "Lương làm thêm giờ ngày thường tính thế nào?"),
]  # fmt: skip


def main() -> None:
    items = [i for i in load_golden() if i.type != "injection"]
    emb = get_embedder()
    questions = [i.question for i in items]
    vec = emb.encode(questions)
    sims = vec @ vec.T
    pairs = []
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            pairs.append((float(sims[a, b]), questions[a], questions[b]))
    pairs.sort(reverse=True)
    print("Cặp KHÁC đáp án giống nhau nhất (cosine):")
    for s, q1, q2 in pairs[:8]:
        print(f"  {s:.3f}  {q1}  |  {q2}")
    worst = pairs[0][0]
    para = [float(emb.encode([a])[0] @ emb.encode([b])[0]) for a, b in PARAPHRASES]
    print("\nCặp CÙNG đáp án (cosine):")
    for s, (a, b) in sorted(zip(para, PARAPHRASES, strict=True), reverse=True):
        print(f"  {s:.3f}  {a}  |  {b}")
    print(f"\nCặp khác đáp án cao nhất: {worst:.3f}")
    for t in (0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98):
        hit = np.mean([s >= t for s in para])
        wrong = sum(s >= t for s, _, _ in pairs)
        print(f"  ngưỡng {t:.2f}: trúng {hit:.0%} cặp cùng ý; {wrong} cặp khác đáp án bị trùng")


if __name__ == "__main__":
    main()
