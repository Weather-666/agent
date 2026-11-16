"use client";

import { Button, Card, Checkbox, Col, Form, Input, Row, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

const { Title, Text } = Typography;

export default function SettingsNotifyPage() {
  const { t } = useI18n();
  const rows = [
    t("adminSettings.notify.rowDocParseFailed"),
    t("adminSettings.notify.rowNewAdminLogin"),
    t("adminSettings.notify.rowStorageAlert"),
    t("adminSettings.notify.rowP95Exceeded"),
  ];
  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#8a8f98]">{t("adminSettings.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminSettings.notify.title")}</Title>
      </div>

      <Card
        styles={{ header: { paddingBlock: 16 }, body: { paddingTop: 16 } }}
        title={
          <div>
            <div className="text-[16px] text-[#1f2933]">{t("adminSettings.notify.heading")}</div>
            <Text type="secondary" className="text-[13px] font-normal">{t("adminSettings.notify.desc")}</Text>
          </div>
        }
      >
        <Form layout="vertical">
          <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {rows.map((r) => (
              <div key={r} className="flex items-center justify-between rounded-[8px] border border-[#e6e6e3] px-4 py-3 text-sm">
                <span>{r}</span>
                <Checkbox defaultChecked />
              </div>
            ))}
          </div>
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item label={t("adminSettings.notify.email")}>
                <Input placeholder="admin@example.com" />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item label="Webhook URL">
                <Input placeholder="https://hook.example.com" />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary">{t("adminSettings.notify.save")}</Button>
        </Form>
      </Card>
    </div>
  );
}
