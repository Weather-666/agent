"use client";

import { Badge, Button, Card, Col, Progress, Row, Typography } from "antd";
import { useI18n, type MessageKey } from "@/lib/i18n";

const { Title, Text } = Typography;

type IssueLevel = "danger" | "warn" | "ok";

const badgeStatus: Record<IssueLevel, "error" | "warning" | "success"> = {
  danger: "error",
  warn: "warning",
  ok: "success",
};

const metricCards: Array<{ label: MessageKey; value: string; note: MessageKey }> = [
  { label: "adminOps.metricAbnormal", value: "17", note: "adminOps.metricAbnormalNote" },
  { label: "adminOps.metricP95", value: "1.8s", note: "adminOps.metricP95Note" },
  { label: "adminOps.metricFailed", value: "3", note: "adminOps.metricFailedNote" },
  { label: "adminOps.metricLowScore", value: "9", note: "adminOps.metricLowScoreNote" },
];

const issues: Array<{ level: IssueLevel; title: MessageKey; desc: MessageKey; action: MessageKey }> = [
  { level: "danger", title: "adminOps.issue1Title", desc: "adminOps.issue1Desc", action: "adminOps.issue1Action" },
  { level: "warn", title: "adminOps.issue2Title", desc: "adminOps.issue2Desc", action: "adminOps.issue2Action" },
  { level: "ok", title: "adminOps.issue3Title", desc: "adminOps.issue3Desc", action: "adminOps.issue3Action" },
];

const scoreBars: Array<{ label: MessageKey; value: number }> = [
  { label: "adminOps.score5", value: 72 },
  { label: "adminOps.score4", value: 18 },
  { label: "adminOps.score3", value: 6 },
  { label: "adminOps.scoreLow", value: 4 },
];

export default function AdminMetricsPage() {
  const { t } = useI18n();
  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminOps.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminOps.pageTitle")}</Title>
      </div>

      <Row gutter={[14, 14]}>
        {metricCards.map((card) => (
          <Col key={card.label} xs={24} sm={12} xl={6}>
            <Card>
              <Text type="secondary" className="text-sm">{t(card.label)}</Text>
              <strong className="my-2 block text-[32px] font-normal leading-none text-[#111827]">{card.value}</strong>
              <Text type="secondary" className="text-xs">{t(card.note)}</Text>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[18, 18]}>
        <Col xs={24} xl={15}>
          <Card>
            <div className="mb-4">
              <Title level={4} className="!mb-1">{t("adminOps.dataIssuesTitle")}</Title>
              <Text type="secondary" className="text-sm">{t("adminOps.dataIssuesDesc")}</Text>
            </div>
            <div className="grid gap-3">
              {issues.map((item) => (
                <div
                  key={item.title}
                  className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-[8px] border border-[#e6e6e3] p-3"
                >
                  <Badge status={badgeStatus[item.level]} />
                  <div>
                    <strong className="block text-sm font-normal text-[#111827]">{t(item.title)}</strong>
                    <p className="mt-1 text-[13px] text-[#8a8f98]">{t(item.desc)}</p>
                  </div>
                  <Button>{t(item.action)}</Button>
                </div>
              ))}
            </div>
          </Card>
        </Col>

        <Col xs={24} xl={9}>
          <Card>
            <div className="mb-4">
              <Title level={4} className="!mb-1">{t("adminOps.ratingsTitle")}</Title>
              <Text type="secondary" className="text-sm">{t("adminOps.ratingsDesc")}</Text>
            </div>
            <div className="grid gap-3">
              {scoreBars.map((row) => (
                <div key={row.label} className="grid grid-cols-[56px_minmax(0,1fr)] items-center gap-3">
                  <Text className="text-sm">{t(row.label)}</Text>
                  <Progress percent={row.value} strokeColor="#111827" size="small" />
                </div>
              ))}
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
