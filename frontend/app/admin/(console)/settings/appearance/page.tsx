"use client";

import { Button, Card, Col, Form, Input, Row, Select, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

const { Title, Text } = Typography;

export default function SettingsAppearancePage() {
  const { t } = useI18n();
  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#8a8f98]">{t("adminSettings.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminSettings.appearance.title")}</Title>
      </div>

      <Card
        styles={{ header: { paddingBlock: 16 }, body: { paddingTop: 16 } }}
        title={
          <div>
            <div className="text-[16px] text-[#1f2933]">{t("adminSettings.appearance.heading")}</div>
            <Text type="secondary" className="text-[13px] font-normal">{t("adminSettings.appearance.desc")}</Text>
          </div>
        }
      >
        <Form
          layout="vertical"
          initialValues={{
            systemName: t("adminSettings.appearance.systemNameValue"),
            language: "简体中文",
            timezone: "Asia/Shanghai",
            dateFormat: "YYYY/MM/DD",
          }}
        >
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="systemName" label={t("adminSettings.appearance.systemName")}>
                <Input />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="language" label={t("adminSettings.appearance.language")}>
                <Select options={[{ value: "简体中文" }, { value: "English" }]} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="timezone" label={t("adminSettings.appearance.timezone")}>
                <Select options={[{ value: "Asia/Shanghai" }, { value: "UTC" }]} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="dateFormat" label={t("adminSettings.appearance.dateFormat")}>
                <Select options={[{ value: "YYYY/MM/DD" }, { value: "YYYY-MM-DD" }]} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary">{t("adminSettings.appearance.save")}</Button>
        </Form>
      </Card>
    </div>
  );
}
