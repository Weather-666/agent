"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

const { Title, Text } = Typography;

export default function AdminDocumentManagePage() {
  const router = useRouter();
  const { t } = useI18n();

  useEffect(() => {
    router.replace("/admin/knowledge");
  }, [router]);

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminDocuments.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminDocuments.pageTitle")}</Title>
      </div>
      <Card>
        <Text type="secondary" className="text-sm">{t("adminDocuments.redirecting")}</Text>
      </Card>
    </div>
  );
}
