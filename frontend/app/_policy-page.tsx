"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function PolicyPage({
  title,
  content,
}: {
  title: string;
  content: string;
}) {
  return (
    <div className="min-h-screen bg-[#f8f8f7]">
      <header className="sticky top-0 z-10 border-b border-[#e8e4de] bg-[#f8f8f7]/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-3xl items-center gap-4 px-4">
          <Link
            href="/login"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-[#6b6b6b] hover:bg-[#ebe8e3] hover:text-[#111]"
            aria-label="返回"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M19 12H5M12 5l-7 7 7 7" />
            </svg>
          </Link>
          <div className="flex items-center gap-2 text-[15px] font-semibold text-[#232f3e]">
            <span className="grid h-5 w-5 place-items-center rounded-full bg-[#111] text-[12px] font-semibold text-white">
              W
            </span>
            <span>{title}</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-10 pb-20">
        <article className="prose prose-sm max-w-none text-[#232323] [&_blockquote]:rounded-lg [&_blockquote]:border-l-4 [&_blockquote]:border-[#d7d4cf] [&_blockquote]:bg-[#f0ece7] [&_blockquote]:px-4 [&_blockquote]:py-3 [&_blockquote]:text-[13px] [&_blockquote]:text-[#6b6b6b] [&_blockquote_p]:my-0 [&_h1]:mb-2 [&_h1]:text-[26px] [&_h1]:font-semibold [&_h2]:mb-3 [&_h2]:mt-10 [&_h2]:text-[17px] [&_h2]:font-semibold [&_h2]:text-[#111] [&_h3]:mb-2 [&_h3]:mt-6 [&_h3]:text-[15px] [&_h3]:font-semibold [&_h3]:text-[#333] [&_li]:my-1 [&_li]:text-[14px] [&_li]:leading-relaxed [&_ol]:my-3 [&_ol]:pl-6 [&_p]:my-3 [&_p]:text-[14px] [&_p]:leading-7 [&_p]:text-[#3d3d3d] [&_strong]:text-[#111] [&_ul]:my-3 [&_ul]:pl-6">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </article>
      </main>
    </div>
  );
}
