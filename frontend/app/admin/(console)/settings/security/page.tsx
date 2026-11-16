"use client";

import { Button, Card, Col, Form, Input, InputNumber, Row, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

const { Title, Text } = Typography;

export default function SettingsSecurityPage() {
  const { t } = useI18n();
  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#8a8f98]">{t("adminSettings.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminSettings.security.title")}</Title>
      </div>

      <Card
        styles={{ header: { paddingBlock: 16 }, body: { paddingTop: 16 } }}
        title={
          <div>
            <div className="text-[16px] text-[#1f2933]">{t("adminSettings.security.heading")}</div>
            <Text type="secondary" className="text-[13px] font-normal">{t("adminSettings.security.desc")}</Text>
          </div>
        }
      >
        <Form
          layout="vertical"
          initialValues={{ lockoutCount: 5, lockoutDuration: 15, sessionTimeout: 30, ipWhitelist: "192.168.1.0/24\n10.0.0.1" }}
        >
          <Row gutter={16}>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="lockoutCount" label={t("adminSettings.security.lockoutCount")}>
                <InputNumber style={{ width: "100%" }} min={0} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="lockoutDuration" label={t("adminSettings.security.lockoutDuration")}>
                <InputNumber style={{ width: "100%" }} min={0} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="sessionTimeout" label={t("adminSettings.security.sessionTimeout")}>
                <InputNumber style={{ width: "100%" }} min={0} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="ipWhitelist" label={t("adminSettings.security.ipWhitelist")}>
                <Input.TextArea rows={4} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary">{t("adminSettings.security.save")}</Button>
        </Form>
      </Card>
    </div>
  );
}
