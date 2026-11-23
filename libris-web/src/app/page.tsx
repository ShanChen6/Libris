import { Scale } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-8 px-4 py-24 sm:px-8">
      <div className="flex items-center gap-3">
        <span className="bg-primary text-primary-foreground flex size-10 items-center justify-center rounded-lg">
          <Scale className="size-5" />
        </span>
        <h1 className="text-2xl font-semibold tracking-tight">Libris</h1>
      </div>
      <div className="space-y-3">
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Trợ lý Pháp luật
        </h2>
        <p className="text-muted-foreground max-w-xl text-lg leading-8">
          Hỏi đáp và tra cứu văn bản quy phạm pháp luật Việt Nam, kèm trích
          dẫn{" "}
          <span className="bg-citation text-citation-foreground rounded px-1.5 py-0.5 text-sm font-medium">
            [Điều 7 - 168/2024/NĐ-CP]
          </span>{" "}
          để đối chiếu nguyên văn.
        </p>
      </div>
      <div>
        <Button disabled>Sắp ra mắt</Button>
      </div>
    </main>
  );
}
